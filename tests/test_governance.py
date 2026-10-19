import copy
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from governance import admit, command, current_pr, dismiss_bot_approvals, finish, human, live_ready

SHA = "a" * 40
USER = {"id": 1, "login": "maintainer", "type": "User"}
TIMESTAMP = "2026-10-19T00:00:00Z"


class API:
    def __init__(self):
        self.repo = "ejmlabs/ejm-cli"
        self.pr = {"state": "open", "draft": False, "head": {"sha": SHA}, "base": {"ref": "main", "sha": "b" * 40}, "changed_files": 5, "additions": 20, "deletions": 4}
        self.comments = {7: {"user": copy.deepcopy(USER), "body": "/ready " + SHA, "issue_url": "https://api.github.com/repos/ejmlabs/ejm-cli/issues/1", "html_url": "https://github.com/ejmlabs/ejm-cli/issues/1#issuecomment-7", "created_at": TIMESTAMP, "updated_at": TIMESTAMP}}
        self.log = []
        self.role = "maintain"
        self.roles = {}
        self.reviews = []
        self.dismiss_code = None

    def permission(self, login):
        return self.roles.get(login, self.role)

    def status(self, sha, context, state, description):
        self.log.insert(0, {"sha": sha, "context": context, "state": state, "description": description})

    def statuses(self, sha):
        result = {}
        for status in self.log:
            if status["sha"] == sha:
                result.setdefault(status["context"], status)
        return result

    def pages(self, path):
        return self.log if "statuses" in path else copy.deepcopy(self.reviews)

    def request(self, path, method="GET", data=None):
        if path == "/pulls/1": return copy.deepcopy(self.pr)
        if path.startswith("/issues/comments/"):
            number = int(path.rsplit("/", 1)[1])
            if number not in self.comments:
                error = urllib.error.HTTPError(path, 404, "Not Found", None, None)
                error.close()
                raise error
            return copy.deepcopy(self.comments[number])
        if path == "/pulls/1/reviews" and method == "POST":
            self.review = data
            review = {**data, "id": len(self.reviews) + 1, "state": "APPROVED", "user": {"login": "github-actions[bot]", "type": "Bot"}}
            self.reviews.append(review)
            if getattr(self, "after_review", None):
                self.after_review()
            return copy.deepcopy(review)
        if path.startswith("/pulls/1/reviews/"):
            review = self.reviews[int(path.split("/")[4]) - 1]
            if method == "PUT":
                if self.dismiss_code is not None:
                    error = urllib.error.HTTPError(path, self.dismiss_code, "Dismissal failed", None, None)
                    error.close()
                    raise error
                review["state"] = "DISMISSED"
            return copy.deepcopy(review)
        if path.endswith("/cancel"): return {}
        raise AssertionError(path)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.old_env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.old_env)))
        os.environ.update(GITHUB_OUTPUT=str(Path(self.directory.name) / "output"), GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1")
        self.api = API()
        self.event = {"action": "created", "issue": {"number": 1, "pull_request": {}}, "comment": {**self.api.comments[7], "id": 7}, "sender": USER}
        self.event["issue"]["pull_request"] = {"url": "test"}

    def approval(self, user=None):
        event = copy.deepcopy(self.event)
        event["comment"].update(id=8, body="/approve " + SHA, html_url="https://github.com/ejmlabs/ejm-cli/issues/1#issuecomment-8")
        if user is not None:
            event["comment"]["user"] = user
            event["sender"] = user
        self.api.comments[8] = copy.deepcopy(event["comment"])
        return event

    def finish_environment(self):
        os.environ.update(PR_NUMBER="1", PR_HEAD=SHA, ADMISSION_ID="7", JOB_RESULTS='{"quality":{"result":"success"},"registry":{"result":"success"},"standards":{"result":"success"},"ai":{"result":"success"}}')

    def test_command_rejects_short_sha_multiline_and_injection(self):
        for text in ("/ready abc", "/ready " + SHA + "\n/approve " + SHA, "/ready $(id)", "/ready " + "A" * 40):
            with self.assertRaises(ValueError): command(text)

    def test_only_human_maintainers_can_admit_including_authors(self):
        self.assertTrue(human(USER, "maintain"))
        self.assertFalse(human(USER, "write"))
        self.assertFalse(human({"type": "Bot"}, "admin"))
        self.api.role = "write"
        with self.assertRaises(ValueError): admit(self.api, self.event)
        self.assertFalse(self.api.log)

    def test_admission_consumed_once_and_reruns_rejected(self):
        admit(self.api, self.event)
        self.assertEqual(self.api.statuses(SHA)["Human readiness"]["state"], "success")
        self.assertIn("run=true", Path(os.environ["GITHUB_OUTPUT"]).read_text())
        with self.assertRaises(ValueError): admit(self.api, self.event)
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        with self.assertRaises(ValueError): admit(API(), self.event)

    def test_stale_heads_drafts_and_large_prs_cannot_admit(self):
        for key, value in (("head", {"sha": "c" * 40}), ("draft", True), ("changed_files", 201), ("additions", 12001)):
            api = API()
            api.pr[key] = value
            with self.assertRaises(ValueError): admit(api, self.event)
            self.assertFalse(api.log)

    def test_live_comment_and_permission_must_survive_until_result(self):
        admit(self.api, self.event)
        live_ready(self.api, 1, SHA, 7)
        self.api.comments[7]["body"] += " edited"
        with self.assertRaises(ValueError): live_ready(self.api, 1, SHA, 7)
        self.api.comments[7]["body"] = "/ready " + SHA
        self.api.role = "read"
        with self.assertRaises(ValueError): live_ready(self.api, 1, SHA, 7)

    def test_self_approval_records_exact_commit_without_granting_readiness(self):
        approve = self.approval()
        with self.assertRaises(ValueError): admit(self.api, approve)
        admit(self.api, self.event)
        admit(self.api, approve)
        self.assertEqual(self.api.review["commit_id"], SHA)
        self.assertEqual(self.api.review["event"], "APPROVE")
        self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "success")

    def test_stale_approval_event_requires_the_exact_live_decision(self):
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

    def test_approval_deleted_during_native_review_creation_is_dismissed(self):
        admit(self.api, self.event)
        approve = self.approval()
        self.api.after_review = lambda: self.api.comments.pop(8)
        with self.assertRaises(urllib.error.HTTPError):
            admit(self.api, approve)
        self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "failure")
        self.assertEqual(self.api.reviews[0]["state"], "DISMISSED")

    def test_another_maintainer_can_invalidate_deleted_decision(self):
        admit(self.api, self.event)
        deleted = copy.deepcopy(self.event)
        deleted.update(action="deleted", sender={"login": "another-maintainer", "type": "User"})
        admit(self.api, deleted)
        self.assertEqual(self.api.statuses(SHA)["Human readiness"]["state"], "failure")

    def test_known_decisions_are_invalidated_before_editor_role_checks(self):
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

    def test_failed_native_dismissal_cannot_silently_keep_an_approval(self):
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

    def test_concurrently_dismissed_review_does_not_fail_invalidation(self):
        admit(self.api, self.event)
        admit(self.api, self.approval())
        self.api.dismiss_code = 422
        request = self.api.request

        def dismissed_elsewhere(path, method="GET", data=None):
            if path.endswith("/dismissals"):
                self.api.reviews[0]["state"] = "DISMISSED"
            return request(path, method, data)

        self.api.request = dismissed_elsewhere
        dismiss_bot_approvals(self.api, 1, SHA, "Already dismissed by another maintainer")

    def test_unknown_deleted_comment_does_not_invalidate_decisions(self):
        admit(self.api, self.event)
        before = copy.deepcopy(self.api.log)
        deleted = copy.deepcopy(self.event)
        deleted.update(action="deleted", sender={"login": "reader", "type": "User"})
        deleted["comment"]["id"] = 99
        self.api.role = "read"
        admit(self.api, deleted)
        self.assertEqual(self.api.log, before)

    def test_finish_revalidates_existing_approval(self):
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
                self.assertEqual(self.api.statuses(SHA)["AI review"]["state"], "pending")
                self.assertTrue(all(review["state"] == "DISMISSED" for review in self.api.reviews))

    def test_finish_allows_approval_after_checks_complete(self):
        admit(self.api, self.event)
        self.finish_environment()
        finish(self.api)
        self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "pending")
        self.assertEqual(self.api.statuses(SHA)["AI review"]["state"], "success")
        admit(self.api, self.approval())
        self.assertEqual(self.api.statuses(SHA)["Maintainer approval"]["state"], "success")

    def test_finish_preserves_a_live_self_approval(self):
        admit(self.api, self.event)
        admit(self.api, self.approval())
        self.finish_environment()
        finish(self.api)
        for context in ("Maintainer approval", "Quality", "Repository standards", "AI review"):
            self.assertEqual(self.api.statuses(SHA)[context]["state"], "success")

    def test_finish_dismisses_approval_when_readiness_was_deleted(self):
        admit(self.api, self.event)
        admit(self.api, self.approval())
        del self.api.comments[7]
        self.finish_environment()
        with self.assertRaises(urllib.error.HTTPError):
            finish(self.api)
        for context in ("Human readiness", "Maintainer approval"):
            self.assertEqual(self.api.statuses(SHA)[context]["state"], "failure")
        self.assertEqual(self.api.reviews[0]["state"], "DISMISSED")

    def test_old_finish_cannot_revoke_a_new_admission(self):
        admit(self.api, self.event)
        admit(self.api, self.approval())
        self.api.status(SHA, "Human readiness", "success", "[ready:9] [run:456] New human admission")
        before = copy.deepcopy(self.api.log)
        self.finish_environment()
        with self.assertRaises(ValueError):
            finish(self.api)
        self.assertEqual(self.api.log, before)
        self.assertEqual(self.api.reviews[0]["state"], "APPROVED")

    def test_old_finish_does_not_dismiss_a_review_for_a_new_head(self):
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

    def test_results_fail_closed_on_missing_review_and_changed_head(self):
        admit(self.api, self.event)
        os.environ.update(PR_NUMBER="1", PR_HEAD=SHA, ADMISSION_ID="7", JOB_RESULTS='{"quality":{"result":"success"},"registry":{"result":"success"},"standards":{"result":"success"},"ai":{"result":"skipped"}}')
        finish(self.api)
        self.assertEqual(self.api.statuses(SHA)["AI review"]["state"], "failure")
        self.api.pr["head"]["sha"] = "c" * 40
        with self.assertRaises(ValueError): finish(self.api)


if __name__ == "__main__": unittest.main()
