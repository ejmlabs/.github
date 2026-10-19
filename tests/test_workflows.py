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
                            self.assertRegex(script.splitlines()[0], r'^python3 - (?:admit|verify|finish|review-result\.json "\$PR_HEAD" "\$REVIEW_PASS")? <<\x27TRUSTED_PYTHON\x27$')
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
        reviews = [step for step in ai["steps"] if step.get("uses", "").startswith("openai/codex-action@")]
        self.assertEqual(len(reviews), 1)
        inputs = reviews[0]["with"]
        self.assertEqual(inputs["model"], "gpt-6.1-sol")
        self.assertEqual(inputs["effort"], "medium")
        self.assertEqual(inputs["working-directory"], "reviewer")
        self.assertEqual(inputs["permission-profile"], ":read-only")
        self.assertEqual(inputs["safety-strategy"], "drop-sudo")
        self.assertEqual(inputs["codex-home"], "${{ runner.temp }}/review-home")
        self.assertEqual(ai["needs"], ["admission", "prepare"])
        self.assertIn("ai", self.governance["jobs"]["finish"]["needs"])

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

    def test_embedded_expressions_survive_as_literal_python_data(self):
        literal = "${{ inputs.commit }} / ${{ secrets.OPENAI_API_KEY }}"
        source = "import sys\nprint(" + repr(literal) + ")\nprint(sys.argv[1])\n"
        script = workflows.python(source, "fixture")
        self.assertNotIn("${{", script)
        self.assertNotIn("${{", workflows.yaml({"run": script}))
        self.assertEqual(embedded_source(script), source)
        result = subprocess.run(["bash", "-e", "-c", script], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout, literal + "\nfixture\n")


if __name__ == "__main__":
    unittest.main()
