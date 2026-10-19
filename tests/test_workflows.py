import ast
import base64
import json
import re
import subprocess
import sys
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
