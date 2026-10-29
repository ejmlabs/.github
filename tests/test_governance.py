import copy
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import governance
from governance import (
    GitHub,
    admit,
    command,
    current_pr,
    dismiss_bot_approvals,
    finish,
    human,
    live_ready,
)

SHA = "a" * 40
USER: dict[str, Any] = {"id": 1, "login": "maintainer", "type": "User"}
TIMESTAMP = "2026-10-19T00:00:00Z"


class API(GitHub):
    review: dict[str, Any]

    def __init__(self) -> None:
        self.repo = "ejmlabs/ejm-cli"
        self.pr: dict[str, Any] = {"state": "open", "draft": False, "head": {"sha": SHA, "repo": {"full_name": self.repo}}, "base": {"ref": "main", "sha": "b" * 40, "repo": {"full_name": self.repo}}, "changed_files": 5, "additions": 20, "deletions": 4, "labels": []}
        self.comments: dict[int, dict[str, Any]] = {7: {"user": copy.deepcopy(USER), "body": "/ready " + SHA, "issue_url": "https://api.github.com/repos/ejmlabs/ejm-cli/issues/1", "html_url": "https://github.com/ejmlabs/ejm-cli/issues/1#issuecomment-7", "created_at": TIMESTAMP, "updated_at": TIMESTAMP}}
        self.log: list[dict[str, Any]] = []
        self.role = "maintain"
        self.roles: dict[str, str] = {}
        self.reviews: list[dict[str, Any]] = []
        self.dismiss_code: int | None = None
        self.after_review: Callable[[], object] | None = None

    def permission(self, login: str) -> str:
        return self.roles.get(login, self.role)

    def status(self, sha: str, context: str, state: str, description: str) -> None:
        self.log.insert(0, {"sha": sha, "context": context, "state": state, "description": description})

    def statuses(self, sha: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for status in self.log:
            if status["sha"] == sha:
                result.setdefault(status["context"], status)
        return result

    def pages(self, path: str, limit: int = 10) -> list[dict[str, Any]]:  # noqa: ARG002 - signature fixed by the base class
        return self.log if "statuses" in path else copy.deepcopy(self.reviews)

    def request(self, path: str, method: str = "GET", data: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/pulls/1":
            return copy.deepcopy(self.pr)
        if path.startswith("/issues/comments/"):
            number = int(path.rsplit("/", 1)[1])
            if number not in self.comments:
                error = urllib.error.HTTPError(path, 404, "Not Found", Message(), None)
                error.close()
                raise error
            return copy.deepcopy(self.comments[number])
        if path == "/pulls/1/reviews" and method == "POST":
            assert data is not None
            self.review = data
            review = {**data, "id": len(self.reviews) + 1, "state": "APPROVED", "user": {"login": "github-actions[bot]", "type": "Bot"}}
            self.reviews.append(review)
            if self.after_review is not None:
                self.after_review()
            return copy.deepcopy(review)
        if path.startswith("/pulls/1/reviews/"):
            review = self.reviews[int(path.split("/")[4]) - 1]
            if method == "PUT":
                if self.dismiss_code is not None:
                    error = urllib.error.HTTPError(path, self.dismiss_code, "Dismissal failed", Message(), None)
                    error.close()
                    raise error
                review["state"] = "DISMISSED"
            return copy.deepcopy(review)
        if path.endswith("/cancel"):
            return {}
        raise AssertionError(path)


class AdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.old_env = dict(os.environ)

        def restore_environment() -> None:
            os.environ.clear()
            os.environ.update(self.old_env)

        self.addCleanup(restore_environment)
        os.environ.update(GITHUB_OUTPUT=str(Path(self.directory.name) / "output"), GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1")
        self.api = API()
        self.event: dict[str, Any] = {"action": "created", "issue": {"number": 1, "pull_request": {}}, "comment": {**self.api.comments[7], "id": 7}, "sender": USER}
        self.event["issue"]["pull_request"] = {"url": "test"}

    def approval(self, user: dict[str, Any] | None = None) -> dict[str, Any]:
        event = copy.deepcopy(self.event)
        event["comment"].update(id=8, body="/approve " + SHA, html_url="https://github.com/ejmlabs/ejm-cli/issues/1#issuecomment-8")
        if user is not None:
            event["comment"]["user"] = user
            event["sender"] = user
        self.api.comments[8] = copy.deepcopy(event["comment"])
        return event

    def finish_environment(self) -> None:
        os.environ.update(PR_NUMBER="1", PR_HEAD=SHA, ADMISSION_ID="7", JOB_RESULTS='{"quality":{"result":"success"},"registry":{"result":"success"},"standards":{"result":"success"}}')

    def test_command_rejects_short_sha_multiline_and_injection(self) -> None:
        for text in ("/ready abc", "/ready " + SHA + "\n/approve " + SHA, "/ready $(id)", "/ready " + "A" * 40):
            with self.assertRaises(ValueError):
                command(text)

    def test_only_human_maintainers_can_admit_including_authors(self) -> None:
        self.assertTrue(human(USER, "maintain"))
        self.assertFalse(human(USER, "write"))
        self.assertFalse(human({"type": "Bot"}, "admin"))
        self.api.role = "write"
        with self.assertRaises(ValueError):
            admit(self.api, self.event)
        self.assertFalse(self.api.log)

    def test_admission_consumed_once_and_reruns_rejected(self) -> None:
        admit(self.api, self.event)
        self.assertEqual(self.api.statuses(SHA)["Human readiness"]["state"], "success")
        self.assertIn("run=true", Path(os.environ["GITHUB_OUTPUT"]).read_text())
        with self.assertRaises(ValueError):
            admit(self.api, self.event)
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        with self.assertRaises(ValueError):
            admit(API(), self.event)

    def test_same_repo_pr_is_admitted_and_verified(self) -> None:
        self.assertTrue(current_pr(self.api.pr, SHA))
        admit(self.api, self.event)
        self.assertEqual(self.api.statuses(SHA)["Human readiness"]["state"], "success")
        self.assertIn("run=true", Path(os.environ["GITHUB_OUTPUT"]).read_text())
        self.assertEqual(live_ready(self.api, 1, SHA, 7), self.api.pr)

    def test_automated_results_never_approve_and_only_success_passes_a_check(self) -> None:
        for state in ("success", "failure", "cancelled", "skipped", None):
            for job, context in (("quality", "Quality"), ("registry", "Quality"), ("standards", "Repository standards")):
                with self.subTest(job=job, state=state):
                    self.api = API()
                    admit(self.api, self.event)
                    self.assertEqual(self.api.statuses(SHA)[context]["state"], "pending")
                    self.finish_environment()
                    results = json.loads(os.environ["JOB_RESULTS"])
                    if state is None:
                        results.pop(job)
                    else:
                        results[job]["result"] = state
                    os.environ["JOB_RESULTS"] = json.dumps(results)
                    finish(self.api)
                    statuses = self.api.statuses(SHA)
                    self.assertEqual(statuses[context]["state"], "success" if state == "success" else "failure")
                    terminal = [status for status in self.api.log if status["context"] == context
                                and status["state"] in ("success", "failure")]
                    self.assertEqual(len(terminal), 1)
                    self.assertEqual(statuses["Maintainer approval"]["state"], "pending")
                    self.assertFalse(self.api.reviews)

    def test_the_gate_has_four_statuses_and_no_review_status_or_label_handling(self) -> None:
        self.assertEqual(governance.CONTEXTS, ("Human readiness", "Maintainer approval", "Quality", "Repository standards"))
        admit(self.api, self.event)
        self.finish_environment()
        finish(self.api)
        self.assertEqual(set(self.api.statuses(SHA)), set(governance.CONTEXTS))
        for name in ("labels", "relabel", "blocking_labels", "is_value_no", "SECURITY_LABEL", "BLOCKING_LABELS", "LABEL_BLOCKED"):
            self.assertFalse(hasattr(governance, name), name)

    def test_readmission_resets_old_successes_before_a_run_can_be_cancelled(self) -> None:
        admit(self.api, self.event)
        self.finish_environment()
        finish(self.api)
        self.assertEqual(self.api.statuses(SHA)["Quality"]["state"], "success")
        revoke = copy.deepcopy(self.event)
        revoke["comment"].update(id=9, body="/revoke " + SHA)
        admit(self.api, revoke)
        readmit = copy.deepcopy(self.event)
        readmit["comment"].update(id=10, html_url="https://github.com/ejmlabs/ejm-cli/issues/1#issuecomment-10")
        self.api.comments[10] = copy.deepcopy(readmit["comment"])
        admit(self.api, readmit)
        # A cancelled run may never call finish; its old review must stay blocked.
        for context in ("Maintainer approval", "Quality", "Repository standards"):
            self.assertEqual(self.api.statuses(SHA)[context]["state"], "pending")

    def test_admit_rejects_fork_and_deleted_fork_heads_with_manual_review_message(self) -> None:
        for repo in ({"full_name": "outside/ejm-cli"}, None):
            with self.subTest(repo=repo):
                api = API()
                api.pr["head"]["repo"] = repo
                with self.assertRaisesRegex(ValueError, "Fork PRs require manual review"):
                    admit(api, self.event)
                self.assertFalse(api.log)
        self.assertNotIn("run=true", Path(os.environ["GITHUB_OUTPUT"]).read_text())

    def test_verify_rejects_fork_and_deleted_fork_heads_after_admission(self) -> None:
        admit(self.api, self.event)
        before = copy.deepcopy(self.api.log)
        for repo in ({"full_name": "outside/ejm-cli"}, None):
            with self.subTest(repo=repo):
                self.api.pr["head"]["repo"] = repo
                self.assertFalse(current_pr(self.api.pr, SHA))
                with self.assertRaises(ValueError):
                    live_ready(self.api, 1, SHA, 7)
                self.assertEqual(self.api.log, before)

    def test_replayed_jobs_cannot_verify_or_overwrite_completed_results(self) -> None:
        admit(self.api, self.event)
        admit(self.api, self.approval())
        self.finish_environment()
        finish(self.api)
        before = copy.deepcopy(self.api.log)
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        with self.assertRaises(ValueError):
            live_ready(self.api, 1, SHA, 7)
        with self.assertRaises(ValueError):
            finish(self.api)
        self.assertEqual(self.api.log, before)
        self.assertEqual(self.api.reviews[0]["state"], "APPROVED")

    def test_stale_heads_drafts_and_large_prs_cannot_admit(self) -> None:
        for key, value in (("head", {"sha": "c" * 40, "repo": {"full_name": self.api.repo}}), ("draft", True), ("changed_files", 201), ("additions", 12001)):
            api = API()
            api.pr[key] = value
            with self.assertRaises(ValueError):
                admit(api, self.event)
            self.assertFalse(api.log)

    def fork(self, api: API, repo: str | None) -> None:
        api.pr["head"]["repo"] = None if repo is None else {"full_name": repo}

    def test_current_pr_rejects_fork_and_deleted_head_repositories(self) -> None:
        self.assertTrue(current_pr(self.api.pr, SHA))
        for repo in ("outside/ejm-cli", None):
            with self.subTest(repo=repo):
                api = API()
                self.fork(api, repo)
                self.assertFalse(current_pr(api.pr, SHA))
                del api.pr["head"]["repo"]
                self.assertFalse(current_pr(api.pr, SHA))

    def test_fork_and_deleted_head_repository_prs_cannot_be_admitted(self) -> None:
        for repo in ("outside/ejm-cli", None):
            for kind in ("ready", "approve"):
                with self.subTest(repo=repo, kind=kind):
                    self.api = API()
                    if kind == "approve":
                        admit(self.api, self.event)
                    event = self.event if kind == "ready" else self.approval()
                    before = copy.deepcopy(self.api.log)
                    self.fork(self.api, repo)
                    with self.assertRaisesRegex(ValueError, "Fork PRs require manual review"):
                        admit(self.api, event)
                    self.assertEqual(self.api.log, before)
                    self.assertFalse(self.api.reviews)
                    self.assertIn("run=false", Path(os.environ["GITHUB_OUTPUT"]).read_text().splitlines()[-1])

    def test_verify_and_finish_fail_closed_when_head_repository_becomes_a_fork(self) -> None:
        for repo in ("outside/ejm-cli", None):
            with self.subTest(repo=repo):
                self.api = API()
                admit(self.api, self.event)
                admit(self.api, self.approval())
                self.fork(self.api, repo)
                with self.assertRaisesRegex(ValueError, "not a same-repository branch"):
                    live_ready(self.api, 1, SHA, 7)
                self.finish_environment()
                with self.assertRaisesRegex(ValueError, "not a same-repository branch"):
                    finish(self.api)
                for context in ("Human readiness", "Maintainer approval"):
                    self.assertEqual(self.api.statuses(SHA)[context]["state"], "failure")
                self.assertNotIn("Quality", {k for k, v in self.api.statuses(SHA).items() if v["state"] == "success"})
                self.assertEqual(self.api.reviews[0]["state"], "DISMISSED")

    def test_edited_or_deleted_decisions_are_invalidated_on_fork_prs(self) -> None:
        for repo in ("outside/ejm-cli", None):
            for kind in ("ready", "approve"):
                for action in ("edited", "deleted"):
                    with self.subTest(repo=repo, kind=kind, action=action):
                        self.api = API()
                        admit(self.api, self.event)
                        approve = self.approval()
                        admit(self.api, approve)
                        self.fork(self.api, repo)
                        changed = copy.deepcopy(self.event if kind == "ready" else approve)
                        changed["action"] = action
                        admit(self.api, changed)
                        for context in ("Human readiness", "Maintainer approval"):
                            self.assertEqual(self.api.statuses(SHA)[context]["state"], "failure")
                        self.assertEqual(self.api.reviews[0]["state"], "DISMISSED")

    def revocation(self, user: dict[str, Any] = USER) -> dict[str, Any]:
        event = copy.deepcopy(self.event)
        event["comment"].update(id=9, body="/revoke " + SHA, user=user)
        event["sender"] = user
        return event

    def test_maintainers_can_revoke_fork_and_deleted_head_repository_prs(self) -> None:
        for repo in ("outside/ejm-cli", None):
            with self.subTest(repo=repo):
                self.api = API()
                admit(self.api, self.event)
                admit(self.api, self.approval())
                self.fork(self.api, repo)
                admit(self.api, self.revocation())
                for context in ("Human readiness", "Maintainer approval"):
                    self.assertEqual(self.api.statuses(SHA)[context]["state"], "failure")
                self.assertEqual(self.api.reviews[0]["state"], "DISMISSED")

    def test_non_maintainers_cannot_revoke_fork_prs(self) -> None:
        admit(self.api, self.event)
        admit(self.api, self.approval())
        self.fork(self.api, "outside/ejm-cli")
        before = copy.deepcopy(self.api.log)
        self.api.roles["writer"] = "write"
        with self.assertRaises(ValueError):
            admit(self.api, self.revocation({"id": 4, "login": "writer", "type": "User"}))
        self.assertEqual(self.api.log, before)
        self.assertEqual(self.api.reviews[0]["state"], "APPROVED")

    def test_live_comment_and_permission_must_survive_until_result(self) -> None:
        admit(self.api, self.event)
        live_ready(self.api, 1, SHA, 7)
        self.api.comments[7]["body"] += " edited"
        with self.assertRaises(ValueError):
            live_ready(self.api, 1, SHA, 7)
        self.api.comments[7]["body"] = "/ready " + SHA
        self.api.role = "read"
        with self.assertRaises(ValueError):
            live_ready(self.api, 1, SHA, 7)

    def test_self_approval_records_exact_commit_without_granting_readiness(self) -> None:
        approve = self.approval()
        with self.assertRaises(ValueError):
            admit(self.api, approve)
        admit(self.api, self.event)
        admit(self.api, approve)
        self.assertEqual(self.api.review["commit_id"], SHA)
        self.assertEqual(self.api.review["event"], "APPROVE")
        self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "success")

    def test_stale_approval_event_requires_the_exact_live_decision(self) -> None:
        cases = (
            ("deleted", None, None),
            ("body", "body", "/approve " + SHA + " "),
            ("head", "body", "/approve " + "c" * 40),
            ("other PR", "issue_url", "https://api.github.com/repos/ejmlabs/ejm-cli/issues/2"),
            ("other repository", "issue_url", "https://api.github.com/repos/ejmlabs/ejm-ide/issues/1"),
            ("author", "user", {"id": 2, "login": "another-maintainer", "type": "User"}),
            ("author ID", "user", {**USER, "id": 2}),
            ("bot", "user", {**USER, "type": "Bot"}),
            ("edited", "updated_at", "2026-10-19T00:00:01Z"),
        )
        for name, key, value in cases:
            with self.subTest(name=name):
                self.api = API()
                admit(self.api, self.event)
                approve = self.approval()
                if key is None:
                    del self.api.comments[8]
                else:
                    self.api.comments[8][key] = value
                with self.assertRaises((ValueError, urllib.error.HTTPError)):
                    admit(self.api, approve)
                self.assertFalse(hasattr(self.api, "review"))
                self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "pending")

    def test_approval_deleted_during_native_review_creation_is_dismissed(self) -> None:
        admit(self.api, self.event)
        approve = self.approval()
        self.api.after_review = lambda: self.api.comments.pop(8)
        with self.assertRaises(urllib.error.HTTPError):
            admit(self.api, approve)
        self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "failure")
        self.assertEqual(self.api.reviews[0]["state"], "DISMISSED")

    def test_another_maintainer_can_invalidate_deleted_decision(self) -> None:
        admit(self.api, self.event)
        deleted = copy.deepcopy(self.event)
        deleted.update(action="deleted", sender={"login": "another-maintainer", "type": "User"})
        admit(self.api, deleted)
        self.assertEqual(self.api.statuses(SHA)["Human readiness"]["state"], "failure")

    def test_known_decisions_are_invalidated_before_editor_role_checks(self) -> None:
        for kind in ("ready", "approve"):
            for action in ("edited", "deleted"):
                for sender in (USER, {"id": 3, "login": "moderation[bot]", "type": "Bot"}):
                    with self.subTest(kind=kind, action=action, sender=sender["type"]):
                        self.api = API()
                        admit(self.api, self.event)
                        approve = self.approval()
                        admit(self.api, approve)
                        changed = copy.deepcopy(self.event if kind == "ready" else approve)
                        changed.update(action=action, sender=sender)
                        self.api.role = "read"
                        admit(self.api, changed)
                        for context in ("Human readiness", "Maintainer approval"):
                            self.assertEqual(self.api.statuses(SHA)[context]["state"], "failure")
                        self.assertTrue(all(review["state"] == "DISMISSED" for review in self.api.reviews))

    def test_failed_native_dismissal_cannot_silently_keep_an_approval(self) -> None:
        for code in (403, 422):
            with self.subTest(code=code):
                self.api = API()
                admit(self.api, self.event)
                approve = self.approval()
                admit(self.api, approve)
                self.api.dismiss_code = code
                deleted = copy.deepcopy(approve)
                deleted["action"] = "deleted"
                with self.assertRaises(urllib.error.HTTPError):
                    admit(self.api, deleted)
                self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "failure")

    def test_concurrently_dismissed_review_does_not_fail_invalidation(self) -> None:
        admit(self.api, self.event)
        admit(self.api, self.approval())
        self.api.dismiss_code = 422
        request = self.api.request

        def dismissed_elsewhere(path: str, method: str = "GET", data: dict[str, Any] | None = None) -> dict[str, Any]:
            if path.endswith("/dismissals"):
                self.api.reviews[0]["state"] = "DISMISSED"
            return request(path, method, data)

        with mock.patch.object(self.api, "request", dismissed_elsewhere):
            dismiss_bot_approvals(self.api, 1, SHA, "Already dismissed by another maintainer")

    def test_unknown_deleted_comment_does_not_invalidate_decisions(self) -> None:
        admit(self.api, self.event)
        before = copy.deepcopy(self.api.log)
        deleted = copy.deepcopy(self.event)
        deleted.update(action="deleted", sender={"login": "reader", "type": "User"})
        deleted["comment"]["id"] = 99
        self.api.role = "read"
        admit(self.api, deleted)
        self.assertEqual(self.api.log, before)

    def test_finish_revalidates_existing_approval(self) -> None:
        cases = ("deleted", "edited", "different SHA", "other PR", "demoted", "missing marker")
        for name in cases:
            with self.subTest(name=name):
                self.api = API()
                admit(self.api, self.event)
                approve = self.approval({"id": 2, "login": "approver", "type": "User"})
                admit(self.api, approve)
                if name == "deleted":
                    del self.api.comments[8]
                elif name == "edited":
                    self.api.comments[8]["updated_at"] = "2026-10-19T00:00:01Z"
                elif name == "different SHA":
                    self.api.comments[8]["body"] = "/approve " + "c" * 40
                elif name == "other PR":
                    self.api.comments[8]["issue_url"] = "https://api.github.com/repos/ejmlabs/ejm-cli/issues/2"
                elif name == "demoted":
                    self.api.roles["approver"] = "read"
                else:
                    self.api.status(SHA, "Maintainer approval", "success", "No human decision marker")
                self.finish_environment()
                with self.assertRaises((ValueError, urllib.error.HTTPError)):
                    finish(self.api)
                self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "failure")
                self.assertEqual(self.api.statuses(SHA)["Quality"]["state"], "pending")
                self.assertTrue(all(review["state"] == "DISMISSED" for review in self.api.reviews))

    def test_finish_allows_approval_after_checks_complete(self) -> None:
        admit(self.api, self.event)
        self.finish_environment()
        finish(self.api)
        self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "pending")
        self.assertEqual(self.api.statuses(SHA)["Quality"]["state"], "success")
        admit(self.api, self.approval())
        self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "success")

    def test_finish_preserves_a_live_self_approval(self) -> None:
        admit(self.api, self.event)
        admit(self.api, self.approval())
        self.finish_environment()
        finish(self.api)
        for context in ("Maintainer approval", "Quality", "Repository standards"):
            self.assertEqual(self.api.statuses(SHA)[context]["state"], "success")

    def test_finish_dismisses_approval_when_readiness_was_deleted(self) -> None:
        admit(self.api, self.event)
        admit(self.api, self.approval())
        del self.api.comments[7]
        self.finish_environment()
        with self.assertRaises(urllib.error.HTTPError):
            finish(self.api)
        for context in ("Human readiness", "Maintainer approval"):
            self.assertEqual(self.api.statuses(SHA)[context]["state"], "failure")
        self.assertEqual(self.api.reviews[0]["state"], "DISMISSED")

    def test_old_finish_cannot_revoke_a_new_admission(self) -> None:
        admit(self.api, self.event)
        admit(self.api, self.approval())
        self.api.status(SHA, "Human readiness", "success", "[ready:9] [run:456] New human admission")
        before = copy.deepcopy(self.api.log)
        self.finish_environment()
        with self.assertRaises(ValueError):
            finish(self.api)
        self.assertEqual(self.api.log, before)
        self.assertEqual(self.api.reviews[0]["state"], "APPROVED")

    def test_old_finish_does_not_dismiss_a_review_for_a_new_head(self) -> None:
        admit(self.api, self.event)
        admit(self.api, self.approval())
        newer = {**self.api.reviews[0], "id": 2, "commit_id": "c" * 40}
        self.api.reviews.append(newer)
        self.api.pr["head"]["sha"] = "c" * 40
        self.finish_environment()
        with self.assertRaises(ValueError):
            finish(self.api)
        self.assertEqual(self.api.reviews[0]["state"], "DISMISSED")
        self.assertEqual(self.api.reviews[1]["state"], "APPROVED")

    def test_results_fail_closed_on_an_incomplete_check_and_changed_head(self) -> None:
        admit(self.api, self.event)
        os.environ.update(PR_NUMBER="1", PR_HEAD=SHA, ADMISSION_ID="7", JOB_RESULTS='{"quality":{"result":"success"},"registry":{"result":"success"},"standards":{"result":"skipped"}}')
        finish(self.api)
        self.assertEqual(self.api.statuses(SHA)["Repository standards"]["state"], "failure")
        self.api.pr["head"]["sha"] = "c" * 40
        with self.assertRaises(ValueError):
            finish(self.api)


if __name__ == "__main__":
    unittest.main()
