import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import configure_repositories as settings


class SettingsSafetyTests(unittest.TestCase):
    def test_ui_is_explicitly_selectable_without_expanding_the_default_rollout(self):
        self.assertEqual(settings.NAMES, (".github", "ejmlabs", "ejm-cli", "ejm-harness", "ejm-ide"))
        self.assertEqual(settings.SUPPORTED_NAMES, (*settings.NAMES, "ejm-ui"))

    def test_hold_never_enables_actions_or_sets_allowlist(self):
        with patch.object(settings, "api", return_value={}) as api:
            settings.configure("ejm-cli", protect=False, hold=True)
        writes = [call for call in api.call_args_list if len(call.args) > 1 and call.args[1] != "GET"]
        action_permissions = [call.args[2] for call in writes if call.args[0].endswith("/actions/permissions")]
        self.assertEqual(action_permissions, [{"enabled": False}])
        self.assertFalse(any(call.args[0].endswith("/selected-actions") for call in writes))

    def test_activation_allows_only_current_workflow_sources(self):
        with patch.object(settings, "api", return_value={}) as api, patch.object(settings, "installed_consumers"):
            settings.configure("ejm-cli", protect=False, hold=False, revision="a" * 40)
        allowed = [call.args[2] for call in api.call_args_list if len(call.args) > 1
                   and call.args[1] == "PUT" and call.args[0].endswith("/selected-actions")]
        self.assertEqual(allowed, [{"github_owned_allowed": False, "verified_allowed": False,
                                   "patterns_allowed": ["actions/*@*", "astral-sh/setup-uv@*", "ejmlabs/.github/*@*"]}])

    def test_review_security_label_is_created_and_read_back(self):
        with patch.object(settings, "api", return_value={}) as api:
            settings.configure("ejm-cli", protect=False, hold=True)
        posts = [call.args[2] for call in api.call_args_list if call.args[:2] == ("repos/ejmlabs/ejm-cli/labels", "POST")]
        self.assertEqual([post["name"] for post in posts], ["Possible security concern"])
        self.assertIn(("repos/ejmlabs/ejm-cli/labels/Possible%20security%20concern",), [call.args for call in api.call_args_list])

    def test_workflow_writer_must_be_a_human_maintainer(self):
        for role, kind in (("write", "User"), ("admin", "Bot")):
            with self.subTest(role=role, kind=kind), patch.object(settings, "api", return_value=[
                {"login": "writer", "type": kind, "role_name": role, "permissions": {"push": True}}
            ]):
                with self.assertRaisesRegex(ValueError, "human maintainers"):
                    settings.collaborators("ejm-cli")

    def test_maintainer_and_readonly_roles_are_allowed(self):
        people = [
            {"login": "owner", "type": "User", "role_name": "admin", "permissions": {"push": True}},
            {"login": "reader", "type": "User", "role_name": "read", "permissions": {"push": False}},
        ]
        with patch.object(settings, "api", return_value=people):
            self.assertEqual(len(settings.collaborators("ejm-cli")), 2)

    def test_activation_requires_a_full_shared_revision(self):
        with self.assertRaisesRegex(ValueError, "full immutable SHA"):
            settings.installed_consumers("ejm-cli", "main")

    def test_native_release_is_checked_on_main_only_where_build_workflow_exists(self):
        import base64
        from standards import consumer_workflows

        revision, build = "a" * 40, "name: Build\non:\n  workflow_dispatch:\n  push:\n    branches: [main]\npermissions:\n  contents: read\njobs: {}\n"
        files = {**consumer_workflows(revision, native=True), "build.yml": "name: Build\n" + build.split("\n", 1)[1].replace("jobs: {}", "jobs:\n  b:\n    steps:\n      - uses: actions/checkout@" + "1" * 40 + "\n      - uses: actions/upload-artifact@" + "2" * 40 + "\n        with:\n          name: release-files")}

        def remote(path, *args, **kwargs):
            if path.endswith("?ref=main") and "/contents/.github/workflows/" in path:
                return {"encoding": "base64", "content": base64.b64encode(files[path.rsplit("/", 1)[1].split("?")[0]].encode()).decode()}
            return [{"name": name} for name in files]

        with patch.object(settings, "api", side_effect=remote):
            settings.installed_consumers("ejm-cli", revision)
            files["build.yml"] = files["build.yml"].replace("contents: read", "contents: write")
            with self.assertRaises(ValueError):
                settings.installed_consumers("ejm-cli", revision)
            with self.assertRaisesRegex(ValueError, "unexpected or missing"):
                settings.installed_consumers("ejm-ui", revision)


if __name__ == "__main__":
    unittest.main()
