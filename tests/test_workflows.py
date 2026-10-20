import ast
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_workflows as workflows


def embedded_source(script):
    match = re.search(r"base64\.b64decode\('([A-Za-z0-9+/=]+)'\)", script)
    return base64.b64decode(match[1], validate=True).decode() if match else None


class WorkflowSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.governance = workflows.governance()
        cls.release = workflows.release_workflow()

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
            "wrangler.jsonc": ({"wrangler.jsonc": "{}\n"}, 0),
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
        trusted_sources = {workflows.source(name) for name in ("governance.py", "prepare.py", "review_result.py")}
        trusted_sources.add("\n".join([
            workflows.source("governance.py", True), workflows.source("standards.py", True),
            workflows.source("prepare.py", True), workflows.source("release.py"),
        ]))
        trusted_actions = {"actions/checkout", "actions/download-artifact", "actions/upload-artifact", "openai/codex-action"}
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
                            if action == "openai/codex-action":
                                self.assertEqual(name, "ai")
                            continue
                        script = step["run"]
                        self.assertNotIn("${{", script, "Embedded source must not expose GitHub expressions")
                        source = embedded_source(script)
                        if source is not None:
                            self.assertIn(source, trusted_sources)
                            self.assertRegex(script.splitlines()[0], r'^python3 - (?:admit|verify|finish|select-harness|ui-pin|review-result\.json "\$PR_HEAD" "\$REVIEW_PASS" --github-output "\$GITHUB_OUTPUT")? <<\x27TRUSTED_PYTHON\x27$')
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
                    self.assertIn(alias.name, {"json", "os", "re", "tarfile", "subprocess"})
                    self.assertIsNone(alias.asname)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.module, "pathlib")
                self.assertEqual([(alias.name, alias.asname) for alias in node.names], [("Path", None)])
            elif isinstance(node, ast.Call):
                function = ast.unparse(node.func)
                self.assertNotIn(function, {"eval", "exec", "compile", "__import__", "getattr"})
                self.assertFalse(function.startswith("os."), "Inline scripts must not execute through os")
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

    def test_ai_uses_two_independent_serial_medium_sol_passes(self):
        ai = self.governance["jobs"]["ai"]
        self.assertEqual(ai["strategy"], {"fail-fast": False, "max-parallel": 1, "matrix": {"pass": [1, 2]}})
        secrets = self.governance["on"]["workflow_call"]["secrets"]
        self.assertEqual(list(secrets), ["MODEL_API_KEY", "OPENAI_API_KEY", "EJM_HARNESS_TOKEN"])
        self.assertFalse(any(item["required"] for item in secrets.values()))
        prepare = next(step for step in ai["steps"] if "HAS_MODEL_KEY" in step.get("env", {}))
        self.assertEqual(prepare["env"]["HAS_MODEL_KEY"], "${{ secrets.MODEL_API_KEY != '' || secrets.OPENAI_API_KEY != '' }}")
        self.assertIn("A model API key is required; review fails closed", prepare["run"])
        self.assertNotIn("OPENAI_API_KEY is required", prepare["run"])
        reviews = [step for step in ai["steps"] if step.get("uses", "").startswith("openai/codex-action@")]
        self.assertEqual(len(reviews), 1)
        inputs = reviews[0]["with"]
        self.assertEqual(reviews[0]["name"], "Independent automated review")
        self.assertEqual(inputs["openai-api-key"], "${{ secrets.MODEL_API_KEY || secrets.OPENAI_API_KEY }}")
        self.assertEqual(inputs["model"], "gpt-6.1-sol")
        self.assertEqual(inputs["effort"], "medium")
        self.assertEqual(inputs["working-directory"], "reviewer")
        self.assertEqual(inputs["permission-profile"], ":read-only")
        self.assertEqual(inputs["safety-strategy"], "drop-sudo")
        self.assertEqual(inputs["codex-home"], "${{ runner.temp }}/review-home")
        self.assertEqual(ai["needs"], ["admission", "prepare"])
        self.assertIn("ai", self.governance["jobs"]["finish"]["needs"])
        validate = next(step for step in ai["steps"] if step.get("name") == "Validate the exact head, pass, and bounded review output")
        upload = next(step for step in ai["steps"] if step.get("with", {}).get("path") == "review-result.json")
        self.assertLess(ai["steps"].index(validate), ai["steps"].index(upload))
        self.assertEqual(upload["if"], "${{ steps.review.outputs.safe == 'true' }}")
        self.assertNotIn("always()", json.dumps(upload))
        self.assertIn("always()", self.governance["jobs"]["finish"]["if"])

    def test_safe_report_upload_precedes_the_blocking_gate_and_requires_live_admission(self):
        ai = self.governance["jobs"]["ai"]
        steps = ai["steps"]
        validate = next(step for step in steps if step.get("id") == "review")
        upload = next(step for step in steps if step.get("with", {}).get("path") == "review-result.json")
        index = steps.index(upload)
        self.assertEqual(steps[index - 1], workflows.VERIFY)
        self.assertLess(steps.index(validate), index - 1)
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        self.assertEqual(upload["with"]["retention-days"], 7)
        gate = steps[index + 1]
        self.assertEqual(gate["if"], "${{ steps.review.outputs.blocked == 'true' }}")
        self.assertNotIn("always()", json.dumps(ai))
        self.assertFalse(any(step.get("continue-on-error") for step in steps))
        failed = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", gate["run"]], capture_output=True, text=True)
        self.assertEqual(failed.returncode, 1)

    def test_review_validator_marks_only_safe_exact_complete_reports_for_upload(self):
        validator = next(step for step in self.governance["jobs"]["ai"]["steps"] if step.get("id") == "review")
        head = "a" * 40
        base = {"head": head, "pass": 1, "complete": True, "summary": "Reviewed the full diff.", "findings": []}
        cases = []
        for severity in ("critical", "high", "medium", "low"):
            report = {**base, "findings": [{"severity": severity, "file": "src/auth.rs", "line": 3,
                                           "title": "Authorization check", "reason": "The boundary requires review."}]}
            cases.append((severity, json.dumps(report), True, severity != "low"))
        secret = "sk-" + "fixture" * 4
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
        for name, payload, safe, blocked in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                report = root / "review-result.json"
                report.write_text(payload)
                output = root / "github-output"
                output.touch()
                env = {**os.environ, "PR_HEAD": head, "REVIEW_PASS": "1", "GITHUB_OUTPUT": str(output)}
                result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", validator["run"]],
                                        cwd=root, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if safe else 1, result.stderr)
                expected = f"safe=true\nblocked={str(blocked).lower()}\n" if safe else ""
                self.assertEqual(output.read_text(), expected)
                self.assertNotIn(secret, result.stdout + result.stderr)
                if safe:
                    default = workflows.python(workflows.source("review_result.py"), 'review-result.json "$PR_HEAD" "$REVIEW_PASS"')
                    gate = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", default],
                                          cwd=root, env=env, capture_output=True, text=True)
                    self.assertEqual(gate.returncode, 1 if blocked else 0, gate.stderr)
                    self.assertEqual(output.read_text(), expected)

    def test_review_step_excludes_ambient_tokens_and_preserves_admission_rechecks(self):
        ai = self.governance["jobs"]["ai"]
        review = next(step for step in ai["steps"] if step.get("uses", "").startswith("openai/codex-action@"))
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            self.assertEqual(review.get("env", {}).get(name), "")
        self.assertEqual(ai["env"]["GH_TOKEN"], "${{ github.token }}")
        checks = [step for step in ai["steps"] if step.get("name") == "Recheck current human admission"]
        self.assertEqual(len(checks), 2)
        for step in checks:
            self.assertNotIn("GH_TOKEN", step.get("env", {}))
            self.assertNotIn("GITHUB_TOKEN", step.get("env", {}))

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

    def test_ai_does_not_repeat_the_action_managed_git_check_flag(self):
        # The pinned action always supplies this single-use codex exec flag.
        # Repeating it in codex-args aborts both reviews before a model call.
        for step in self.governance["jobs"]["ai"]["steps"]:
            if step.get("uses", "").startswith("openai/codex-action@"):
                extra_args = json.loads(step["with"].get("codex-args", "[]"))
                self.assertFalse(any(arg.split("=", 1)[0] == "--skip-git-repo-check" for arg in extra_args))

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
        literal = "${{ inputs.commit }} / ${{ secrets.MODEL_API_KEY }}"
        source = "import sys\nprint(" + repr(literal) + ")\nprint(sys.argv[1])\n"
        script = workflows.python(source, "fixture")
        self.assertNotIn("${{", script)
        self.assertNotIn("${{", workflows.yaml({"run": script}))
        self.assertEqual(embedded_source(script), source)
        result = subprocess.run(["bash", "-e", "-c", script], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout, literal + "\nfixture\n")


if __name__ == "__main__":
    unittest.main()
