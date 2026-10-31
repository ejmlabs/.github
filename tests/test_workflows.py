import ast
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_workflows as workflows
from standards import consumer_workflows


def embedded_source(script: str) -> str | None:
    match = re.search(r"base64\.b64decode\('([A-Za-z0-9+/=]+)'\)", script)
    return base64.b64decode(match[1], validate=True).decode() if match else None


def generated_yaml(text: str) -> Any:
    """Read the generator's JSON scalars, block strings, maps, and lists."""
    lines = [line for line in text.splitlines() if not line.startswith("#")]

    def parse(index: int, indent: int) -> tuple[Any, int]:
        result: Any = [] if lines[index].strip() == "-" or lines[index].lstrip().startswith("- ") else {}
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            if len(line) - len(line.lstrip()) != indent:
                break
            if isinstance(result, list):
                if line.strip() == "-":
                    item, index = parse(index + 1, indent + 2)
                else:
                    item, index = json.loads(line.strip()[2:]), index + 1
                result.append(item)
                continue
            match = re.fullmatch(r'\s*("(?:[^"\\]|\\.)*"):(?: (.*))?', line)
            assert match is not None
            key, value = json.loads(match[1]), match[2]
            index += 1
            if value == "|":
                block = []
                while index < len(lines) and (not lines[index].strip() or len(lines[index]) - len(lines[index].lstrip()) > indent):
                    block.append(lines[index][indent + 2:])
                    index += 1
                result[key] = "\n".join(block) + "\n"
            elif value is None:
                result[key], index = parse(index, indent + 2)
            else:
                result[key] = json.loads(value)
        return result, index

    parsed, end = parse(0, 0)
    if end != len(lines):
        raise ValueError("Unexpected generated YAML")
    return parsed


# Every command a gate script may run is a stub that only records itself, and a product's own gate is a script that does the same.
RECORDER = """import json, os, sys
sys.stdin.read()
with open(os.environ['COMMAND_LOG'], 'a') as log:
    log.write(json.dumps({'command': [os.path.basename(sys.argv[0]), *sys.argv[1:]], 'cwd': os.path.basename(os.getcwd()), 'ignore_scripts': os.environ.get('npm_config_ignore_scripts')}) + '\\n')
sys.exit(19 if os.path.basename(sys.argv[0]) == os.environ.get('FAIL_AT') else 0)
"""
OWNED_GATE = """#!/bin/sh
printf '{"command": ["%s"], "cwd": "%s", "ignore_scripts": "%s"}\\n' "$(basename "$0")" "$(basename "$PWD")" "$npm_config_ignore_scripts" >> "$COMMAND_LOG"
[ "$FAIL_AT" = "$(basename "$0")" ] && exit 19
exit 0
"""


def run_gate(script: str, profile: str, files: dict[str, str], fail_at: str = "") -> tuple[int, list[dict[str, Any]]]:
    """Run a gate script in a fresh workspace. `files` maps a path to "file", "executable", "directory" or "-> target"."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "bin").mkdir()
        (root / "product").mkdir()
        for name in ("npm", "node", "rustup", "cargo", "python3"):
            stub = root / "bin" / name
            stub.write_text("#!" + sys.executable + "\n" + RECORDER)
            stub.chmod(0o755)
        for path, kind in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if kind == "directory":
                target.mkdir()
            elif kind.startswith("-> "):
                target.symlink_to(kind[3:])
            else:
                target.write_text(OWNED_GATE)
                target.chmod(0o755 if kind == "executable" else 0o644)
        log = root / "commands.jsonl"
        env = {**os.environ, "PROFILE": profile, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"], "COMMAND_LOG": str(log), "FAIL_AT": fail_at}
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=root, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        return result.returncode, [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


class WorkflowSecurityTests(unittest.TestCase):
    governance: dict[str, Any]
    release: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.governance = generated_yaml((workflows.ROOT / ".github/workflows/governance.yml").read_text())
        cls.release = workflows.release_workflow()

    def test_own_callers_match_the_secrets_declared_at_their_pinned_revisions(self) -> None:
        repository = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=workflows.ROOT, capture_output=True, check=False)
        if repository.returncode:
            self.skipTest("Pinned caller secrets require Git metadata; this source extract is not a Git repository")
        for filename in ("pr.yml", "release.yml"):
            caller = (workflows.ROOT / ".github/workflows" / filename).read_text()
            jobs = dict(re.findall(r"(?ms)^  ([\w-]+):\n(.*?)(?=^  \S|\Z)", caller.split("\njobs:\n", 1)[1]))
            self.assertTrue(jobs)
            for name, job in jobs.items():
                with self.subTest(caller=filename, job=name):
                    reference = re.search(r"(?m)^    uses: ejmlabs/\.github/(\.github/workflows/[\w-]+\.yml)@([0-9a-f]{40})$", job)
                    self.assertIsNotNone(reference)
                    assert reference is not None
                    path, revision = reference.groups()
                    kind = subprocess.check_output(
                        ["git", "cat-file", "--batch-check=%(objecttype)"], input=revision + "\n",
                        cwd=workflows.ROOT, text=True).strip()
                    if kind == revision + " missing":
                        self.skipTest(f"Pinned workflow commit {revision} is absent from the local Git object store")
                    self.assertEqual(kind, "commit")
                    pinned = subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=workflows.ROOT, text=True)
                    declared = generated_yaml(pinned)["on"]["workflow_call"].get("secrets", {})
                    forwarded: dict[str, str] = {}
                    if "    secrets:" in job:
                        self.assertIn("    secrets:\n", job)
                        section = re.search(r"(?ms)^    secrets:\n(.*?)(?=^    \S|\Z)", job)
                        assert section is not None
                        for line in section[1].splitlines():
                            secret = re.fullmatch(r"      (\w+): \$\{\{ secrets\.(\w+) \}\}", line)
                            self.assertIsNotNone(secret)
                            assert secret is not None
                            key, source = secret.groups()
                            self.assertNotIn(key, forwarded)
                            self.assertEqual(key, source)
                            forwarded[key] = source
                    if filename == "pr.yml" and name == "missing_model_key":
                        # This acceptance fixture deliberately omits every optional secret.
                        self.assertNotIn("    secrets:", job)
                        self.assertIn(reference[0], jobs["governance"])
                        self.assertTrue(declared)
                        self.assertTrue(all(secret.get("required") is False for secret in declared.values()))
                    else:
                        # Callers may omit unused optional secrets declared at an older pin
                        # (for example the retired review model key during the Ready-for-review rollout).
                        self.assertTrue(set(forwarded) <= set(declared))
                        self.assertTrue(all(key in forwarded for key, meta in declared.items() if meta.get("required")))

    def test_every_source_consumer_uses_the_preparation_artifact_id(self) -> None:
        jobs = self.governance["jobs"]
        prepare = jobs["prepare"]
        match = re.fullmatch(r"\$\{\{ steps\.([A-Za-z0-9_-]+)\.outputs\.artifact-id \}\}", prepare["outputs"]["artifact"])
        self.assertIsNotNone(match, "Source identity must come from an upload action's artifact-id")
        assert match is not None
        uploads = [step for step in prepare["steps"] if step.get("id") == match[1]]
        self.assertEqual(len(uploads), 1)
        self.assertTrue(uploads[0]["uses"].startswith("actions/upload-artifact@"))
        self.assertEqual(uploads[0]["with"]["path"], "prepared/")
        self.assertFalse(uploads[0]["with"].get("overwrite", False))
        consumers = set()
        for name, job in jobs.items():
            for step in job["steps"]:
                if step.get("uses", "").startswith("actions/download-artifact@"):
                    with self.subTest(job=name):
                        consumers.add(name)
                        self.assertIn("prepare", job["needs"])
                        self.assertEqual(step["with"], {
                            "artifact-ids": "${{ needs.prepare.outputs.artifact }}",
                            "merge-multiple": True,
                            "path": "prepared",
                        })
        self.assertEqual(consumers, {"quality", "registry", "standards"})

    def test_untrusted_jobs_have_no_repository_or_model_credentials(self) -> None:
        for name in ("quality", "registry", "standards"):
            with self.subTest(job=name):
                job = self.governance["jobs"][name]
                self.assertEqual(job["permissions"], {})
                self.assertNotIn("secrets.", json.dumps(job))
                self.assertNotIn("GH_TOKEN", job.get("env", {}))

    def test_every_job_rejects_replays_before_allocating_a_runner(self) -> None:
        for name, job in self.governance["jobs"].items():
            with self.subTest(job=name):
                self.assertRegex(job.get("if", ""), r"^\$\{\{ github\.run_attempt == 1(?: && | \}\}$)")

    def test_cli_setup_runs_after_tools_only_in_the_unprivileged_quality_job(self) -> None:
        hooks = [(name, index, step) for name, job in self.governance["jobs"].items()
                 for index, step in enumerate(job["steps"]) if step.get("uses", "").startswith("./")]
        self.assertEqual(len(hooks), 1)
        name, index, hook = hooks[0]
        self.assertEqual(name, "quality")
        self.assertEqual(hook["uses"], "./product/.github/actions/setup-ci")
        self.assertEqual(hook["if"], "${{ needs.admission.outputs.profile == 'ejm-cli' }}")
        steps = self.governance["jobs"][name]["steps"]
        self.assertIn("rustup toolchain install", steps[index - 1]["run"])
        self.assertIn("./scripts/check", steps[index + 1]["run"])

    def test_warm_cache_builds_reviewed_main_like_the_gate_and_is_the_only_cache_writer(self) -> None:
        warm = generated_yaml(workflows.yaml(workflows.warm_workflow()))
        as_gate = "github.event.repository.name", "needs.admission.outputs.profile"
        miss = "${{ steps.lookup.outputs.cache-hit != 'true' }}"
        for name, job in warm["jobs"].items():
            with self.subTest(job=name):
                gate = self.governance["jobs"][name]
                self.assertEqual(job["permissions"], {"contents": "read"})
                self.assertNotIn("secrets.", json.dumps(job))
                self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/main'", job["if"])
                # Same environment and build steps as the gate, so the saved artifacts are the ones the gate reuses.
                self.assertEqual({key: value.replace(*as_gate) for key, value in job["env"].items()}, gate["env"])
                steps = [step for step in gate["steps"] if step not in (workflows.ARTIFACT, workflows.EXTRACT) and not step.get("uses", "").startswith("actions/cache/")]
                # Only the build is skipped on a hit. The setup hook and toolchain steps keep the gate's exact form.
                expected = [{**step, "if": miss} if step.get("name") in (workflows.GATE["name"], workflows.REGISTRY["name"]) else step for step in steps]
                lookup = next(index for index, step in enumerate(job["steps"]) if step.get("id") == "lookup")
                self.assertEqual(json.dumps(job["steps"][lookup + 1:-1]).replace(*as_gate), json.dumps(expected))
                checkouts = [step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")]
                self.assertEqual([step["with"]["path"] for step in checkouts], ["product", "ejm-harness", "ejm-ui"])
                self.assertTrue(all(step["with"]["persist-credentials"] is False for step in checkouts))
                # The key hashes lockfiles, so the checkout and the exported-layout step come first.
                layout = next(index for index, step in enumerate(job["steps"]) if step.get("name") == "Match the gate's exported source layout")
                self.assertLess(layout, lookup)
                restore = next(step for step in gate["steps"] if step.get("uses", "").startswith("actions/cache/"))
                probe, save = job["steps"][lookup], job["steps"][-1]
                self.assertTrue(probe["uses"].startswith("actions/cache/restore@"))
                self.assertTrue(save["uses"].startswith("actions/cache/save@"))
                self.assertIs(probe["with"]["lookup-only"], True)
                self.assertEqual(probe["with"].keys() - {"lookup-only"}, {"path", "key"})
                self.assertEqual(save["with"].keys(), {"path", "key"})
                for step in (probe, save):
                    self.assertEqual(step["with"]["path"].replace(*as_gate), restore["with"]["path"])
                    self.assertEqual(step["with"]["key"].replace(*as_gate), restore["with"]["key"])
                # Saved only by a build that passed and found no cache: a saved key is never replaced.
                self.assertEqual(save["if"], miss)
                self.assertEqual(job["steps"].index(save), len(job["steps"]) - 1)
        self.assertEqual(warm["jobs"]["quality"]["strategy"]["matrix"]["os"].replace(*as_gate), self.governance["jobs"]["quality"]["strategy"]["matrix"]["os"])
        self.assertFalse(warm["concurrency"]["cancel-in-progress"])

    def test_site_deploy_builds_without_credentials_and_holds_the_token_only_in_trusted_steps(self) -> None:
        document = generated_yaml(workflows.yaml(workflows.deploy_workflow()))
        jobs = document["jobs"]
        self.assertEqual(document["permissions"], {})
        build = jobs["build"]
        self.assertEqual(build["permissions"], {"contents": "read"})
        self.assertNotIn("environment", build)
        self.assertNotIn("secrets.", json.dumps(build))
        self.assertEqual((jobs["staging"]["needs"], jobs["production"]["needs"]), ("build", "staging"))
        self.assertEqual((jobs["staging"]["environment"], jobs["production"]["environment"]), ("staging", "production"))
        for name in ("staging", "production"):
            with self.subTest(job=name):
                steps = jobs[name]["steps"]
                # The deploy job checks out and runs no product code: only the built files, the pinned deployer and trusted scripts.
                self.assertEqual([step["uses"].split("@")[0] for step in steps if "uses" in step], ["actions/download-artifact", "actions/setup-node"])
                self.assertTrue(all("secrets." not in json.dumps(step) for step in steps[:-1]))
                self.assertEqual(steps[-1]["env"]["CLOUDFLARE_API_TOKEN"], "${{ secrets.CLOUDFLARE_API_TOKEN }}")
                self.assertEqual(embedded_source(steps[-1]["run"]), workflows.source("deploy.py"))
                install = steps[-2]["run"]
                self.assertIn("npm ci --ignore-scripts", install)
                lock = (workflows.ROOT / "deploy/package-lock.json").read_text()
                self.assertIn(repr(lock), embedded_source(install) or "")
        self.assertEqual(jobs["production"]["permissions"], {"actions": "read"})
        self.assertTrue(jobs["production"]["concurrency"]["cancel-in-progress"])
        self.assertFalse(jobs["staging"]["concurrency"]["cancel-in-progress"])

    def test_harness_dbus_setup_is_linux_only_and_before_the_required_gate(self) -> None:
        installers = [(name, index, step) for name, job in self.governance["jobs"].items()
                      for index, step in enumerate(job["steps"]) if "libdbus-1-dev" in step.get("run", "")]
        self.assertEqual(len(installers), 1)
        name, index, step = installers[0]
        self.assertEqual(name, "quality")
        self.assertEqual(step["if"], "${{ needs.admission.outputs.profile == 'ejm-harness' && runner.os == 'Linux' }}")
        gates = [i for i, item in enumerate(self.governance["jobs"][name]["steps"])
                 if "./scripts/check" in item.get("run", "")]
        self.assertEqual(len(gates), 1)
        self.assertLess(index, gates[0])

    def test_harness_checkout_uses_only_the_trusted_selector_and_fixed_repository(self) -> None:
        prepare = self.governance["jobs"]["prepare"]
        self.assertEqual(prepare["permissions"], {"contents": "read", "pull-requests": "read", "statuses": "read"})
        selectors = [(index, step) for index, step in enumerate(prepare["steps"]) if step.get("id") == "harness"]
        self.assertEqual(len(selectors), 1)
        index, selector = selectors[0]
        self.assertEqual(selector["run"], workflows.python(workflows.source("prepare.py"), "select-harness"))
        self.assertEqual(selector["run"].splitlines()[0], "python3 - select-harness <<'TRUSTED_PYTHON'")
        self.assertEqual(selector["env"], {
            "PROFILE": "${{ needs.admission.outputs.profile }}",
            "HARNESS_READ_TOKEN": "${{ secrets.EJM_HARNESS_TOKEN || github.token }}",
        })
        for path, ref in (("product", "head"), ("base", "base")):
            checkouts = [i for i, step in enumerate(prepare["steps"])
                         if step.get("with", {}).get("path") == path]
            self.assertEqual(len(checkouts), 1)
            self.assertLess(checkouts[0], index)
            self.assertEqual(prepare["steps"][checkouts[0]]["with"]["ref"], "${{ needs.admission.outputs." + ref + " }}")
        checkout = prepare["steps"][index + 1]
        self.assertTrue(checkout["uses"].startswith("actions/checkout@"))
        self.assertEqual(checkout["if"], "${{ steps.harness.outputs.revision != '' }}")
        self.assertEqual(checkout["with"], {
            "repository": "ejmlabs/ejm-harness", "ref": "${{ steps.harness.outputs.revision }}",
            "path": "harness", "persist-credentials": False,
            "token": "${{ secrets.EJM_HARNESS_TOKEN || github.token }}",
        })
        archive_index, archive = next((i, step) for i, step in enumerate(prepare["steps"])
                                      if step.get("name") == "Archive admitted source")
        self.assertLess(index + 1, archive_index)
        self.assertEqual(archive["run"], workflows.python(workflows.source("prepare.py")))
        self.assertNotIn("HARNESS_READ_TOKEN", archive.get("env", {}))
        self.assertNotIn("HARNESS_READ_TOKEN", prepare["env"])

    def test_owner_gates_run_required_checks_and_stop_after_a_failure(self) -> None:
        job = self.governance["jobs"]["quality"]
        script = next(step["run"] for step in job["steps"] if "./scripts/check" in step.get("run", ""))
        gates = {
            "ejm-ui": [
                ["npm", "ci", "--ignore-scripts"],
                ["npm", "rebuild", "node-pty", "--ignore-scripts=false"],
                ["npm", "run", "check"],
                ["npm", "run", "build"],
                ["npm", "run", "check:rust"],
                ["node", "scripts/pack-proof.mjs"],
            ],
            "ejmlabs": [
                ["node", "scripts/check.mjs"],
                ["npm", "--prefix", "site", "test"],
                ["npm", "--prefix", "site", "run", "build"],
            ],
        }
        for profile, expected in gates.items():
            for failure in (None, *range(len(expected))):
                with self.subTest(profile=profile, failure=failure), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "product").mkdir()
                    (root / "bin").mkdir()
                    log = root / "commands.jsonl"
                    for executable in ("npm", "node"):
                        stub = root / "bin" / executable
                        stub.write_text("#!/usr/bin/env python3\nimport json, os, sys\nfrom pathlib import Path\nlog = Path(os.environ['COMMAND_LOG'])\ncount = len(log.read_text().splitlines()) if log.exists() else 0\nwith log.open('a') as output:\n    output.write(json.dumps({'command': [Path(sys.argv[0]).name, *sys.argv[1:]], 'ignore_scripts': os.environ.get('npm_config_ignore_scripts')}) + '\\n')\nsys.exit(19 if str(count) == os.environ.get('FAIL_AT') else 0)\n")
                        stub.chmod(0o755)
                    env = {**os.environ, "PROFILE": profile, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
                           "COMMAND_LOG": str(log), "FAIL_AT": "none" if failure is None else str(failure)}
                    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=root, env=env, capture_output=True, text=True, check=False)
                    self.assertEqual(result.returncode, 0 if failure is None else 19, result.stderr)
                    calls = [json.loads(line) for line in log.read_text().splitlines()]
                    self.assertEqual([call["command"] for call in calls], expected if failure is None else expected[:failure + 1])
                    if profile == "ejm-ui":
                        self.assertTrue(all(call["ignore_scripts"] == "true" for call in calls))

    def test_ui_installs_its_rust_toolchain_without_unused_audit_binaries(self) -> None:
        script = next(step["run"] for step in self.governance["jobs"]["quality"]["steps"]
                      if step.get("name") == "Install pinned Rust tools")
        for profile in ("ejm-ui", "ejm-cli", "ejm-harness", "ejm-ide"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "bin").mkdir()
                log = root / "commands.jsonl"
                # The python3 stub records its arguments and the trusted source it would run, never fetching anything.
                for executable in ("rustup", "cargo", "python3"):
                    stub = root / "bin" / executable
                    stub.write_text("#!" + sys.executable + "\nimport json, os, sys\nsource = sys.stdin.read() if os.path.basename(sys.argv[0]) == 'python3' else ''\n"
                                    "with open(os.environ['COMMAND_LOG'], 'a') as log:\n    log.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:], source]) + '\\n')\n")
                    stub.chmod(0o755)
                env = {**os.environ, "PROFILE": profile, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"], "COMMAND_LOG": str(log)}
                subprocess.run(["bash", "-e", "-c", script], cwd=root, env=env, check=True, capture_output=True, text=True)
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                expected = [["rustup", "toolchain", "install", "1.99.1", "--profile", "minimal", "--component", "clippy,rustfmt", ""], ["rustup", "default", "1.99.1", ""]]
                self.assertEqual([call for call in calls if call[0] != "python3"], expected)
                installs = [call for call in calls if call[0] == "python3"]
                if profile == "ejm-ui":
                    self.assertEqual(installs, [])
                else:
                    # Prebuilt, digest-pinned binaries replace compiling the audit tools from source on every run.
                    self.assertEqual([call[1:-1] for call in installs], [["-I", "-", "cargo-deny", "cargo-machete"]])
                    self.assertEqual(embedded_source(installs[0][-1]), workflows.source("tools.py"))

    def test_rust_gates_use_every_core_and_never_wait_for_a_matrix_slot(self) -> None:
        for name in ("quality", "registry"):
            with self.subTest(job=name):
                job = self.governance["jobs"][name]
                self.assertEqual(job["env"]["CARGO_BUILD_JOBS"], "default")
                self.assertNotIn("max-parallel", job.get("strategy", {}))
        self.assertNotIn("--jobs", workflows.REGISTRY["run"])

    def test_gate_restores_main_caches_keyed_by_toolchain_and_lockfile_and_never_saves(self) -> None:
        for name in ("quality", "registry"):
            with self.subTest(job=name):
                steps = self.governance["jobs"][name]["steps"]
                caches = [step for step in steps if step.get("uses", "").startswith("actions/cache")]
                self.assertEqual(len(caches), 1)
                restore = caches[0]
                self.assertTrue(restore["uses"].startswith("actions/cache/restore@"), "the admitted gate must never save a cache")
                prefix = "gate-" + name + "-${{ runner.os }}-rust" + workflows.RUST_VERSION + "-"
                self.assertEqual(restore["with"].keys(), {"path", "key", "restore-keys"})
                self.assertEqual(restore["with"]["restore-keys"], prefix)
                lookup = re.fullmatch(re.escape(prefix) + r"\$\{\{ hashFiles\(fromJSON\('(\{.*\})'\)\[needs\.admission\.outputs\.profile\]\) \}\}", restore["with"]["key"])
                self.assertIsNotNone(lookup, restore["with"]["key"])
                assert lookup is not None
                locks = json.loads(lookup[1])
                self.assertEqual(locks.keys(), workflows.RUST_TARGETS[name].keys())
                for profile, target in workflows.RUST_TARGETS[name].items():
                    # The lockfile sits beside the cached target directory, in the layout the gate extracts and the warm job checks out.
                    self.assertEqual(locks[profile], target.removesuffix("target") + "Cargo.lock")
                    self.assertTrue(locks[profile].startswith("product/"))
                # Nothing is deleted after a restore, and an exact main commit is no longer the key.
                self.assertFalse(any("rm -rf" in step.get("run", "") for step in steps))
                self.assertNotIn("needs.admission.outputs.base", json.dumps(restore))
                # The restore follows extraction, which marks every admitted source newer than any cached build.
                self.assertLess(steps.index(next(step for step in steps if step.get("name") == "Extract source data safely")), steps.index(restore))

    def test_gate_jobs_never_save_any_cache(self) -> None:
        for name, job in self.governance["jobs"].items():
            for step in job["steps"]:
                with self.subTest(job=name, step=step.get("name") or step.get("uses")):
                    self.assertFalse(step.get("uses", "").startswith("actions/cache/save"))
                    if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                        self.assertIs(step["with"]["enable-cache"], False)
                    if step.get("uses", "").startswith("actions/setup-node@"):
                        self.assertNotIn("cache", step["with"])

    def test_one_toolchain_version_feeds_every_install_and_cache_key(self) -> None:
        self.assertEqual(workflows.RUST_VERSION, "1.99.1")
        for script in (workflows.RUST_TOOLS["run"], workflows.REGISTRY["run"]):
            self.assertIn("rustup toolchain install " + workflows.RUST_VERSION + " ", script)
            self.assertIn("rustup default " + workflows.RUST_VERSION + "\n", script)
        self.assertIn("-rust" + workflows.RUST_VERSION + "-", workflows.cache_prefix("quality"))

    def test_extraction_runs_the_tested_script_right_after_the_artifact_download(self) -> None:
        found = {name for name, job in self.governance["jobs"].items() if any(step.get("name") == "Extract source data safely" for step in job["steps"])}
        self.assertEqual(found, {"quality", "registry", "standards"})
        for name in found:
            with self.subTest(job=name):
                steps = self.governance["jobs"][name]["steps"]
                index = next(i for i, step in enumerate(steps) if step.get("name") == "Extract source data safely")
                self.assertTrue(steps[index - 1]["uses"].startswith("actions/download-artifact@"))
                self.assertEqual(steps[index]["run"].split()[:3], ["python3", "-I", "-"])
                self.assertEqual(embedded_source(steps[index]["run"]), workflows.source("extract.py"))
                self.assertEqual(steps[index], workflows.EXTRACT)

    def test_generated_extraction_step_rejects_hostile_archives_and_accepts_the_prepared_form(self) -> None:
        script = workflows.EXTRACT["run"]
        for hostile in (False, True):
            with self.subTest(hostile=hostile), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "prepared").mkdir()
                (root / "bin").mkdir()
                (root / "bin/python3").symlink_to(sys.executable)
                names = ["product/", "product/ok.txt"] + (["product/../../escape.txt"] if hostile else [])
                with tarfile.open(root / "prepared/product.tar", "w") as archive:
                    for name in names:
                        info = tarfile.TarInfo(name)
                        info.type = tarfile.DIRTYPE if name.endswith("/") else tarfile.REGTYPE
                        info.mtime = 0
                        archive.addfile(info)
                env = {**os.environ, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"]}
                result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=root, env=env, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode == 0, not hostile, result.stderr)
                self.assertEqual((root / "product/ok.txt").exists(), not hostile)
                self.assertFalse((root.parent / "escape.txt").exists())
                if not hostile:
                    self.assertGreater((root / "product/ok.txt").stat().st_mtime, time.time() - 60)

    def test_product_owned_quality_replaces_the_built_in_gate_and_runs_from_the_product_root(self) -> None:
        self.assertIn(workflows.GATE, self.governance["jobs"]["quality"]["steps"])
        for profile in ("ejm-cli", "ejm-harness", "ejm-ide", "ejm-ui", "ejmlabs", ".github"):
            with self.subTest(profile=profile):
                status, calls = run_gate(workflows.GATE["run"], profile, {"product/.github/quality": "executable"})
                self.assertEqual(status, 0)
                self.assertEqual(calls, [{"command": ["quality"], "cwd": "product", "ignore_scripts": "true"}])
        # The shared sibling install stays first, and the product's failure fails the gate.
        files = {"product/.github/quality": "executable", "ejm-ui": "directory"}
        status, calls = run_gate(workflows.GATE["run"], "ejm-cli", files)
        self.assertEqual((status, [call["command"] for call in calls]), (0, [["npm", "--prefix", "../ejm-ui", "ci", "--ignore-scripts"], ["quality"]]))
        status, calls = run_gate(workflows.GATE["run"], "ejm-cli", files, fail_at="quality")
        self.assertEqual((status, calls[-1]["command"]), (19, ["quality"]))

    def test_anything_but_a_regular_executable_quality_file_falls_back_to_the_built_in_commands(self) -> None:
        cases = {
            "absent": {},
            "not executable": {"product/.github/quality": "file"},
            "directory": {"product/.github/quality": "directory"},
            "symlink": {"product/.github/real": "executable", "product/.github/quality": "-> real"},
            "symlinked directory": {"product/elsewhere/quality": "executable", "product/.github": "-> elsewhere"},
            "the registry gate only": {"product/.github/quality-registry": "executable"},
        }
        expected = [["node", "scripts/check.mjs"], ["npm", "--prefix", "site", "test"], ["npm", "--prefix", "site", "run", "build"]]
        for name, files in cases.items():
            with self.subTest(case=name):
                status, calls = run_gate(workflows.GATE["run"], "ejmlabs", files)
                self.assertEqual((status, [call["command"] for call in calls]), (0, expected))

    def test_product_owned_registry_gate_replaces_only_the_registry_commands(self) -> None:
        self.assertIn(workflows.REGISTRY, self.governance["jobs"]["registry"]["steps"])
        shared = [["rustup", "toolchain", "install", workflows.RUST_VERSION, "--profile", "minimal", "--component", "clippy,rustfmt", "--target", "wasm32-unknown-unknown"],
                  ["rustup", "default", workflows.RUST_VERSION], ["python3", "-I", "-", "cargo-deny", "cargo-machete"],
                  ["cargo", "install", "worker-build", "--version", "0.8.7", "--locked"], ["npm", "--prefix", "../ejm-ui", "ci", "--ignore-scripts"]]
        status, calls = run_gate(workflows.REGISTRY["run"], "ejm-harness", {"product/.github/quality-registry": "executable", "ejm-ui": "directory"})
        self.assertEqual(status, 0)
        self.assertEqual([call["command"] for call in calls], [*shared, ["quality-registry"]])
        self.assertEqual((calls[-1]["cwd"], calls[-1]["ignore_scripts"]), ("product", "true"))
        self.assertTrue(all(call["ignore_scripts"] is None for call in calls[:-1]))
        fallback = {"product/.github/quality": "executable", "product/scripts/check-registry": "executable", "ejm-ui": "directory"}
        status, calls = run_gate(workflows.REGISTRY["run"], "ejm-harness", fallback)
        self.assertEqual(status, 0)
        self.assertEqual([call["command"] for call in calls], [*shared, ["npm", "ci", "--ignore-scripts"], ["npm", "--prefix", "registry", "ci", "--ignore-scripts"], ["check-registry"]])
        status, calls = run_gate(workflows.REGISTRY["run"], "ejm-cli", {"product/.github/quality-registry": "executable"})
        self.assertEqual((status, calls), (0, []))
        status, calls = run_gate(workflows.REGISTRY["run"], "ejm-harness", {"product/.github/quality-registry": "executable"}, fail_at="quality-registry")
        self.assertEqual((status, calls[-1]["command"]), (19, ["quality-registry"]))


    def test_privileged_jobs_run_only_trusted_scripts_and_actions(self) -> None:
        trusted_sources: set[str | None] = {workflows.source(name) for name in ("governance.py", "prepare.py")}
        trusted_sources.add(embedded_source(workflows.REJECT_DEBUG["run"]))
        trusted_sources.add("\n".join([
            workflows.source("governance.py", library=True), workflows.source("standards.py", library=True),
            workflows.source("prepare.py", library=True), workflows.source("release.py"),
        ]))
        trusted_actions = {"actions/checkout", "actions/download-artifact", "actions/upload-artifact"}
        for document in (self.governance, self.release):
            self.assertNotIn("defaults", document)
            for name, job in document["jobs"].items():
                if not job["permissions"] and "secrets." not in json.dumps(job):
                    continue
                with self.subTest(job=name):
                    self.assertNotIn("defaults", job)
                    for step in job["steps"]:
                        self.assertNotIn("working-directory", step)
                        if "uses" in step:
                            action, separator, revision = step["uses"].partition("@")
                            self.assertIn(action, trusted_actions)
                            self.assertEqual(separator, "@")
                            self.assertRegex(revision, r"^[0-9a-f]{40}$")
                            if action == "actions/checkout":
                                self.assertIs(step["with"]["persist-credentials"], False)
                            continue
                        script = step["run"]
                        self.assertNotIn("${{", script, "Embedded source must not expose GitHub expressions")
                        source = embedded_source(script)
                        if source is not None:
                            self.assertIn(source, trusted_sources)
                            self.assertRegex(script.splitlines()[0], r"^python3 - (?:admit|verify|finish|select-harness|ui-pin)? <<\x27TRUSTED_PYTHON\x27$")
                            encoded = base64.b64encode(source.encode()).decode()
                            self.assertEqual(script.splitlines()[1:], [
                                "import base64",
                                f"exec(compile(base64.b64decode('{encoded}'), 'trusted-workflow.py', 'exec'))",
                                "TRUSTED_PYTHON",
                            ])
                        else:
                            self.assertEqual(script.splitlines()[0], "python3 - <<'PY'")
                            self.assertEqual(script.splitlines()[-1], "PY")
                            self.assert_data_only_python("\n".join(script.splitlines()[1:-1]))

    def assert_data_only_python(self, source: str) -> None:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name, {"json", "os", "re", "stat", "tarfile", "subprocess"})
                    self.assertIsNone(alias.asname)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.module, "pathlib")
                self.assertEqual([(alias.name, alias.asname) for alias in node.names], [("Path", None)])
            elif isinstance(node, ast.Call):
                function = ast.unparse(node.func)
                self.assertNotIn(function, {"eval", "exec", "compile", "__import__", "getattr"})
                if function.startswith("os."):
                    self.assertEqual(function, "os.walk", "Inline scripts must not execute through os")
                if function.startswith("subprocess."):
                    self.assertEqual(function, "subprocess.run")
                    command = node.args[0]
                    assert isinstance(command, ast.List)
                    self.assertEqual(ast.literal_eval(command.elts[0]), "gh")
                    for item in node.keywords:
                        if item.arg == "shell":
                            self.assertIs(ast.literal_eval(item.value), False)
                if isinstance(node.func, ast.Attribute) and node.func.attr == "extractall":
                    filters = [item.value for item in node.keywords if item.arg == "filter"]
                    self.assertEqual([ast.literal_eval(value) for value in filters], ["data"])

    def test_public_reviewer_text_uses_neutral_names(self) -> None:
        denied = ("gpt", "glm-5.3", "kimi-k2.7-code", "opencode", "codex", "pr-agent", "pr_agent", "xai", "grok",
                  "openai", "litellm", "setup-uv", "actions/*")
        texts = {name: (workflows.ROOT / name).read_text() for name in ("docs/operations.md", "CHANGELOG.md")}
        texts.update({f"step {document['name']}.{job}.{index}": step["name"] for document in (self.governance, self.release)
                      for job, config in document["jobs"].items()
                      for index, step in enumerate(config["steps"]) if "name" in step})
        for name, text in texts.items():
            with self.subTest(file=name):
                lowered = text.replace("`XAI_API_KEY`", "`review model key secret`").lower()
                for term in denied:
                    self.assertNotIn(term, lowered)
                self.assertNotRegex(lowered, r"\b(?:sol|python|pip)\b")

    def test_label_approve_records_bot_approval_and_two_statuses_are_required(self) -> None:
        tree = ast.parse(workflows.source("governance.py"))
        approvals = [node for node in ast.walk(tree) if isinstance(node, ast.Dict) and any(
            isinstance(key, ast.Constant) and key.value == "event" and isinstance(value, ast.Constant) and value.value == "APPROVE"
            for key, value in zip(node.keys, node.values, strict=True))]
        self.assertEqual(len(approvals), 1)
        source = workflows.source("governance.py")
        self.assertIn('APPROVE_LABEL = "gate:approve"', source)
        self.assertIn('REVOKE_LABEL = "gate:revoke"', source)
        self.assertNotIn("command(", source)
        contexts = next(node for node in ast.parse(workflows.source("configure_repositories.py")).body if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CONTEXTS" for target in node.targets))
        self.assertEqual(ast.literal_eval(contexts.value), ("Quality", "Repository standards"))
        required = next(node for node in tree.body if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "REQUIRED_CONTEXTS" for target in node.targets))
        self.assertEqual(ast.literal_eval(required.value), ("Quality", "Repository standards"))

    def test_ui_source_is_a_fixed_owner_checkout_before_the_credential_free_handoff(self) -> None:
        steps = self.governance["jobs"]["prepare"]["steps"]
        read = next(step for step in steps if step.get("id") == "ui")
        self.assertEqual(embedded_source(read["run"]), workflows.source("prepare.py"))
        self.assertIn(" ui-pin ", read["run"].splitlines()[0])
        owner = next(step for step in steps if step.get("with", {}).get("repository") == "ejmlabs/ejm-ui")
        self.assertEqual(owner["if"], "${{ steps.ui.outputs.revision != '' }}")
        self.assertEqual(owner["with"], {"repository": "ejmlabs/ejm-ui", "ref": "${{ steps.ui.outputs.revision }}", "path": "ejm-ui", "persist-credentials": False, "fetch-depth": 1, "submodules": False})
        self.assertLess(steps.index(read), steps.index(owner))
        archive = next(step for step in steps if step.get("name") == "Archive admitted source")
        self.assertLess(steps.index(owner), steps.index(archive))

    def test_generated_workflow_admits_pull_request_lifecycle_and_gate_labels(self) -> None:
        self.assertEqual(self.governance, workflows.governance())
        self.assertEqual(set(self.governance["on"]), {"workflow_call"})
        self.assertNotIn("codex" + "-action", json.dumps(self.governance))
        caller = consumer_workflows("a" * 40)["pr.yml"]
        found = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", caller)
        assert found is not None
        triggers = found[1]
        self.assertEqual(re.findall(r"(?m)^  (\w+):", triggers), ["pull_request"])
        self.assertIn("types: [opened, reopened, synchronize, ready_for_review, converted_to_draft, labeled]", caller)
        self.assertNotIn("issue_comment", caller)
        self.assertNotIn("XAI_API_KEY", caller)
        # The previous comment-only form stays accepted for one generation.
        previous = consumer_workflows("a" * 40, current=True)["pr.yml"]
        self.assertIn("  issue_comment:\n    types: [created, edited, deleted]\n", previous)
        self.assertNotIn("pull_request:", previous)
        admission = self.governance["jobs"]["admission"]["if"]
        self.assertIn("github.event_name == 'pull_request'", admission)
        self.assertIn("gate:approve", admission)
        self.assertIn("gate:revoke", admission)
        self.assertNotIn("issue_comment", admission)
        self.assertNotIn("startsWith(github.event.comment.body", admission)

    def test_tracked_sources_exclude_retired_review_configuration(self) -> None:
        repository = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=workflows.ROOT, capture_output=True, check=False)
        if repository.returncode:
            files = [path.relative_to(workflows.ROOT).as_posix() for path in workflows.ROOT.rglob("*")
                     if path.is_file() and "__pycache__" not in path.relative_to(workflows.ROOT).parts]
        else:
            tracked = subprocess.run(["git", "ls-files", "-z"], cwd=workflows.ROOT, check=True, capture_output=True).stdout
            files = [os.fsdecode(raw) for raw in tracked.split(b"\0") if raw]
        retired = ("codex" + "-action", "OPENAI" + "_API_KEY", "OPENAI" + "__")
        for name in files:
            if (workflows.ROOT / name).is_symlink():
                continue  # a tracked symlink's target is scanned as its own tracked file
            content = (workflows.ROOT / name).read_bytes()
            for value in retired:
                with self.subTest(file=name, value=value):
                    self.assertNotIn(value.encode(), content)

    def test_only_finish_publishes_the_check_results(self) -> None:
        finish = self.governance["jobs"]["finish"]
        self.assertEqual(finish["env"]["JOB_RESULTS"], "${{ toJSON(needs) }}")
        self.assertEqual(finish["needs"], ["admission", "prepare", "quality", "registry", "standards"])
        publishers = []
        for document in (self.governance, self.release):
            for job, config in document["jobs"].items():
                for step in config["steps"]:
                    script = step.get("run", "")
                    if embedded_source(script) == workflows.source("governance.py"):
                        entry = shlex.split(script.splitlines()[0])[2]
                        self.assertIn(entry, ("admit", "verify", "finish"))
                        if entry == "finish":
                            publishers.append((document["name"], job, entry))
        self.assertEqual(publishers, [(self.governance["name"], "finish", "finish")])

    def test_no_job_receives_the_model_key_and_no_review_job_remains(self) -> None:
        text = json.dumps(self.governance)
        self.assertNotRegex(text, r"secrets\.XAI_API_KEY")
        self.assertNotIn("OPENAI" + "_API_KEY", text)
        self.assertEqual(set(self.governance["jobs"]), {"admission", "prepare", "quality", "registry", "standards", "finish"})
        # Optional unused key kept for one generation so older pins' scaffold checks pass.
        self.assertEqual(self.governance["on"]["workflow_call"]["secrets"]["XAI_API_KEY"], {"required": False})
        self.assertEqual(self.governance["on"]["workflow_call"]["secrets"]["EJM_HARNESS_TOKEN"], {"required": False})
        for job in self.governance["jobs"].values():
            self.assertNotIn("pull_request_target", job.get("if", ""))

    def test_no_job_declares_an_environment(self) -> None:
        environments = [(document["name"], name, job["environment"])
                        for document in (self.governance, self.release)
                        for name, job in document["jobs"].items() if "environment" in job]
        self.assertEqual(environments, [])

    def test_prepare_rejects_runner_debug_before_other_steps(self) -> None:
        for name in ("prepare",):
            with self.subTest(job=name):
                job = self.governance["jobs"][name]
                self.assertNotIn("runner.", job["if"])
                first = job["steps"][0]
                self.assertEqual(first, workflows.REJECT_DEBUG)
                debug_source = embedded_source(first["run"])
                assert debug_source is not None
                self.assertIn("RUNNER_DEBUG", debug_source)
                self.assertEqual(job["steps"][1], workflows.VERIFY)
                for debug, expected in (("1", 1), ("0", 0), ("", 0)):
                    completed = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", first["run"]],
                                               env={**os.environ, "RUNNER_DEBUG": debug}, capture_output=True, text=True, check=False)
                    self.assertEqual(completed.returncode, expected, completed.stderr)

        for workflow in (self.governance, self.release):
            for job in workflow["jobs"].values():
                self.assertNotIn("runner.", job.get("if", ""))

    def test_release_draft_classifies_prereleases_without_replacing_existing_assets(self) -> None:
        script = self.release["jobs"]["draft"]["steps"][-1]["run"]
        cases: tuple[tuple[str, list[str]], ...] = (
            ("1.2.3", []),
            ("1.2.3-rc.1", ["--prerelease", "--latest=false"]),
            ("1.2.3+build-alpha", []),
            ("1.2.3-beta.1+build-2", ["--prerelease", "--latest=false"]),
        )
        for version, flags in cases:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "bin").mkdir()
                gh = root / "bin/gh"
                gh.write_text("#!/usr/bin/env python3\nimport json, os, sys\nwith open(os.environ['COMMAND_LOG'], 'a') as log:\n    log.write(json.dumps(sys.argv[1:]) + '\\n')\n")
                gh.chmod(0o755)
                assets = root / "release-assets"
                assets.mkdir()
                (assets / "provenance.json").write_text(json.dumps({"version": version, "commit": "a" * 40}))
                (assets / "source.zip").write_bytes(b"source fixture")
                (root / "release-notes.md").write_text("Source release fixture.\n")
                log = root / "commands.jsonl"
                env = {**os.environ, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
                       "GITHUB_REPOSITORY": "ejmlabs/ejmlabs", "COMMAND_LOG": str(log)}
                subprocess.run(["bash", "-e", "-c", script], cwd=root, env=env, check=True, capture_output=True, text=True)
                commands = [json.loads(line) for line in log.read_text().splitlines()]
                tag = "v" + version
                self.assertEqual(commands, [
                    ["api", "--method", "POST", "repos/ejmlabs/ejmlabs/git/refs", "-f", "ref=refs/tags/" + tag, "-f", "sha=" + "a" * 40],
                    ["release", "create", tag, "--repo", "ejmlabs/ejmlabs", "--verify-tag", "--draft", "--title", tag,
                     "--notes-file", "release-notes.md", *flags, "release-assets/provenance.json", "release-assets/source.zip"],
                ])

    def test_release_keeps_the_standard_library_embedding_and_static_source_boundary(self) -> None:
        draft = self.release["jobs"]["draft"]
        self.assertEqual(draft["permissions"], {"contents": "write", "pull-requests": "read", "statuses": "read"})
        self.assertEqual(draft["env"], {
            "GH_TOKEN": "${{ github.token }}", "RELEASE_COMMIT": "${{ inputs.commit }}",
            "RELEASE_VERSION": "${{ inputs.version }}", "STANDARDS_REF": "${{ inputs.standards-ref }}",
        })
        self.assertEqual(len(draft["steps"]), 3)
        self.assertEqual(draft["steps"][0], workflows.checkout("product", "${{ inputs.commit }}"))
        library = "\n".join([workflows.source("governance.py", library=True), workflows.source("standards.py", library=True),
                              workflows.source("prepare.py", library=True), workflows.source("release.py")])
        self.assertEqual(draft["steps"][1]["run"], workflows.python(library))
        self.assertNotIn("select-harness", draft["steps"][1]["run"].splitlines()[0])

    def test_embedded_expressions_survive_as_literal_python_data(self) -> None:
        literal = "${{ inputs.commit }} / ${{ secrets.XAI_API_KEY }}"
        source = "import sys\nprint(" + repr(literal) + ")\nprint(sys.argv[1])\n"
        script = workflows.python(source, "fixture")
        self.assertNotIn("${{", script)
        self.assertNotIn("${{", workflows.yaml({"run": script}))
        self.assertEqual(embedded_source(script), source)
        result = subprocess.run(["bash", "-e", "-c", script], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout, literal + "\nfixture\n")


if __name__ == "__main__":
    unittest.main()
