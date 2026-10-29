import ast
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
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
                        self.assertEqual(set(declared), set(forwarded))

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
        for name, job in warm["jobs"].items():
            with self.subTest(job=name):
                gate = self.governance["jobs"][name]
                self.assertEqual(job["permissions"], {"contents": "read"})
                self.assertNotIn("secrets.", json.dumps(job))
                self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/main'", job["if"])
                # Same environment and build steps as the gate, so the saved artifacts are the ones the gate reuses.
                self.assertEqual({key: value.replace("github.event.repository.name", "needs.admission.outputs.profile") for key, value in job["env"].items()}, gate["env"])
                steps = [step for step in gate["steps"] if step not in (workflows.ARTIFACT, workflows.EXTRACT) and not step.get("uses", "").startswith("actions/cache/")
                         and step.get("name") != "Discard any cache that is not main's exact build"]
                self.assertEqual(json.dumps(job["steps"][-1 - len(steps):-1]).replace("github.event.repository.name", "needs.admission.outputs.profile"), json.dumps(steps))
                save, restore = job["steps"][-1], next(step for step in gate["steps"] if step.get("id") == "cache")
                self.assertTrue(save["uses"].startswith("actions/cache/save@"))
                self.assertEqual(save["with"]["path"].replace("github.event.repository.name", "needs.admission.outputs.profile"), restore["with"]["path"])
                self.assertEqual(save["with"]["key"].replace("github.sha", "needs.admission.outputs.base"), restore["with"]["key"])
                checkouts = [step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")]
                self.assertEqual([step["with"]["path"] for step in checkouts], ["product", "ejm-harness", "ejm-ui"])
                self.assertTrue(all(step["with"]["persist-credentials"] is False for step in checkouts))
        self.assertEqual(warm["jobs"]["quality"]["strategy"]["matrix"]["os"].replace("github.event.repository.name", "needs.admission.outputs.profile"),
                         self.governance["jobs"]["quality"]["strategy"]["matrix"]["os"])

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

    def test_gate_restores_only_an_exact_main_build_and_discards_anything_else(self) -> None:
        for name, cache_id in (("quality", "cache"), ("registry", "cache")):
            with self.subTest(job=name):
                steps = self.governance["jobs"][name]["steps"]
                restore = next(step for step in steps if step.get("uses", "").startswith("actions/cache/"))
                self.assertTrue(restore["uses"].startswith("actions/cache/restore@"), "the admitted gate must never save a cache")
                self.assertEqual(restore["id"], cache_id)
                self.assertNotIn("restore-keys", restore["with"])
                self.assertEqual(restore["with"]["key"], "gate-" + name + "-${{ runner.os }}-${{ needs.admission.outputs.base }}")
                discard = steps[steps.index(restore) + 1]
                self.assertIn("steps.cache.outputs.cache-hit != 'true'", discard["if"])
                self.assertEqual(discard["env"]["TARGET_DIR"], restore["with"]["path"].splitlines()[-1])
                # The restore follows extraction, which marks every admitted source newer than any cached build.
                self.assertLess(steps.index(next(step for step in steps if step.get("name") == "Extract source data safely")), steps.index(restore))
                self.assertFalse(any(step.get("uses", "").startswith("actions/cache/save") for step in steps))

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
                        if name == "ai" and step["name"] in {"Install the pinned reviewer", "Automated review", "Require the review model key"}:
                            if step["name"] == "Install the pinned reviewer":
                                installer = embedded_source(script)
                                assert installer is not None
                                self.assert_data_only_python(installer)
                                shell = script.split("TRUSTED_PYTHON\n", 1)[1]
                                self.assertEqual(script.splitlines()[0], 'cd "$RUNNER_TEMP"')
                                commands = {"set", "{", "python3", "$RUNNER_TEMP/reviewer-venv/bin/python", "}", "reviewer_status=$?", "if", "printf", "exit", "fi"}
                            elif step["name"] == "Automated review":
                                self.assertIsNone(embedded_source(script))
                                shell = script
                                commands = {"printf", "cd", "GITHUB_EVENT_NAME=pull_request"}
                            else:
                                shell = script
                                commands = {"test"}
                            for line in shell.splitlines():
                                self.assertIn(shlex.split(line)[0], commands)
                            continue
                        source = embedded_source(script)
                        if source is not None:
                            self.assertIn(source, trusted_sources)
                            self.assertRegex(script.splitlines()[0], r"^python3 - (?:admit|verify|finish|labels|relabel|select-harness|ui-pin)? <<\x27TRUSTED_PYTHON\x27$")
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

    def test_ai_runs_the_pinned_action_runner_before_the_label_gate(self) -> None:
        jobs = self.governance["jobs"]
        ai = jobs["ai"]
        self.assertNotIn("strategy", ai)
        reviews = [step for step in ai["steps"] if step.get("name") == "Automated review"]
        self.assertEqual(len(reviews), 1)
        settings = reviews[0]["env"]
        self.assertEqual(workflows.REVIEWER_MODEL, "xai/grok-4.5")
        self.assertEqual(workflows.REVIEWER_FALLBACK_MODELS, "[]")
        self.assertEqual(settings["CONFIG__MODEL"], workflows.REVIEWER_MODEL)
        self.assertEqual(settings["CONFIG__FALLBACK_MODELS"], workflows.REVIEWER_FALLBACK_MODELS)
        for name in ("OPENAI" + "__KEY", "OPENAI" + "__API_BASE", "LITELLM__EXTRA_HEADERS", "CONFIG__CUSTOM_MODEL_MAX_TOKENS"):
            self.assertNotIn(name, settings)
        self.assertFalse(any("API_BASE" in name for name in settings))
        self.assertEqual(settings["CONFIG__REASONING_EFFORT"], "high")
        self.assertIn("-I -m pr_agent.servers.github_action_runner", reviews[0]["run"])
        self.assertEqual(ai["needs"], "admission")
        # The label gate runs only after the review job succeeded for this admission.
        self.assertEqual(jobs["labels"]["needs"], ["admission", "ai"])
        self.assertNotIn("always()", jobs["labels"]["if"])
        self.assertIn("needs.admission.outputs.run == 'true'", jobs["labels"]["if"])
        self.assertEqual(jobs["labels"]["permissions"], {"pull-requests": "read"})
        self.assertNotIn("secrets.", json.dumps(jobs["labels"]))
        self.assertTrue({"ai", "labels"} <= set(jobs["finish"]["needs"]))

    def test_public_reviewer_text_uses_neutral_names(self) -> None:
        denied = ("gpt", "glm-5.3", "kimi-k2.7-code", "opencode", "codex", "pr-agent", "pr_agent", "xai", "grok",
                  "openai", "litellm", "setup-uv", "actions/*")
        texts = {name: (workflows.ROOT / name).read_text() for name in ("docs/operations.md", "CHANGELOG.md")}
        texts.update({str(file.relative_to(workflows.ROOT)): file.read_text() for file in (workflows.ROOT / "review").glob("*.md")})
        texts.update({f"step {document['name']}.{job}.{index}": step["name"] for document in (self.governance, self.release)
                      for job, config in document["jobs"].items()
                      for index, step in enumerate(config["steps"]) if "name" in step})
        for name, text in texts.items():
            with self.subTest(file=name):
                lowered = text.replace("`XAI_API_KEY`", "`review model key secret`").lower()
                for term in denied:
                    self.assertNotIn(term, lowered)
                self.assertNotRegex(lowered, r"\b(?:sol|python|pip)\b")

    def test_review_step_gets_only_the_job_token_and_preserves_admission_rechecks(self) -> None:
        ai = self.governance["jobs"]["ai"]
        review = next(step for step in ai["steps"] if step.get("name") == "Automated review")
        self.assertEqual(review["env"]["GITHUB_TOKEN"], "${{ github.token }}")
        self.assertEqual(ai["env"]["GH_TOKEN"], "${{ github.token }}")
        checks = [step for step in ai["steps"] if step.get("name") == "Recheck current human admission"]
        self.assertEqual(len(checks), 2)
        self.assertEqual(ai["steps"][1], checks[0])
        self.assertEqual(ai["steps"][-1], checks[-1])
        self.assertLess(ai["steps"].index(checks[0]), ai["steps"].index(review))
        for step in checks:
            self.assertNotIn("GH_TOKEN", step.get("env", {}))
            self.assertNotIn("GITHUB_TOKEN", step.get("env", {}))

    def test_automated_review_can_only_gate_and_never_create_an_approval(self) -> None:
        ai = self.governance["jobs"]["ai"]
        # Comments and labels only: no source writes, statuses, or PR code checkout next to the model key.
        self.assertEqual(ai["permissions"], {"contents": "read", "pull-requests": "write", "statuses": "read"})
        self.assertFalse(any("uses" in step for step in ai["steps"]))
        tree = ast.parse(workflows.source("governance.py"))
        approvals = [node for node in ast.walk(tree) if isinstance(node, ast.Dict) and any(
            isinstance(key, ast.Constant) and key.value == "event" and isinstance(value, ast.Constant) and value.value == "APPROVE"
            for key, value in zip(node.keys, node.values, strict=True))]
        self.assertEqual(len(approvals), 1)
        admit = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "admit")
        human_approval = next(node for node in ast.walk(admit) if isinstance(node, ast.If) and ast.unparse(node.test) == "action == 'approve'")
        self.assertIn(approvals[0], list(ast.walk(human_approval)))
        contexts = next(node for node in tree.body if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CONTEXTS" for target in node.targets))
        self.assertIn("AI review", ast.literal_eval(contexts.value))

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

    def test_generated_workflow_retains_only_the_admitted_review_route(self) -> None:
        self.assertEqual(self.governance, workflows.governance())
        self.assertEqual(set(self.governance["on"]), {"workflow_call"})
        self.assertNotIn("codex" + "-action", json.dumps(self.governance))
        ai = self.governance["jobs"]["ai"]
        self.assertIn("needs.admission.outputs.run == 'true'", ai["if"])
        caller = consumer_workflows("a" * 40, current=True)["pr.yml"]
        found = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", caller)
        assert found is not None
        triggers = found[1]
        self.assertEqual(re.findall(r"(?m)^  (\w+):", triggers), ["issue_comment", "pull_request_target"])
        # Label removal only re-evaluates; it runs base-branch workflow code and never admits.
        self.assertIn("  pull_request_target:\n    types: [unlabeled]\n", triggers)
        self.assertNotRegex(caller, r"(?m)^\s+pull_request:")
        found = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", consumer_workflows("a" * 40)["pr.yml"])
        assert found is not None
        triggers = found[1]
        self.assertEqual(re.findall(r"(?m)^  (\w+):", triggers), ["issue_comment"])
        admission = self.governance["jobs"]["admission"]["if"]
        self.assertIn("github.event_name == 'issue_comment'", admission)

    def test_label_override_job_reads_state_only_and_never_runs_pr_code(self) -> None:
        jobs = self.governance["jobs"]
        override = jobs["override"]
        self.assertEqual(override["if"], "${{ github.run_attempt == 1 && github.event_name == 'pull_request_target' && github.event.action == 'unlabeled' }}")
        self.assertNotIn("needs", override)
        self.assertEqual(override["permissions"], {"contents": "read", "pull-requests": "read", "statuses": "write"})
        self.assertNotIn("secrets.", json.dumps(override))
        self.assertFalse(any("uses" in step for step in override["steps"]))
        self.assertEqual(override["concurrency"]["group"], "human-command-${{ github.repository }}-${{ github.event.pull_request.number }}")
        self.assertEqual([shlex.split(step["run"].splitlines()[0])[2] for step in override["steps"]], ["relabel"])
        for name, job in jobs.items():
            if name != "override":
                self.assertNotIn("pull_request_target", job["if"])

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
            if name == "review/reviewer-requirements.txt":
                continue
            content = (workflows.ROOT / name).read_bytes()
            for value in retired:
                with self.subTest(file=name, value=value):
                    self.assertNotIn(value.encode(), content)

    def test_only_finish_and_the_label_override_publish_the_ai_review_result(self) -> None:
        finish = self.governance["jobs"]["finish"]
        self.assertEqual(finish["env"]["JOB_RESULTS"], "${{ toJSON(needs) }}")
        self.assertIn("ai", finish["needs"])
        publishers = []
        for document in (self.governance, self.release):
            for job, config in document["jobs"].items():
                for step in config["steps"]:
                    script = step.get("run", "")
                    if embedded_source(script) == workflows.source("governance.py"):
                        entry = shlex.split(script.splitlines()[0])[2]
                        self.assertIn(entry, ("admit", "verify", "finish", "labels", "relabel"))
                        if entry in ("finish", "relabel"):
                            publishers.append((document["name"], job, entry))
        self.assertEqual(publishers, [(self.governance["name"], "finish", "finish"), (self.governance["name"], "override", "relabel")])

    def test_model_key_is_confined_to_the_single_review_step_environment(self) -> None:
        locations: list[tuple[str | int, ...]] = []

        def find(value: Any, path: tuple[str | int, ...] = ()) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    find(item, (*path, key))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    find(item, (*path, index))
            elif isinstance(value, str) and re.search(r"\$\{\{\s*secrets\.XAI_API_KEY\s*\}\}", value):
                locations.append(path)

        find(self.governance)
        steps = self.governance["jobs"]["ai"]["steps"]
        index = next(index for index, step in enumerate(steps) if step.get("name") == "Automated review")
        self.assertEqual(locations, [("jobs", "ai", "steps", index, "env", "XAI__KEY")])
        guard = next(step for step in steps if "HAS_MODEL_KEY" in step.get("env", {}))
        self.assertEqual(guard["env"]["HAS_MODEL_KEY"], "${{ secrets.XAI_API_KEY != '' }}")
        self.assertEqual(self.governance["on"]["workflow_call"]["secrets"]["XAI_API_KEY"], {"required": False})
        self.assertNotIn("OPENAI" + "_API_KEY", json.dumps(self.governance))
        self.assertEqual(guard["run"], 'test "$HAS_MODEL_KEY" = true\n')
        self.assertLess(steps.index(guard), index)

    def test_only_the_review_job_declares_the_protected_environment(self) -> None:
        environments = [(document["name"], name, job["environment"])
                        for document in (self.governance, self.release)
                        for name, job in document["jobs"].items() if "environment" in job]
        self.assertEqual(environments, [(self.governance["name"], "ai", "legacy-review")])

    def test_review_settings_keep_the_model_and_otherwise_documented_defaults(self) -> None:
        ai = self.governance["jobs"]["ai"]
        review = next(step for step in ai["steps"] if step.get("name") == "Automated review")
        self.assertEqual(review["env"], {
            "GITHUB_TOKEN": "${{ github.token }}", "XAI__KEY": "${{ secrets.XAI_API_KEY }}",
            "CONFIG__MODEL": "xai/grok-4.5", "CONFIG__FALLBACK_MODELS": "[]", "CONFIG__REASONING_EFFORT": "high",
            "CONFIG__AI_TIMEOUT": "225", "CONFIG__MAX_MODEL_TOKENS": "160000", "CONFIG__MAX_OUTPUT_TOKENS": "16000",
            "CONFIG__LOG_LEVEL": "INFO", "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "CONFIG__USE_REPO_SETTINGS_FILE": "false", "CONFIG__USE_GLOBAL_SETTINGS_FILE": "false",
            "GITHUB_ACTION_CONFIG__AUTO_REVIEW": "true", "GITHUB_ACTION_CONFIG__AUTO_DESCRIBE": "false",
            "GITHUB_ACTION_CONFIG__AUTO_IMPROVE": "false", "GITHUB_ACTION_CONFIG__ENABLE_OUTPUT": "true",
            "PR_REVIEWER__ENABLE_REVIEW_LABELS_SECURITY": "true", "PR_REVIEWER__ENABLE_REVIEW_LABELS_EFFORT": "true",
            "PR_REVIEWER__REQUIRE_MERGE_RECOMMENDATION": "true",
            "PR_REVIEWER__EXTRA_INSTRUCTIONS": workflows.REVIEWER_EXTRA_INSTRUCTIONS,
        })
        # Fail-on-tool-errors stays at its default (true), so a run without a review fails the job.
        self.assertNotIn("FAIL_ON_TOOL_ERRORS", json.dumps(self.governance))
        self.assertNotIn("DEBUG", json.dumps(ai))
        self.assertEqual(ai["timeout-minutes"], 12)

    def test_review_instruction_covers_only_full_hash_pins_of_this_repository(self) -> None:
        text = workflows.REVIEWER_EXTRA_INSTRUCTIONS
        for required in ("ejmlabs/.github/.github/workflows/", "40 hex characters", "`standards-ref`", "not a full 40-character commit hash",
                         "another repository or path", "older revision", "new permissions, secrets or triggers"):
            self.assertIn(required, text)
        # The wording is neutral, contains no expression and stays one bounded paragraph.
        self.assertNotIn("${{", text)
        self.assertNotIn("\n", text)
        self.assertLess(len(text), 1000)
        lowered = text.lower()
        for term in ("gpt", "grok", "xai", "openai", "litellm", "pr-agent", "pr_agent"):
            self.assertNotIn(term, lowered)

    def test_review_verdict_reaches_the_label_gate_only_through_env(self) -> None:
        jobs = self.governance["jobs"]
        review = next(step for step in jobs["ai"]["steps"] if step.get("name") == "Automated review")
        self.assertEqual(review["id"], "review")
        self.assertEqual(jobs["ai"]["outputs"], {"review": "${{ steps.review.outputs.review }}"})
        self.assertEqual(jobs["labels"]["env"]["REVIEW_OUTPUT"], "${{ needs.ai.outputs.review }}")
        # Model output is never interpolated into a script or any other field.
        for name, job in jobs.items():
            for step in job["steps"]:
                self.assertNotIn("outputs.review", json.dumps({k: v for k, v in step.items() if k != "env"}))
            if name not in ("ai", "labels"):
                self.assertNotIn("outputs.review", json.dumps(job))
        self.assertEqual(json.dumps(jobs["labels"]).count("outputs.review"), 1)
        self.assertEqual([shlex.split(step["run"].splitlines()[0])[2] for step in jobs["labels"]["steps"]], ["labels"])

    def test_review_step_runs_the_documented_runner_on_an_opened_event_and_fails_closed(self) -> None:
        review = next(step for step in self.governance["jobs"]["ai"]["steps"] if step.get("name") == "Automated review")
        for status in (0, 1):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                binary = temporary / "reviewer-venv/bin/python"
                binary.parent.mkdir(parents=True)
                binary.write_text("#!" + sys.executable + "\n" + """import json, os, sys
from pathlib import Path
assert sys.argv[1:] == ['-I', '-m', 'pr_agent.servers.github_action_runner']
assert Path.cwd() == Path(os.environ['RUNNER_TEMP'])
assert os.environ['GITHUB_EVENT_NAME'] == 'pull_request'
Path(os.environ['RUNNER_TEMP'], 'seen.json').write_text(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
sys.exit(int(os.environ['REVIEW_EXIT']))
""")
                binary.chmod(0o755)
                env = {**os.environ, "RUNNER_TEMP": str(temporary), "GITHUB_REPOSITORY": "ejmlabs/ejm-cli", "PR_NUMBER": "12",
                       "GITHUB_EVENT_NAME": "issue_comment", "REVIEW_EXIT": str(status)}
                completed = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", review["run"]],
                                           cwd=directory, env=env, capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, status, completed.stderr)
                self.assertEqual(json.loads((temporary / "seen.json").read_text()), {
                    "action": "opened", "pull_request": {"url": "https://api.github.com/repos/ejmlabs/ejm-cli/pulls/12"}})

    def test_install_embeds_the_complete_hash_lock_without_credentials(self) -> None:
        steps = self.governance["jobs"]["ai"]["steps"]
        install = next(step for step in steps if step.get("name") == "Install the pinned reviewer")
        review = next(step for step in steps if step.get("name") == "Automated review")
        self.assertFalse(any(step.get("uses", "").startswith("astral-sh/setup-uv@") for step in steps))
        self.assertLess(steps.index(install), steps.index(review))
        self.assertNotIn("secrets.", json.dumps(install))
        self.assertEqual(install["env"], {"GH_TOKEN": "", "GITHUB_TOKEN": "", "PIP_CONFIG_FILE": "/dev/null"})
        script = install["run"]
        self.assertTrue(script.startswith('cd "$RUNNER_TEMP"\n'))
        self.assertIn('python3 -m venv "$RUNNER_TEMP/reviewer-venv"', script)
        self.assertIn('"$RUNNER_TEMP/reviewer-venv/bin/python" -m pip install --isolated --no-cache-dir --require-hashes --no-deps --only-binary=:all:', script)
        self.assertIn('> "$RUNNER_TEMP/reviewer-install.log" 2>&1', script)
        lock = (workflows.ROOT / "review/reviewer-requirements.txt").read_text()
        installer = embedded_source(script)
        assert installer is not None
        calls = [node for node in ast.walk(ast.parse(installer)) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "write_text"]
        self.assertEqual([ast.literal_eval(node.args[0]) for node in calls], [lock])
        pins = [line for line in lock.splitlines() if line and not line.startswith("#")]
        self.assertEqual(len(pins), 100)
        for pin in pins:
            self.assertRegex(pin, r"^[a-z0-9_.-]+==\S+ --hash=sha256:[0-9a-f]{64}$")
        for package, version in (("pr-agent", "0.48.0"), ("litellm", "1.105.0")):
            matches = [pin for pin in pins if pin.startswith(package + "==")]
            self.assertEqual(len(matches), 1)
            self.assertRegex(matches[0], rf"^{package}=={re.escape(version)} --hash=sha256:[0-9a-f]{{64}}$")

    def test_prepare_and_review_reject_runner_debug_before_other_steps(self) -> None:
        for name in ("prepare", "ai"):
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

    def test_generated_install_logs_are_private_on_success_and_failure(self) -> None:
        install = next(step for step in self.governance["jobs"]["ai"]["steps"] if step.get("name") == "Install the pinned reviewer")
        marker = "PRIVATE_INSTALL_LOG_SENTINEL_2138"
        for status in (0, 42):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                bin_dir = root / "bin"
                bin_dir.mkdir()
                bootstrap = bin_dir / "python3"
                bootstrap.write_text("#!" + sys.executable + "\n" + """import os, sys
from pathlib import Path
if sys.argv[1:] == ['-m', 'venv', str(Path(os.environ['RUNNER_TEMP'], 'reviewer-venv'))]:
    assert Path.cwd() == Path(os.environ['RUNNER_TEMP'])
    assert os.environ['PIP_CONFIG_FILE'] == '/dev/null'
    target = Path(sys.argv[-1], 'bin/python')
    target.parent.mkdir(parents=True)
    target.write_text('#!' + sys.executable + '\\nimport os, sys\\n' +
        'print(os.environ["INSTALL_MARKER"])\\nprint(os.environ["INSTALL_MARKER"], file=sys.stderr)\\n' +
        'assert sys.argv[1:5] == ["-m", "pip", "install", "--isolated"]\\n' +
        'sys.exit(int(os.environ["INSTALL_EXIT"]))\\n')
    target.chmod(0o755)
    print(os.environ['INSTALL_MARKER'])
else:
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
""")
                bootstrap.chmod(0o755)
                env = {**os.environ, **install["env"], "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                       "RUNNER_TEMP": str(root), "INSTALL_MARKER": marker, "INSTALL_EXIT": str(status)}
                completed = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", install["run"]],
                                           cwd=root, env=env, capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, status, completed.stderr)
                self.assertEqual(completed.stdout, f"reviewer install exit {status}\n" if status else "")
                self.assertEqual(completed.stderr, "")
                self.assertNotIn(marker, completed.stdout + completed.stderr)
                self.assertIn(marker, (root / "reviewer-install.log").read_text())
                self.assertEqual((root / "reviewer-requirements.txt").read_bytes(), (workflows.ROOT / "review/reviewer-requirements.txt").read_bytes())

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
