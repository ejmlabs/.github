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
from contextlib import chdir
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_workflows as workflows
from standards import consumer_workflows


def embedded_source(script):
    match = re.search(r"base64\.b64decode\('([A-Za-z0-9+/=]+)'\)", script)
    return base64.b64decode(match[1], validate=True).decode() if match else None


def generated_yaml(text):
    """Read the generator's JSON scalars, block strings, maps, and lists."""
    lines = [line for line in text.splitlines() if not line.startswith("#")]

    def parse(index, indent):
        result = [] if lines[index].strip() == "-" or lines[index].lstrip().startswith("- ") else {}
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

    result, end = parse(0, 0)
    if end != len(lines):
        raise ValueError("Unexpected generated YAML")
    return result


class WorkflowSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.governance = generated_yaml((workflows.ROOT / ".github/workflows/governance.yml").read_text())
        cls.release = workflows.release_workflow()

    def test_own_callers_match_the_secrets_declared_at_their_pinned_revisions(self):
        repository = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=workflows.ROOT, capture_output=True)
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
                    path, revision = reference.groups()
                    kind = subprocess.check_output(
                        ["git", "cat-file", "--batch-check=%(objecttype)"], input=revision + "\n",
                        cwd=workflows.ROOT, text=True).strip()
                    if kind == revision + " missing":
                        self.skipTest(f"Pinned workflow commit {revision} is absent from the local Git object store")
                    self.assertEqual(kind, "commit")
                    pinned = subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=workflows.ROOT, text=True)
                    declared = generated_yaml(pinned)["on"]["workflow_call"].get("secrets", {})
                    forwarded = {}
                    if "    secrets:" in job:
                        self.assertIn("    secrets:\n", job)
                        section = re.search(r"(?ms)^    secrets:\n(.*?)(?=^    \S|\Z)", job)[1]
                        for line in section.splitlines():
                            secret = re.fullmatch(r"      (\w+): \$\{\{ secrets\.(\w+) \}\}", line)
                            self.assertIsNotNone(secret)
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

    def test_every_source_consumer_uses_the_preparation_artifact_id(self):
        jobs = self.governance["jobs"]
        prepare = jobs["prepare"]
        match = re.fullmatch(r"\$\{\{ steps\.([A-Za-z0-9_-]+)\.outputs\.artifact-id \}\}", prepare["outputs"]["artifact"])
        self.assertIsNotNone(match, "Source identity must come from an upload action's artifact-id")
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
        self.assertEqual(consumers, {"quality", "registry", "standards", "ai"})

    def test_untrusted_jobs_have_no_repository_or_model_credentials(self):
        for name in ("quality", "registry", "standards"):
            with self.subTest(job=name):
                job = self.governance["jobs"][name]
                self.assertEqual(job["permissions"], {})
                self.assertNotIn("secrets.", json.dumps(job))
                self.assertNotIn("GH_TOKEN", job.get("env", {}))

    def test_every_job_rejects_replays_before_allocating_a_runner(self):
        for name, job in self.governance["jobs"].items():
            with self.subTest(job=name):
                self.assertRegex(job.get("if", ""), r"^\$\{\{ github\.run_attempt == 1(?: && | \}\}$)")

    def test_cli_setup_runs_after_tools_only_in_the_unprivileged_quality_job(self):
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

    def test_harness_dbus_setup_is_linux_only_and_before_the_required_gate(self):
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

    def test_harness_checkout_uses_only_the_trusted_selector_and_fixed_repository(self):
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
                                      if step.get("name") == "Archive source and bounded diff")
        self.assertLess(index + 1, archive_index)
        self.assertEqual(archive["run"], workflows.python(workflows.source("prepare.py")))
        self.assertNotIn("HARNESS_READ_TOKEN", archive.get("env", {}))
        self.assertNotIn("HARNESS_READ_TOKEN", prepare["env"])

    def test_owner_gates_run_required_checks_and_stop_after_a_failure(self):
        job = self.governance["jobs"]["quality"]
        script = next(step["run"] for step in job["steps"] if "./scripts/check" in step.get("run", ""))
        gates = {
            "ejm-ui": [
                ["npm", "ci", "--ignore-scripts"],
                ["npm", "rebuild", "node-pty", "--ignore-scripts=false"],
                ["npm", "run", "check"],
                ["npm", "run", "build"],
                ["node", "scripts/size.mjs"],
                ["npm", "run", "size", "-w", "@ejm/demos"],
                ["npm", "run", "check:rust"],
                ["node", "scripts/pack-proof.mjs"],
            ],
            "ejmlabs": [
                ["node", "scripts/check.mjs"],
                ["npm", "--prefix", "site", "test"],
                ["npm", "--prefix", "site", "run", "build"],
            ],
            "ejm-chess": [],
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
                    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=root, env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0 if failure is None else 19, result.stderr)
                    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
                    self.assertEqual([call["command"] for call in calls], expected if failure is None else expected[:failure + 1])
                    if profile == "ejm-ui":
                        self.assertTrue(all(call["ignore_scripts"] == "true" for call in calls))

    def test_ejm_chess_quality_fails_closed_when_application_code_appears(self):
        script = next(step["run"] for step in self.governance["jobs"]["quality"]["steps"] if "ejm-chess)" in step.get("run", ""))
        message = "ejm-chess has application code; add its quality recipe in ejmlabs/.github"
        cases = {
            "empty": ({}, 0),
            "package.json": ({"package.json": "{}\n"}, 1),
            "src": ({"src/main.ts": "export {}\n"}, 1),
            "documentation": ({"README.md": "# Chess\n", "VERSION": "0.1.0\n", "LICENSE": "MIT\n", ".gitignore": "node_modules/\n",
                               ".gitattributes": "* text=auto\n", "docs/a.md": "Rules\n", "docs/b/c.yaml": "name: chess\n",
                               "openspec/x.yml": "name: chess\n", ".github/workflows/pr.yml": "name: PR\n",
                               ".github/ISSUE_TEMPLATE/bug.md": "Bug report\n", ".github/CODEOWNERS": "* @ejmlabs\n",
                               ".github/SECURITY.md": "Security policy\n", "docs/x.yml": "name: chess\n",
                               "openspec/a.md": "Proposal\n", "openspec/b/c.yaml": "name: chess\n"}, 0),
            "docs worker": ({"docs/app/worker.ts": "export {}\n"}, 1),
            "docs wrangler": ({"docs/wrangler.jsonc": "{}\n"}, 1),
            "github source": ({".github/src/main.rs": "fn main() {}\n"}, 1),
            "nested issue template source": ({".github/ISSUE_TEMPLATE/app/worker.ts": "export {}\n"}, 1),
            "nested workflow": ({".github/workflows/sub/x.yml": "name: PR\n"}, 1),
            "docs source": ({"docs/x.ts": "export {}\n"}, 1),
            "github script": ({".github/x.js": "export {}\n"}, 1),
            "openspec source": ({"openspec/x.py": "pass\n"}, 1),
            "wrangler.jsonc": ({"wrangler.jsonc": "{}\n"}, 1),
            "worker.ts": ({"worker.ts": "export {}\n"}, 1),
            "app": ({"app/index.html": "<p></p>\n"}, 1),
            "functions": ({"functions/api.js": "export {}\n"}, 1),
            "nested VERSION": ({"tools/VERSION": "1\n"}, 1),
            "nested gitignore": ({"sub/.gitignore": "node_modules/\n"}, 1),
        }
        for name, (files, code) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                product = root / "product"
                product.mkdir()
                for path, text in files.items():
                    target = product / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text)
                result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=root, env={**os.environ, "PROFILE": "ejm-chess"}, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
                if code:
                    self.assertIn(message, result.stderr)

    def test_ui_installs_its_rust_toolchain_without_unused_audit_binaries(self):
        script = next(step["run"] for step in self.governance["jobs"]["quality"]["steps"]
                      if step.get("name") == "Install pinned Rust tools")
        for profile in ("ejm-ui", "ejm-cli", "ejm-harness", "ejm-ide", "ejm-chess"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "bin").mkdir()
                log = root / "commands.jsonl"
                for executable in ("rustup", "cargo"):
                    stub = root / "bin" / executable
                    stub.write_text("#!/usr/bin/env python3\nimport json, os, sys\nwith open(os.environ['COMMAND_LOG'], 'a') as log:\n    log.write(json.dumps(sys.argv[1:]) + '\\n')\n")
                    stub.chmod(0o755)
                env = {**os.environ, "PROFILE": profile, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"], "COMMAND_LOG": str(log)}
                subprocess.run(["bash", "-e", "-c", script], cwd=root, env=env, check=True, capture_output=True, text=True)
                calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
                expected = []
                if profile != "ejm-chess":
                    expected = [["toolchain", "install", "1.99.1", "--profile", "minimal", "--component", "clippy,rustfmt"], ["default", "1.99.1"]]
                    if profile != "ejm-ui":
                        expected.extend([["install", "cargo-deny", "--version", "0.20.2", "--locked"], ["install", "cargo-machete", "--version", "0.9.2", "--locked"]])
                self.assertEqual(calls, expected)

    def test_privileged_jobs_run_only_trusted_scripts_and_actions(self):
        trusted_sources = {workflows.source(name) for name in ("governance.py", "prepare.py", "review_result.py", "pr_agent_result.py")}
        trusted_sources.add(embedded_source(workflows.REJECT_DEBUG["run"]))
        trusted_sources.add("\n".join([
            workflows.source("governance.py", True), workflows.source("standards.py", True),
            workflows.source("prepare.py", True), workflows.source("release.py"),
        ]))
        trusted_sources.add(workflows.REVIEWER_COVERAGE_CHECK)
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
                        if name == "ai" and step["name"] in {"Install the pinned reviewer", "Independent automated review"}:
                            if step["name"] == "Install the pinned reviewer":
                                self.assert_data_only_python(embedded_source(script))
                                shell = script.split("TRUSTED_PYTHON\n", 1)[1]
                                self.assertEqual(script.splitlines()[0], 'cd "$RUNNER_TEMP"')
                                commands = {"set", "{", "python3", "$RUNNER_TEMP/reviewer-venv/bin/python", "}", "reviewer_status=$?", "if", "printf", "exit", "fi"}
                            else:
                                self.assertEqual(embedded_source(script), workflows.source("reviewer_cli.py"))
                                before, after = script.split(" <<'TRUSTED_PYTHON'\n", 1)
                                shell = before + "\n" + after.split("TRUSTED_PYTHON\n", 1)[1]
                                commands = {"set", "cd", "mkdir", "timeout", "reviewer_status=$?", "printf", "exit"}
                            for line in shell.splitlines():
                                self.assertIn(shlex.split(line)[0], commands)
                            continue
                        source = embedded_source(script)
                        if source is not None:
                            self.assertIn(source, trusted_sources)
                            if step["name"] == "Check reviewer file coverage":
                                self.assertEqual(source, workflows.REVIEWER_COVERAGE_CHECK)
                                self.assertEqual(script.splitlines()[0], '"$RUNNER_TEMP/reviewer-venv/bin/python" -I - "$GITHUB_WORKSPACE/reviewer/review-data/change.patch" "$RUNNER_TEMP/reviewer-skipped.txt" "$GITHUB_WORKSPACE/reviewer/review-data/context.json" > "$RUNNER_TEMP/reviewer-precheck.log" 2>&1 <<\'TRUSTED_PYTHON\'')
                            else:
                                self.assertRegex(script.splitlines()[0], r'^python3 - (?:admit|verify|finish|select-harness|ui-pin|review-result\.json "\$PR_HEAD" "\$REVIEW_PASS"|"\$RUNNER_TEMP/review\.json" "\$RUNNER_TEMP/review\.md" "\$RUNNER_TEMP/reviewer-exit-code" reviewer/review-data/context\.json reviewer/review-data/change\.patch "\$RUNNER_TEMP/reviewer-skipped\.txt" "\$PR_HEAD" "\$REVIEW_PASS" review-result\.json)? <<\x27TRUSTED_PYTHON\x27$')
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

    def assert_data_only_python(self, source):
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
                    self.assertIsInstance(node.args[0], ast.List)
                    self.assertEqual(ast.literal_eval(node.args[0].elts[0]), "gh")
                    for item in node.keywords:
                        if item.arg == "shell":
                            self.assertIs(ast.literal_eval(item.value), False)
                if isinstance(node.func, ast.Attribute) and node.func.attr == "extractall":
                    filters = [item.value for item in node.keywords if item.arg == "filter"]
                    self.assertEqual([ast.literal_eval(value) for value in filters], ["data"])

    def test_ai_uses_two_independent_serial_provider_passes(self):
        ai = self.governance["jobs"]["ai"]
        self.assertEqual(ai["strategy"], {"fail-fast": False, "max-parallel": 1, "matrix": {"pass": [1, 2]}})
        reviews = [step for step in ai["steps"] if step.get("name") == "Independent automated review"]
        self.assertEqual(len(reviews), 1)
        settings = reviews[0]["env"]
        self.assertEqual(workflows.REVIEWER_MODEL, "xai/grok-4.5")
        self.assertEqual(workflows.REVIEWER_FALLBACK_MODELS, '[]')
        self.assertEqual(settings["CONFIG__MODEL"], workflows.REVIEWER_MODEL)
        self.assertEqual(settings["CONFIG__FALLBACK_MODELS"], workflows.REVIEWER_FALLBACK_MODELS)
        for name in ("OPENAI" + "__KEY", "OPENAI" + "__API_BASE", "LITELLM__EXTRA_HEADERS", "CONFIG__CUSTOM_MODEL_MAX_TOKENS"):
            self.assertNotIn(name, settings)
        self.assertFalse(any("API_BASE" in name for name in settings))
        self.assertEqual(settings["CONFIG__REASONING_EFFORT"], "high")
        self.assertEqual(settings["HOME"], "${{ runner.temp }}/review-home")
        self.assertEqual(ai["needs"], ["admission", "prepare"])
        self.assertIn("ai", self.governance["jobs"]["finish"]["needs"])

    def test_public_reviewer_text_uses_neutral_names(self):
        denied = ("gpt", "glm-5.3", "kimi-k2.7-code", "opencode", "codex", "pr-agent", "pr_agent", "xai", "grok",
                  "openai", "litellm", "setup-uv", "actions/*")
        texts = {name: (workflows.ROOT / name).read_text() for name in ("docs/operations.md", "CHANGELOG.md")}
        texts.update({str(file.relative_to(workflows.ROOT)): file.read_text() for file in (workflows.ROOT / "review").glob("*.md")})
        texts.update({f"step {document['name']}.{job}.{index}": step["name"] for document in (self.governance, self.release)
                      for job, config in document["jobs"].items()
                      for index, step in enumerate(config["steps"]) if "name" in step})
        for name, text in texts.items():
            with self.subTest(file=name):
                text = text.replace("`XAI_API_KEY`", "`review model key secret`").lower()
                for term in denied:
                    self.assertNotIn(term, text)
                self.assertNotRegex(text, r"\b(?:sol|python|pip)\b")

    def test_review_validator_rejects_unsafe_reports_and_decoded_key_like_text(self):
        validator = next(step for step in self.governance["jobs"]["ai"]["steps"] if step.get("name") == "Validate the exact head, pass, and bounded review output")
        head = "a" * 40
        base = {"head": head, "pass": 1, "complete": True, "summary": "Reviewed the full diff.", "findings": []}
        cases = []
        for severity in ("critical", "high", "medium", "low"):
            report = {**base, "findings": [{"severity": severity, "file": "src/auth.rs", "line": 3,
                                           "title": "Authorization check", "reason": "The boundary requires review."}]}
            cases.append((severity, json.dumps(report), True, severity != "low"))
        secret = "s" + "k-" + "proj-" + "A" * 24
        unsafe = json.dumps({**base, "summary": secret})
        duplicate = json.dumps(base)[:-1] + ', "summary": "Replacement"}'
        hidden = unsafe.replace("sk-", "s\\u006b-")[:-1] + ', "summary": "Replacement"}'
        cases.extend([
            ("empty findings", json.dumps(base), True, False),
            ("wrong head", json.dumps({**base, "head": "b" * 40}), False, False),
            ("wrong pass", json.dumps({**base, "pass": 2}), False, False),
            ("incomplete", json.dumps({**base, "complete": False}), False, False),
            ("malformed", "{", False, False),
            ("oversized", " " * 64001, False, False),
            ("key marker", unsafe, False, False),
            ("escaped key marker", unsafe.replace("sk-", "s\\u006b-"), False, False),
            ("duplicate field", duplicate, False, False),
            ("overwritten escaped key marker", hidden, False, False),
        ])
        for word in ("risk-based", "task-list", "src/task-runner.ts",
                     "use the task-runner-configuration-file and risk-assessment-documentation-notes"):
            cases.append(("prose " + word, json.dumps({**base, "summary": "See " + word + "."}), True, False))
        for prefix in ('"', " ", "="):
            payload = json.dumps({**base, "summary": prefix + secret})
            cases.append(("key after " + repr(prefix), payload, False, False))
            cases.append(("escaped key after " + repr(prefix), payload.replace("sk-", "s\\u006b-"), False, False))
        for prefix in ("line\n", "\t"):
            cases.append(("decoded key after " + repr(prefix), json.dumps({**base, "summary": prefix + secret}), False, False))
        finding = {"severity": "low", "file": "src/auth.rs", "line": 3,
                   "title": "Authorization check", "reason": "line\n" + secret}
        cases.extend([
            ("decoded key in finding", json.dumps({**base, "findings": [finding]}), False, False),
            ("decoded key in field name", json.dumps({**base, "\n" + secret: "hidden"}), False, False),
        ])
        body = "Ab1x" * 10
        for key in ("sk" + "-" + body, "sk" + "-proj-" + body, "sk" + "-svcacct-" + body, "sk" + "-admin-" + body,
                    "gh" + "p_" + body, "gh" + "s_" + body, "github" + "_pat_" + body):
            cases.append(("key shape " + key[:6], json.dumps({**base, "summary": "Leaked " + key}), False, False))
        for name, payload, safe, blocked in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                report = root / "review-result.json"
                report.write_text(payload)
                env = {**os.environ, "PR_HEAD": head, "REVIEW_PASS": "1"}
                result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", validator["run"]],
                                        cwd=root, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if safe and not blocked else 1, result.stderr)
                self.assertNotIn(secret, result.stdout + result.stderr)
                if name.startswith("decoded key"):
                    self.assertIn("Review output matches a key-like pattern", result.stderr)

    def test_review_step_excludes_ambient_tokens_and_preserves_admission_rechecks(self):
        ai = self.governance["jobs"]["ai"]
        review = next(step for step in ai["steps"] if step.get("name") == "Independent automated review")
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            self.assertEqual(review.get("env", {}).get(name), "")
        self.assertEqual(ai["env"]["GH_TOKEN"], "${{ github.token }}")
        checks = [step for step in ai["steps"] if step.get("name") == "Recheck current human admission"]
        self.assertEqual(len(checks), 2)
        self.assertEqual(ai["steps"][1], checks[0])
        self.assertEqual(ai["steps"][-1], checks[-1])
        self.assertLess(ai["steps"].index(checks[0]), ai["steps"].index(review))
        for step in checks:
            self.assertNotIn("GH_TOKEN", step.get("env", {}))
            self.assertNotIn("GITHUB_TOKEN", step.get("env", {}))

    def test_automated_review_can_only_gate_and_never_create_an_approval(self):
        ai = self.governance["jobs"]["ai"]
        self.assertTrue(all(permission == "read" for permission in ai["permissions"].values()))
        review = next(step for step in ai["steps"] if step.get("name") == "Independent automated review")
        self.assertEqual(review["env"]["GH_TOKEN"], "")
        self.assertEqual(review["env"]["GITHUB_TOKEN"], "")
        self.assertFalse(any(step.get("uses", "").startswith("actions/checkout@") for step in ai["steps"]))
        tree = ast.parse(workflows.source("governance.py"))
        approvals = [node for node in ast.walk(tree) if isinstance(node, ast.Dict) and any(
            isinstance(key, ast.Constant) and key.value == "event" and isinstance(value, ast.Constant) and value.value == "APPROVE"
            for key, value in zip(node.keys, node.values))]
        self.assertEqual(len(approvals), 1)
        admit = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "admit")
        human_approval = next(node for node in ast.walk(admit) if isinstance(node, ast.If) and ast.unparse(node.test) == "action == 'approve'")
        self.assertIn(approvals[0], list(ast.walk(human_approval)))
        contexts = next(node for node in tree.body if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CONTEXTS" for target in node.targets))
        self.assertIn("AI review", ast.literal_eval(contexts.value))

    def test_ui_source_is_a_fixed_owner_checkout_before_the_credential_free_handoff(self):
        steps = self.governance["jobs"]["prepare"]["steps"]
        read = next(step for step in steps if step.get("id") == "ui")
        self.assertEqual(embedded_source(read["run"]), workflows.source("prepare.py"))
        self.assertIn(" ui-pin ", read["run"].splitlines()[0])
        owner = next(step for step in steps if step.get("with", {}).get("repository") == "ejmlabs/ejm-ui")
        self.assertEqual(owner["if"], "${{ steps.ui.outputs.revision != '' }}")
        self.assertEqual(owner["with"], {"repository": "ejmlabs/ejm-ui", "ref": "${{ steps.ui.outputs.revision }}", "path": "ejm-ui", "persist-credentials": False, "fetch-depth": 1, "submodules": False})
        self.assertLess(steps.index(read), steps.index(owner))
        archive = next(step for step in steps if step.get("name") == "Archive source and bounded diff")
        self.assertLess(steps.index(owner), steps.index(archive))

    def test_generated_workflow_retains_only_the_admitted_review_route(self):
        self.assertEqual(self.governance, workflows.governance())
        self.assertEqual(set(self.governance["on"]), {"workflow_call"})
        self.assertNotIn("codex" + "-action", json.dumps(self.governance))
        ai = self.governance["jobs"]["ai"]
        self.assertIn("needs.admission.outputs.run == 'true'", ai["if"])
        caller = consumer_workflows("a" * 40)["pr.yml"]
        triggers = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", caller)[1]
        self.assertEqual(re.findall(r"(?m)^  (\w+):", triggers), ["issue_comment"])
        self.assertNotRegex(caller, r"(?m)^\s+(?:pull_request|pull_request_target):")

    def test_tracked_sources_exclude_retired_review_configuration(self):
        repository = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=workflows.ROOT, capture_output=True)
        if repository.returncode:
            files = [path.relative_to(workflows.ROOT).as_posix() for path in workflows.ROOT.rglob("*")
                     if path.is_file() and "__pycache__" not in path.relative_to(workflows.ROOT).parts]
        else:
            tracked = subprocess.run(["git", "ls-files", "-z"], cwd=workflows.ROOT, check=True, capture_output=True).stdout
            files = [os.fsdecode(raw) for raw in tracked.split(b"\0") if raw]
        retired = ("codex" + "-action", "OPENAI" + "_API_KEY", "OPENAI" + "__")
        for name in files:
            if name.startswith(".github/review-context/") or name == "review/reviewer-requirements.txt":
                continue
            content = (workflows.ROOT / name).read_bytes()
            for value in retired:
                with self.subTest(file=name, value=value):
                    self.assertNotIn(value.encode(), content)

    def test_only_finish_publishes_the_terminal_ai_job_result(self):
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
                        self.assertIn(entry, ("admit", "verify", "finish"))
                        if entry == "finish":
                            publishers.append((document["name"], job))
        self.assertEqual(publishers, [(self.governance["name"], "finish")])

    def test_model_key_is_confined_to_the_single_review_step_environment(self):
        locations = []

        def find(value, path=()):
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
        index = next(index for index, step in enumerate(steps) if step.get("name") == "Independent automated review")
        self.assertEqual(locations, [("jobs", "ai", "steps", index, "env", "XAI__KEY")])
        guard = next(step for step in steps if "HAS_MODEL_KEY" in step.get("env", {}))
        self.assertEqual(guard["env"]["HAS_MODEL_KEY"], "${{ secrets.XAI_API_KEY != '' }}")
        self.assertEqual(self.governance["on"]["workflow_call"]["secrets"]["XAI_API_KEY"], {"required": False})
        self.assertNotIn("OPENAI" + "_API_KEY", json.dumps(self.governance))
        self.assertIn("if os.environ['HAS_MODEL_KEY'] != 'true': raise ValueError", guard["run"])

    def test_only_the_review_job_declares_the_protected_environment(self):
        environments = [(document["name"], name, job["environment"])
                        for document in (self.governance, self.release)
                        for name, job in document["jobs"].items() if "environment" in job]
        self.assertEqual(environments, [(self.governance["name"], "ai", "legacy-review")])

    def test_review_settings_keep_coverage_spending_and_log_limits(self):
        self.assertEqual(workflows.REVIEW_TOKEN_CAPS, {"T0": 32000, "T1": 64000, "T2": 128000, "T3": 160000})
        self.assertEqual(workflows.REVIEW_TOKEN_CEILING, 180000)
        self.assertEqual(workflows.DEFAULT_REVIEW_TIER, "T3")
        self.assertTrue(all(0 < cap <= workflows.REVIEW_TOKEN_CEILING for cap in workflows.REVIEW_TOKEN_CAPS.values()))
        ai = self.governance["jobs"]["ai"]
        review = next(step for step in ai["steps"] if step.get("name") == "Independent automated review")
        settings = review["env"]
        for key, value in {
                "LOG_LEVEL": "INFO", "CONFIG__MAX_MODEL_TOKENS": "160000", "CONFIG__MAX_OUTPUT_TOKENS": "16000",
                "CONFIG__VERBOSITY_LEVEL": "0", "LITELLM__TURN_OFF_MESSAGE_LOGGING": "true",
                "CONFIG__AI_TIMEOUT": "120", "CONFIG__PROPAGATE_TOOL_ERRORS": "true",
                "CONFIG__USE_REPO_SETTINGS_FILE": "false", "CONFIG__USE_GLOBAL_SETTINGS_FILE": "false",
                "PR_REVIEWER__NUM_MAX_FINDINGS": "50", "PR_REVIEWER__ENABLE_REVIEW_COVERAGE_FOOTER": "true",
                "IGNORE__GLOB": "[]", "IGNORE__REGEX": "[]", "GITHUB_ACTION_CONFIG__ENABLE_OUTPUT": "false",
                "LITELLM_LOCAL_MODEL_COST_MAP": "True"}.items():
            self.assertEqual(settings[key], value)
        self.assertEqual(settings["LITELLM_MODE"], "PRODUCTION")
        self.assertLessEqual(int(settings["CONFIG__MAX_MODEL_TOKENS"]), 180000)
        self.assertEqual(settings["PR_REVIEWER__EXTRA_INSTRUCTIONS"], (workflows.ROOT / "review/reviewer-instructions.md").read_text())
        self.assertNotIn("DEBUG", json.dumps(ai))
        for name in settings:
            self.assertFalse(name.startswith(("PR_AGENT_EXTRA_CONFIG", "PR_AGENT_CONFIG_BRANCH")))
        self.assertEqual(ai["timeout-minutes"], 12)
        self.assertEqual(review["timeout-minutes"], 9)
        script = review["run"]
        match = re.search(r"\btimeout -k ([0-9]+) ([0-9]+) ", script)
        self.assertEqual(int(match[1]), 15)
        seconds = int(match[2])
        self.assertEqual(seconds, 480)
        self.assertLess(seconds + int(match[1]), review["timeout-minutes"] * 60)
        self.assertIn('> "$RUNNER_TEMP/reviewer.log" 2>&1', script)
        self.assertNotRegex(script, r"(?m)^\s*(?:cat|tail|head|less)\b")
        self.assertIn("cd reviewer/review-data/product", script)
        self.assertIn("mkdir .git", script)
        self.assertIn('"$RUNNER_TEMP/reviewer-venv/bin/python" -I - --diff-file', script)
        self.assertEqual(embedded_source(script), workflows.source("reviewer_cli.py"))
        self.assertTrue(script.rstrip().endswith("exit 0"))
        steps = ai["steps"]
        adapter = next(step for step in steps if step.get("name") == "Adapt reviewer output")
        validation = next(step for step in steps if step.get("name", "").startswith("Validate the exact head"))
        self.assertEqual(embedded_source(adapter["run"]), workflows.source("pr_agent_result.py"))
        self.assertEqual(embedded_source(validation["run"]), workflows.source("review_result.py"))
        self.assertLess(steps.index(review), steps.index(adapter))
        self.assertLess(steps.index(adapter), steps.index(validation))
        self.assertFalse(any(step.get("uses", "").startswith(("actions/upload-artifact@", "actions/cache@", "actions/checkout@")) for step in steps))
        for step in (review, adapter, validation):
            self.assertNotIn("GITHUB_STEP_SUMMARY", step["run"])
            self.assertNotIn("GITHUB_OUTPUT", step["run"])
            if embedded_source(step["run"]) is not None:
                self.assertNotIn("GITHUB_STEP_SUMMARY", embedded_source(step["run"]))
                self.assertNotIn("GITHUB_OUTPUT", embedded_source(step["run"]))

    def test_install_embeds_the_complete_hash_lock_without_credentials(self):
        steps = self.governance["jobs"]["ai"]["steps"]
        install = next(step for step in steps if step.get("name") == "Install the pinned reviewer")
        review = next(step for step in steps if step.get("name") == "Independent automated review")
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
        calls = [node for node in ast.walk(ast.parse(embedded_source(script))) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "write_text"]
        self.assertEqual([ast.literal_eval(node.args[0]) for node in calls], [lock])
        pins = [line for line in lock.splitlines() if line and not line.startswith("#")]
        self.assertEqual(len(pins), 95)
        for pin in pins:
            self.assertRegex(pin, r"^[a-z0-9_.-]+==\S+ --hash=sha256:[0-9a-f]{64}$")
        for package, version in (("pr-agent", "0.48.0"), ("litellm", "1.105.0")):
            matches = [pin for pin in pins if pin.startswith(package + "==")]
            self.assertEqual(len(matches), 1)
            self.assertRegex(matches[0], rf"^{package}=={re.escape(version)} --hash=sha256:[0-9a-f]{{64}}$")

    def test_prepare_and_review_reject_runner_debug_before_other_steps(self):
        for name in ("prepare", "ai"):
            with self.subTest(job=name):
                job = self.governance["jobs"][name]
                self.assertNotIn("runner.", job["if"])
                first = job["steps"][0]
                self.assertEqual(first, workflows.REJECT_DEBUG)
                self.assertIn("RUNNER_DEBUG", embedded_source(first["run"]))
                self.assertEqual(job["steps"][1], workflows.VERIFY)
                for debug, expected in (("1", 1), ("0", 0), ("", 0)):
                    completed = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", first["run"]],
                                               env={**os.environ, "RUNNER_DEBUG": debug}, capture_output=True, text=True)
                    self.assertEqual(completed.returncode, expected, completed.stderr)

        for workflow in (self.governance, self.release):
            for job in workflow["jobs"].values():
                self.assertNotIn("runner.", job.get("if", ""))

    def test_generated_review_adapter_and_validation_never_leak_review_text(self):
        steps = self.governance["jobs"]["ai"]["steps"]
        review = next(step for step in steps if step.get("name") == "Independent automated review")
        adapter = next(step for step in steps if step.get("name") == "Adapt reviewer output")
        validation = next(step for step in steps if step.get("name", "").startswith("Validate the exact head"))
        marker = "PRIVATE_REVIEW_OUTPUT_SENTINEL_7412"
        for reviewer_status in (0, 1, 124):
            with self.subTest(reviewer_status=reviewer_status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                temporary = root / "runner-temp"
                binary = temporary / "reviewer-venv/bin/python"
                binary.parent.mkdir(parents=True)
                (temporary / "reviewer-skipped.txt").write_text("[]")
                data = root / "reviewer/review-data"
                (data / "product").mkdir(parents=True)
                (data / "context.json").write_text(json.dumps({"head": "a" * 40, "pass": 2, "files": [{
                    "source": "src/file.py", "target": "src/file.py", "status": "modified",
                    "additions": 1, "deletions": 1, "has_patch": True}]}))
                (data / "change.patch").write_text("diff --git a/src/file.py b/src/file.py\n--- a/src/file.py\n+++ b/src/file.py\n@@ -1 +1 @@\n-old\n+new\n")
                binary.write_text("#!" + sys.executable + "\n" + """import json, os, sys
from pathlib import Path
marker = os.environ['REVIEW_MARKER']
assert sys.argv[1:3] == ['-I', '-']
assert Path.cwd() == Path(os.environ['GITHUB_WORKSPACE'], 'reviewer/review-data/product')
assert Path('.git').is_dir()
review = {'review': {'key_issues_to_review': [{'relevant_file': 'src/file.py', 'start_line': 3,
          'issue_header': marker + ' <b>Check</b> @review-user',
          'issue_content': marker + ' HTTPS://example.invalid/leak <img src=ftp://example.invalid/image> @@review-user'}],
          'security_concerns': 'No'}, 'summary': marker}
print(marker, json.dumps(review))
print(marker, json.dumps(review), file=sys.stderr)
Path(sys.argv[sys.argv.index('--output') + 1]).write_text('## Review\\n' + marker)
Path(sys.argv[sys.argv.index('--json-output') + 1]).write_text(json.dumps(review))
Path(os.environ['RUNNER_TEMP'], 'reviewer-finish-reasons.txt').write_text('stop\\n')
sys.exit(int(os.environ['REVIEW_EXIT']))
""")
                binary.chmod(0o755)
                env = {**os.environ, **review["env"], "GITHUB_WORKSPACE": str(root), "RUNNER_TEMP": str(temporary),
                       "HOME": str(temporary / "review-home"), "XAI__KEY": "test-only", "PR_HEAD": "a" * 40,
                       "REVIEW_PASS": "2", "REVIEW_MARKER": marker, "REVIEW_EXIT": str(reviewer_status)}
                for step, expected in ((review, 0), (adapter, 0), (validation, 1)):
                    completed = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
                                               cwd=root, env=env, capture_output=True, text=True)
                    self.assertEqual(completed.returncode, expected, completed.stderr)
                    self.assertNotIn(marker, completed.stdout + completed.stderr)
                    if step is review:
                        self.assertEqual(completed.stdout, f"reviewer exit {reviewer_status}\n")
                        self.assertEqual(completed.stderr, "")
                self.assertIn(marker, (temporary / "reviewer.log").read_text())
                self.assertEqual((temporary / "reviewer-exit-code").read_text(), f"{reviewer_status}\n")
                result = json.loads((root / "review-result.json").read_text())
                self.assertIs(result["complete"], reviewer_status == 0)
                self.assertNotIn(result["summary"], completed.stdout + completed.stderr)
                if reviewer_status == 0:
                    self.assertEqual(result["findings"][0]["title"], marker + " Check review-user")
                serialized = json.dumps(result)
                self.assertNotRegex(serialized, r"(?i)https?://|ftp://|www\.|@|<|>")

    def test_reviewer_preparation_removes_links_and_special_files(self):
        prepare = next(step for step in self.governance["jobs"]["ai"]["steps"]
                       if step.get("name") == "Prepare trusted reviewer directory and isolated configuration")
        source = "\n".join(prepare["run"].splitlines()[1:-1])
        for linked_root in (False, True):
            with self.subTest(linked_root=linked_root), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "prepared").mkdir()
                (root / "prepared/product.tar").touch()
                (root / "prepared/context.json").write_text(json.dumps({"head": "a" * 40}))
                (root / "prepared/change.patch").write_text("fixture diff")
                temporary = root / "temporary"
                temporary.mkdir()

                class Archive:
                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        pass

                    def extractall(self, destination, *, filter):
                        if filter != "data":
                            raise AssertionError("Unsafe archive filter")
                        product = destination / "product"
                        dependency = destination / "dependency"
                        dependency.mkdir()
                        (dependency / "keep.txt").write_text("preserve sibling source")
                        if linked_root:
                            product.symlink_to("dependency", target_is_directory=True)
                            return
                        product.mkdir()
                        (product / "keep.txt").write_text("regular source")
                        (product / "nested").mkdir()
                        (product / "nested/keep.txt").write_text("nested source")
                        (product / "file-link").symlink_to("../dependency/keep.txt")
                        (product / "directory-link").symlink_to("../dependency", target_is_directory=True)
                        (product / "hardlink-source").write_text("linked source")
                        os.link(product / "hardlink-source", product / "hardlink-copy")
                        if hasattr(os, "mkfifo"):
                            os.mkfifo(product / "fifo")

                with chdir(root), mock.patch.dict(os.environ, {"RUNNER_TEMP": str(temporary), "REVIEW_PASS": "2", "HAS_MODEL_KEY": "true"}), mock.patch("tarfile.open", return_value=Archive()):
                    exec(compile(source, "trusted-prepare-test", "exec"), {})
                product = root / "reviewer/review-data/product"
                self.assertTrue(product.is_dir())
                self.assertFalse(product.is_symlink())
                self.assertEqual((product.parent / "dependency/keep.txt").read_text(), "preserve sibling source")
                expected = [] if linked_root else ["keep.txt", "nested", "nested/keep.txt"]
                self.assertEqual(sorted(str(file.relative_to(product)) for file in product.rglob("*")), expected)
                for file in product.rglob("*"):
                    self.assertFalse(file.is_symlink())
                    self.assertTrue(file.is_dir() or (file.is_file() and file.stat().st_nlink == 1))

    def test_coverage_precheck_runs_without_a_key_and_records_library_rejections(self):
        steps = self.governance["jobs"]["ai"]["steps"]
        precheck = next(step for step in steps if step.get("name") == "Check reviewer file coverage")
        install = next(step for step in steps if step.get("name") == "Install the pinned reviewer")
        review = next(step for step in steps if step.get("name") == "Independent automated review")
        self.assertLess(steps.index(install), steps.index(precheck))
        self.assertLess(steps.index(precheck), steps.index(review))
        self.assertNotIn("secrets.", json.dumps(precheck))
        self.assertNotIn("XAI__KEY", precheck.get("env", {}))
        self.assertEqual(precheck["env"]["GH_TOKEN"], "")
        self.assertEqual(precheck["env"]["GITHUB_TOKEN"], "")
        source = embedded_source(precheck["run"])
        self.assertIn("from pr_agent.algo.language_handler import is_valid_file", source)
        self.assertIn("strip_excluded_review_paths", source)
        for rejected in ([], ["Cargo.lock", "logo.png", "café.svg"]):
            with self.subTest(rejected=rejected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                patch = root / "change.patch"
                names = ("Cargo.lock", "logo.png", "src/app.py", "café.svg")
                patch.write_text("".join(f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-old\n+new\n" for name in names))
                context = root / "context.json"
                context.write_text(json.dumps({"files": [{"source": name, "target": name, "status": "modified",
                                                         "additions": 1, "deletions": 1, "has_patch": True} for name in names]}))
                skipped = root / "reviewer-skipped.txt"
                files = [mock.Mock(source_file="a/" + name, target_file="b/" + name)
                         for name in ("Cargo.lock", "logo.png", "src/app.py")]
                files.append(mock.Mock(source_file='"a/caf\\303\\251.svg"', target_file='"b/caf\\303\\251.svg"'))
                parser = mock.Mock(return_value=files)
                valid = mock.Mock(side_effect=lambda name: name not in rejected)
                modules = {"unidiff": mock.Mock(PatchSet=parser), "pr_agent": mock.Mock(), "pr_agent.algo": mock.Mock(),
                           "pr_agent.algo.language_handler": mock.Mock(is_valid_file=valid)}
                with mock.patch.dict(sys.modules, modules), mock.patch.object(sys, "argv", ["precheck", str(patch), str(skipped), str(context)]):
                    exec(compile(source, "trusted-precheck-test", "exec"), {})
                self.assertEqual(json.loads(skipped.read_text()), rejected)
                self.assertEqual([call.args[0] for call in valid.call_args_list], ["Cargo.lock", "logo.png", "src/app.py", "café.svg"])

    def test_coverage_precheck_strips_exact_generated_workflow_paths(self):
        precheck = next(step for step in self.governance["jobs"]["ai"]["steps"]
                        if step.get("name") == "Check reviewer file coverage")
        source = embedded_source(precheck["run"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch = root / "change.patch"
            names = (".github/workflows/governance.yml", ".github/workflows/draft-release.yml", "src/app.py")
            patch.write_text("".join(
                f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-old\n+new\n"
                for name in names))
            context = root / "context.json"
            context.write_text(json.dumps({
                "repository": "ejmlabs/.github",
                "files": [
                    {"source": name, "target": name, "status": "modified", "additions": 1, "deletions": 1,
                     "has_patch": name == "src/app.py"} for name in names],
            }))
            skipped = root / "reviewer-skipped.txt"
            files = [mock.Mock(source_file="a/src/app.py", target_file="b/src/app.py")]
            parser = mock.Mock(return_value=files)
            valid = mock.Mock(return_value=True)
            modules = {"unidiff": mock.Mock(PatchSet=parser), "pr_agent": mock.Mock(), "pr_agent.algo": mock.Mock(),
                       "pr_agent.algo.language_handler": mock.Mock(is_valid_file=valid)}
            with mock.patch.dict(sys.modules, modules), mock.patch.object(sys, "argv", ["precheck", str(patch), str(skipped), str(context)]):
                exec(compile(source, "trusted-precheck-strip-test", "exec"), {})
            remaining = patch.read_text()
            self.assertIn("src/app.py", remaining)
            self.assertNotIn("governance.yml", remaining)
            self.assertNotIn("draft-release.yml", remaining)
            self.assertEqual(json.loads(skipped.read_text()), [
                ".github/workflows/governance.yml", ".github/workflows/draft-release.yml",
            ])
        # Non-.github profiles must not strip generated paths.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch = root / "change.patch"
            patch.write_text(
                "diff --git a/.github/workflows/governance.yml b/.github/workflows/governance.yml\n"
                "--- a/.github/workflows/governance.yml\n+++ b/.github/workflows/governance.yml\n"
                "@@ -1 +1 @@\n-old\n+new\n"
                "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
                "@@ -1 +1 @@\n-old\n+new\n"
            )
            context = root / "context.json"
            context.write_text(json.dumps({
                "repository": "ejmlabs/ejm-ui",
                "files": [
                    {"source": ".github/workflows/governance.yml", "target": ".github/workflows/governance.yml",
                     "status": "modified", "additions": 1, "deletions": 1, "has_patch": True},
                    {"source": "src/app.py", "target": "src/app.py", "status": "modified",
                     "additions": 1, "deletions": 1, "has_patch": True},
                ],
            }))
            skipped = root / "reviewer-skipped.txt"
            files = [
                mock.Mock(source_file="a/.github/workflows/governance.yml",
                          target_file="b/.github/workflows/governance.yml"),
                mock.Mock(source_file="a/src/app.py", target_file="b/src/app.py"),
            ]
            parser = mock.Mock(return_value=files)
            valid = mock.Mock(return_value=True)
            modules = {"unidiff": mock.Mock(PatchSet=parser), "pr_agent": mock.Mock(), "pr_agent.algo": mock.Mock(),
                       "pr_agent.algo.language_handler": mock.Mock(is_valid_file=valid)}
            with mock.patch.dict(sys.modules, modules), mock.patch.object(sys, "argv", ["precheck", str(patch), str(skipped), str(context)]):
                exec(compile(source, "trusted-precheck-nostrip-test", "exec"), {})
            self.assertIn("governance.yml", patch.read_text())
            self.assertEqual(json.loads(skipped.read_text()), [])

    def test_generated_install_logs_are_private_on_success_and_failure(self):
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
                                           cwd=root, env=env, capture_output=True, text=True)
                self.assertEqual(completed.returncode, status, completed.stderr)
                self.assertEqual(completed.stdout, f"reviewer install exit {status}\n" if status else "")
                self.assertEqual(completed.stderr, "")
                self.assertNotIn(marker, completed.stdout + completed.stderr)
                self.assertIn(marker, (root / "reviewer-install.log").read_text())
                self.assertEqual((root / "reviewer-requirements.txt").read_bytes(), (workflows.ROOT / "review/reviewer-requirements.txt").read_bytes())

    def test_release_draft_classifies_prereleases_without_replacing_existing_assets(self):
        script = self.release["jobs"]["draft"]["steps"][-1]["run"]
        cases = (
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

    def test_release_keeps_the_standard_library_embedding_and_static_source_boundary(self):
        draft = self.release["jobs"]["draft"]
        self.assertEqual(draft["permissions"], {"contents": "write", "pull-requests": "read", "statuses": "read"})
        self.assertEqual(draft["env"], {
            "GH_TOKEN": "${{ github.token }}", "RELEASE_COMMIT": "${{ inputs.commit }}",
            "RELEASE_VERSION": "${{ inputs.version }}", "STANDARDS_REF": "${{ inputs.standards-ref }}",
        })
        self.assertEqual(len(draft["steps"]), 3)
        self.assertEqual(draft["steps"][0], workflows.checkout("product", "${{ inputs.commit }}"))
        library = "\n".join([workflows.source("governance.py", True), workflows.source("standards.py", True),
                              workflows.source("prepare.py", True), workflows.source("release.py")])
        self.assertEqual(draft["steps"][1]["run"], workflows.python(library))
        self.assertNotIn("select-harness", draft["steps"][1]["run"].splitlines()[0])

    def test_embedded_expressions_survive_as_literal_python_data(self):
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
