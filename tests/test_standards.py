import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from standards import MIT_TERMS, consumer_workflows, licenses, missing_model_key_workflows, read, semver, versions, workflows
from build_workflows import governance, release_workflow, yaml
from review_result import validate


class StandardTests(unittest.TestCase):
    def test_semver_boundaries(self):
        for value in ("0.1.0", "1.0.0-rc.1", "1.2.3+build.04", "9.0.1-alpha.0"):
            self.assertTrue(semver(value), value)
        for value in ("v1.0.0", "01.0.0", "1.0", "1.0.0-01", "1.0.0-", "1.2.3\n"):
            self.assertFalse(semver(value), value)

    def test_mismatched_version_and_missing_notes_block_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "site").mkdir()
            (root / "VERSION").write_text("0.1.0\n")
            (root / "site/package.json").write_text('{"version":"0.2.0","license":"SEE LICENSE IN ../LICENSE"}')
            (root / "CHANGELOG.md").write_text("## [0.1.0] - 2026-10-18\nNotes\n")
            with self.assertRaises(ValueError): versions(root, "ejmlabs")
            (root / "site/package.json").write_text('{"version":"0.1.0","license":"SEE LICENSE IN ../LICENSE"}')
            self.assertEqual(versions(root, "ejmlabs"), "0.1.0")
            (root / "CHANGELOG.md").write_text("## Unreleased\n")
            with self.assertRaises(ValueError): versions(root, "ejmlabs")

    def test_symlinked_policy_cannot_read_outside_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").symlink_to("/etc/passwd")
            with self.assertRaises(ValueError): read(root, "README.md")

    def test_license_cannot_be_truncated_or_changed_in_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "LICENSE").write_text("MIT License\nCopyright (c) 2026 Example\n" + MIT_TERMS)
            (root / "Cargo.toml").write_text('[workspace]\nmembers=[]\n[workspace.package]\nlicense="MIT"\n')
            licenses(root, "ejm-cli")
            (root / "Cargo.toml").write_text('[workspace]\nmembers=[]\n[workspace.package]\nlicense="Apache-2.0"\n')
            with self.assertRaises(ValueError): licenses(root, "ejm-cli")
            (root / "Cargo.toml").write_text('[workspace]\nmembers=[]\n[workspace.package]\nlicense="MIT"\n')
            (root / "LICENSE").write_text("MIT License\nCopyright (c) 2026 Example\nOnly a fragment.")
            with self.assertRaises(ValueError): licenses(root, "ejm-cli")

    def test_ai_result_identity_limits_and_blocking_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "result.json"
            result = {"head": "a" * 40, "pass": 1, "complete": True, "summary": "Checked the complete diff.", "findings": []}
            file.write_text(json.dumps(result))
            self.assertFalse(validate(file, "a" * 40, 1)[1])
            with self.assertRaises(ValueError): validate(file, "b" * 40, 1)
            with self.assertRaises(ValueError): validate(file, "a" * 40, 2)
            result["findings"] = [{"severity": "medium", "file": "src/auth.rs", "line": 3, "title": "Missing authorization", "reason": "A request skips the maintainer check."}]
            file.write_text(json.dumps(result))
            self.assertTrue(validate(file, "a" * 40, 1)[1])
            result["findings"][0]["file"] = "../../etc/passwd"
            file.write_text(json.dumps(result))
            with self.assertRaises(ValueError): validate(file, "a" * 40, 1)
            file.write_text("x" * 64001)
            with self.assertRaises(ValueError): validate(file, "a" * 40, 1)

    def test_ai_incomplete_review_cannot_pass_with_empty_findings(self):
        # Actual harness PR #12 pass 1 output, accepted by the old validator.
        result = {
            "head": "7a409665b4259135c85ca55c83bc5815cba237aa",
            "pass": 1,
            "summary": "Incomplete review. Inspected all four changed files and local workflow callers. The shared workflow implementations at the old and new pins are absent from the archive, so their behavioral changes and trust boundaries could not be verified offline. No concrete defects established from the supplied source.",
            "findings": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "result.json"
            file.write_text(json.dumps(result))
            with self.assertRaises(ValueError):
                validate(file, result["head"], result["pass"])
            result["complete"] = False
            file.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "incomplete"):
                validate(file, result["head"], result["pass"])

    def test_ai_completion_requires_a_json_boolean(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "result.json"
            result = {"head": "a" * 40, "pass": 1, "summary": "Checked the complete diff.", "findings": []}
            for value in (None, 0, 1, "true", "false", [], {}):
                with self.subTest(complete=value):
                    result["complete"] = value
                    file.write_text(json.dumps(result))
                    with self.assertRaises(ValueError):
                        validate(file, "a" * 40, 1)


class WorkflowTests(unittest.TestCase):
    revision = "0123456789abcdef0123456789abcdef01234567"
    other_revision = "a" * 40

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.directory = self.root / ".github/workflows"
        self.directory.mkdir(parents=True)
        self.reset_callers()

    def reset_callers(self, revision=None):
        for name, text in consumer_workflows(revision or self.revision).items():
            (self.directory / name).write_text(text)

    def add_reusable(self, name, data):
        text = "# Generated by scripts/build_workflows.py. Edit scripts and regenerate.\n" + yaml(data) + "\n"
        (self.directory / name).write_text(text)
        return text

    def reusable(self, *, model_key="OPENAI_API_KEY"):
        data = governance()
        data["on"]["workflow_call"]["secrets"] = {
            model_key if key == "OPENAI_API_KEY" else key: value
            for key, value in data["on"]["workflow_call"]["secrets"].items()
        }
        data["jobs"] = {"check": {"runs-on": "ubuntu-24.04", "steps": [{"uses": "actions/checkout@" + self.revision}]}}
        return self.add_reusable("governance.yml", data)

    def test_exact_callers_accept_one_immutable_revision(self):
        workflows(self.root, "ejm-cli")
        self.reset_callers("1" * 40)
        workflows(self.root, "ejm-ide")
        self.assertIn('      standards-ref: "' + "1" * 40 + '"\n', (self.directory / "release.yml").read_text())

    def test_revision_must_be_a_lowercase_full_sha(self):
        for caller in (consumer_workflows, missing_model_key_workflows):
            for revision in (None, 1, "a" * 39, "a" * 41, "A" * 40, "a" * 40 + "\n", "main"):
                with self.subTest(caller=caller.__name__, revision=revision), self.assertRaises(ValueError):
                    caller(revision)

    def test_callers_and_shared_scaffold_accept_either_model_key(self):
        for model_key in ("OPENAI_API_KEY", "XAI_API_KEY"):
            for caller in (consumer_workflows, missing_model_key_workflows):
                with self.subTest(model_key=model_key, caller=caller.__name__):
                    for name, text in caller(self.revision, model_key=model_key).items():
                        (self.directory / name).write_text(text)
                    self.reusable(model_key=model_key)
                    workflows(self.root, ".github")
                    (self.directory / "governance.yml").unlink()
                    if caller is consumer_workflows:
                        workflows(self.root, "ejm-cli")
                    else:
                        with self.assertRaises(ValueError):
                            workflows(self.root, "ejm-cli")

    def test_callers_cannot_render_unsupported_model_keys(self):
        for caller in (consumer_workflows, missing_model_key_workflows):
            for model_key in ("MODEL_API_KEY", "", None, "OPENAI_API_KEY || XAI_API_KEY"):
                with self.subTest(caller=caller.__name__, model_key=model_key), self.assertRaises(ValueError):
                    caller(self.revision, model_key=model_key)

    def test_callers_reject_extra_unknown_and_indirect_model_keys(self):
        for model_key, other_key in (("OPENAI_API_KEY", "XAI_API_KEY"), ("XAI_API_KEY", "OPENAI_API_KEY")):
            for caller in (consumer_workflows, missing_model_key_workflows):
                original = caller(self.revision, model_key=model_key)["pr.yml"]
                line = "      " + model_key + ": ${{ secrets." + model_key + " }}\n"
                extra = "      " + other_key + ": ${{ secrets." + other_key + " }}\n"
                mutations = {
                    "both model keys": original.replace(line, line + extra),
                    "unknown model key": original.replace(model_key, "MODEL_API_KEY"),
                    "fallback expression": original.replace("secrets." + model_key, "secrets." + model_key + " || secrets." + other_key),
                    "different source key": original.replace("secrets." + model_key, "secrets." + other_key),
                    "missing model key": original.replace(line, ""),
                    "missing harness token": original.replace("      EJM_HARNESS_TOKEN: ${{ secrets.EJM_HARNESS_TOKEN }}\n", ""),
                }
                for case, text in mutations.items():
                    with self.subTest(model_key=model_key, caller=caller.__name__, case=case):
                        (self.directory / "pr.yml").write_text(text)
                        with self.assertRaises(ValueError):
                            workflows(self.root, ".github")

    def test_shared_scaffold_rejects_extra_unknown_and_missing_model_keys(self):
        for model_key, other_key in (("OPENAI_API_KEY", "XAI_API_KEY"), ("XAI_API_KEY", "OPENAI_API_KEY")):
            for name, text in consumer_workflows(self.revision, model_key=model_key).items():
                (self.directory / name).write_text(text)
            original = self.reusable(model_key=model_key)
            declaration = '      "' + model_key + '":\n        "required": false\n'
            extra = '      "' + other_key + '":\n        "required": false\n'
            mutations = {
                "both model keys": original.replace(declaration, declaration + extra),
                "unknown model key": original.replace(model_key, "MODEL_API_KEY"),
                "missing model key": original.replace(declaration, ""),
                "missing harness token": original.replace('      "EJM_HARNESS_TOKEN":\n        "required": false\n', ""),
            }
            for case, text in mutations.items():
                with self.subTest(model_key=model_key, case=case):
                    (self.directory / "governance.yml").write_text(text)
                    with self.assertRaises(ValueError):
                        workflows(self.root, ".github")

    def test_shared_scaffold_and_own_callers_must_use_the_same_model_key(self):
        for model_key, other_key in (("OPENAI_API_KEY", "XAI_API_KEY"), ("XAI_API_KEY", "OPENAI_API_KEY")):
            self.reusable(model_key=model_key)
            for caller in (consumer_workflows, missing_model_key_workflows):
                with self.subTest(model_key=model_key, caller=caller.__name__):
                    for name, text in caller(self.revision, model_key=other_key).items():
                        (self.directory / name).write_text(text)
                    with self.assertRaises(ValueError):
                        workflows(self.root, ".github")

    def test_missing_model_key_caller_is_accepted_only_for_the_shared_profile(self):
        profiles = (".github", "ejm-cli", "ejm-harness", "ejm-ide", "ejmlabs")
        for profile in profiles:
            workflows(self.root, profile)
        for name, text in missing_model_key_workflows(self.revision).items():
            (self.directory / name).write_text(text)
        workflows(self.root, ".github")
        for profile in profiles[1:]:
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                workflows(self.root, profile)

    def test_missing_model_key_routes_keep_admission_and_omit_fixture_secrets(self):
        normal = consumer_workflows(self.revision)
        fixture = missing_model_key_workflows(self.revision)
        self.assertEqual(fixture["release.yml"], normal["release.yml"])
        normal_header, original_job = normal["pr.yml"].split("  governance:\n", 1)
        header, jobs = fixture["pr.yml"].split("  governance:\n", 1)
        normal_job, missing_job = jobs.split("  missing_model_key:\n", 1)
        self.assertEqual(header, normal_header)
        original = "    if: ${{ github.event.issue.pull_request }}\n"
        normal_condition = "    if: ${{ github.event.issue.pull_request && github.repository == 'ejmlabs/.github' && !contains(github.event.issue.labels.*.name, 'acceptance:missing-model-key') }}\n"
        missing_condition = "    if: ${{ github.event.issue.pull_request && github.repository == 'ejmlabs/.github' && contains(github.event.issue.labels.*.name, 'acceptance:missing-model-key') }}\n"
        self.assertTrue(normal_job.startswith(normal_condition))
        self.assertTrue(missing_job.startswith(missing_condition))
        self.assertEqual(normal_job.replace(normal_condition, original), original_job)
        self.assertEqual(missing_job.replace(missing_condition, original), original_job.split("    secrets:\n", 1)[0])
        self.assertNotIn("secrets:", missing_job)
        self.assertNotIn("inherit", fixture["pr.yml"])

    def test_missing_model_key_caller_rejects_changed_routes_credentials_permissions_and_pins(self):
        original = missing_model_key_workflows(self.revision)
        normal_job, missing_job = original["pr.yml"].split("  missing_model_key:\n", 1)
        mutations = {
            "different label": original["pr.yml"].replace("acceptance:missing-model-key", "acceptance:other"),
            "repository guard removed": original["pr.yml"].replace(" && github.repository == 'ejmlabs/.github'", ""),
            "routes overlap": original["pr.yml"].replace(" && !contains(", " && contains("),
            "automatic event": original["pr.yml"].replace("on:\n", "on:\n  push:\n"),
            "fixture receives key": original["pr.yml"] + "    secrets:\n      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}\n",
            "fixture inherits secrets": original["pr.yml"] + "    secrets: inherit\n",
            "normal key omitted": original["pr.yml"].replace("      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}\n", ""),
            "fixture can write source": normal_job + "  missing_model_key:\n" + missing_job.replace("contents: read", "contents: write"),
            "root write permissions": original["pr.yml"].replace("permissions: {}", "permissions:\n  contents: write"),
            "fixture uses another pin": normal_job + "  missing_model_key:\n" + missing_job.replace(self.revision, self.other_revision),
            "additional job": original["pr.yml"] + "  extra:\n    runs-on: ubuntu-24.04\n    steps: []\n",
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                (self.directory / "pr.yml").write_text(text)
                with self.assertRaises(ValueError):
                    workflows(self.root, ".github")
        (self.directory / "pr.yml").write_text(original["pr.yml"])
        (self.directory / "release.yml").write_text(consumer_workflows(self.other_revision)["release.yml"])
        with self.assertRaises(ValueError):
            workflows(self.root, ".github")

    def test_consumer_trigger_and_yaml_bypasses_are_rejected(self):
        original = consumer_workflows(self.revision)["pr.yml"]
        mutations = {
            "inline automatic trigger": original.replace("on:\n  issue_comment:\n    types: [created, edited, deleted]", "on: [push]"),
            "duplicate trigger": original + "on: [push]\n",
            "extra automatic trigger": original.replace("on:\n", "on:\n  push:\n"),
            "quoted mutable uses and fake pin": original.replace("    uses: ejmlabs/.github/.github/workflows/governance.yml@" + self.revision,
                '    "uses": "ejmlabs/.github/.github/workflows/governance.yml@main"\n    # uses: ejmlabs/.github/.github/workflows/governance.yml@' + self.revision),
            "additional job": original + "  unsafe:\n    runs-on: ubuntu-24.04\n    steps: []\n",
            "alternate quoted trigger": original.replace("on:\n", '"on":\n'),
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                (self.directory / "pr.yml").write_text(text)
                with self.assertRaises(ValueError):
                    workflows(self.root, "ejm-cli")

    def test_release_must_match_the_pr_revision_and_manual_trigger(self):
        original = consumer_workflows(self.revision)["release.yml"]
        mutations = {
            "different called workflow revision": original.replace("draft-release.yml@" + self.revision, "draft-release.yml@" + self.other_revision),
            "different standards revision": original.replace('standards-ref: "' + self.revision + '"', 'standards-ref: "' + self.other_revision + '"'),
            "automatic trigger": original.replace("  workflow_dispatch:\n", "  push:\n  workflow_dispatch:\n"),
            "number standards revision": original.replace('standards-ref: "' + self.revision + '"', "standards-ref: " + self.revision),
            "number commit input": original.replace("        type: string", "        type: number", 1),
            "duplicate trigger": original + "on: [push]\n",
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                (self.directory / "release.yml").write_text(text)
                with self.assertRaises(ValueError):
                    workflows(self.root, "ejm-cli")

    def test_extra_workflow_or_directory_entry_is_rejected(self):
        for name in ("extra.yml", "extra.yaml", "notes.md", "extra"):
            with self.subTest(name=name):
                file = self.directory / name
                file.write_text("on: [push]\n")
                with self.assertRaises(ValueError):
                    workflows(self.root, "ejm-harness")
                file.unlink()

    def test_symlinked_workflow_is_rejected(self):
        file = self.directory / "release.yml"
        original = file.read_text()
        file.unlink()
        target = self.root / "caller.yml"
        target.write_text(original)
        file.symlink_to(target)
        with self.assertRaises(ValueError):
            workflows(self.root, "ejm-cli")

    def test_shared_profile_accepts_both_full_generated_reusables(self):
        self.add_reusable("governance.yml", governance())
        self.add_reusable("draft-release.yml", release_workflow())
        workflows(self.root, ".github")
        with self.assertRaises(ValueError):
            workflows(self.root, "ejm-cli")

    def test_reusable_trigger_bypasses_are_rejected(self):
        original = self.reusable()
        mutations = {
            "inline automatic trigger": original.replace('"on":\n  "workflow_call":', '"on": ["push"]\n"unused":\n  "workflow_call":'),
            "duplicate trigger": original + '"on": ["push"]\n',
            "nested automatic trigger": original.replace('"on":\n', '"on":\n  "push": {}\n'),
            "additional root key": original + '"env": {}\n',
            "second YAML document": original + '---\n"on": ["push"]\n',
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                (self.directory / "governance.yml").write_text(text)
                with self.assertRaises(ValueError):
                    workflows(self.root, ".github")

    def test_reusable_mutable_uses_cannot_hide_behind_yaml_syntax(self):
        original = self.reusable()
        pinned = '"uses": "actions/checkout@' + self.revision + '"'
        mutations = {
            "quoted mutable uses": original.replace(pinned, '"uses": "actions/checkout@main"'),
            "escaped uses key": original.replace(pinned, r'"u\u0073es": "actions/checkout@main"'),
            "unquoted uses key": original.replace(pinned, 'uses: "actions/checkout@main"'),
            "flow mapping": original.replace(pinned, '"uses": {"ref": "actions/checkout@main"}'),
            "alias value": original.replace(pinned, '"uses": *mutable'),
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                (self.directory / "governance.yml").write_text(text)
                with self.assertRaises(ValueError):
                    workflows(self.root, ".github")

    def test_workflow_lookalikes_inside_literal_script_are_data(self):
        data = governance()
        data["jobs"] = {"check": {"runs-on": "ubuntu-24.04", "steps": [{"run": 'on: [push]\n"uses": "actions/checkout@main"\n---\n'}]}}
        self.add_reusable("governance.yml", data)
        workflows(self.root, ".github")

    def test_local_cli_setup_hook_accepts_only_the_scoped_quality_step(self):
        cases = ("valid", "different path", "missing profile", "different profile", "extra environment", "privileged job", "other unprivileged job", "duplicate step", "release")
        for case in cases:
            with self.subTest(case=case):
                data = governance()
                steps = data["jobs"]["quality"]["steps"]
                steps[:] = [step for step in steps if step.get("uses") != "./product/.github/actions/setup-ci"]
                hook = {
                    "name": "Prepare ejm-cli remote test prerequisites",
                    "if": "${{ needs.admission.outputs.profile == 'ejm-cli' }}",
                    "uses": "./product/.github/actions/setup-ci",
                }
                steps.insert(-1, hook)
                if case == "different path":
                    hook["uses"] = "./product/.github/actions/other"
                elif case == "missing profile":
                    del hook["if"]
                elif case == "different profile":
                    hook["if"] = "${{ needs.admission.outputs.profile == 'ejm-harness' }}"
                elif case == "extra environment":
                    hook["env"] = {"EXTRA": "value"}
                elif case in ("privileged job", "other unprivileged job"):
                    steps.remove(hook)
                    data["jobs"]["prepare" if case == "privileged job" else "registry"]["steps"].append(hook)
                elif case == "duplicate step":
                    steps.append(hook.copy())
                elif case == "release":
                    data = release_workflow()
                    data["jobs"]["draft"]["steps"].append(hook)
                name = "draft-release.yml" if case == "release" else "governance.yml"
                self.add_reusable(name, data)
                if case == "valid":
                    workflows(self.root, ".github")
                else:
                    with self.assertRaises(ValueError):
                        workflows(self.root, ".github")
                (self.directory / name).unlink()

    def test_literal_hook_lookalike_cannot_authorize_another_step(self):
        for case in ("prepare hook", "unconditioned quality hook", "valid quality hook"):
            with self.subTest(case=case):
                data = governance()
                for job in data["jobs"].values():
                    job["steps"] = [step for step in job["steps"] if step.get("uses") != "./product/.github/actions/setup-ci"]
                hook = {
                    "name": "Prepare ejm-cli remote test prerequisites",
                    "if": "${{ needs.admission.outputs.profile == 'ejm-cli' }}",
                    "uses": "./product/.github/actions/setup-ci",
                }
                data["jobs"]["quality"]["name"] = '-\n' + yaml(hook, 2) + '\n-\n'
                if case == "prepare hook":
                    data["jobs"]["prepare"]["steps"].append({"uses": hook["uses"]})
                elif case == "unconditioned quality hook":
                    data["jobs"]["quality"]["steps"].append({"uses": hook["uses"]})
                else:
                    data["jobs"]["quality"]["steps"].insert(-1, hook)
                self.add_reusable("governance.yml", data)
                if case == "valid quality hook":
                    workflows(self.root, ".github")
                else:
                    with self.assertRaises(ValueError):
                        workflows(self.root, ".github")

    def test_comment_dash_cannot_hide_extra_cli_setup_fields(self):
        hook = {
            "name": "Prepare ejm-cli remote test prerequisites",
            "if": "${{ needs.admission.outputs.profile == 'ejm-cli' }}",
            "uses": "./product/.github/actions/setup-ci",
        }
        name = '        "name": "Prepare ejm-cli remote test prerequisites"\n'
        for extra in ({"env": {"EXTRA": "value"}}, {"continue-on-error": True}, {}):
            with self.subTest(extra=extra):
                data = governance()
                for job in data["jobs"].values():
                    job["steps"] = [step for step in job["steps"] if step.get("uses") != hook["uses"]]
                data["jobs"]["quality"]["steps"].insert(-1, {**extra, **hook})
                text = self.add_reusable("governance.yml", data)
                if extra:
                    # This is still one real YAML step with an extra field. The
                    # comment must not become a second, canonical step boundary.
                    text = text.replace(name, "        #      -\n" + name)
                else:
                    # Comments before a real sequence boundary retain source
                    # line mapping and must not reject the permitted hook.
                    text = text.replace("      -\n" + name, "      # setup prerequisites\n      -\n" + name)
                (self.directory / "governance.yml").write_text(text)
                if extra:
                    with self.assertRaises(ValueError):
                        workflows(self.root, ".github")
                else:
                    workflows(self.root, ".github")


if __name__ == "__main__": unittest.main()
