import ast
import base64
import bz2
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_workflows as workflows
import configure_repositories as settings
import governance
from standards import SHARED_WORKFLOWS, SITE_DEPLOY_CALLER, consumer_workflows

from deploy import SITES, source_path


def embedded_source(script: str, env: dict[str, Any] | None = None) -> str | None:
    match = re.search(r"base64\.b64decode\('([A-Za-z0-9+/=]+)'\)", script)
    if match:
        encoded = match[1]
    elif "base64.b64decode(_trusted_script, validate=True)" in script and env is not None:
        keys = [key for key in env if key.startswith("EJM_TRUSTED_SCRIPT_")]
        encoded = "".join(env[f"EJM_TRUSTED_SCRIPT_{index}"] for index in range(len(keys)))
    else:
        return None
    return bz2.decompress(base64.b64decode(encoded, validate=True)).decode()


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


# Sites that link @ejm/* from a sibling ejm-ui install its dependencies first, so the file: links resolve into built packages.
UI_INSTALL = ["npm", "--prefix", "../ejm-ui", "ci", "--ignore-scripts"]
HARNESS_BUILD = [UI_INSTALL, ["npm", "--prefix", "site", "ci", "--ignore-scripts"], ["npm", "--prefix", "site", "run", "build"]]
IDE_BUILD = [UI_INSTALL, ["npm", "ci", "--ignore-scripts"], ["npm", "run", "site:build"]]

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

    def test_generated_workflows_fit_github_size_limits(self) -> None:
        for name in ("governance.yml", "draft-release.yml", "verify-build.yml", "attach-assets.yml", "warm-cache.yml", "deploy-site.yml"):
            path = workflows.ROOT / ".github/workflows" / name
            document = generated_yaml(path.read_text())
            with self.subTest(workflow=path.name):
                self.assertLessEqual(path.stat().st_size, 450_000)
                for job in document.get("jobs", {}).values():
                    for step in job.get("steps", []):
                        self.assertLessEqual(len(step.get("run", "")), 18_000)

    def test_codeql_scans_the_requested_languages_with_scoped_permissions(self) -> None:
        reusable = generated_yaml((workflows.ROOT / ".github/workflows/codeql-analysis.yml").read_text())
        caller = generated_yaml((workflows.ROOT / ".github/workflows/codeql.yml").read_text())
        self.assertEqual(reusable["permissions"], {})
        self.assertEqual(reusable["on"]["workflow_call"]["inputs"]["languages"]["default"], "javascript-typescript")
        job = reusable["jobs"]["codeql-analysis"]
        self.assertEqual(job["permissions"], {"contents": "read", "actions": "read", "security-events": "write"})
        self.assertEqual([step["uses"].split("@")[0] for step in job["steps"]],
                         ["actions/checkout", "github/codeql-action/init", "github/codeql-action/autobuild", "github/codeql-action/analyze"])
        self.assertEqual(job["steps"][1]["with"], {"languages": "${{ inputs.languages }}", "queries": "security-extended"})
        self.assertFalse(job["steps"][0]["with"]["persist-credentials"])
        self.assertEqual(caller["permissions"], {})
        self.assertEqual(caller["on"]["push"]["branches"], ["main"])
        self.assertTrue(caller["on"]["schedule"])
        self.assertEqual(caller["jobs"]["codeql-analysis"], {"permissions": job["permissions"], "uses": "./.github/workflows/codeql-analysis.yml",
                                                               "with": {"languages": "python, actions"}})

    def test_member_codeql_caller_grants_the_reusable_job_permissions(self) -> None:
        reusable = generated_yaml((workflows.ROOT / ".github/workflows/codeql-analysis.yml").read_text())
        permissions = reusable["jobs"]["codeql-analysis"]["permissions"]
        caller = consumer_workflows("a" * 40, codeql_languages="javascript-typescript")["code-scan.yml"]
        block = "    permissions:\n" + "".join(f"      {name}: {level}\n" for name, level in permissions.items())
        self.assertIn(block, caller)

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
                    # Callers may omit optional secrets that a pin declares; they must forward every required one.
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
        # A rerun of every job uploads again in the same run, so the name carries the attempt instead of overwriting.
        self.assertEqual(uploads[0]["with"]["name"], "admitted-sources-${{ github.run_attempt }}")
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

    def test_untrusted_jobs_have_no_repository_credentials(self) -> None:
        for name in ("quality", "registry", "standards"):
            with self.subTest(job=name):
                job = self.governance["jobs"][name]
                self.assertEqual(job["permissions"], {})
                self.assertNotIn("secrets.", json.dumps(job))
                self.assertNotIn("GH_TOKEN", job.get("env", {}))

    def test_reruns_are_allowed_and_each_job_keeps_only_its_own_condition(self) -> None:
        # Ownership of the statuses, not the attempt number, decides whether a rerun may publish.
        jobs = self.governance["jobs"]
        # The attempt number may name a per-attempt artifact, but no job or step condition may depend on it.
        conditions = [job.get("if", "") for job in jobs.values()] + [step.get("if", "") for job in jobs.values() for step in job["steps"]]
        self.assertFalse([condition for condition in conditions if "run_attempt" in condition])
        self.assertEqual(jobs["prepare"]["if"], "${{ needs.admission.outputs.run == 'true' }}")
        # A cancelled run (a stop cancels its older runs) starts no finish job, so a stopped run publishes nothing late.
        self.assertEqual(jobs["finish"]["if"], "${{ !cancelled() && needs.admission.outputs.run == 'true' }}")
        for name in ("quality", "registry", "standards"):
            self.assertNotIn("if", jobs[name], "a skipped prepare job already skips the jobs that need it")
            self.assertIn("prepare", jobs[name]["needs"])

    def test_admission_serializes_per_head_across_pull_requests_and_never_cancels_a_running_admission(self) -> None:
        # Statuses belong to the commit, so two PRs at one commit must share a group; a PR number would split them.
        self.assertEqual(self.governance["jobs"]["admission"]["concurrency"], {
            "group": "gate-${{ github.repository }}-${{ github.event.pull_request.head.sha }}",
            "cancel-in-progress": False,
        })
        self.assertNotIn("admission", self.governance["jobs"]["admission"]["outputs"])
        self.assertNotIn("ADMISSION_ID", json.dumps(self.governance))

    def test_embedded_scripts_run_isolated(self) -> None:
        # -I keeps the admitted sources in the working directory, and PYTHON* variables, out of the trusted imports.
        steps = [step for job in self.governance["jobs"].values() for step in job["steps"] if "TRUSTED_PYTHON" in step.get("run", "")]
        interpreters = [line for step in steps for line in step["run"].splitlines() if line.endswith("<<'TRUSTED_PYTHON'")]
        self.assertTrue(interpreters)
        for line in interpreters:
            self.assertRegex(line, r"^\s*python3 -I - [^<]*<<'TRUSTED_PYTHON'$")
        for step in steps:
            source = embedded_source(step["run"], step.get("env"))
            assert source is not None
            compile(source, "embedded", "exec")
        self.assertEqual(workflows.python("print(1)").splitlines()[0], "python3 -I -  <<'TRUSTED_PYTHON'")

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
        granted = dict(re.findall(r"(?m)^      (\w+): (\w+)$", SITE_DEPLOY_CALLER))
        self.assertEqual(granted, {"contents": "read", "actions": "read"})
        # Each repository has exactly one of these source paths, so the sparse checkout fetches only the reviewed config (and ejm-ide's Worker directory).
        reviewed = "".join(line + "\n" for line in sorted({"/" + source_path(name) for name in SITES}))
        for name in ("staging", "production"):
            with self.subTest(job=name):
                job = jobs[name]
                steps = job["steps"]
                # Within what the canonical caller grants: the reviewed config is read as data, and the environment's rules are read through the API.
                self.assertEqual(job["permissions"], {"contents": "read", "actions": "read"})
                self.assertLessEqual(job["permissions"].items(), granted.items())
                self.assertEqual(job["env"], {"PROFILE": "${{ github.event.repository.name }}"})
                self.assertEqual([step["uses"].split("@")[0] for step in steps if "uses" in step], ["actions/download-artifact", "actions/checkout", "actions/setup-node"])
                self.assertEqual(steps[1]["uses"], workflows.CHECKOUT)
                self.assertEqual(steps[1]["with"], {"path": "reviewed", "ref": "${{ github.sha }}", "persist-credentials": False, "fetch-depth": 1, "submodules": False,
                                                    "sparse-checkout": reviewed, "sparse-checkout-cone-mode": False})
                # The checkout is data: no step runs anything from it. The only trusted steps are the pinned deployer install and deploy.py.
                protection, deploy = steps[-2], steps[-1]
                self.assertTrue(all("secrets." not in json.dumps(step) for step in steps[:-1]))
                self.assertEqual(protection["env"], {"GH_TOKEN": "${{ github.token }}"})
                self.assertEqual(deploy["env"], {"CLOUDFLARE_API_TOKEN": "${{ secrets.CLOUDFLARE_API_TOKEN }}"})
                self.assertNotIn("GH_TOKEN", json.dumps(deploy))
                for step, mode in ((protection, "protection"), (deploy, "deploy")):
                    self.assertEqual(embedded_source(step["run"]), workflows.source("deploy.py"))
                    self.assertEqual(step["run"].splitlines()[0], f"python3 -I - {mode} {name} <<'TRUSTED_PYTHON'")
                install = steps[-3]["run"]
                self.assertIn("npm ci --ignore-scripts", install)
                lock = (workflows.ROOT / "deploy/package-lock.json").read_text()
                self.assertIn(repr(lock), embedded_source(install) or "")

    def test_site_deploys_queue_per_environment_and_never_cancel_a_running_deploy(self) -> None:
        jobs = generated_yaml(workflows.yaml(workflows.deploy_workflow()))["jobs"]
        # Production runs by itself once staging succeeds, so a newer push must never stop a Wrangler deploy that is running.
        for name in ("build", "staging", "production"):
            with self.subTest(job=name):
                self.assertFalse(jobs[name]["concurrency"]["cancel-in-progress"])
        groups = [jobs[name]["concurrency"]["group"] for name in ("build", "staging", "production")]
        self.assertEqual(groups, ["deploy-build-${{ github.repository }}", "deploy-staging-${{ github.repository }}", "deploy-production-${{ github.repository }}"])

    def build_site(self, profile: str, prepare: Callable[[Path], None] | None = None, *, stub_npm: bool = True) -> tuple[subprocess.CompletedProcess[str], Path]:
        """Run the generated build step for a profile in a scratch workspace with a recording npm. Returns the result and the workspace."""
        script = next(step["run"] for step in workflows.deploy_workflow()["jobs"]["build"]["steps"] if step.get("name") == "Build the site without credentials")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "temp").mkdir()
        (root / "bin").mkdir()
        product = root / "product"
        for name in ("distribution", "website/dist", "site/dist"):
            (product / name).mkdir(parents=True)
        for name in ("distribution/wrangler.jsonc", "website/dist/index.html", "site/wrangler.jsonc", "site/dist/index.html"):
            (product / name).write_text(name)
        if stub_npm:
            stub = root / "bin/npm"
            stub.write_text("#!" + sys.executable + "\nimport json, os, sys\nwith open(os.environ['COMMAND_LOG'], 'a') as log:\n    log.write(json.dumps({'command': ['npm', *sys.argv[1:]], 'ignore_scripts': os.environ.get('npm_config_ignore_scripts')}) + '\\n')\n")
            stub.chmod(0o755)
        if prepare is not None:
            prepare(product)
        env = {**os.environ, "PROFILE": profile, "RUNNER_TEMP": str(root / "temp"), "COMMAND_LOG": str(root / "commands.jsonl"), "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"]}
        env.pop("npm_config_ignore_scripts", None)
        return subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=root, env=env, capture_output=True, text=True, check=False), root

    def commands(self, root: Path) -> list[dict[str, Any]]:
        log = root / "commands.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def packed(self, root: Path) -> set[str]:
        return {name.rstrip("/") for name in subprocess.run(["tar", "-tf", str(root / "temp/site.tar")], check=True, capture_output=True, text=True).stdout.splitlines()}

    def test_site_build_runs_the_profile_commands_when_the_product_has_no_build_script(self) -> None:
        result, root = self.build_site("ejm-ide")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call["command"] for call in self.commands(root)], IDE_BUILD)
        self.assertEqual(self.packed(root), {"distribution", "distribution/wrangler.jsonc", "website/dist", "website/dist/index.html"})

    def test_the_harness_site_installs_ejm_ui_first_then_builds_and_packs_site_dist(self) -> None:
        result, root = self.build_site("ejm-harness")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call["command"] for call in self.commands(root)], HARNESS_BUILD)
        self.assertEqual(self.packed(root), {"site/wrangler.jsonc", "site/dist", "site/dist/index.html"})

    def test_a_product_owned_site_build_replaces_the_profile_commands(self) -> None:
        def script(product: Path) -> None:
            build = product / ".github/site-build"
            build.parent.mkdir(parents=True)
            build.write_text('#!/usr/bin/env bash\nset -euo pipefail\npwd > "$RUNNER_TEMP/site-build-cwd"\necho "$npm_config_ignore_scripts" > "$RUNNER_TEMP/site-build-ignore"\n'
                             "mkdir -p website/dist\necho built > website/dist/index.html\n")
            build.chmod(0o755)
        result, root = self.build_site("ejm-ide", script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(root), [])
        self.assertEqual((root / "temp/site-build-cwd").read_text().strip(), str(root / "product"))
        self.assertEqual((root / "temp/site-build-ignore").read_text().strip(), "true")
        self.assertEqual(self.packed(root), {"distribution", "distribution/wrangler.jsonc", "website/dist", "website/dist/index.html"})

    def test_a_site_build_that_fails_or_is_not_a_plain_executable_file_never_replaces_the_fallback_silently(self) -> None:
        def failing(product: Path) -> None:
            build = product / ".github/site-build"
            build.parent.mkdir(parents=True)
            build.write_text("#!/usr/bin/env bash\nexit 7\n")
            build.chmod(0o755)
        result, root = self.build_site("ejm-ide", failing)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(self.commands(root), [])
        self.assertFalse((root / "temp/site.tar").exists())

        def not_executable(product: Path) -> None:
            (product / ".github").mkdir()
            (product / ".github/site-build").write_text("#!/usr/bin/env bash\nexit 7\n")

        def linked_script(product: Path) -> None:
            (product / ".github").mkdir()
            elsewhere = product.parent / "elsewhere"
            elsewhere.write_text("#!/usr/bin/env bash\nexit 7\n")
            elsewhere.chmod(0o755)
            (product / ".github/site-build").symlink_to(elsewhere)

        def linked_directory(product: Path) -> None:
            elsewhere = product.parent / "elsewhere"
            elsewhere.mkdir()
            (elsewhere / "site-build").write_text("#!/usr/bin/env bash\nexit 7\n")
            (elsewhere / "site-build").chmod(0o755)
            (product / ".github").symlink_to(elsewhere)

        def directory(product: Path) -> None:
            (product / ".github/site-build").mkdir(parents=True)

        for name, prepare in (("not executable", not_executable), ("symlinked script", linked_script), ("symlinked .github", linked_directory), ("a directory", directory)):
            with self.subTest(name):
                result, root = self.build_site("ejm-ide", prepare)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([call["command"] for call in self.commands(root)], IDE_BUILD)

    def test_every_site_profile_packs_its_declared_paths_and_unknown_profiles_fail(self) -> None:
        for profile in ("ejm-harness", "ejmlabs"):
            with self.subTest(profile=profile):
                result, root = self.build_site(profile)
                self.assertEqual(result.returncode, 0, result.stderr)
                _, _, files = SITES[profile]
                self.assertTrue(all(any(name == path or name.startswith(path + "/") for name in self.packed(root)) for path in files))
        result, root = self.build_site("ejm-unknown")
        self.assertEqual(result.returncode, 1)
        self.assertFalse((root / "temp/site.tar").exists())

    def test_action_pins_come_from_the_manifest_dependabot_updates(self) -> None:
        pins = workflows.action_pins(workflows.ROOT / "action.yml")
        self.assertEqual(set(pins), {"actions/checkout", "actions/setup-node", "astral-sh/setup-uv", "actions/attest-build-provenance",
                                     "actions/upload-artifact", "actions/download-artifact", "actions/cache/restore", "actions/cache/save",
                                     "github/codeql-action/init", "github/codeql-action/autobuild", "github/codeql-action/analyze"})
        constants = {workflows.CHECKOUT, workflows.NODE, workflows.UV, workflows.ATTEST, workflows.UPLOAD, workflows.DOWNLOAD, workflows.CACHE_RESTORE, workflows.CACHE_SAVE,
                     workflows.CODEQL_INIT, workflows.CODEQL_AUTOBUILD, workflows.CODEQL_ANALYZE}
        self.assertEqual(constants, set(pins.values()))
        # Dependabot bumps every cache action to one revision, so the two must agree.
        self.assertEqual(workflows.CACHE_RESTORE.split("@")[1], workflows.CACHE_SAVE.split("@")[1])
        used = set()
        for name in SHARED_WORKFLOWS:
            used.update(re.findall(r'(?m)^ +"uses": "((?!\./)[^"]+)"$', (workflows.ROOT / ".github/workflows" / name).read_text()))
        self.assertEqual(used, constants)
        manifest = (workflows.ROOT / "action.yml").read_text()
        # Every step of the manifest is disabled, so the file can never run an action.
        self.assertEqual(re.findall(r"(?m)^\s+- if: (.+)$", manifest), ["${{ false }}"] * len(pins))
        self.assertIn("using: composite", manifest)

    def test_the_pin_reader_accepts_only_full_commit_pins_listed_once(self) -> None:
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "action.yml"
            for text in (f"steps:\n  - uses: actions/checkout@{sha}\n", f"steps:\n  - uses: actions/checkout@{sha} # v6.0.1\n    if: false\n"):
                path.write_text(text)
                self.assertEqual(workflows.action_pins(path), {"actions/checkout": "actions/checkout@" + sha})
            for text in ("steps:\n  - uses: actions/checkout@v6\n", f"steps:\n  - uses: actions/checkout@{sha[:39]}\n", f"steps:\n  - uses: ./local@{sha}\n",
                         f"steps:\n  - uses: actions/checkout@{sha}\n  - uses: actions/checkout@{'b' * 40}\n", f"steps:\n  - uses: 'actions/checkout@{sha}'\n"):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaisesRegex(ValueError, "pinned to a full commit SHA"):
                    workflows.action_pins(path)

    def test_dependabot_waits_two_weeks_like_the_dependency_age_rule(self) -> None:
        text = (workflows.ROOT / ".github/dependabot.yml").read_text()
        self.assertEqual(re.findall(r"(?m)^\s+default-days: (\d+)$", text), ["14"])
        self.assertEqual(re.findall(r'(?m)^  - package-ecosystem: "([^"]+)"$', text), ["github-actions"])
        # The shared workflows' own pins are bumped with their manifest in one pull request; the caller pin of this repository moves only by hand.
        self.assertIn('dependency-name: "ejmlabs/.github*"', text)

    def test_attach_alone_holds_the_release_write_token_and_attestation_is_its_own_job(self) -> None:
        document = generated_yaml(workflows.yaml(workflows.attach_workflow()))
        self.assertEqual(set(document["jobs"]), {"attach", "attest"})
        attach, attest = document["jobs"]["attach"], document["jobs"]["attest"]
        # The job that writes the release holds neither OIDC nor attestation permissions, whether or not `attest` is set.
        self.assertEqual(attach["permissions"], {"contents": "write", "actions": "read"})
        self.assertNotIn("if", attach)
        check, download, attached = attach["steps"]
        self.assertEqual([step.get("uses", "").split("@")[0] for step in attach["steps"]], ["", "actions/download-artifact", ""])
        library = workflows.libraries("governance.py", "versioning.py") + "\n" + workflows.source("attach.py")
        for step, mode in ((check, "check"), (attached, "attach")):
            self.assertEqual(step["run"], workflows.python(library, mode, "python3 -I"))
        self.assertEqual(download["with"], {"name": "release-files", "run-id": "${{ inputs.build-run-id }}", "github-token": "${{ github.token }}", "path": "built"})
        # The verified digests, the manifest's included, leave the attach job as one output.
        self.assertEqual(attached["id"], "attached")
        self.assertEqual(attach["outputs"], {"digests": "${{ steps.attached.outputs.digests }}"})
        # The attestation job runs only on request, after attach, and cannot write contents or releases.
        self.assertEqual(attest["needs"], "attach")
        self.assertEqual(attest["if"], "${{ inputs.attest }}")
        self.assertEqual(attest["permissions"], {"contents": "read", "actions": "read", "id-token": "write", "attestations": "write"})
        again, confirm, action = attest["steps"]
        self.assertEqual(again, download)
        self.assertEqual(confirm["run"], workflows.python(library, "confirm", "python3 -I"))
        self.assertEqual(attest["env"]["ATTACHED_DIGESTS"], "${{ needs.attach.outputs.digests }}")
        self.assertNotIn("RELEASE_VERSION", attest["env"])
        # Attestation comes last: a changed or swapped file fails the confirm step first. Its subjects are the files confirmed.
        self.assertEqual(action["uses"].split("@")[0], "actions/attest-build-provenance")
        self.assertEqual(action["with"], {"subject-path": "built/*", "show-summary": False})
        self.assertEqual([step.get("uses", "").split("@")[0] for step in attest["steps"]], ["actions/download-artifact", "", "actions/attest-build-provenance"])
        # No job holds the release write token together with the permissions to sign.
        for job in (attach, attest):
            self.assertFalse(job["permissions"].get("contents") == "write" and ({"id-token", "attestations"} & set(job["permissions"])))
        verify = generated_yaml(workflows.yaml(workflows.verify_build_workflow()))["jobs"]["verify"]
        self.assertEqual(verify["permissions"], {"actions": "read"})
        self.assertEqual(len(verify["steps"]), 1)
        self.assertNotIn("uses", verify["steps"][0])

    def test_a_caller_job_grants_what_its_called_workflow_needs_and_no_more(self) -> None:
        """A called job cannot exceed its caller job's grant, so the grant must cover every job and should equal the union of them."""
        called = {"governance.yml": workflows.governance(), "draft-release.yml": workflows.release_workflow(), "verify-build.yml": workflows.verify_build_workflow(),
                  "attach-assets.yml": workflows.attach_workflow(), "warm-cache.yml": workflows.warm_workflow(), "deploy-site.yml": workflows.deploy_workflow()}
        rank = {"read": 1, "write": 2}
        seen: set[str] = set()
        for native in (False, True):
            for filename, text in consumer_workflows("a" * 40, native=native, cache=True, deploy=True).items():
                for name, job in re.findall(r"(?ms)^  ([\w-]+):\n(.*?)(?=^  \S|\Z)", text.split("\njobs:\n", 1)[1]):
                    reference = re.search(r"(?m)^    uses: ejmlabs/\.github/\.github/workflows/([\w-]+\.yml)@", job)
                    assert reference is not None
                    section = re.search(r"(?ms)^    permissions:\n(.*?)(?=^    \S|\Z)", job)
                    granted = dict(line.strip().split(": ") for line in section[1].splitlines()) if section else {}
                    needed: dict[str, str] = {}
                    for callee in called[reference[1]]["jobs"].values():
                        for key, level in callee["permissions"].items():
                            needed[key] = max(needed.get(key, level), level, key=rank.__getitem__)
                    with self.subTest(caller=filename, job=name, workflow=reference[1]):
                        self.assertEqual(granted, needed)
                    seen.add(reference[1])
        self.assertEqual(seen, set(called))

    def test_each_workflow_embeds_only_the_libraries_it_uses_and_defines_semver_before_it_is_called(self) -> None:
        for name in ("governance.yml", "draft-release.yml", "verify-build.yml", "attach-assets.yml"):
            document = generated_yaml((workflows.ROOT / ".github/workflows" / name).read_text())
            sources = {source for job in document["jobs"].values() for step in job.get("steps", [])
                       if (source := embedded_source(step.get("run", ""), step.get("env"))) is not None}
            self.assertTrue(sources, name)
            for source in sources:
                with self.subTest(workflow=name):
                    self.assertLessEqual(source.count("def semver("), 1)
                    # Every use of semver, and the standards file's own import guard, comes after the versioning library.
                    for use in re.finditer(r'(?<!def )\bsemver\(|"semver" not in globals\(\)', source):
                        self.assertIn("def semver(", source[: use.start()])
                    if name in ("verify-build.yml", "attach-assets.yml"):
                        # The two small helpers are all these need: no standards check is embedded.
                        self.assertNotIn("def standards_main", source)
                        self.assertNotIn("def workflow_problems", source)
        self.assertLess(len((workflows.ROOT / ".github/workflows/verify-build.yml").read_text()), 60_000)

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
        self.assertEqual(selector["run"].splitlines()[0], "python3 -I - select-harness <<'TRUSTED_PYTHON'")
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

    def test_job_level_keys_use_only_the_contexts_github_allows_there(self) -> None:
        # GitHub refuses to start a workflow whose job-level key reads a context it does not offer there, for
        # example the job context in a job's env, and every caller of that revision then fails at startup.
        default = {"github", "needs", "strategy", "matrix", "vars", "inputs"}
        allowed = {"env": default | {"secrets"}, "if": {"github", "needs", "vars", "inputs"}, "strategy": {"github", "needs", "vars", "inputs"},
                   "secrets": default | {"secrets"}}
        for name in SHARED_WORKFLOWS:
            document = generated_yaml((workflows.ROOT / ".github/workflows" / name).read_text())
            for job_name, job in document["jobs"].items():
                for key, value in job.items():
                    if key in ("steps", "outputs"):
                        continue
                    with self.subTest(workflow=name, job=job_name, key=key):
                        used = {match for expression in re.findall(r"\$\{\{(.*?)\}\}", json.dumps(value))
                                for match in re.findall(r"(?<![\w.])([a-z_]+)\.", re.sub(r"'[^']*'", "", expression))}
                        self.assertLessEqual(used, allowed.get(key, default))

    def test_standards_check_the_agent_files_against_the_templates_at_the_pin(self) -> None:
        job = self.governance["jobs"]["standards"]
        fetch, check = job["steps"][-2:]
        self.assertEqual((fetch, check), (workflows.SHARED_TEMPLATES, workflows.AGENT_SYNC))
        self.assertEqual(job["env"], {"PROFILE": "${{ needs.admission.outputs.profile }}"})
        # Plain git on the public repository: no checkout action, no token and no credential helper.
        self.assertNotIn("uses", fetch)
        self.assertEqual(fetch["if"], "${{ needs.admission.outputs.profile != '.github' }}")
        self.assertEqual(fetch["env"], {"WORKFLOW_REPOSITORY": "${{ job.workflow_repository }}", "WORKFLOW_SHA": "${{ job.workflow_sha }}", "GIT_TERMINAL_PROMPT": "0"})
        self.assertEqual(check["env"], {"WORKFLOW_SHA": "${{ job.workflow_sha }}"})
        self.assertIn('-c credential.helper= fetch -q --depth 1 --no-tags https://github.com/ejmlabs/.github.git "$WORKFLOW_SHA"', fetch["run"])
        self.assertNotIn("${{", fetch["run"] + check["run"].split("<<")[0])
        self.assertEqual(embedded_source(check["run"]), workflows.source("sync_agents.py"))
        self.assertIn('--check --templates "$templates" product', check["run"])

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
        for profile in ("ejm-chess", "ejm-cli", "ejm-harness", "ejm-ide", "ejm-rightkit-fs", "ejm-ui", "ejmlabs", ".github"):
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

    def test_chess_requires_its_own_quality_command_and_skips_rust_tools(self) -> None:
        status, calls = run_gate(workflows.GATE["run"], "ejm-chess", {})
        self.assertNotEqual(status, 0)
        self.assertEqual(calls, [])
        status, calls = run_gate(workflows.RUST_TOOLS["run"], "ejm-chess", {})
        self.assertEqual((status, calls), (0, []))

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
        trusted_sources.add(workflows.libraries("governance.py", "versioning.py", "standards.py", "prepare.py") + "\n" + workflows.source("release.py"))
        trusted_sources.add(workflows.libraries("governance.py") + "\n" + workflows.source("pr_guidance.py").replace("from governance import REQUIRED_CONTEXTS, GitHub, checked_sha, same_repository\n", ""))
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
                        source = embedded_source(script, step.get("env"))
                        if source is not None:
                            self.assertIn(source, trusted_sources)
                            self.assertRegex(script.splitlines()[0], r"^python3 -I - (?:admit|verify|finish|select-harness|ui-pin)? <<\x27TRUSTED_PYTHON\x27$")
                            entry = shlex.split(script.splitlines()[0])[3:-1]
                            expected = workflows.run("trusted", workflows.python(source, " ".join(entry)))
                            self.assertEqual(script, expected["run"])
                            for key, value in expected.get("env", {}).items():
                                self.assertEqual(step.get("env", {}).get(key), value)
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

    def test_the_gate_and_the_repository_settings_require_the_same_two_contexts(self) -> None:
        self.assertEqual(governance.REQUIRED_CONTEXTS, ("Quality", "Repository standards"))
        self.assertEqual(settings.CONTEXTS, governance.REQUIRED_CONTEXTS)

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
        caller = consumer_workflows("a" * 40)["pr.yml"]
        found = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", caller)
        assert found is not None
        triggers = found[1]
        self.assertEqual(re.findall(r"(?m)^  (\w+):", triggers), ["pull_request"])
        self.assertIn("types: [opened, reopened, synchronize, ready_for_review, converted_to_draft, labeled]", caller)
        self.assertNotIn("issue_comment", caller)
        admission = self.governance["jobs"]["admission"]["if"]
        self.assertIn("github.event_name == 'pull_request'", admission)
        self.assertIn("gate:approve", admission)
        self.assertIn("gate:revoke", admission)
        self.assertNotIn("issue_comment", admission)
        self.assertNotIn("startsWith(github.event.comment.body", admission)

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
                        entry = shlex.split(script.splitlines()[0])[3]
                        self.assertIn(entry, ("admit", "verify", "finish"))
                        if entry == "finish":
                            publishers.append((document["name"], job, entry))
        self.assertEqual(publishers, [(self.governance["name"], "finish", "finish")])

    def test_the_gate_has_no_review_job_and_reads_only_the_harness_secret(self) -> None:
        self.assertEqual(set(self.governance["jobs"]), {"admission", "prepare", "quality", "registry", "standards", "finish", "guidance", "guidance_finish"})
        self.assertEqual(set(re.findall(r"secrets\.(\w+)", json.dumps(self.governance["jobs"]))), {"EJM_HARNESS_TOKEN"})
        # The retired model key is no longer declared, because no caller passes it and nothing reads it.
        declared = self.governance["on"]["workflow_call"]["secrets"]
        self.assertEqual(declared, {"EJM_HARNESS_TOKEN": {"required": False}})
        self.assertNotIn("XAI_API_KEY", (workflows.ROOT / ".github/workflows/governance.yml").read_text())
        for job in self.governance["jobs"].values():
            self.assertNotIn("pull_request_target", job.get("if", ""))

    def test_no_job_declares_an_environment(self) -> None:
        environments = [(document["name"], name, job["environment"])
                        for document in (self.governance, self.release)
                        for name, job in document["jobs"].items() if "environment" in job]
        self.assertEqual(environments, [])

    def test_prepare_rechecks_admission_first_and_no_condition_reads_runner_state(self) -> None:
        prepare = self.governance["jobs"]["prepare"]
        self.assertEqual(prepare["steps"][0], workflows.VERIFY)
        self.assertEqual(prepare["steps"][-2], workflows.VERIFY)
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
                # One call and no tag ref: the draft targets the commit, and the tag appears when a human publishes it.
                self.assertEqual(commands, [
                    ["release", "create", tag, "--repo", "ejmlabs/ejmlabs", "--target", "a" * 40, "--draft", "--title", tag,
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
        library = workflows.libraries("governance.py", "versioning.py", "standards.py", "prepare.py") + "\n" + workflows.source("release.py")
        self.assertEqual(embedded_source(draft["steps"][1]["run"], draft["steps"][1].get("env")), library)
        self.assertNotIn("select-harness", draft["steps"][1]["run"].splitlines()[0])

    def test_embedded_expressions_survive_as_literal_python_data(self) -> None:
        literal = "${{ inputs.commit }} / ${{ secrets.EXAMPLE }}"
        source = "import sys\nprint(" + repr(literal) + ")\nprint(sys.argv[1])\n"
        script = workflows.python(source, "fixture")
        self.assertNotIn("${{", script)
        self.assertNotIn("${{", workflows.yaml({"run": script}))
        self.assertEqual(embedded_source(script), source)
        result = subprocess.run(["bash", "-e", "-c", script], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout, literal + "\nfixture\n")

    def test_large_trusted_payload_runs_and_rejects_invalid_or_missing_chunks(self) -> None:
        payload = "".join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(782))[:50_000]
        source = "payload = " + repr(payload) + "\nprint(len(payload))\n"
        step = workflows.run("large", workflows.python(source))
        chunks = step["env"]
        self.assertGreaterEqual(len(chunks), 2)
        env = {**os.environ, "EJM_TRUSTED_SCRIPT_0": "poisoned", **chunks}
        result = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "50000\n")
        env["EJM_TRUSTED_SCRIPT_0"] = "!" + chunks["EJM_TRUSTED_SCRIPT_0"][1:]
        result = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Only base64 data is allowed", result.stderr)
        del env["EJM_TRUSTED_SCRIPT_0"]
        result = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("EJM_TRUSTED_SCRIPT_0", result.stderr)

    def test_real_chunked_workflow_commands_reconstruct_trusted_source(self) -> None:
        documents = (workflows.governance(), workflows.release_workflow(), workflows.verify_build_workflow(),
                     workflows.attach_workflow(), workflows.warm_workflow(), workflows.deploy_workflow())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / "python3"
            python.write_text(
                f"#!{sys.executable}\n"
                "import builtins, os, sys\n"
                "from pathlib import Path\n"
                "real = builtins.compile\n"
                "def capture(source, filename, mode, *args, **kwargs):\n"
                "    if filename == 'trusted-workflow.py':\n"
                "        Path(os.environ['CAPTURE']).write_bytes(source)\n"
                "        return real('', filename, mode)\n"
                "    return real(source, filename, mode, *args, **kwargs)\n"
                "builtins.compile = capture\n"
                "exec(real(sys.stdin.read(), '<wrapper>', 'exec'))\n"
            )
            python.chmod(0o755)
            checked = 0
            for document in documents:
                for job in document["jobs"].values():
                    for step in job.get("steps", []):
                        chunks = {key: value for key, value in step.get("env", {}).items()
                                  if key.startswith("EJM_TRUSTED_SCRIPT_")}
                        if not chunks:
                            continue
                        with self.subTest(step=step["name"]):
                            captured = root / "source.py"
                            captured.unlink(missing_ok=True)
                            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                                   "CAPTURE": str(captured), "PROFILE": "example", **chunks}
                            result = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=root, env=env,
                                                    capture_output=True, text=True, check=False)
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(captured.read_text(), embedded_source(step["run"], chunks))
                            checked += 1
            self.assertGreater(checked, 0)

    def test_generator_rejects_oversize_before_any_write(self) -> None:
        from unittest import mock

        self.assertEqual(len(workflows.run("exact", "x" * workflows.MAX_RUN_CHARS)["run"]), workflows.MAX_RUN_CHARS)
        with self.assertRaisesRegex(ValueError, "oversized run step"):
            workflows.run("too long", "x" * (workflows.MAX_RUN_CHARS + 1))
        with mock.patch.object(workflows, "MAX_WORKFLOW_BYTES", 1), mock.patch.object(Path, "write_bytes") as write:
            with self.assertRaisesRegex(SystemExit, "exceeds .*byte budget"):
                workflows.main()
            write.assert_not_called()

    def test_workflow_checkout_remains_lf_with_autocrlf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "core.autocrlf", "true"], cwd=root, check=True)
            (root / ".gitattributes").write_bytes((workflows.ROOT / ".gitattributes").read_bytes())
            path = root / ".github/workflows/generated.yml"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"name: sample\non: push\n")
            subprocess.run(["git", "add", ".gitattributes", ".github/workflows/generated.yml"], cwd=root, check=True, capture_output=True)
            path.unlink()
            subprocess.run(["git", "checkout", "--", ".github/workflows/generated.yml"], cwd=root, check=True)
            self.assertEqual(path.read_bytes(), b"name: sample\non: push\n")


def step_shell(step: dict[str, Any], cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    """Run a generated step's script the way GitHub runs a bash step, with only the named variables."""
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]], cwd=cwd, capture_output=True, text=True,
                          check=False, env={"PATH": os.environ["PATH"], **env})


class AgentSyncStepTests(unittest.TestCase):
    def test_the_fetch_refuses_any_other_repository_or_revision_before_it_writes(self) -> None:
        for repository, sha in (("someone/.github", "a" * 40), ("ejmlabs/.github", "a" * 39), ("ejmlabs/.github", ""), ("ejmlabs/.github", "A" * 40),
                                ("ejmlabs/.github", "a" * 40 + "\n")):
            with self.subTest(repository=repository, sha=sha), tempfile.TemporaryDirectory() as directory:
                result = step_shell(workflows.SHARED_TEMPLATES, Path(directory), WORKFLOW_REPOSITORY=repository, WORKFLOW_SHA=sha)
                self.assertEqual(result.returncode, 1)
                self.assertIn("::error::The shared gate must run from ejmlabs/.github at a full commit SHA", result.stdout)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def layout(self, directory: str) -> Path:
        """This repository's agent files as the admitted product, and its templates as the fetched shared copy."""
        work = Path(directory)
        for name in ("AGENTS.md", ".agents", ".claude", "templates/agents"):
            source, target = workflows.ROOT / name, work / "product" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree(source, target, symlinks=True) if source.is_dir() else shutil.copy2(source, target))
        shutil.copytree(workflows.ROOT / "templates/agents", work / "shared/templates/agents")
        return work

    def test_the_check_passes_in_sync_and_names_drift_with_the_fix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = self.layout(directory)
            for profile in (".github", "ejm-ui"):
                with self.subTest(profile=profile):
                    result = step_shell(workflows.AGENT_SYNC, work, PROFILE=profile, WORKFLOW_SHA="a" * 40)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            skill = work / "product/.agents/skills/ejmlabs-writing/SKILL.md"
            skill.write_text(skill.read_text() + "A local edit.\n")
            drift = step_shell(workflows.AGENT_SYNC, work, PROFILE="ejm-ui", WORKFLOW_SHA="a" * 40)
            self.assertEqual(drift.returncode, 1)
            self.assertIn("ejmlabs-writing: differs from the shared skill", drift.stderr)
            self.assertIn("::error::Shared agent files differ from ejmlabs/.github at " + "a" * 40, drift.stdout)
            self.assertIn("python3 scripts/sync_agents.py PATH_TO_THIS_REPOSITORY", drift.stdout)

    def test_the_check_reads_the_pinned_templates_and_fails_closed_without_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = self.layout(directory)
            # A consumer is held to the fetched templates, never to templates its own PR carries.
            rules = work / "product/templates/agents/house-rules.md"
            rules.write_text(rules.read_text() + "A rule the PR added.\n")
            self.assertEqual(step_shell(workflows.AGENT_SYNC, work, PROFILE="ejm-ui", WORKFLOW_SHA="a" * 40).returncode, 0)
            self.assertEqual(step_shell(workflows.AGENT_SYNC, work, PROFILE=".github", WORKFLOW_SHA="a" * 40).returncode, 1)
            shutil.rmtree(work / "shared")
            missing = step_shell(workflows.AGENT_SYNC, work, PROFILE="ejm-ui", WORKFLOW_SHA="a" * 40)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("not a shared templates directory", missing.stderr)


if __name__ == "__main__":
    unittest.main()
