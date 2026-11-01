import base64
import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import configure_repositories as settings
from standards import SITE_DEPLOY, SITE_DEPLOY_CALLER, consumer_workflows

ROOT = Path(__file__).resolve().parents[1]
PIN, OTHER_PIN, COMMIT = "a" * 40, "b" * 40, "c" * 40
EMPTY = object()
NATIVE_BUILD = ("name: Build\non:\n  workflow_dispatch:\n  push:\n    branches: [main]\npermissions:\n  contents: read\njobs:\n  b:\n"
                "    steps:\n      - uses: actions/checkout@" + "1" * 40 + "\n      - uses: actions/upload-artifact@" + "2" * 40
                + "\n        with:\n          name: release-files\n")
EVIL = "name: Evil\non: pull_request_target\npermissions: write-all\njobs:\n  run:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ${{ secrets.TOKEN }}\n"
REPO: dict[str, Any] = {"allow_squash_merge": True, "allow_merge_commit": False, "allow_rebase_merge": False, "allow_auto_merge": True, "delete_branch_on_merge": True}
PROTECTION: dict[str, Any] = {
    "required_status_checks": {"strict": True, "contexts": ["Quality", "Repository standards"],
                               "checks": [{"context": "Quality", "app_id": 15368}, {"context": "Repository standards", "app_id": 15368}]},
    "enforce_admins": {"enabled": True},
    "required_pull_request_reviews": {"dismiss_stale_reviews": True, "require_code_owner_reviews": False,
                                      "required_approving_review_count": 1, "require_last_push_approval": False},
    "required_linear_history": {"enabled": True}, "allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
    "block_creations": {"enabled": False}, "required_conversation_resolution": {"enabled": True},
    "lock_branch": {"enabled": False}, "allow_fork_syncing": {"enabled": False},
}
RULESET: dict[str, Any] = {"id": 7, "name": "Immutable semantic version tags", "target": "tag", "enforcement": "active", "bypass_actors": [],
           "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}}, "rules": [{"type": "update"}, {"type": "deletion"}]}
ACTIONS: dict[str, Any] = {"enabled": True, "allowed_actions": "selected", "sha_pinning_required": True}
ALLOWLIST: dict[str, Any] = {"github_owned_allowed": False, "verified_allowed": False, "patterns_allowed": ["ejmlabs/.github/*@*", "actions/*@*", "astral-sh/setup-uv@*"]}
WORKFLOW_PERMISSIONS: dict[str, Any] = {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": True}
FORK_RUNS: dict[str, Any] = {"run_workflows_from_fork_pull_requests": False, "send_write_tokens_to_workflows": False,
             "send_secrets_and_variables": False, "require_approval_for_fork_pr_workflows": True}
PEOPLE = [{"login": "owner", "type": "User", "role_name": "admin", "permissions": {"push": True}},
          {"login": "reader", "type": "User", "role_name": "read", "permissions": {"push": False}}]
REVIEWER = {"type": "User", "reviewer": {"id": 42, "login": "owner", "type": "User"}}
MAIN_POLICY: dict[str, Any] = {"total_count": 1, "branch_policies": [{"id": 5, "name": "main", "type": "branch"}]}
BRANCH_POLICY: dict[str, Any] = {"protected_branches": False, "custom_branch_policies": True}


@dataclass
class Failure:
    """A failed gh api call: gh exits 1, prints the message and status on stderr and the error body on stdout."""

    status: int
    message: str


@dataclass
class Later:
    """Answers in order, then repeats the last answer: a resource that changes after a write."""

    answers: list[Any]


class FakeGh:
    """Stands in for subprocess.run. Unknown reads are a 404 like GitHub's; unknown writes succeed with no body."""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args[:3] == ["gh", "api", "--method"], args
        method, path = args[3], args[4]
        assert ("--input" in args) == (kwargs.get("input") is not None), args
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        assert kwargs["timeout"] > 0
        body = json.loads(kwargs["input"]) if kwargs.get("input") is not None else None
        self.calls.append((method, path, body))
        answer = self.routes.get((method, path), Failure(404, "Not Found") if method == "GET" else EMPTY)
        if isinstance(answer, Later):
            answer = answer.answers.pop(0) if len(answer.answers) > 1 else answer.answers[0]
        if isinstance(answer, Failure):
            return subprocess.CompletedProcess(args, 1, json.dumps({"message": answer.message}), f"gh: {answer.message} (HTTP {answer.status})")
        return subprocess.CompletedProcess(args, 0, "" if answer is EMPTY else json.dumps(answer), "")

    def writes(self) -> list[tuple[str, str, Any]]:
        return [call for call in self.calls if call[0] != "GET"]

    def written(self, method: str, suffix: str) -> list[Any]:
        return [body for verb, path, body in self.calls if verb == method and path.endswith(suffix)]


def patched(value: Any, path: tuple[str, ...], new: Any) -> Any:
    """A copy of nested JSON with one value replaced."""
    if not path:
        return new
    return {**value, path[0]: patched(value[path[0]], path[1:], new)}


def wrapped(text: str) -> str:
    """Base64 the way the contents API returns it, wrapped at 60 characters."""
    encoded = base64.b64encode(text.encode()).decode()
    return "\n".join(encoded[start:start + 60] for start in range(0, len(encoded), 60)) + "\n"


def entry(filename: str, text: str) -> dict[str, Any]:
    return {"name": filename, "path": ".github/workflows/" + filename, "type": "file", "size": len(text.encode()),
            "sha": hashlib.sha256(text.encode()).hexdigest()[:40]}


def default_files(name: str, pin: str = PIN, *, deploy: bool = True) -> dict[str, str]:
    files = consumer_workflows(pin)
    if deploy and name in SITE_DEPLOY:
        files["deploy.yml"] = SITE_DEPLOY_CALLER.replace("STANDARDS_REVISION", pin)
    return files


def environment(*, reviewers: list[dict[str, Any]] | None = None, wait: int | None = None, prevent_self_review: bool = False) -> dict[str, Any]:
    rules: list[dict[str, Any]] = [{"id": 1, "node_id": "x", "type": "branch_policy"}]
    if wait is not None:
        rules.append({"id": 2, "type": "wait_timer", "wait_timer": wait})
    if reviewers is not None:
        rules.append({"id": 3, "type": "required_reviewers", "prevent_self_review": prevent_self_review, "reviewers": reviewers})
    return {"name": "x", "deployment_branch_policy": BRANCH_POLICY, "protection_rules": rules}


def workflow_routes(root: str, files: dict[str, str], entries: list[dict[str, Any]] | None = None) -> dict[tuple[str, str], Any]:
    directory = root + "/contents/.github/workflows"
    listed = [entry(filename, text) for filename, text in files.items()] if entries is None else entries
    routes: dict[tuple[str, str], Any] = {("GET", f"{directory}?ref=main"): listed, ("GET", f"{directory}?ref={COMMIT}"): listed}
    for filename, text in files.items():
        routes[("GET", f"{directory}/{filename}?ref={COMMIT}")] = {**entry(filename, text), "encoding": "base64", "content": wrapped(text)}
    return routes


def healthy(name: str = "ejm-cli", *, files: dict[str, str] | None = None, pin: str = PIN) -> dict[tuple[str, str], Any]:
    """Every read a correct repository answers, in the shapes GitHub returns."""
    root = "repos/ejmlabs/" + name
    files = default_files(name, pin) if files is None else files
    rulesets = [{"id": 7, "name": RULESET["name"]}]
    routes: dict[tuple[str, str], Any] = {
        ("GET", root): REPO,
        ("GET", root + "/branches/main"): {"name": "main", "commit": {"sha": COMMIT}},
        ("GET", root + "/branches/main/protection"): PROTECTION,
        ("GET", root + "/rulesets"): rulesets,
        ("GET", root + "/rulesets?includes_parents=false&per_page=100&page=1"): rulesets,
        ("GET", root + "/rulesets/7"): RULESET,
        ("GET", root + "/actions/permissions"): ACTIONS,
        ("GET", root + "/actions/permissions/selected-actions"): ALLOWLIST,
        ("GET", root + "/actions/permissions/workflow"): WORKFLOW_PERMISSIONS,
        ("GET", root + "/actions/permissions/fork-pr-workflows-private-repos"): FORK_RUNS,
        ("GET", root + "/actions/permissions/fork-pr-contributor-approval"): {"approval_policy": "all_external_contributors"},
        ("GET", root + "/vulnerability-alerts"): EMPTY,
        ("GET", root + "/labels/gate%3Aapprove"): {"name": "gate:approve"},
        ("GET", root + "/labels/gate%3Arevoke"): {"name": "gate:revoke"},
        ("GET", root + "/collaborators?per_page=100&page=1"): PEOPLE,
        ("GET", f"repos/ejmlabs/.github/compare/{pin}...main?per_page=1"): {"status": "ahead"},
        ("GET", "repos/ejmlabs/.github/git/matching-refs/heads/workflow-pins/?per_page=100&page=1"): [],
        **workflow_routes(root, files),
    }
    if "deploy.yml" in files:
        for target in settings.ENVIRONMENTS:
            routes[("GET", f"{root}/environments/{target}")] = environment(reviewers=[REVIEWER] if target == "production" else None)
            routes[("GET", f"{root}/environments/{target}/deployment-branch-policies?per_page=100")] = MAIN_POLICY
    return routes


def shared_files() -> dict[str, str]:
    """This repository's own workflows: the callers and every shared reusable."""
    return {file.name: file.read_text(encoding="utf-8") for file in sorted((ROOT / ".github/workflows").iterdir())}


def pin_of(files: dict[str, str]) -> str:
    match = settings.PIN.search(files["pr.yml"])
    assert match is not None
    return match[1]


class GhCase(unittest.TestCase):
    def gh(self, routes: dict[tuple[str, str], Any]) -> FakeGh:
        fake = FakeGh(routes)
        self.enterContext(patch.object(subprocess, "run", fake))
        return fake

    def cli(self, *argv: str) -> tuple[str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            settings.main(list(argv))
        return out.getvalue(), err.getvalue()


class ApplyTests(GhCase):
    def test_ui_is_explicitly_selectable_without_expanding_the_default_rollout(self) -> None:
        self.assertEqual(settings.NAMES, (".github", "ejmlabs", "ejm-cli", "ejm-harness", "ejm-ide"))
        self.assertEqual(settings.SUPPORTED_NAMES, (*settings.NAMES, "ejm-ui", "ejm-calm"))

    def test_hold_never_enables_actions_or_sets_allowlist(self) -> None:
        gh = self.gh(healthy())
        settings.configure("ejm-cli", protect=False, hold=True)
        self.assertEqual(gh.written("PUT", "/actions/permissions"), [{"enabled": False}])
        self.assertEqual(gh.written("PUT", "/selected-actions"), [])
        self.assertFalse(any(path.endswith("/branches/main") for _, path, _ in gh.calls))

    def test_activation_sets_the_allowlist_only_after_main_is_verified(self) -> None:
        gh = self.gh(healthy())
        settings.configure("ejm-cli", protect=False, hold=False)
        self.assertEqual(gh.written("PUT", "/selected-actions"), [{"github_owned_allowed": False, "verified_allowed": False,
                                                                  "patterns_allowed": ["actions/*@*", "astral-sh/setup-uv@*", "ejmlabs/.github/*@*"]}])
        self.assertEqual(gh.written("PUT", "/actions/permissions")[-1], {"enabled": True, "allowed_actions": "selected", "sha_pinning_required": True})
        first_read = next(index for index, call in enumerate(gh.calls) if "/contents/.github/workflows/pr.yml" in call[1])
        first_write = next(index for index, call in enumerate(gh.calls) if call[0] != "GET")
        self.assertLess(first_read, first_write)

    def test_activation_refuses_unreviewed_workflows_before_any_write(self) -> None:
        for label, files in (("extra workflow", {**default_files("ejm-cli"), "evil.yml": EVIL}),
                             ("changed caller", {**default_files("ejm-cli"), "pr.yml": default_files("ejm-cli")["pr.yml"] + "  extra:\n    runs-on: x\n"})):
            with self.subTest(label):
                gh = self.gh(healthy(files=files))
                with self.assertRaisesRegex(ValueError, "workflows on main"):
                    settings.configure("ejm-cli", protect=False, hold=False)
                self.assertEqual(gh.writes(), [])

    def test_activation_refuses_a_pin_that_is_not_reviewed(self) -> None:
        routes = healthy()
        routes[("GET", f"repos/ejmlabs/.github/compare/{PIN}...main?per_page=1")] = {"status": "diverged"}
        gh = self.gh(routes)
        with self.assertRaisesRegex(ValueError, "neither on ejmlabs/.github main nor a workflow-pins ref"):
            settings.configure("ejm-cli", protect=False, hold=False)
        self.assertEqual(gh.writes(), [])

    def test_missing_gate_labels_are_created(self) -> None:
        # A failed optional read returns a truthy placeholder. The old code PATCHed a label that did not exist.
        gh = self.gh({**healthy(), ("GET", "repos/ejmlabs/ejm-cli/labels/gate%3Aapprove"): Failure(404, "Not Found"),
                      ("GET", "repos/ejmlabs/ejm-cli/labels/gate%3Arevoke"): Failure(404, "Not Found")})
        settings.configure("ejm-cli", protect=False, hold=True)
        self.assertEqual([body["name"] for body in gh.written("POST", "/labels")], ["gate:approve", "gate:revoke"])
        self.assertEqual(gh.written("PATCH", "/labels/gate%3Aapprove"), [])
        self.assertEqual(gh.written("PATCH", "/labels/gate%3Arevoke"), [])

    def test_existing_gate_labels_are_updated_not_recreated(self) -> None:
        gh = self.gh(healthy())
        settings.configure("ejm-cli", protect=False, hold=True)
        self.assertEqual(gh.written("POST", "/labels"), [])
        self.assertEqual(gh.written("PATCH", "/labels/gate%3Aapprove"), [{"new_name": "gate:approve", "color": "0E8A16",
                                                                          "description": "Maintainer approval that also admits the current head"}])
        self.assertEqual(len(gh.written("PATCH", "/labels/gate%3Arevoke")), 1)

    def test_a_label_lookup_error_is_not_read_as_a_missing_label(self) -> None:
        gh = self.gh({**healthy(), ("GET", "repos/ejmlabs/ejm-cli/labels/gate%3Aapprove"): Failure(403, "Resource not accessible")})
        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            settings.configure("ejm-cli", protect=False, hold=True)
        self.assertEqual(gh.written("POST", "/labels"), [])

    def test_a_failed_label_create_is_an_error(self) -> None:
        self.gh({**healthy(), ("GET", "repos/ejmlabs/ejm-cli/labels/gate%3Aapprove"): Failure(404, "Not Found"),
                 ("POST", "repos/ejmlabs/ejm-cli/labels"): Failure(422, "Validation Failed")})
        with self.assertRaisesRegex(RuntimeError, "HTTP 422"):
            settings.configure("ejm-cli", protect=False, hold=True)

    def test_main_requires_quality_and_standards_and_enforces_them_for_admins(self) -> None:
        gh = self.gh(healthy())
        settings.configure("ejm-cli", protect=True, hold=True)
        protection = gh.written("PUT", "/branches/main/protection")[0]
        self.assertEqual(protection["required_status_checks"], {"strict": True, "checks": [{"context": "Quality", "app_id": 15368},
                                                                                              {"context": "Repository standards", "app_id": 15368}]})
        self.assertIs(protection["enforce_admins"], True)
        self.assertEqual(protection["required_pull_request_reviews"]["required_approving_review_count"], 1)
        self.assertIs(protection["required_pull_request_reviews"]["dismiss_stale_reviews"], True)
        self.assertIs(protection["required_linear_history"], True)
        self.assertIs(protection["required_conversation_resolution"], True)
        self.assertIs(protection["allow_force_pushes"], False)
        self.assertIs(protection["allow_deletions"], False)

    def test_the_immutable_tag_ruleset_is_created_or_updated_in_place(self) -> None:
        gh = self.gh({**healthy(), ("GET", "repos/ejmlabs/ejm-cli/rulesets?includes_parents=false&per_page=100&page=1"): []})
        settings.configure("ejm-cli", protect=True, hold=True)
        created = gh.written("POST", "/rulesets")
        self.assertEqual(len(created), 1)
        self.assertEqual((created[0]["target"], created[0]["enforcement"], created[0]["bypass_actors"]), ("tag", "active", []))
        gh = self.gh(healthy())
        settings.configure("ejm-cli", protect=True, hold=True)
        self.assertEqual(gh.written("POST", "/rulesets"), [])
        self.assertEqual(len(gh.written("PUT", "/rulesets/7")), 1)

    def test_merge_settings_stay_squash_only_with_auto_merge_and_a_read_only_token(self) -> None:
        gh = self.gh(healthy())
        settings.configure("ejm-cli", protect=False, hold=True)
        merge = gh.written("PATCH", "ejmlabs/ejm-cli")[0]
        self.assertEqual((merge["allow_squash_merge"], merge["allow_merge_commit"], merge["allow_rebase_merge"], merge["allow_auto_merge"]),
                         (True, False, False, True))
        self.assertEqual(gh.written("PUT", "/actions/permissions/workflow"), [WORKFLOW_PERMISSIONS])

    def test_the_result_names_every_setting_that_could_not_be_read(self) -> None:
        self.gh(healthy())
        result = settings.configure("ejm-cli", protect=False, hold=True)
        self.assertIn("security_updates", result["unavailable"])
        self.assertIn("immutable_releases", result["unavailable"])
        self.assertNotIn("actions", result["unavailable"])
        self.assertTrue(settings.unavailable(result["security_updates"]))

    def test_workflow_writer_must_be_a_human_maintainer(self) -> None:
        for role, kind in (("write", "User"), ("admin", "Bot")):
            people = [{"login": "writer", "type": kind, "role_name": role, "permissions": {"push": True}}]
            with self.subTest(role=role, kind=kind):
                self.gh({("GET", "repos/ejmlabs/ejm-cli/collaborators?per_page=100&page=1"): people})
                with self.assertRaisesRegex(ValueError, "human maintainers"):
                    settings.collaborators("ejm-cli")

    def test_maintainer_and_readonly_roles_are_allowed(self) -> None:
        self.gh(healthy())
        self.assertEqual([person["login"] for person in settings.collaborators("ejm-cli")], ["owner", "reader"])

    def test_a_collaborator_list_past_the_inspection_limit_is_an_error(self) -> None:
        page = [{"login": f"user{number}", "type": "User", "role_name": "read", "permissions": {"push": False}} for number in range(100)]
        self.gh({("GET", f"repos/ejmlabs/ejm-cli/collaborators?per_page=100&page={number}"): page for number in range(1, 11)})
        with self.assertRaisesRegex(ValueError, "inspection limit"):
            settings.collaborators("ejm-cli")

    def test_the_whole_scope_is_audited_before_any_repository_changes(self) -> None:
        writer = [{"login": "writer", "type": "User", "role_name": "write", "permissions": {"push": True}}]
        gh = self.gh({**healthy("ejm-cli"), **healthy("ejm-ide"), ("GET", "repos/ejmlabs/ejm-ide/collaborators?per_page=100&page=1"): writer})
        with self.assertRaisesRegex(ValueError, "human maintainers"):
            settings.apply(["ejm-cli", "ejm-ide"], protect=True, hold=False)
        self.assertEqual(gh.writes(), [])

    def test_every_repository_is_verified_before_the_first_one_changes(self) -> None:
        bad = {**default_files("ejm-ide"), "evil.yml": EVIL}
        gh = self.gh({**healthy("ejm-cli"), **healthy("ejm-ide", files=bad)})
        with self.assertRaisesRegex(ValueError, "ejm-ide"):
            settings.apply(["ejm-cli", "ejm-ide"], protect=True, hold=False)
        self.assertEqual(gh.writes(), [])

    def test_hold_does_not_need_installed_callers(self) -> None:
        gh = self.gh({**healthy(), **workflow_routes("repos/ejmlabs/ejm-cli", {"old.yml": EVIL})})
        out, _ = self.cli("--hold-actions", "--repository", "ejm-cli")
        self.assertEqual(json.loads(out)["repository"], "ejmlabs/ejm-cli")
        self.assertEqual(gh.written("PUT", "/actions/permissions"), [{"enabled": False}])


class EnvironmentTests(GhCase):
    def test_new_environments_get_a_main_only_policy_no_invented_reviewer_and_a_warning(self) -> None:
        routes = healthy()
        for target in settings.ENVIRONMENTS:
            path = f"repos/ejmlabs/ejm-cli/environments/{target}"
            routes[("GET", path)] = Later([Failure(404, "Not Found"), environment()])
            routes[("GET", path + "/deployment-branch-policies?per_page=100")] = Later([{"total_count": 0, "branch_policies": []}, MAIN_POLICY])
        gh = self.gh(routes)
        result = settings.configure("ejm-cli", protect=False, hold=True)
        for target in settings.ENVIRONMENTS:
            path = f"repos/ejmlabs/ejm-cli/environments/{target}"
            self.assertEqual(gh.written("PUT", path), [{"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}])
            self.assertEqual(gh.written("POST", path + "/deployment-branch-policies"), [{"name": "main", "type": "branch"}])
            self.assertEqual(gh.written("DELETE", "/deployment-branch-policies/5"), [])
        self.assertEqual(result["environments"]["staging"], {"deployment_branch_policy": BRANCH_POLICY,
                                                              "branch_policies": [{"name": "main", "type": "branch"}], "required_reviewers": 0})
        self.assertEqual(result["warnings"], [settings.NO_RELEASER])

    def test_reapplying_keeps_the_human_reviewer_and_removes_every_other_branch_policy(self) -> None:
        routes = healthy()
        listing = {"total_count": 3, "branch_policies": [{"id": 1, "name": "release/*", "type": "branch"}, {"id": 2, "name": "main", "type": "branch"},
                                                         {"id": 3, "name": "v*", "type": "tag"}]}
        for target in settings.ENVIRONMENTS:
            path = f"repos/ejmlabs/ejm-cli/environments/{target}"
            routes[("GET", path)] = environment(reviewers=[REVIEWER], wait=15, prevent_self_review=True)
            routes[("GET", path + "/deployment-branch-policies?per_page=100")] = Later([listing, MAIN_POLICY])
        gh = self.gh(routes)
        result = settings.configure("ejm-cli", protect=False, hold=True)
        production = "repos/ejmlabs/ejm-cli/environments/production"
        self.assertEqual(gh.written("PUT", production), [{"deployment_branch_policy": BRANCH_POLICY, "wait_timer": 15,
                                                          "prevent_self_review": True, "reviewers": [{"type": "User", "id": 42}]}])
        self.assertEqual([path for verb, path, _ in gh.calls if verb == "DELETE" and path.startswith(production)],
                         [production + "/deployment-branch-policies/1", production + "/deployment-branch-policies/3"])
        self.assertEqual(gh.written("POST", production + "/deployment-branch-policies"), [])
        self.assertNotIn("warnings", result)

    def test_other_branches_are_removed_before_main_is_added(self) -> None:
        routes = healthy()
        path = "repos/ejmlabs/ejm-cli/environments/staging"
        routes[("GET", path + "/deployment-branch-policies?per_page=100")] = Later([{"total_count": 1, "branch_policies": [{"id": 9, "name": "dev", "type": "branch"}]}, MAIN_POLICY])
        gh = self.gh(routes)
        settings.configure("ejm-cli", protect=False, hold=True)
        order = [(verb, call_path.rsplit("/", 1)[1]) for verb, call_path, _ in gh.writes() if call_path.startswith(path + "/")]
        self.assertEqual(order, [("DELETE", "9"), ("POST", "deployment-branch-policies")])

    def test_a_reviewer_that_cannot_be_carried_over_stops_before_the_environment_changes(self) -> None:
        routes = healthy()
        routes[("GET", "repos/ejmlabs/ejm-cli/environments/production")] = environment(reviewers=[{"type": "Mannequin", "reviewer": {"id": 1}}])
        gh = self.gh(routes)
        with self.assertRaisesRegex(ValueError, "reviewer"):
            settings.configure("ejm-cli", protect=False, hold=True)
        self.assertFalse(any("/environments/production" in path for _, path, _ in gh.writes()))

    def test_only_site_repositories_with_a_deploy_workflow_on_main_get_environments(self) -> None:
        for name, files in ((".github", shared_files()), ("ejm-cli", default_files("ejm-cli", deploy=False)), ("ejm-ui", default_files("ejm-ui", deploy=False))):
            with self.subTest(name):
                gh = self.gh(healthy(name, files=files))
                result = settings.configure(name, protect=False, hold=True)
                self.assertNotIn("environments", result)
                self.assertFalse(any("/environments/" in path for _, path, _ in gh.calls))

    def test_a_missing_workflow_directory_means_no_deploy(self) -> None:
        routes = healthy()
        routes[("GET", "repos/ejmlabs/ejm-cli/contents/.github/workflows?ref=main")] = Failure(404, "Not Found")
        gh = self.gh(routes)
        self.assertNotIn("environments", settings.configure("ejm-cli", protect=False, hold=True))
        self.assertFalse(any("/environments/" in path for _, path, _ in gh.calls))


class CheckTests(GhCase):
    def check(self, routes: dict[tuple[str, str], Any], name: str = "ejm-cli", pin: str | None = None) -> dict[str, Any]:
        self.gh(routes)
        return settings.check_repository(name, pin)

    def test_a_correct_repository_has_no_failures_and_check_only_reads(self) -> None:
        gh = self.gh(healthy())
        report = settings.check_repository("ejm-cli")
        self.assertEqual(report, {"ok": True, "failures": [], "unreadable": [], "commit": COMMIT, "pin": PIN, "environments": "checked"})
        self.assertEqual(gh.writes(), [])

    def test_each_wrong_control_is_reported(self) -> None:
        protection = "/branches/main/protection"
        checks = ("required_status_checks", "checks")
        cases: tuple[tuple[str, str, Any, str], ...] = (
            ("only one required check", protection, patched(PROTECTION, checks, [{"context": "Quality", "app_id": 15368}]), "required checks must be exactly"),
            ("an extra required check", protection, patched(PROTECTION, checks, [*PROTECTION["required_status_checks"]["checks"], {"context": "Other", "app_id": 15368}]), "required checks must be exactly"),
            ("a check from any app", protection, patched(PROTECTION, checks, [{"context": "Quality", "app_id": None}, {"context": "Repository standards", "app_id": None}]), "required checks must be exactly"),
            ("not strict", protection, patched(PROTECTION, ("required_status_checks", "strict"), False), "strict required checks"),
            ("admins bypass", protection, patched(PROTECTION, ("enforce_admins", "enabled"), False), "enforce_admins"),
            ("two reviews", protection, patched(PROTECTION, ("required_pull_request_reviews", "required_approving_review_count"), 2), "approving review count"),
            ("no review count", protection, patched(PROTECTION, ("required_pull_request_reviews", "required_approving_review_count"), 0), "approving review count"),
            ("stale approvals stay", protection, patched(PROTECTION, ("required_pull_request_reviews", "dismiss_stale_reviews"), False), "stale review dismissal"),
            ("merge commits in history", protection, patched(PROTECTION, ("required_linear_history", "enabled"), False), "linear history"),
            ("unresolved conversations", protection, patched(PROTECTION, ("required_conversation_resolution", "enabled"), False), "conversation resolution"),
            ("force pushes", protection, patched(PROTECTION, ("allow_force_pushes", "enabled"), True), "force pushes allowed"),
            ("deletions", protection, patched(PROTECTION, ("allow_deletions", "enabled"), True), "deletions allowed"),
            ("unprotected main", protection, Failure(404, "Branch not protected"), "check_protection: repos/ejmlabs/ejm-cli/branches/main/protection: gh: Branch not protected (HTTP 404)"),
            ("merge commits", "", patched(REPO, ("allow_merge_commit",), True), "allow_merge_commit"),
            ("no auto-merge", "", patched(REPO, ("allow_auto_merge",), False), "allow_auto_merge"),
            ("no tag ruleset", "/rulesets?includes_parents=false&per_page=100&page=1", [], "ruleset Immutable semantic version tags is missing"),
            ("tag ruleset not enforced", "/rulesets/7", patched(RULESET, ("enforcement",), "evaluate"), "tag ruleset enforcement"),
            ("tag ruleset bypass", "/rulesets/7", patched(RULESET, ("bypass_actors",), [{"actor_id": 1, "actor_type": "Team", "bypass_mode": "always"}]), "tag ruleset bypass actors"),
            ("tag ruleset allows updates", "/rulesets/7", patched(RULESET, ("rules",), [{"type": "deletion"}]), "tag ruleset rules"),
            ("actions disabled", "/actions/permissions", patched(ACTIONS, ("enabled",), False), "actions enabled"),
            ("all actions allowed", "/actions/permissions", patched(ACTIONS, ("allowed_actions",), "all"), "actions allowed_actions"),
            ("sha pinning off", "/actions/permissions", patched(ACTIONS, ("sha_pinning_required",), False), "actions sha_pinning_required"),
            ("extra allowed action", "/actions/permissions/selected-actions", patched(ALLOWLIST, ("patterns_allowed",), [*ALLOWLIST["patterns_allowed"], "evil/*@*"]), "patterns_allowed"),
            ("github owned actions allowed", "/actions/permissions/selected-actions", patched(ALLOWLIST, ("github_owned_allowed",), True), "github_owned_allowed"),
            ("verified creators allowed", "/actions/permissions/selected-actions", patched(ALLOWLIST, ("verified_allowed",), True), "verified_allowed"),
            ("write token default", "/actions/permissions/workflow", patched(WORKFLOW_PERMISSIONS, ("default_workflow_permissions",), "write"), "default workflow permissions"),
            ("workflows cannot approve", "/actions/permissions/workflow", patched(WORKFLOW_PERMISSIONS, ("can_approve_pull_request_reviews",), False), "workflows may approve"),
            ("fork runs get a write token", "/actions/permissions/fork-pr-workflows-private-repos", patched(FORK_RUNS, ("send_write_tokens_to_workflows",), True), "send_write_tokens_to_workflows"),
            ("fork runs get secrets", "/actions/permissions/fork-pr-workflows-private-repos", patched(FORK_RUNS, ("send_secrets_and_variables",), True), "send_secrets_and_variables"),
            ("fork approval is weak", "/actions/permissions/fork-pr-contributor-approval", {"approval_policy": "first_time_contributors"}, "fork pull request approval policy"),
            ("missing approve label", "/labels/gate%3Aapprove", Failure(404, "Not Found"), "gate label gate:approve is missing"),
            ("missing revoke label", "/labels/gate%3Arevoke", Failure(404, "Not Found"), "gate label gate:revoke is missing"),
            ("label read fails", "/labels/gate%3Aapprove", Failure(500, "Server Error"), "check_labels"),
            ("missing staging", "/environments/staging", Failure(404, "Not Found"), "environment staging is missing"),
            ("staging allows every branch", "/environments/staging", patched(environment(), ("deployment_branch_policy",), None), "environment staging deployment branch policy"),
            ("protected branch policy", "/environments/staging", patched(environment(), ("deployment_branch_policy",), {"protected_branches": True, "custom_branch_policies": False}), "environment staging deployment branch policy"),
            ("production allows dev", "/environments/production/deployment-branch-policies?per_page=100",
             {"total_count": 2, "branch_policies": [{"id": 5, "name": "main", "type": "branch"}, {"id": 6, "name": "dev", "type": "branch"}]}, "environment production branch policies"),
            ("production allows a tag named main", "/environments/production/deployment-branch-policies?per_page=100",
             {"total_count": 1, "branch_policies": [{"id": 5, "name": "main", "type": "tag"}]}, "environment production branch policies"),
            ("no branch policy", "/environments/staging/deployment-branch-policies?per_page=100", {"total_count": 0, "branch_policies": []}, "environment staging branch policies"),
            ("an ordinary writer", "/collaborators?per_page=100&page=1", [{"login": "writer", "type": "User", "role_name": "write", "permissions": {"push": True}}], "workflow writers must be human maintainers"),
            ("a bot admin", "/collaborators?per_page=100&page=1", [{"login": "bot", "type": "Bot", "role_name": "admin", "permissions": {"push": True}}], "workflow writers must be human maintainers"),
        )
        for label, suffix, value, expected in cases:
            with self.subTest(label):
                routes = healthy()
                routes[("GET", "repos/ejmlabs/ejm-cli" + suffix)] = value
                report = self.check(routes)
                self.assertFalse(report["ok"])
                self.assertEqual(len(report["failures"]), 1, report["failures"])
                self.assertIn(expected, report["failures"][0])

    def test_production_needs_a_maintainer_reviewer_and_staging_does_not(self) -> None:
        missing: tuple[list[dict[str, Any]] | None, ...] = (None, [])
        for reviewers in missing:
            with self.subTest(reviewers=reviewers):
                routes = healthy()
                routes[("GET", "repos/ejmlabs/ejm-cli/environments/production")] = environment(reviewers=reviewers)
                self.assertEqual(self.check(routes)["failures"], ["environment production must require at least one maintainer as a reviewer"])
        for reviewers in (None, [], [REVIEWER]):
            with self.subTest(staging=reviewers):
                routes = healthy()
                routes[("GET", "repos/ejmlabs/ejm-cli/environments/staging")] = environment(reviewers=reviewers)
                self.assertEqual(self.check(routes)["failures"], [])

    def test_every_failed_assertion_is_listed_not_only_the_first(self) -> None:
        routes = healthy()
        routes[("GET", "repos/ejmlabs/ejm-cli/branches/main/protection")] = patched(patched(PROTECTION, ("enforce_admins", "enabled"), False),
                                                                                  ("required_status_checks", "strict"), False)
        routes[("GET", "repos/ejmlabs/ejm-cli/actions/permissions")] = patched(ACTIONS, ("sha_pinning_required",), False)
        routes[("GET", "repos/ejmlabs/ejm-cli/labels/gate%3Aapprove")] = Failure(404, "Not Found")
        report = self.check(routes)
        self.assertEqual(len(report["failures"]), 4)

    def test_fork_settings_that_the_api_does_not_offer_are_listed_not_failed(self) -> None:
        routes = healthy()
        for suffix in ("/actions/permissions/fork-pr-workflows-private-repos", "/actions/permissions/fork-pr-contributor-approval"):
            routes[("GET", "repos/ejmlabs/ejm-cli" + suffix)] = Failure(404, "Not Found")
        report = self.check(routes)
        self.assertTrue(report["ok"])
        self.assertEqual([item.split(":")[0] for item in report["unreadable"]], ["fork-pr-workflows-private-repos", "fork-pr-contributor-approval"])
        self.assertIn("HTTP 404", report["unreadable"][0])

    def test_the_readable_fork_setting_is_still_asserted_when_the_other_is_not(self) -> None:
        routes = healthy()
        routes[("GET", "repos/ejmlabs/ejm-cli/actions/permissions/fork-pr-workflows-private-repos")] = Failure(422, "Unprocessable")
        routes[("GET", "repos/ejmlabs/ejm-cli/actions/permissions/fork-pr-contributor-approval")] = {"approval_policy": "first_time_contributors_new_to_github"}
        report = self.check(routes)
        self.assertEqual(len(report["unreadable"]), 1)
        self.assertEqual(len(report["failures"]), 1)

    def test_environments_are_not_checked_without_a_deploy_workflow(self) -> None:
        for name, files in (("ejm-cli", default_files("ejm-cli", deploy=False)), (".github", shared_files())):
            with self.subTest(name):
                gh = self.gh(healthy(name, files=files, pin=pin_of(files)))
                report = settings.check_repository(name)
                self.assertEqual(report["environments"], "not applicable: no deploy.yml on main")
                self.assertFalse(any("/environments/" in path for _, path, _ in gh.calls), report["failures"])

    def test_the_governance_pin_must_be_on_shared_main_or_retained(self) -> None:
        compare = f"repos/ejmlabs/.github/compare/{PIN}...main?per_page=1"
        refs = "repos/ejmlabs/.github/git/matching-refs/heads/workflow-pins/?per_page=100&page=1"
        retained = [{"ref": "refs/heads/workflow-pins/" + PIN, "object": {"sha": PIN, "type": "commit"}}]
        other = [{"ref": "refs/heads/workflow-pins/" + OTHER_PIN, "object": {"sha": OTHER_PIN, "type": "commit"}}]
        cases: tuple[tuple[str, Any, list[dict[str, Any]], bool], ...] = (
            ("on main", {"status": "ahead"}, [], True),
            ("main itself", {"status": "identical"}, [], True),
            ("retained, off main", {"status": "diverged"}, retained, True),
            ("retained, behind", {"status": "behind"}, retained, True),
            ("retained, unknown to compare", Failure(404, "Not Found"), retained, True),
            ("off main, nothing retained", {"status": "diverged"}, [], False),
            ("another ref is retained", {"status": "diverged"}, other, False),
            ("unknown commit", Failure(404, "Not Found"), [], False),
            ("unmergeable commit", Failure(422, "Unprocessable"), [], False),
        )
        for label, status, retained_refs, ok in cases:
            with self.subTest(label):
                report = self.check({**healthy(), ("GET", compare): status, ("GET", refs): retained_refs})
                self.assertEqual(report["ok"], ok, report["failures"])
                if not ok:
                    self.assertIn("neither on ejmlabs/.github main nor a workflow-pins ref", report["failures"][0])

    def test_a_compare_outage_is_a_failure_not_a_pass(self) -> None:
        report = self.check({**healthy(), ("GET", f"repos/ejmlabs/.github/compare/{PIN}...main?per_page=1"): Failure(502, "Bad Gateway")})
        self.assertFalse(report["ok"])
        self.assertIn("HTTP 502", report["failures"][0])

    def test_the_pin_can_be_required_to_equal_one_revision(self) -> None:
        self.assertTrue(self.check(healthy(), pin=PIN)["ok"])
        report = self.check(healthy(), pin=OTHER_PIN)
        self.assertEqual(report["failures"], [f"governance pin {PIN} is not the expected {OTHER_PIN}"])

    def test_the_caller_must_pin_governance_to_a_full_sha(self) -> None:
        files = default_files("ejm-cli")
        files["pr.yml"] = files["pr.yml"].replace(PIN, "main")
        report = self.check(healthy(files=files))
        self.assertTrue(any("workflows on main" in failure for failure in report["failures"]))
        self.assertTrue(any("does not pin governance.yml to a full commit SHA" in failure for failure in report["failures"]))


class InstalledTests(GhCase):
    def failures(self, routes: dict[tuple[str, str], Any], name: str = "ejm-cli") -> list[str]:
        self.gh(routes)
        found = settings.Findings()
        settings.check_installed(name, None, found)
        return found.failures

    def test_workflows_are_copied_to_a_temporary_tree_that_is_removed(self) -> None:
        files = default_files("ejm-cli")
        self.gh(healthy(files=files))
        with settings.main_workflows("ejm-cli") as (tree, commit):
            self.assertEqual(commit, COMMIT)
            self.assertEqual({file.name: file.read_text(encoding="utf-8") for file in (tree / ".github/workflows").iterdir()}, files)
        self.assertFalse(tree.exists())

    def test_the_approved_callers_pass(self) -> None:
        self.assertEqual(self.failures(healthy()), [])

    def test_an_extra_or_changed_workflow_is_reported_through_the_standards_check(self) -> None:
        files = default_files("ejm-cli")
        for label, changed in (("extra", {**files, "evil.yml": EVIL}), ("changed release", {**files, "release.yml": files["release.yml"] + "# x\n"})):
            with self.subTest(label):
                self.assertTrue(any(failure.startswith("workflows on main:") for failure in self.failures(healthy(files=changed))))

    def test_native_release_is_checked_where_build_workflow_exists(self) -> None:
        files = {**consumer_workflows(PIN, native=True), "build.yml": NATIVE_BUILD, "deploy.yml": default_files("ejm-cli")["deploy.yml"]}
        self.assertEqual(self.failures(healthy(files=files)), [])
        files["build.yml"] = NATIVE_BUILD.replace("contents: read", "contents: write")
        self.assertTrue(self.failures(healthy(files=files)))
        # A repository outside the native list cannot adopt it by adding build.yml.
        files = {**consumer_workflows(PIN, native=True), "build.yml": NATIVE_BUILD}
        self.assertTrue(self.failures(healthy("ejm-ide", files=files), "ejm-ide"))

    def test_the_shared_repository_reusables_are_validated_the_same_way(self) -> None:
        files = shared_files()
        pin = pin_of(files)
        self.assertEqual(self.failures(healthy(".github", files=files, pin=pin), ".github"), [])
        unpinned = re.sub(r"(actions/[a-z-]+@)[0-9a-f]{40}", r"\1v4", files["governance.yml"], count=1)
        self.assertNotEqual(unpinned, files["governance.yml"])
        self.assertTrue(any(failure.startswith("workflows on main:") for failure in
                            self.failures(healthy(".github", files={**files, "governance.yml": unpinned}, pin=pin), ".github")))

    def test_links_directories_and_submodules_are_not_workflow_files(self) -> None:
        files = default_files("ejm-cli")
        for kind in ("symlink", "dir", "submodule"):
            with self.subTest(kind):
                listed = [{**entry(filename, text), "type": kind if filename == "release.yml" else "file"} for filename, text in files.items()]
                routes = {**healthy(files=files), **workflow_routes("repos/ejmlabs/ejm-cli", files, listed)}
                self.assertEqual(self.failures(routes), ["workflows on main: ejm-cli: release.yml is not a regular file"])

    def test_a_file_that_resolves_to_a_different_blob_is_rejected(self) -> None:
        # The contents API follows a symlink to a normal file, so the fetched blob differs from the listed one.
        files = default_files("ejm-cli")
        routes = healthy(files=files)
        directory = "repos/ejmlabs/ejm-cli/contents/.github/workflows"
        routes[("GET", f"{directory}/release.yml?ref={COMMIT}")] = {**routes[("GET", f"{directory}/release.yml?ref={COMMIT}")], "sha": "f" * 40}
        self.assertEqual(self.failures(routes), ["workflows on main: ejm-cli: cannot read release.yml as the committed file"])

    def test_files_over_the_bound_are_not_fetched(self) -> None:
        files = default_files("ejm-cli")
        listed = [{**entry(filename, text), "size": settings.MAX_WORKFLOW_BYTES + 1} for filename, text in files.items()]
        gh = self.gh({**healthy(files=files), **workflow_routes("repos/ejmlabs/ejm-cli", files, listed)})
        found = settings.Findings()
        settings.check_installed("ejm-cli", None, found)
        self.assertIn("exceeds", found.failures[0])
        self.assertFalse(any(re.search(r"/workflows/[^?]+\?", path) for _, path, _ in gh.calls))

    def test_a_file_whose_content_is_not_its_listed_size_is_rejected(self) -> None:
        files = default_files("ejm-cli")
        directory = "repos/ejmlabs/ejm-cli/contents/.github/workflows"
        routes = healthy(files=files)
        routes[("GET", f"{directory}/release.yml?ref={COMMIT}")] = {**routes[("GET", f"{directory}/release.yml?ref={COMMIT}")], "content": wrapped("short")}
        self.assertEqual(self.failures(routes), ["workflows on main: ejm-cli: release.yml differs from its listed size"])

    def test_content_that_is_not_base64_is_rejected(self) -> None:
        files = default_files("ejm-cli")
        directory = "repos/ejmlabs/ejm-cli/contents/.github/workflows"
        routes = healthy(files=files)
        routes[("GET", f"{directory}/release.yml?ref={COMMIT}")] = {**routes[("GET", f"{directory}/release.yml?ref={COMMIT}")], "encoding": "none", "content": ""}
        self.assertEqual(self.failures(routes), ["workflows on main: ejm-cli: cannot read release.yml as the committed file"])

    def test_unsafe_names_and_too_many_files_are_rejected(self) -> None:
        files = default_files("ejm-cli")
        for label, listed, expected in (
            ("parent path", [{**entry("../escape.yml", "x"), "name": "../escape.yml"}], "unsafe workflow file name"),
            ("hidden name", [{**entry(".hidden", "x")}], "unsafe workflow file name"),
            ("no name", [{"type": "file", "size": 1}], "unsafe workflow file name"),
            ("too many", [entry(f"w{number}.yml", "x") for number in range(settings.MAX_WORKFLOW_FILES + 1)], "at most"),
        ):
            with self.subTest(label):
                routes = {**healthy(files=files), **workflow_routes("repos/ejmlabs/ejm-cli", {}, listed)}
                self.assertIn(expected, self.failures(routes)[0])

    def test_a_workflows_path_that_is_a_file_or_missing_is_rejected(self) -> None:
        directory = "repos/ejmlabs/ejm-cli/contents/.github/workflows"
        for label, answer, expected in (("a file", {"type": "file", "name": "workflows"}, "must be a directory"),
                                        ("a symlink", {"type": "symlink", "target": "../x"}, "must be a directory"),
                                        ("missing", Failure(404, "Not Found"), "HTTP 404")):
            with self.subTest(label):
                failures = self.failures({**healthy(), ("GET", f"{directory}?ref={COMMIT}"): answer})
                self.assertIn(expected, failures[0])

    def test_an_unresolvable_main_is_a_failure(self) -> None:
        self.assertIn("HTTP 404", self.failures({**healthy(), ("GET", "repos/ejmlabs/ejm-cli/branches/main"): Failure(404, "Branch not found")})[0])
        self.assertIn("cannot resolve the main commit", self.failures({**healthy(), ("GET", "repos/ejmlabs/ejm-cli/branches/main"): {"commit": {"sha": "main"}}})[0])


class CommandLineTests(GhCase):
    def test_check_exits_zero_and_prints_a_summary_when_everything_is_correct(self) -> None:
        gh = self.gh(healthy())
        out, err = self.cli("--check", "--repository", "ejm-cli")
        report = json.loads(out)
        self.assertEqual((report["mode"], report["ok"]), ("check", True))
        self.assertEqual(report["repositories"]["ejm-cli"]["pin"], PIN)
        self.assertEqual(err, "")
        self.assertEqual(gh.writes(), [])

    def test_check_exits_nonzero_listing_every_failure(self) -> None:
        routes = healthy()
        routes[("GET", "repos/ejmlabs/ejm-cli/branches/main/protection")] = patched(PROTECTION, ("enforce_admins", "enabled"), False)
        routes[("GET", "repos/ejmlabs/ejm-cli/labels/gate%3Arevoke")] = Failure(404, "Not Found")
        gh = self.gh(routes)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            settings.main(["--check", "--repository", "ejm-cli"])
        self.assertEqual(raised.exception.code, 1)
        self.assertFalse(json.loads(out.getvalue())["ok"])
        self.assertEqual(len(json.loads(out.getvalue())["repositories"]["ejm-cli"]["failures"]), 2)
        self.assertEqual(err.getvalue().count("FAIL ejm-cli:"), 2)
        self.assertEqual(gh.writes(), [])

    def test_check_covers_the_default_repositories_and_changes_nothing(self) -> None:
        shared = shared_files()
        routes: dict[tuple[str, str], Any] = {}
        for name in settings.NAMES:
            routes.update(healthy(name, files=shared, pin=pin_of(shared)) if name == ".github" else healthy(name))
        gh = self.gh(routes)
        out, _ = self.cli("--check")
        report = json.loads(out)
        self.assertEqual(list(report["repositories"]), list(settings.NAMES))
        self.assertTrue(report["ok"], out)
        self.assertEqual(gh.writes(), [])

    def test_unreadable_settings_are_printed_without_failing_the_check(self) -> None:
        self.gh({**healthy(), ("GET", "repos/ejmlabs/ejm-cli/actions/permissions/fork-pr-workflows-private-repos"): Failure(404, "Not Found")})
        out, err = self.cli("--check", "--repository", "ejm-cli")
        self.assertTrue(json.loads(out)["ok"])
        self.assertIn("UNREADABLE ejm-cli: fork-pr-workflows-private-repos: gh: Not Found (HTTP 404)", err)

    def test_a_missing_or_hung_gh_is_an_error_message_not_a_traceback(self) -> None:
        for error in (FileNotFoundError("gh"), subprocess.TimeoutExpired("gh", 120)):
            with self.subTest(type(error).__name__), patch.object(subprocess, "run", side_effect=error), self.assertRaises(SystemExit) as raised:
                self.cli("--hold-actions", "--repository", "ejm-cli")
            self.assertEqual(raised.exception.code, "error: repos/ejmlabs/ejm-cli/collaborators?per_page=100&page=1: cannot run gh: " + type(error).__name__)

    def test_check_cannot_be_combined_with_a_write_mode(self) -> None:
        for flag in ("--protect-main", "--hold-actions"):
            with self.subTest(flag), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                settings.main(["--check", flag])
            self.assertEqual(raised.exception.code, 2)

    def test_a_standards_revision_must_be_a_full_sha(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as raised:
            settings.main(["--standards-revision", "main"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("full lowercase commit SHA", err.getvalue())

    def test_an_error_exits_with_a_message_instead_of_a_traceback(self) -> None:
        self.gh({**healthy(), ("GET", "repos/ejmlabs/ejm-cli/collaborators?per_page=100&page=1"):
                 [{"login": "writer", "type": "User", "role_name": "write", "permissions": {"push": True}}]})
        with self.assertRaises(SystemExit) as raised:
            self.cli("--hold-actions", "--repository", "ejm-cli")
        self.assertIn("human maintainers", str(raised.exception.code))

    def test_apply_prints_one_json_result_per_repository_and_warns_when_production_has_no_reviewer(self) -> None:
        routes = {**healthy("ejm-cli"), **healthy("ejm-ide")}
        for name in ("ejm-cli", "ejm-ide"):
            routes[("GET", f"repos/ejmlabs/{name}/environments/production")] = environment()
        self.gh(routes)
        out, err = self.cli("--hold-actions", "--repository", "ejm-cli", "--repository", "ejm-ide", "--repository", "ejm-cli")
        results = [json.loads(line) for line in out.splitlines()]
        self.assertEqual([result["repository"] for result in results], ["ejmlabs/ejm-cli", "ejmlabs/ejm-ide"])
        self.assertEqual([person["login"] for person in results[0]["collaborators"]], ["owner", "reader"])
        self.assertEqual(err.splitlines(), [f"warning: {name}: {settings.NO_RELEASER}" for name in ("ejm-cli", "ejm-ide")])
        self.gh({**healthy("ejm-cli")})
        _, err = self.cli("--hold-actions", "--repository", "ejm-cli")
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
