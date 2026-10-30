import copy
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from governance import (
    APPROVE_LABEL,
    REQUIRED_CONTEXTS,
    REVOKE_LABEL,
    GitHub,
    admit,
    current_pr,
    finish,
    human,
    live_ready,
)

SHA = "a" * 40
USER: dict[str, Any] = {"id": 1, "login": "maintainer", "type": "User"}
OUTSIDER: dict[str, Any] = {"id": 2, "login": "contributor", "type": "User"}


class API(GitHub):
    def __init__(self) -> None:
        self.repo = "ejmlabs/ejm-cli"
        self.pr: dict[str, Any] = {
            "number": 1,
            "state": "open",
            "draft": False,
            "user": copy.deepcopy(USER),
            "head": {"sha": SHA, "repo": {"full_name": self.repo}},
            "base": {"ref": "main", "sha": "b" * 40, "repo": {"full_name": self.repo}},
            "changed_files": 5,
            "additions": 20,
            "deletions": 4,
            "labels": [],
        }
        self.log: list[dict[str, Any]] = []
        self.role = "maintain"
        self.roles: dict[str, str] = {}
        self.reviews: list[dict[str, Any]] = []
        self.deleted_labels: list[str] = []
        self.cancelled: list[str] = []
        self.review: dict[str, Any] = {}
        self.after_review: Callable[[], object] | None = None

    def permission(self, login: str) -> str:
        return self.roles.get(login, self.role if login == USER["login"] else "write")

    def status(self, sha: str, context: str, state: str, description: str) -> None:
        self.log.insert(0, {"sha": sha, "context": context, "state": state, "description": description})

    def statuses(self, sha: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for status in self.log:
            if status["sha"] == sha:
                result.setdefault(status["context"], status)
        return result

    def pages(self, path: str, limit: int = 10) -> list[dict[str, Any]]:  # noqa: ARG002
        return copy.deepcopy(self.reviews) if "reviews" in path else self.log

    def request(self, path: str, method: str = "GET", data: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/pulls/1":
            return copy.deepcopy(self.pr)
        if path.startswith("/actions/runs") and "cancel" in path:
            self.cancelled.append(path)
            return {}
        if path.startswith("/actions/runs"):
            return {"workflow_runs": []}
        if path == "/pulls/1/reviews" and method == "POST":
            assert data is not None
            self.review = data
            review = {**data, "id": len(self.reviews) + 1, "state": "APPROVED", "user": {"login": "github-actions[bot]", "type": "Bot"}, "commit_id": data["commit_id"]}
            self.reviews.append(review)
            if self.after_review is not None:
                self.after_review()
            return copy.deepcopy(review)
        if path.startswith("/pulls/1/reviews/") and method == "PUT":
            review = self.reviews[int(path.split("/")[4]) - 1]
            review["state"] = "DISMISSED"
            return copy.deepcopy(review)
        if path.startswith("/issues/1/labels/") and method == "DELETE":
            self.deleted_labels.append(urllib.parse.unquote(path.rsplit("/", 1)[1]))
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

    def pr_event(self, action: str, sender: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
        event = {"action": action, "number": 1, "pull_request": copy.deepcopy(self.api.pr), "sender": copy.deepcopy(sender or USER)}
        event.update(extra)
        return event

    def finish_environment(self) -> None:
        os.environ.update(
            PR_NUMBER="1",
            PR_HEAD=SHA,
            ADMISSION_ID="123",
            JOB_RESULTS='{"quality":{"result":"success"},"registry":{"result":"success"},"standards":{"result":"success"}}',
        )

    def test_only_human_maintainers_count(self) -> None:
        self.assertTrue(human(USER, "maintain"))
        self.assertFalse(human(USER, "write"))
        self.assertFalse(human({"type": "Bot", "login": "bot"}, "admin"))

    def test_maintainer_non_draft_pr_auto_admits_on_open(self) -> None:
        admit(self.api, self.pr_event("opened"))
        self.assertIn("run=true", Path(os.environ["GITHUB_OUTPUT"]).read_text())
        for context in REQUIRED_CONTEXTS:
            self.assertEqual(self.api.statuses(SHA)[context]["state"], "pending")
        self.assertEqual(live_ready(self.api, 1, SHA, "123"), self.api.pr)

    def test_draft_prs_spend_nothing(self) -> None:
        self.api.pr["draft"] = True
        admit(self.api, self.pr_event("opened"))
        self.assertFalse(self.api.log)
        self.assertIn("run=false", Path(os.environ["GITHUB_OUTPUT"]).read_text())

    def test_outsider_ready_is_ignored_maintainer_ready_admits(self) -> None:
        self.api.pr["user"] = copy.deepcopy(OUTSIDER)
        self.api.roles[OUTSIDER["login"]] = "write"
        admit(self.api, self.pr_event("ready_for_review", sender=OUTSIDER))
        self.assertFalse(self.api.log)
        admit(self.api, self.pr_event("ready_for_review", sender=USER))
        self.assertIn("run=true", Path(os.environ["GITHUB_OUTPUT"]).read_text())

    def test_outsider_synchronize_does_not_auto_admit(self) -> None:
        self.api.pr["user"] = copy.deepcopy(OUTSIDER)
        self.api.roles[OUTSIDER["login"]] = "write"
        admit(self.api, self.pr_event("synchronize", sender=OUTSIDER))
        self.assertFalse(self.api.log)

    def test_slash_commands_are_not_admission_signals(self) -> None:
        admit(self.api, {"action": "created", "issue": {"number": 1, "pull_request": {}}, "comment": {"body": "/ready " + SHA}, "sender": USER})
        self.assertFalse(self.api.log)

    def test_gate_approve_records_bot_review_and_removes_label(self) -> None:
        admit(self.api, self.pr_event("labeled", label={"name": APPROVE_LABEL}))
        self.assertEqual(self.api.review["commit_id"], SHA)
        self.assertEqual(self.api.review["event"], "APPROVE")
        self.assertEqual(self.api.deleted_labels, [APPROVE_LABEL])

    def test_non_maintainer_label_is_removed_without_approval(self) -> None:
        self.api.roles[OUTSIDER["login"]] = "write"
        with self.assertRaises(ValueError):
            admit(self.api, self.pr_event("labeled", sender=OUTSIDER, label={"name": APPROVE_LABEL}))
        self.assertEqual(self.api.deleted_labels, [APPROVE_LABEL])
        self.assertFalse(self.api.reviews)

    def test_gate_revoke_fails_checks_and_dismisses_bot_approval(self) -> None:
        admit(self.api, self.pr_event("opened"))
        admit(self.api, self.pr_event("labeled", label={"name": APPROVE_LABEL}))
        admit(self.api, self.pr_event("labeled", label={"name": REVOKE_LABEL}))
        for context in REQUIRED_CONTEXTS:
            self.assertEqual(self.api.statuses(SHA)[context]["state"], "failure")
        self.assertEqual(self.api.reviews[0]["state"], "DISMISSED")
        self.assertIn(REVOKE_LABEL, self.api.deleted_labels)

    def test_converted_to_draft_fails_pending_checks(self) -> None:
        admit(self.api, self.pr_event("opened"))
        self.api.pr["draft"] = True
        admit(self.api, self.pr_event("converted_to_draft"))
        for context in REQUIRED_CONTEXTS:
            self.assertEqual(self.api.statuses(SHA)[context]["state"], "failure")

    def test_finish_publishes_only_required_contexts(self) -> None:
        admit(self.api, self.pr_event("opened"))
        self.finish_environment()
        finish(self.api)
        self.assertEqual(set(self.api.statuses(SHA)), set(REQUIRED_CONTEXTS))
        for context in REQUIRED_CONTEXTS:
            self.assertEqual(self.api.statuses(SHA)[context]["state"], "success")

    def test_finish_fails_closed_when_head_moves(self) -> None:
        admit(self.api, self.pr_event("opened"))
        self.finish_environment()
        self.api.pr["head"]["sha"] = "c" * 40
        with self.assertRaises(ValueError):
            finish(self.api)
        for context in REQUIRED_CONTEXTS:
            self.assertEqual(self.api.statuses(SHA)[context]["state"], "failure")

    def test_reruns_are_rejected(self) -> None:
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        with self.assertRaises(ValueError):
            admit(self.api, self.pr_event("opened"))

    def test_large_prs_cannot_admit(self) -> None:
        self.api.pr["changed_files"] = 201
        with self.assertRaises(ValueError):
            admit(self.api, self.pr_event("opened"))
        self.assertFalse(self.api.log)

    def test_current_pr_requires_same_repository(self) -> None:
        self.assertTrue(current_pr(self.api.pr, SHA))
        self.api.pr["head"]["repo"] = {"full_name": "outside/ejm-cli"}
        self.assertFalse(current_pr(self.api.pr, SHA))

    def test_fork_can_be_admitted_by_maintainer_ready(self) -> None:
        self.api.pr["user"] = copy.deepcopy(OUTSIDER)
        self.api.pr["head"]["repo"] = {"full_name": "outside/ejm-cli"}
        self.api.roles[OUTSIDER["login"]] = "write"
        admit(self.api, self.pr_event("ready_for_review", sender=USER))
        self.assertIn("run=true", Path(os.environ["GITHUB_OUTPUT"]).read_text())


if __name__ == "__main__":
    unittest.main()
