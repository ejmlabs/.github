import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from email.message import Message
from pathlib import Path
from typing import Any, Self
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_workflows
import governance
from governance import APPROVE_LABEL, REQUIRED_CONTEXTS, REVOKE_LABEL, GitHub, human

SHA = "a" * 40
BASE = "b" * 40
OLD = "c" * 40
REPO = "ejmlabs/ejm-cli"
ROOT = "https://api.github.com/repos/" + REPO
RUN = 500
WORKFLOW = 7
USER: dict[str, Any] = {"id": 1, "login": "maintainer", "type": "User"}
OUTSIDER: dict[str, Any] = {"id": 2, "login": "contributor", "type": "User"}
BOT: dict[str, Any] = {"id": 3, "login": "dependabot[bot]", "type": "Bot"}
FAKE_AUTH = "placeholder-not-a-credential"


def run_url(run: int) -> str:
    return f"https://github.com/{REPO}/actions/runs/{run}"


class Response:
    def __init__(self, payload: Any) -> None:
        self.raw = b"" if payload is None else json.dumps(payload).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self.raw if limit < 0 else self.raw[:limit]


class Server:
    """A stateful in-memory GitHub that answers the gate's API calls through urlopen."""

    def __init__(self) -> None:
        self.pr: dict[str, Any] = {
            "number": 1, "state": "open", "draft": False, "user": copy.deepcopy(USER), "labels": [],
            "head": {"sha": SHA, "ref": "feature", "repo": {"full_name": REPO}},
            "base": {"ref": "main", "sha": BASE, "repo": {"full_name": REPO}},
        }
        self.roles = {USER["login"]: "maintain", OUTSIDER["login"]: "write"}
        self.users = {user["login"]: user for user in (USER, OUTSIDER, BOT)}
        self.log: list[dict[str, Any]] = []
        self.reviews: list[dict[str, Any]] = []
        self.runs: dict[int, dict[str, Any]] = {RUN: {"id": RUN, "status": "in_progress", "workflow_id": WORKFLOW, "head_sha": SHA}}
        self.calls: list[tuple[str, str]] = []
        self.writes: list[str] = []
        self.timeouts: list[float] = []
        self.cancelled: list[int] = []
        self.faults: list[dict[str, Any]] = []
        self.hooks: list[dict[str, Any]] = []

    def fail(self, method: str, prefix: str, failure: int | OSError, times: int = 1000, effect: Callable[[], object] | None = None,
             *, after_write: bool = False, context: str | None = None) -> None:
        """Make matching calls fail. An effect runs when a failure fires, to model another writer winning a race.

        With after_write the call takes effect first and only its response fails, as when GitHub stores a status and
        the connection drops before the client reads the answer. A context limits the fault to status writes for it.
        """
        self.faults.append({"method": method, "prefix": prefix, "failure": failure, "times": times, "effect": effect,
                            "after_write": after_write, "context": context})

    def on(self, method: str, prefix: str, effect: Callable[[], object], times: int = 1) -> None:
        """Run an effect just before matching calls are answered, to model another writer acting in that gap."""
        self.hooks.append({"method": method, "prefix": prefix, "effect": effect, "times": times})

    def add_run(self, run: int, status: str, workflow: int = WORKFLOW, head: str = SHA) -> None:
        self.runs[run] = {"id": run, "status": status, "workflow_id": workflow, "head_sha": head}

    def add_status(self, state: str, context: str, url: str, sha: str = SHA, creator: str = "github-actions[bot]") -> None:
        self.log.append({"id": len(self.log) + 1, "sha": sha, "context": context, "state": state, "description": "seeded", "target_url": url,
                         "creator": {"login": creator}})

    def latest(self, sha: str = SHA) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for status in self.log:
            if status["sha"] == sha:
                found[status["context"]] = status
        return found

    def urlopen(self, req: urllib.request.Request, timeout: float | None = None) -> Response:
        assert timeout is not None
        assert 0 < timeout <= 30
        self.timeouts.append(timeout)
        assert req.get_header("Authorization") == "Bearer " + FAKE_AUTH
        url, method = req.full_url, req.get_method()
        path = url.removeprefix(ROOT) if url.startswith(ROOT) else url.removeprefix("https://api.github.com")
        assert path != url
        self.calls.append((method, path))
        for hook in self.hooks:
            if hook["method"] == method and path.startswith(hook["prefix"]) and hook["times"] > 0:
                hook["times"] -= 1
                hook["effect"]()
        sent = json.loads(req.data) if isinstance(req.data, bytes) else None
        for fault in self.faults:
            if fault["context"] is not None and (sent or {}).get("context") != fault["context"]:
                continue
            if fault["method"] == method and path.startswith(fault["prefix"]) and fault["times"] > 0:
                fault["times"] -= 1
                if fault["effect"] is not None:
                    fault["effect"]()
                if fault["after_write"]:
                    self.route(method, path, sent)
                if isinstance(fault["failure"], int):
                    raise urllib.error.HTTPError(url, fault["failure"], "injected", Message(), None)
                raise fault["failure"]
        code, payload = self.route(method, path, sent)
        if code >= 400:
            raise urllib.error.HTTPError(url, code, "not found", Message(), None)
        return Response(payload)

    def page(self, items: list[Any], params: dict[str, list[str]]) -> list[Any]:
        size, number = int(params["per_page"][0]), int(params["page"][0])
        return copy.deepcopy(items[(number - 1) * size:number * size])

    def route(self, method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        bare, _, query = path.partition("?")
        params = urllib.parse.parse_qs(query)
        match method, bare.strip("/").split("/"):
            case "GET", ["pulls", "1"]:
                return 200, copy.deepcopy(self.pr)
            case "GET", ["collaborators", login, "permission"]:
                if login not in self.roles:
                    return 404, None
                return 200, {"role_name": self.roles[login], "permission": "write"}
            case "GET", ["users", login]:
                name = urllib.parse.unquote(login)
                return (200, self.users[name]) if name in self.users else (404, None)
            case "GET", ["commits", sha, "statuses"]:
                return 200, self.page([status for status in reversed(self.log) if status["sha"] == sha], params)
            case "GET", ["commits", sha, "status"]:
                return 200, {"statuses": self.page(list(reversed(list(self.latest(sha).values()))), params)}
            case "POST", ["statuses", sha]:
                assert body is not None
                self.writes.append("status:" + body["state"])
                self.log.append({"id": len(self.log) + 1, "sha": sha, **body, "creator": {"login": "github-actions[bot]"}})
                return 201, {}
            case "DELETE", ["issues", "1", "labels", name]:
                self.writes.append("label:" + urllib.parse.unquote(name))
                self.pr["labels"] = [label for label in self.pr["labels"] if label["name"] != urllib.parse.unquote(name)]
                return 200, []
            case "GET", ["pulls", "1", "reviews"]:
                return 200, self.page(self.reviews, params)
            case "POST", ["pulls", "1", "reviews"]:
                assert body is not None
                self.writes.append("review")
                review = {"id": len(self.reviews) + 1, "state": "APPROVED", "user": {"login": "github-actions[bot]", "type": "Bot"}, **body}
                self.reviews.append(review)
                return 200, copy.deepcopy(review)
            case "GET", ["pulls", "1", "reviews", rid]:
                return 200, copy.deepcopy(self.reviews[int(rid) - 1])
            case "PUT", ["pulls", "1", "reviews", rid, "dismissals"]:
                self.writes.append("dismiss:" + rid)
                self.reviews[int(rid) - 1]["state"] = "DISMISSED"
                return 200, copy.deepcopy(self.reviews[int(rid) - 1])
            case "GET", ["actions", "runs", rid]:
                return (200, copy.deepcopy(self.runs[int(rid)])) if int(rid) in self.runs else (404, None)
            case "GET", ["actions", "workflows", workflow, "runs"]:
                found = [run for run in self.runs.values() if run["workflow_id"] == int(workflow)
                         and run["head_sha"] == params["head_sha"][0] and run["status"] == params["status"][0]]
                return 200, {"workflow_runs": copy.deepcopy(found)}
            case "POST", ["actions", "runs", rid, "cancel"]:
                if self.runs[int(rid)]["status"] == "completed":
                    return 409, None
                self.writes.append("cancel:" + rid)
                self.cancelled.append(int(rid))
                if not self.runs[int(rid)].get("lingers"):  # a lingering run has a job that is still ending when the cancel lands
                    self.runs[int(rid)]["status"] = "completed"
                return 202, {}
        raise AssertionError(f"Unexpected call {method} {path}")


class GateCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        environment = mock.patch.dict(os.environ, {
            "GITHUB_REPOSITORY": REPO, "GH_TOKEN": FAKE_AUTH, "GITHUB_RUN_ID": str(RUN), "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_OUTPUT": str(self.directory / "output"), "GITHUB_EVENT_PATH": str(self.directory / "event.json"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.server = Server()
        transport = mock.patch("urllib.request.urlopen", self.server.urlopen)
        transport.start()
        self.addCleanup(transport.stop)
        self.sleeps: list[float] = []
        self.notices = ""
        self.api = GitHub(sleep=self.sleeps.append)

    def event(self, action: str, sender: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
        return {"action": action, "number": 1, "pull_request": copy.deepcopy(self.server.pr), "sender": copy.deepcopy(sender or USER), **extra}

    def admit(self, event: dict[str, Any]) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            governance.admit(self.api, event)
        return out.getvalue()

    def labeled(self, name: str, sender: dict[str, Any] | None = None) -> dict[str, Any]:
        """A labeled event for a label that is now on the PR."""
        self.server.pr["labels"].append({"name": name})
        return self.event("labeled", sender=sender, label={"name": name})

    def admit_as(self, run: int, event: dict[str, Any], attempt: str = "1", actor: str = USER["login"]) -> dict[str, str]:
        """Run one admission as its own Actions run, with its own output file, and return that run's outputs."""
        self.server.runs.setdefault(run, {"id": run, "status": "in_progress", "workflow_id": WORKFLOW, "head_sha": SHA})
        out = self.directory / f"output-{run}-{attempt}"
        env = {"GITHUB_RUN_ID": str(run), "GITHUB_RUN_ATTEMPT": attempt, "GITHUB_OUTPUT": str(out), "GITHUB_TRIGGERING_ACTOR": actor}
        text = io.StringIO()
        try:
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(text):
                governance.admit(self.api, event)
        finally:
            self.notices = text.getvalue()
        return dict(line.split("=", 1) for line in out.read_text().splitlines()) if out.exists() else {}

    def complete(self, *runs: int) -> None:
        for run in runs:
            self.server.runs[run]["status"] = "completed"

    def approved(self) -> list[int]:
        return [review["id"] for review in self.server.reviews if review["state"] == "APPROVED"]

    def outputs(self) -> dict[str, str]:
        path = Path(os.environ["GITHUB_OUTPUT"])
        lines = path.read_text().splitlines() if path.exists() else []
        return dict(line.split("=", 1) for line in lines)

    def states(self, sha: str = SHA) -> dict[str, str]:
        return {context: status["state"] for context, status in self.server.latest(sha).items()}

    def seed_admission(self, state: str = "pending", run: int = 400, status: str | None = "in_progress") -> None:
        if status is not None:
            self.server.add_run(run, status)
        for context in REQUIRED_CONTEXTS:
            self.server.add_status(state, context, run_url(run))

    @contextlib.contextmanager
    def as_run(self, run: int, attempt: str = "1") -> Iterator[None]:
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": str(run), "GITHUB_RUN_ATTEMPT": attempt}):
            yield

    @contextlib.contextmanager
    def finishing(self, results: str | None = None) -> Iterator[None]:
        ok = {"result": "success"}
        text = json.dumps({"quality": ok, "registry": ok, "standards": ok}) if results is None else results
        with mock.patch.dict(os.environ, {"PR_NUMBER": "1", "PR_HEAD": SHA, "JOB_RESULTS": text}):
            yield

    def finish(self) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            governance.finish(self.api)
        return out.getvalue()


class AdmissionTests(GateCase):
    def test_only_human_maintainers_count(self) -> None:
        self.assertTrue(human(USER, "maintain"))
        self.assertFalse(human(USER, "write"))
        self.assertFalse(human(BOT, "admin"))

    def test_maintainer_non_draft_pr_auto_admits_on_open(self) -> None:
        self.assertEqual(self.admit(self.event("opened")), "")
        self.assertEqual(self.outputs(), {"run": "true", "pr": "1", "head": SHA, "base": BASE, "profile": "ejm-cli"})
        self.assertEqual(self.states(), {"Quality": "pending", "Repository standards": "pending"})
        self.assertEqual({status["target_url"] for status in self.server.log}, {run_url(RUN)})
        with self.finishing():
            governance.verify(self.api)

    def test_draft_prs_spend_nothing(self) -> None:
        self.server.pr["draft"] = True
        self.assertIn("::notice::", self.admit(self.event("opened")))
        self.assertEqual(self.server.writes, [])
        self.assertEqual(self.outputs(), {"run": "false"})

    def test_outsider_ready_is_ignored_maintainer_ready_admits(self) -> None:
        self.server.pr["user"] = copy.deepcopy(OUTSIDER)
        self.assertIn("not admitted yet", self.admit(self.event("ready_for_review", sender=OUTSIDER)))
        self.assertEqual(self.server.writes, [])
        self.admit(self.event("ready_for_review", sender=USER))
        self.assertEqual(self.outputs()["run"], "true")

    def test_outsider_synchronize_does_not_auto_admit(self) -> None:
        self.server.pr["user"] = copy.deepcopy(OUTSIDER)
        self.admit(self.event("synchronize", sender=OUTSIDER, before=OLD))
        self.assertEqual(self.server.writes, [])
        self.assertEqual(self.outputs(), {"run": "false"})

    def test_a_pr_author_that_lost_access_is_not_a_maintainer(self) -> None:
        del self.server.roles[USER["login"]]
        self.assertIn("not admitted yet", self.admit(self.event("opened")))
        self.assertEqual(self.server.writes, [])

    def test_slash_commands_are_not_admission_signals(self) -> None:
        text = self.admit({"action": "created", "issue": {"number": 1, "pull_request": {}}, "comment": {"body": "/ready " + SHA}, "sender": USER})
        self.assertIn("::notice::", text)
        self.assertEqual(self.server.calls, [])
        self.assertEqual(self.outputs(), {"run": "false"})

    def test_the_event_head_binds_admission_to_the_head_that_was_seen(self) -> None:
        event = self.event("opened")
        event["pull_request"]["head"]["sha"] = OLD
        self.assertIn("head changed", self.admit(event))
        self.assertEqual(self.server.writes, [])
        self.assertEqual(self.outputs(), {"run": "false"})

    def test_closed_and_non_main_prs_are_not_admitted(self) -> None:
        changes: dict[str, Callable[[], object]] = {
            "closed": lambda: self.server.pr.update(state="closed"),
            "base": lambda: self.server.pr["base"].update(ref="release"),
        }
        for change, apply in changes.items():
            with self.subTest(change=change):
                self.setUp()
                event = self.event("opened")
                apply()
                self.assertIn("::notice::", self.admit(event))
                self.assertEqual(self.server.writes, [])
                self.assertEqual(self.outputs(), {"run": "false"})

    def test_fork_prs_are_never_admitted_and_nothing_is_written(self) -> None:
        for repo in ({"full_name": "outside/ejm-cli"}, None):
            self.server.pr["head"]["repo"] = repo
            self.server.pr["user"] = copy.deepcopy(OUTSIDER)
            events = [self.event("opened"), self.event("synchronize", before=OLD), self.event("ready_for_review"),
                      self.event("converted_to_draft"), self.event("labeled", label={"name": APPROVE_LABEL}),
                      self.event("labeled", label={"name": REVOKE_LABEL})]
            for event in events:
                with self.subTest(action=event["action"], repo=repo):
                    self.assertIn("forks are not admitted", self.admit(event))
                    self.assertEqual(self.server.writes, [])
                    self.assertEqual(self.server.calls, [])
                    self.assertEqual(self.outputs(), {"run": "false"})

    def test_the_dependabot_flow_is_one_label_by_a_maintainer(self) -> None:
        self.server.pr["user"] = copy.deepcopy(BOT)
        self.admit(self.event("opened", sender=BOT))
        self.assertEqual(self.server.writes, [])
        self.admit(self.event("labeled", label={"name": APPROVE_LABEL}))
        self.assertEqual(self.server.writes, ["label:" + APPROVE_LABEL, "review", "status:pending", "status:pending"])
        self.assertEqual((self.server.reviews[0]["commit_id"], self.server.reviews[0]["event"]), (SHA, "APPROVE"))
        self.assertEqual(self.outputs()["run"], "true")

    def test_gate_approve_binds_the_approval_to_the_event_head_without_admitting_twice(self) -> None:
        self.admit(self.event("opened"))
        self.server.writes.clear()
        self.server.add_run(501, "in_progress")
        with self.as_run(501):
            self.assertIn("already admitted", self.admit(self.event("labeled", label={"name": APPROVE_LABEL})))
        self.assertEqual(self.server.reviews[0]["commit_id"], SHA)
        self.assertEqual(self.server.writes, ["label:" + APPROVE_LABEL, "review"])
        self.assertEqual({status["target_url"] for status in self.server.latest().values()}, {run_url(RUN)})

    def test_gate_approve_on_an_admitted_or_passed_head_only_records_the_approval(self) -> None:
        for state, message in (("pending", "already admitted"), ("success", "already passed")):
            with self.subTest(state=state):
                self.setUp()
                self.seed_admission(state)
                self.assertIn(message, self.admit(self.event("labeled", label={"name": APPROVE_LABEL})))
                self.assertEqual(self.server.writes, ["label:" + APPROVE_LABEL, "review"])
                self.assertEqual(self.outputs(), {"run": "false"})

    def test_pending_checks_of_a_finished_run_are_stale_and_admit_again(self) -> None:
        both = REQUIRED_CONTEXTS
        # Each case is the runs that exist (id to status) and the pending status URL of each context.
        cases: dict[str, tuple[dict[int, str], dict[str, str]]] = {
            "completed run": ({400: "completed"}, dict.fromkeys(both, run_url(400))),
            "missing run": ({}, dict.fromkeys(both, run_url(400))),
            "foreign url": ({400: "in_progress"}, dict.fromkeys(both, "https://github.com/other/repo/actions/runs/400")),
            "no url": ({}, dict.fromkeys(both, "")),
            "trailing text": ({400: "in_progress"}, dict.fromkeys(both, run_url(400) + "/jobs/1")),
            "one context of a completed run": ({400: "completed"}, {"Quality": run_url(400)}),
            "this run": ({}, dict.fromkeys(both, run_url(RUN))),
        }
        for name, (runs, urls) in cases.items():
            with self.subTest(name):
                self.setUp()
                for run, status in runs.items():
                    self.server.add_run(run, status)
                for context, url in urls.items():
                    self.server.add_status("pending", context, url)
                self.assertEqual(self.admit(self.event("opened")), "")
                self.assertEqual(self.outputs()["run"], "true")
                self.assertEqual({status["target_url"] for status in self.server.latest().values()}, {run_url(RUN)})

    def test_pending_checks_of_a_live_run_are_not_admitted_twice(self) -> None:
        for status in ("in_progress", "queued"):
            with self.subTest(status=status):
                self.setUp()
                self.seed_admission("pending", 400, status)
                self.assertIn("already admitted", self.admit(self.event("opened")))
                self.assertEqual(self.server.writes, [])
                self.assertEqual(self.outputs(), {"run": "false"})

    def test_a_live_run_holds_its_head_whatever_its_statuses_say(self) -> None:
        # A run that wrote one admission status, or one result, still holds the head until it completes.
        cases = {"one pending context": [("pending", "Quality")], "one result written": [("pending", "Quality"), ("pending", "Repository standards"),
                                                                                      ("success", "Quality")]}
        for name, statuses in cases.items():
            with self.subTest(name):
                self.setUp()
                self.server.add_run(400, "in_progress")
                for state, context in statuses:
                    self.server.add_status(state, context, run_url(400))
                self.assertIn("already admitted", self.admit(self.event("opened")))
                self.assertEqual(self.server.writes, [])

    def test_passed_checks_are_not_run_again(self) -> None:
        self.seed_admission("success", 400, "completed")
        self.assertIn("already passed", self.admit(self.event("ready_for_review")))
        self.assertEqual(self.server.writes, [])

    def test_failed_checks_admit_again_on_ready(self) -> None:
        self.seed_admission("failure", 400, "completed")
        self.admit(self.event("ready_for_review"))
        self.assertEqual(self.states(), {"Quality": "pending", "Repository standards": "pending"})

    def test_non_maintainer_label_is_removed_without_approval(self) -> None:
        for sender in (OUTSIDER, BOT):
            with self.subTest(sender=sender["login"]):
                self.setUp()
                with self.assertRaises(ValueError):
                    self.admit(self.event("labeled", sender=sender, label={"name": APPROVE_LABEL}))
                self.assertEqual(self.server.writes, ["label:" + APPROVE_LABEL])

    def test_other_labels_are_ignored(self) -> None:
        self.assertIn("Not a gate label", self.admit(self.event("labeled", label={"name": "bug"})))
        self.assertEqual(self.server.writes, [])

    def test_a_label_on_a_stale_closed_draft_or_other_base_pr_is_removed_and_does_nothing(self) -> None:
        changes: dict[str, Callable[[dict[str, Any]], object]] = {
            "head": lambda event: event["pull_request"]["head"].update(sha=OLD),
            "closed": lambda _event: self.server.pr.update(state="closed"),
            "draft": lambda _event: self.server.pr.update(draft=True),
            "base": lambda _event: self.server.pr["base"].update(ref="release"),
        }
        for name in (APPROVE_LABEL, REVOKE_LABEL):
            for change, apply in changes.items():
                with self.subTest(label=name, change=change):
                    self.setUp()
                    event = self.event("labeled", label={"name": name})
                    apply(event)
                    self.assertIn("::notice::", self.admit(event))
                    self.assertEqual(self.server.writes, ["label:" + name])
                    self.assertEqual(self.outputs(), {"run": "false"})

    def test_reruns_replay_an_old_event_so_only_a_maintainer_can_start_one(self) -> None:
        self.assertEqual(self.admit(self.event("opened")), "")
        self.assertNotIn("/users/", "".join(path for _, path in self.server.calls))
        for actor in ("", OUTSIDER["login"], BOT["login"]):
            with self.subTest(actor=actor):
                self.setUp()
                with self.as_run(RUN, "2"), mock.patch.dict(os.environ, {"GITHUB_TRIGGERING_ACTOR": actor}):
                    self.assertIn("rerun", self.admit(self.event("opened")))
                self.assertEqual(self.server.writes, [])
                self.assertEqual(self.outputs(), {"run": "false"})
        self.setUp()
        with self.as_run(RUN, "2"), mock.patch.dict(os.environ, {"GITHUB_TRIGGERING_ACTOR": USER["login"]}):
            self.assertEqual(self.admit(self.event("opened")), "")
        self.assertEqual(self.outputs()["run"], "true")

    def test_a_rerun_that_admits_again_takes_over_the_checks_it_wrote_before(self) -> None:
        self.admit(self.event("opened"))
        with self.finishing('{"quality": {"result": "failure"}}'):
            self.finish()
        self.assertEqual(set(self.states().values()), {"failure"})
        with self.as_run(RUN, "2"), mock.patch.dict(os.environ, {"GITHUB_TRIGGERING_ACTOR": USER["login"]}):
            self.admit(self.event("opened"))
        self.assertEqual(self.states(), {"Quality": "pending", "Repository standards": "pending"})


class StopTests(GateCase):
    def admitted(self) -> None:
        self.admit(self.event("opened"))
        self.server.reviews.append({"id": 1, "state": "APPROVED", "user": {"login": "github-actions[bot]"}, "commit_id": SHA})
        self.server.writes.clear()

    def test_revoke_fails_checks_cancels_older_runs_of_this_workflow_dismisses_and_writes_last(self) -> None:
        self.admitted()
        self.server.add_run(400, "queued")
        self.server.add_run(401, "in_progress")
        self.server.add_run(402, "in_progress", workflow=8)
        self.server.add_run(403, "in_progress", head=OLD)
        self.server.add_run(404, "completed")
        self.server.add_run(600, "in_progress")
        self.admit(self.labeled(REVOKE_LABEL))
        # The label is removed only after the stop has completed.
        self.assertEqual(self.server.writes, [
            "status:failure", "status:failure", "cancel:400", "cancel:401", "dismiss:1", "status:failure", "status:failure", "label:" + REVOKE_LABEL])
        self.assertEqual(self.server.pr["labels"], [])
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})
        self.assertEqual(self.server.reviews[0]["state"], "DISMISSED")
        self.assertEqual([self.server.runs[run]["status"] for run in (402, 403, 600, RUN)], ["in_progress"] * 4)

    def test_converted_to_draft_stops_the_head_the_same_way(self) -> None:
        self.admitted()
        self.server.add_run(401, "in_progress")
        self.server.pr["draft"] = True
        self.admit(self.event("converted_to_draft"))
        self.assertEqual(self.server.writes, ["status:failure", "status:failure", "cancel:401", "dismiss:1", "status:failure", "status:failure"])
        self.assertEqual(self.outputs()["run"], "false")

    def test_a_draft_event_older_than_a_newer_admission_stops_nothing(self) -> None:
        self.admitted()
        self.server.add_run(502, "in_progress")
        for context in REQUIRED_CONTEXTS:
            self.server.add_status("pending", context, run_url(502))
        self.assertIn("newer run already decided", self.admit(self.event("converted_to_draft")))
        self.assertEqual(self.server.writes, [])
        self.assertEqual(set(self.states().values()), {"pending"})

    def test_stop_tolerates_a_review_without_a_user_and_cancel_conflicts(self) -> None:
        self.admitted()
        self.server.pr["draft"] = True
        self.server.reviews.append({"id": 2, "state": "APPROVED", "user": None, "commit_id": SHA})
        self.server.add_run(401, "in_progress")
        self.server.fail("POST", "/actions/runs/401/cancel", 409)
        self.admit(self.event("converted_to_draft"))
        self.assertEqual(self.server.writes[-2:], ["status:failure", "status:failure"])
        self.assertEqual([review["state"] for review in self.server.reviews], ["DISMISSED", "APPROVED"])

    def test_stop_surfaces_list_errors_but_still_writes_the_final_failure(self) -> None:
        self.admitted()
        self.server.pr["draft"] = True
        self.server.fail("GET", "/actions/workflows/", 403)
        with self.assertRaises(urllib.error.HTTPError):
            self.admit(self.event("converted_to_draft"))
        self.assertEqual(self.server.writes, ["status:failure", "status:failure", "dismiss:1", "status:failure", "status:failure"])

    def test_stop_surfaces_cancel_errors_other_than_conflicts_but_still_dismisses_and_keeps_the_label(self) -> None:
        self.admitted()
        self.server.add_run(401, "in_progress")
        self.server.fail("POST", "/actions/runs/401/cancel", 403)
        with self.assertRaises(urllib.error.HTTPError):
            self.admit(self.labeled(REVOKE_LABEL))
        self.assertEqual(self.server.writes[-3:], ["dismiss:1", "status:failure", "status:failure"])
        self.assertEqual(self.server.reviews[0]["state"], "DISMISSED")
        self.assertEqual(self.server.pr["labels"], [{"name": REVOKE_LABEL}])

    def test_dismissal_failures_are_tolerated_only_when_the_review_is_no_longer_approved(self) -> None:
        self.admitted()
        self.server.pr["draft"] = True
        self.server.fail("PUT", "/pulls/1/reviews/1/dismissals", 422)
        with self.assertRaises(urllib.error.HTTPError):
            self.admit(self.event("converted_to_draft"))
        self.assertEqual(self.server.reviews[0]["state"], "APPROVED")
        self.server.faults.clear()
        self.server.fail("PUT", "/pulls/1/reviews/1/dismissals", 422, effect=lambda: self.server.reviews[0].update(state="DISMISSED"))
        self.admit(self.event("converted_to_draft"))
        self.assertEqual(self.server.reviews[0]["state"], "DISMISSED")

    def test_synchronize_cancels_only_this_workflows_runs_of_the_previous_head(self) -> None:
        self.server.add_run(400, "in_progress", head=OLD)
        self.server.add_run(401, "queued", head=OLD)
        self.server.add_run(402, "in_progress", head=OLD, workflow=8)
        self.server.add_run(403, "in_progress", head=SHA)
        self.admit(self.event("synchronize", before=OLD))
        self.assertEqual(self.server.cancelled, [401, 400])
        self.assertEqual(self.outputs()["run"], "true")

    def test_synchronize_ignores_a_malformed_previous_head(self) -> None:
        for before in ("not-a-sha", "../" + "a" * 37, None, 5):
            with self.subTest(before=before):
                self.setUp()
                self.server.add_run(400, "in_progress", head=OLD)
                self.admit(self.event("synchronize", before=before))
                self.assertEqual(self.server.cancelled, [])
                self.assertEqual(self.outputs()["run"], "true")

    def test_a_read_only_token_cannot_cancel_but_the_push_is_still_handled(self) -> None:
        self.server.add_run(400, "in_progress", head=OLD)
        self.server.fail("POST", "/actions/runs/", 403)
        text = self.admit(self.event("synchronize", before=OLD))
        self.assertIn("::warning::", text)
        self.assertEqual(self.outputs()["run"], "true")


class StopWaitTests(GateCase):
    """A stop waits for the runs it cancelled, so a finish job already running cannot write after the last write."""

    def lingering(self, *runs: int) -> None:
        for run in runs:
            self.server.add_run(run, "in_progress")
            self.server.runs[run]["lingers"] = True

    def late_finish(self, run: int) -> Callable[[], None]:
        """The finish job of an older run: it writes success, then its run completes."""
        def land() -> None:
            if self.server.runs[run]["status"] != "completed":
                for context in REQUIRED_CONTEXTS:
                    self.server.add_status("success", context, run_url(run))
                self.server.runs[run]["status"] = "completed"
        return land

    def test_a_finish_that_is_still_running_when_its_cancel_lands_cannot_write_after_the_stop(self) -> None:
        self.admit(self.event("opened"))
        self.lingering(400)
        land = self.late_finish(400)

        def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)
            land()  # time passes while the stop waits, and the finish job's write lands

        self.api.sleep = sleep
        self.admit(self.labeled(REVOKE_LABEL))
        land()  # a stop that did not wait returned before this write, which then comes last
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})
        self.assertEqual([status["state"] for status in self.server.log[2:]],
                         ["failure", "failure", "success", "success", "failure", "failure"])
        self.assertEqual(self.sleeps, [governance.RUN_POLL_SECONDS])

    def test_a_run_that_never_completes_is_waited_for_only_so_long_and_the_last_write_still_goes_out(self) -> None:
        self.admit(self.event("opened"))
        self.lingering(400, 401)
        self.server.writes.clear()
        out = self.admit(self.labeled(REVOKE_LABEL))
        self.assertEqual(self.sleeps, [governance.RUN_POLL_SECONDS] * governance.RUN_POLLS)
        self.assertTrue(out.startswith("::warning::"), out)
        self.assertTrue(out.strip().endswith("400, 401"), out)
        self.assertEqual(self.server.writes[-3:], ["status:failure", "status:failure", "label:" + REVOKE_LABEL])
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})

    def test_the_current_run_is_never_waited_on(self) -> None:
        self.admit(self.event("opened"))
        self.server.add_run(600, "in_progress")  # a newer run is a later decision and is not cancelled or waited on either
        self.assertEqual(self.server.runs[RUN]["status"], "in_progress")
        self.assertEqual(self.admit(self.labeled(REVOKE_LABEL)), "")
        self.assertEqual((self.sleeps, self.server.cancelled), ([], []))
        self.assertEqual(self.server.calls.count(("GET", f"/actions/runs/{RUN}")), 1)  # the workflow lookup, not a poll

    def test_a_run_that_cannot_be_read_does_not_stop_the_last_write_and_a_deleted_run_counts_as_done(self) -> None:
        self.admit(self.event("opened"))
        self.server.add_run(400, "in_progress")
        self.server.add_run(401, "in_progress")
        self.server.fail("GET", "/actions/runs/400", 503)
        self.server.on("GET", "/actions/runs/401", lambda: self.server.runs.pop(401))
        out = self.admit(self.labeled(REVOKE_LABEL))
        self.assertTrue(out.strip().endswith("::warning::Runs not confirmed completed after the stop, so a finish job in one may still write a status: 400"), out)
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})
        self.assertEqual(self.server.pr["labels"], [])

    def test_a_failed_cancel_still_waits_for_the_runs_it_listed(self) -> None:
        self.admit(self.event("opened"))
        self.lingering(400)
        self.server.fail("POST", "/actions/runs/400/cancel", 403)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(urllib.error.HTTPError):
            governance.admit(self.api, self.labeled(REVOKE_LABEL))
        self.assertTrue(out.getvalue().strip().endswith("400"), out.getvalue())
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})

    def test_a_final_write_that_fails_says_the_head_may_still_read_success_and_fails_the_job(self) -> None:
        self.admit(self.event("opened"))
        self.server.add_run(400, "in_progress")

        def late_success_then_outage() -> None:
            # The older finish job wrote success after the stop's first writes, and then GitHub stops taking statuses.
            self.late_finish(400)()
            self.server.fail("POST", "/statuses/", 503)

        self.server.on("POST", "/actions/runs/400/cancel", late_success_then_outage)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(urllib.error.HTTPError):
            governance.admit(self.api, self.labeled(REVOKE_LABEL))
        self.assertIn("::error::The final failure status could not be written, so this head may still read success. Do not merge it", out.getvalue())
        self.assertEqual(self.states(), {"Quality": "success", "Repository standards": "success"})
        self.assertEqual(self.sleeps, list(governance.STATUS_RETRY_DELAYS))
        self.assertEqual(self.server.pr["labels"], [{"name": REVOKE_LABEL}])  # the label keeps finish and admission blocked

    def test_a_final_write_that_succeeds_prints_no_error(self) -> None:
        self.admit(self.event("opened"))
        self.assertNotIn("::error::", self.admit(self.labeled(REVOKE_LABEL)))


class StopTimingTests(GateCase):
    """A stop must end inside the admission job's time limit, whatever GitHub does."""

    def test_the_worst_case_of_a_stop_fits_the_admission_job_with_a_margin(self) -> None:
        limit = build_workflows.governance()["jobs"]["admission"]["timeout-minutes"] * 60
        worst = governance.STOP_STEPS_SECONDS + governance.FINAL_WRITE_SECONDS
        # The rest of the job is the runner start, the reads before a stop and the label removal after it.
        self.assertLessEqual(worst + 60, limit, f"a stop can take {worst} s of the job's {limit} s")
        self.assertLess(governance.RUN_POLLS * governance.RUN_POLL_SECONDS, governance.STOP_STEPS_SECONDS)
        self.assertGreaterEqual(governance.FINAL_WRITE_SECONDS, 2 * governance.STATUS_TIMEOUT, "the last write needs room for a retry")

    def test_a_stop_ends_within_its_budget_when_every_call_after_the_first_writes_hangs(self) -> None:
        self.admit(self.event("opened"))
        now = [0.0]
        attempts: list[tuple[float, str, str]] = []

        def sleep(seconds: float) -> None:
            now[0] += seconds

        def hung(req: urllib.request.Request, timeout: float | None = None) -> Response:
            assert timeout is not None
            assert timeout > 0
            attempts.append((now[0], req.get_method(), req.full_url.removeprefix(ROOT)))
            if len(attempts) <= 2:  # the first two failure writes go through
                return self.server.urlopen(req, timeout)
            now[0] += timeout
            raise TimeoutError("hung")

        api = GitHub(sleep=sleep, clock=lambda: now[0])
        out = io.StringIO()
        with mock.patch("urllib.request.urlopen", hung), contextlib.redirect_stdout(out), self.assertRaises(TimeoutError):
            governance.stop(api, 1, SHA, "stop")
        worst = governance.STOP_STEPS_SECONDS + governance.FINAL_WRITE_SECONDS
        self.assertLessEqual(now[0], worst)
        self.assertGreater(now[0], governance.STOP_STEPS_SECONDS, "the last write got its own time after the steps used theirs")
        last_writes = [at for at, method, path in attempts[2:] if method == "POST" and path.startswith("/statuses/")]
        self.assertTrue(last_writes and min(last_writes) >= governance.STOP_STEPS_SECONDS, attempts)
        self.assertIn("::error::", out.getvalue())
        self.assertIsNone(api.deadline)

    def test_a_first_write_that_hangs_still_leaves_the_cancels_and_the_last_write(self) -> None:
        self.admit(self.event("opened"))
        self.server.add_run(400, "in_progress")
        now = [0.0]
        hung_writes: list[float] = []

        def sleep(seconds: float) -> None:
            now[0] += seconds

        def first_write_hangs(req: urllib.request.Request, timeout: float | None = None) -> Response:
            assert timeout is not None
            assert timeout > 0
            if req.get_method() == "POST" and req.full_url.removeprefix(ROOT).startswith("/statuses/") and len(hung_writes) < 5:
                hung_writes.append(now[0])  # every attempt of the first write hangs until its timeout
                now[0] += timeout
                raise TimeoutError("hung")
            return self.server.urlopen(req, timeout)

        api = GitHub(sleep=sleep, clock=lambda: now[0])
        out = io.StringIO()
        with mock.patch("urllib.request.urlopen", first_write_hangs), contextlib.redirect_stdout(out):
            governance.stop(api, 1, SHA, "stop")
        self.assertEqual(len(hung_writes), 1 + len(governance.STATUS_RETRY_DELAYS))
        self.assertIn("::warning::The first failure status could not be written (TimeoutError); the stop goes on", out.getvalue())
        self.assertNotIn("::error::", out.getvalue())
        self.assertEqual(self.server.cancelled, [400])
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})
        self.assertLessEqual(now[0], governance.STOP_STEPS_SECONDS + governance.FINAL_WRITE_SECONDS)
        self.assertIsNone(api.deadline)

    def test_no_request_starts_or_sleeps_past_the_deadline(self) -> None:
        self.api.deadline = self.api.clock() - 1
        with self.assertRaises(TimeoutError):
            self.api.request("/pulls/1")
        self.assertEqual(self.server.calls, [])
        self.api.deadline = self.api.clock() + 2
        self.api.pause(60)
        self.assertLessEqual(self.sleeps[-1], 2)

    def test_status_writes_have_their_own_shorter_timeout(self) -> None:
        self.api.status(SHA, "Quality", "pending", "queued")
        self.api.request("/pulls/1")
        self.assertEqual(self.server.timeouts, [governance.STATUS_TIMEOUT, governance.REQUEST_TIMEOUT])

    def test_the_deadline_is_cleared_after_every_stop(self) -> None:
        self.admit(self.event("opened"))
        self.server.fail("POST", "/statuses/", 503)
        with self.assertRaises(urllib.error.HTTPError):
            self.admit(self.labeled(REVOKE_LABEL))
        self.assertIsNone(self.api.deadline)


class FinishTests(GateCase):
    def test_finish_publishes_only_the_required_contexts(self) -> None:
        self.admit(self.event("opened"))
        with self.finishing():
            self.finish()
        self.assertEqual(set(self.server.latest()), set(REQUIRED_CONTEXTS))
        self.assertEqual(set(self.states().values()), {"success"})

    def test_finish_reports_each_check_from_its_jobs(self) -> None:
        self.admit(self.event("opened"))
        ok = {"result": "success"}
        for results, expected in (
            ({"quality": ok, "registry": {"result": "skipped"}, "standards": ok}, {"Quality": "failure", "Repository standards": "success"}),
            ({"quality": ok, "registry": ok, "standards": {"result": "cancelled"}}, {"Quality": "success", "Repository standards": "failure"}),
            ({}, {"Quality": "failure", "Repository standards": "failure"}),
        ):
            with self.subTest(results=results), self.finishing(json.dumps(results)):
                self.finish()
                self.assertEqual(self.states(), expected)

    def test_a_rerun_of_failed_jobs_keeps_ownership_and_publishes_the_new_result(self) -> None:
        self.admit(self.event("opened"))
        with self.finishing('{"quality": {"result": "failure"}, "registry": {"result": "success"}, "standards": {"result": "success"}}'):
            self.finish()
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "success"})
        with self.as_run(RUN, "2"), self.finishing():
            governance.verify(self.api)
            self.finish()
        self.assertEqual(set(self.states().values()), {"success"})

    def test_finish_after_a_revoke_by_another_run_writes_nothing(self) -> None:
        self.admit(self.event("opened"))
        self.server.add_run(501, "in_progress")
        with self.as_run(501):
            self.admit(self.event("labeled", label={"name": REVOKE_LABEL}))
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})
        self.server.writes.clear()
        with self.finishing():
            self.assertIn("Another run owns", self.finish())
            with self.assertRaises(ValueError):
                governance.verify(self.api)
        self.assertEqual(self.server.writes, [])
        self.assertEqual(set(self.states().values()), {"failure"})

    def test_finish_after_a_newer_admission_of_the_same_head_writes_nothing(self) -> None:
        self.admit(self.event("opened"))
        self.server.add_run(501, "in_progress")
        with self.as_run(501):
            for context in REQUIRED_CONTEXTS:
                self.api.status(SHA, context, "pending", "Admitted checks queued")
        self.server.writes.clear()
        with self.finishing():
            self.finish()
        self.assertEqual(self.server.writes, [])

    def revoke_as(self, run: int) -> Callable[[], None]:
        def effect() -> None:
            self.server.add_run(run, "in_progress")
            with self.as_run(run), contextlib.redirect_stdout(io.StringIO()):
                governance.admit(self.api, self.event("labeled", label={"name": REVOKE_LABEL}))
        return effect

    def test_a_revoke_that_lands_while_finish_rechecks_the_pr_wins(self) -> None:
        self.admit(self.event("opened"))
        self.server.on("GET", "/pulls/1", self.revoke_as(501))
        with self.finishing():
            self.assertIn("Another run owns", self.finish())
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})

    def test_a_revoke_between_the_ownership_check_and_the_write_still_wins(self) -> None:
        self.admit(self.event("opened"))
        self.server.on("POST", "/statuses/", self.revoke_as(501))
        with self.finishing():
            self.finish()
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})
        self.assertEqual(self.server.writes[-2:], ["status:failure", "status:failure"])

    def test_a_retried_duplicate_write_cannot_hide_a_revoke(self) -> None:
        # GitHub stores the first success but the answer is lost, so the retry writes a second, adjacent success.
        self.admit(self.event("opened"))
        revoke = self.revoke_as(501)

        def revoke_then_drop_the_answers() -> None:
            revoke()
            # Registered after the revoke, so finish's own writes are the ones stored twice, in both contexts.
            for context in REQUIRED_CONTEXTS:
                self.server.fail("POST", "/statuses/", 502, times=1, after_write=True, context=context)

        self.server.on("POST", "/statuses/", revoke_then_drop_the_answers)
        with self.finishing():
            self.finish()
        for context in REQUIRED_CONTEXTS:
            states = [status["state"] for status in self.server.log if status["context"] == context]
            self.assertEqual(states[-3:-1], ["success", "success"], "the retry stored a second success")
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})

    def test_an_unreadable_history_after_the_write_fails_closed_and_a_rerun_publishes(self) -> None:
        self.admit(self.event("opened"))
        # The ownership read before the write succeeds; the read after the write fails every attempt.
        self.server.on("POST", "/statuses/", lambda: self.server.fail("GET", f"/commits/{SHA}/statuses", 503, times=3))
        with self.finishing(), self.assertRaises(urllib.error.HTTPError):
            self.finish()
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})
        with self.as_run(RUN, attempt="2"), self.finishing():
            self.finish()
        self.assertEqual(self.states(), {"Quality": "success", "Repository standards": "success"})

    def test_an_unreadable_history_before_the_write_publishes_nothing(self) -> None:
        self.admit(self.event("opened"))
        self.server.fail("GET", f"/commits/{SHA}/statuses", 503, times=3)
        self.server.writes.clear()
        with self.finishing(), self.assertRaises(urllib.error.HTTPError):
            self.finish()
        self.assertEqual(self.server.writes, [])
        self.assertEqual(set(self.states().values()), {"pending"})

    def test_a_stop_ends_a_runs_ownership_for_good(self) -> None:
        mine, other = run_url(RUN), run_url(501)
        history = [{"context": context, "target_url": url} for url in (other, mine) for context in REQUIRED_CONTEXTS]
        self.assertTrue(governance.stopped(history, mine))
        self.assertFalse(governance.owns(history, mine))
        # This run writing again on top does not restore it.
        newer = [{"context": context, "target_url": mine} for context in REQUIRED_CONTEXTS] + history
        self.assertTrue(governance.stopped(newer, mine))
        self.assertFalse(governance.owns(newer, mine))
        # Statuses of an older run do not count against a newer one.
        older = [{"context": context, "target_url": url} for url in (mine, other) for context in REQUIRED_CONTEXTS]
        self.assertFalse(governance.stopped(older, mine))
        self.assertTrue(governance.owns(older, mine))

    def test_a_rerun_after_a_revoke_and_an_unreadable_history_cannot_undo_the_revoke(self) -> None:
        self.admit(self.event("opened"))
        revoke = self.revoke_as(501)

        def revoke_then_break_the_history() -> None:
            revoke()
            # The ownership read before the write already succeeded; the read after it fails every attempt.
            self.server.fail("GET", f"/commits/{SHA}/statuses", 503, times=3)

        self.server.on("POST", "/statuses/", revoke_then_break_the_history)
        with self.finishing(), self.assertRaises(urllib.error.HTTPError):
            self.finish()
        self.assertEqual(set(self.states().values()), {"failure"})
        self.server.writes.clear()
        with self.as_run(RUN, attempt="2"), self.finishing():
            self.assertIn("Another run owns", self.finish())
        self.assertEqual(self.server.writes, [])
        self.assertEqual(set(self.states().values()), {"failure"})

    def test_a_revoke_between_the_two_result_writes_fails_both(self) -> None:
        self.admit(self.event("opened"))
        revoke = self.revoke_as(501)
        writes = {"count": 0}

        def revoke_before_the_second_write() -> None:
            writes["count"] += 1
            if writes["count"] == 2:
                revoke()

        self.server.on("POST", "/statuses/", revoke_before_the_second_write, times=1000)
        with self.finishing():
            self.finish()
        self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})

    def test_an_approval_while_finish_writes_its_results_admits_nothing_beside_it(self) -> None:
        # After finish writes Quality, the head has one success and one pending; the run is still live and holds it.
        self.admit(self.event("opened"))
        writes = {"count": 0}

        def approve_before_the_second_write() -> None:
            writes["count"] += 1
            if writes["count"] == 2:
                self.server.add_run(501, "in_progress")
                with self.as_run(501), contextlib.redirect_stdout(io.StringIO()) as out:
                    governance.admit(self.api, self.event("labeled", label={"name": APPROVE_LABEL}))
                self.assertIn("already admitted", out.getvalue())

        self.server.on("POST", "/statuses/", approve_before_the_second_write, times=1000)
        with self.finishing():
            self.finish()
        self.assertEqual(self.states(), {"Quality": "success", "Repository standards": "success"})
        self.assertEqual({status["target_url"] for status in self.server.log}, {run_url(RUN)})

    def test_a_rerun_of_a_stopped_runs_admission_does_not_admit_again(self) -> None:
        self.admit(self.event("opened"))
        self.server.add_run(501, "in_progress")
        with self.as_run(501):
            self.admit(self.event("labeled", label={"name": REVOKE_LABEL}))
        self.server.runs[501]["status"] = "completed"
        self.server.writes.clear()
        with self.as_run(RUN, attempt="2"), mock.patch.dict(os.environ, {"GITHUB_TRIGGERING_ACTOR": USER["login"]}):
            self.assertIn("newer run already decided", self.admit(self.event("opened")))
        self.assertEqual(self.outputs()["run"], "false")
        self.assertEqual(self.server.writes, [])

    def test_a_rerun_of_a_run_that_an_older_id_stopped_does_not_admit_again(self) -> None:
        # A stop whose run id is lower than the rerun's (so the rerun is not superseded) still ends the claim by history.
        self.admit(self.event("opened"))
        for context in REQUIRED_CONTEXTS:
            self.server.add_status("failure", context, run_url(499))
        self.server.writes.clear()
        with self.as_run(RUN, attempt="2"), mock.patch.dict(os.environ, {"GITHUB_TRIGGERING_ACTOR": USER["login"]}):
            self.assertIn("stopped this run", self.admit(self.event("opened")))
        self.assertEqual(self.server.writes, [])

    def test_a_clean_finish_reads_the_history_and_leaves_its_result(self) -> None:
        self.admit(self.event("opened"))
        self.server.writes.clear()
        with self.finishing():
            self.finish()
        self.assertEqual(self.server.writes, ["status:success", "status:success"])
        self.assertIn(("GET", f"/commits/{SHA}/statuses?per_page=100&page=1"), self.server.calls)

    def test_a_rerun_of_every_job_after_success_publishes_nothing(self) -> None:
        # The admission writes run=false for a head that already passed, and finish runs only when run is true.
        self.admit(self.event("opened"))
        with self.finishing():
            self.finish()
        self.server.writes.clear()
        with self.as_run(RUN, attempt="2"), mock.patch.dict(os.environ, {"GITHUB_TRIGGERING_ACTOR": USER["login"]}):
            self.assertIn("already passed", self.admit(self.event("opened")))
        self.assertEqual(self.outputs()["run"], "false")
        self.assertEqual(self.server.writes, [])
        self.assertEqual(set(self.states().values()), {"success"})

    def test_ownership_needs_both_contexts(self) -> None:
        self.admit(self.event("opened"))
        self.server.add_status("pending", "Quality", run_url(501))
        with self.finishing():
            self.assertIn("Another run owns", self.finish())

    def test_finish_fails_closed_when_the_head_moves_or_the_pr_stops_being_admissible(self) -> None:
        changes: dict[str, Callable[[], object]] = {
            "head": lambda: self.server.pr["head"].update(sha=OLD),
            "closed": lambda: self.server.pr.update(state="closed"),
            "draft": lambda: self.server.pr.update(draft=True),
            "base": lambda: self.server.pr["base"].update(ref="release"),
        }
        for change, apply in changes.items():
            with self.subTest(change=change):
                self.setUp()
                self.admit(self.event("opened"))
                self.server.reviews.append({"id": 1, "state": "APPROVED", "user": {"login": "github-actions[bot]"}, "commit_id": SHA})
                apply()
                with self.finishing(), self.assertRaises(ValueError):
                    self.finish()
                self.assertEqual(set(self.states().values()), {"failure"})
                self.assertEqual(self.server.reviews[0]["state"], "DISMISSED")

    def test_finish_fails_closed_on_unreadable_job_results(self) -> None:
        self.admit(self.event("opened"))
        with self.finishing("not json"), self.assertRaises(ValueError):
            self.finish()
        self.assertEqual(set(self.states().values()), {"failure"})

    def test_a_rejected_status_write_stops_the_command(self) -> None:
        self.admit(self.event("opened"))
        self.server.fail("POST", "/statuses/", 403)
        with self.finishing(), self.assertRaises(urllib.error.HTTPError):
            self.finish()

    def test_verify_requires_a_live_owned_admission(self) -> None:
        self.admit(self.event("opened"))
        with self.finishing():
            governance.verify(self.api)
            self.server.pr["head"]["sha"] = OLD
            with self.assertRaises(ValueError):
                governance.verify(self.api)

    def test_the_head_and_number_from_job_outputs_are_validated(self) -> None:
        for number, head in (("", SHA), ("0", SHA), ("1; echo", SHA), ("1", ""), ("1", "../" + "a" * 37), ("1", SHA.upper())):
            with self.subTest(number=number, head=head), mock.patch.dict(os.environ, {"PR_NUMBER": number, "PR_HEAD": head}), self.assertRaises(ValueError):
                governance.verify(self.api)
        self.assertEqual(self.server.calls, [])


class DecisionOrderTests(GateCase):
    """A later decision wins, a stop is durable until it completes, and only a maintainer's event admits."""

    def test_an_older_admission_event_that_runs_after_a_newer_revoke_admits_nothing(self) -> None:
        # Run 500 (Ready, the earlier event) reaches its job after run 501 (revoke, the later event).
        self.admit_as(501, self.labeled(REVOKE_LABEL))
        self.complete(501)
        self.assertEqual(self.admit_as(500, self.event("ready_for_review")).get("run"), "false")
        self.assertIn("newer run already decided", self.notices)
        self.assertEqual(set(self.states().values()), {"failure"})

    def test_a_rerun_of_an_approve_run_after_a_revoke_records_no_approval(self) -> None:
        approve = self.labeled(APPROVE_LABEL)
        self.assertEqual(self.admit_as(500, approve)["run"], "true")
        self.admit_as(501, self.labeled(REVOKE_LABEL))
        self.complete(500, 501)
        self.assertEqual(self.approved(), [])
        self.admit_as(500, approve, attempt="2")
        self.assertEqual(self.approved(), [], "the replay posted an approval after the revoke dismissed it")
        self.assertEqual(set(self.states().values()), {"failure"})

    def test_a_superseded_approve_records_nothing_and_its_label_is_removed(self) -> None:
        self.server.pr["user"] = copy.deepcopy(OUTSIDER)
        approve = self.labeled(APPROVE_LABEL)
        self.admit_as(501, self.labeled(REVOKE_LABEL))
        self.assertEqual(self.admit_as(500, approve)["run"], "false")
        self.assertEqual((self.approved(), self.server.pr["labels"]), ([], []))

    def test_a_rerun_of_a_run_that_wrote_nothing_does_not_admit_after_a_stop(self) -> None:
        self.server.fail("POST", "/statuses/", 503)  # run 500 never stores a status
        with self.assertRaises(urllib.error.HTTPError):
            self.admit_as(500, self.event("opened"))
        self.server.faults.clear()
        self.admit_as(501, self.labeled(REVOKE_LABEL))
        self.complete(500, 501)
        self.assertEqual(self.admit_as(500, self.event("opened"), attempt="2")["run"], "false")
        self.assertEqual(set(self.states().values()), {"failure"})

    def test_a_forged_newer_status_cannot_disarm_a_revoke(self) -> None:
        # Statuses that name a higher run id but were not written by a real run of this workflow are ignored.
        self.server.add_run(9000, "completed", workflow=WORKFLOW + 1)
        forged = {
            "by a person": (run_url(8000), "everettmorgan"),
            "for a run that does not exist": (run_url(8000), "github-actions[bot]"),
            "for a run of another workflow": (run_url(9000), "github-actions[bot]"),
        }
        for name, (url, creator) in forged.items():
            with self.subTest(name):
                self.setUp()
                self.server.add_run(9000, "completed", workflow=WORKFLOW + 1)
                self.assertEqual(self.admit_as(500, self.event("opened"))["run"], "true")
                for context in REQUIRED_CONTEXTS:
                    self.server.add_status("success", context, url, creator=creator)
                self.admit_as(501, self.labeled(REVOKE_LABEL))
                self.assertNotIn("newer run already decided", self.notices)
                self.assertEqual(self.states(), {"Quality": "failure", "Repository standards": "failure"})
                self.assertEqual(self.server.pr["labels"], [])

    def test_a_superseded_revoke_is_skipped_and_its_label_is_removed(self) -> None:
        revoke = self.labeled(REVOKE_LABEL)
        self.admit_as(501, revoke)
        self.complete(501)
        self.assertEqual(self.admit_as(502, self.event("ready_for_review"))["run"], "true")
        self.server.writes.clear()
        self.admit_as(501, revoke, attempt="2")  # a maintainer reruns the old revoke after the newer admission
        self.assertEqual(self.server.writes, ["label:" + REVOKE_LABEL])
        self.assertEqual(set(self.states().values()), {"pending"})

    def test_a_draft_stop_is_not_swallowed_because_someone_set_the_pr_ready_again(self) -> None:
        self.server.pr["user"] = copy.deepcopy(OUTSIDER)
        self.assertEqual(self.admit_as(500, self.labeled(APPROVE_LABEL))["run"], "true")
        # The maintainer converts to draft. The author, who is not a maintainer, sets Ready before the draft event runs.
        draft = self.event("converted_to_draft")
        self.assertEqual(self.admit_as(501, self.event("ready_for_review", sender=OUTSIDER))["run"], "false")
        self.admit_as(502, draft)
        self.assertEqual(set(self.states().values()), {"failure"})
        with self.finishing():
            self.assertIn("Another run owns", self.finish())
        self.assertEqual(set(self.states().values()), {"failure"})

    def test_only_a_maintainers_event_admits_a_head_a_maintainer_stopped(self) -> None:
        self.assertEqual(self.admit_as(500, self.event("opened"))["run"], "true")
        self.admit_as(501, self.labeled(REVOKE_LABEL))
        self.complete(500, 501)
        for run, action in enumerate(("reopened", "ready_for_review", "synchronize"), 502):
            with self.subTest(action=action):
                out = self.admit_as(run, self.event(action, sender=OUTSIDER, before=OLD), actor=OUTSIDER["login"])
                self.assertEqual(out["run"], "false")
                self.assertIn("not admitted yet", self.notices)
        self.assertEqual(set(self.states().values()), {"failure"})
        self.assertEqual(self.admit_as(510, self.event("ready_for_review"))["run"], "true")

    def test_a_revoke_whose_stop_fails_keeps_its_label_and_finish_and_verify_fail_closed(self) -> None:
        self.assertEqual(self.admit_as(500, self.event("opened"))["run"], "true")
        revoke = self.labeled(REVOKE_LABEL)
        self.server.fail("POST", "/statuses/", 503)
        with self.assertRaises(urllib.error.HTTPError):
            self.admit_as(501, revoke)
        self.server.faults.clear()
        self.assertEqual(self.server.pr["labels"], [{"name": REVOKE_LABEL}])
        self.complete(501)
        with self.finishing():
            with self.assertRaises(ValueError):
                governance.verify(self.api)
            with self.assertRaises(ValueError):
                self.finish()
        self.assertEqual(set(self.states().values()), {"failure"})

    def test_a_revoke_label_that_no_job_processed_still_blocks_admission_approval_and_finish(self) -> None:
        # The revoke job was cancelled while it waited, so nothing but the label records the maintainer's decision.
        self.server.pr["user"] = copy.deepcopy(OUTSIDER)
        self.assertEqual(self.admit_as(500, self.labeled(APPROVE_LABEL))["run"], "true")
        self.server.pr["labels"].append({"name": REVOKE_LABEL})
        with self.finishing(), self.assertRaises(ValueError):
            self.finish()
        self.assertEqual(set(self.states().values()), {"failure"})
        self.complete(500)
        self.server.writes.clear()
        self.assertEqual(self.admit_as(501, self.event("ready_for_review"))["run"], "false")
        self.assertIn("gate:revoke is on this PR; remove it to admit again", self.notices)
        self.assertEqual(self.admit_as(502, self.labeled(APPROVE_LABEL))["run"], "false")
        self.assertIn("gate:revoke is on this PR", self.notices)
        self.assertEqual(self.server.writes, ["label:" + APPROVE_LABEL])
        self.assertEqual(self.approved(), [])

    def test_a_failed_stop_blocks_a_ready_with_a_notice_until_the_stop_is_rerun(self) -> None:
        self.assertEqual(self.admit_as(500, self.event("opened"))["run"], "true")
        revoke = self.labeled(REVOKE_LABEL)
        self.server.fail("POST", "/statuses/", 503, context="Repository standards")  # Quality fails, Standards cannot be written
        with self.assertRaises(urllib.error.HTTPError):
            self.admit_as(501, revoke)
        self.server.faults.clear()
        self.complete(501)
        self.assertEqual(self.admit_as(502, self.event("ready_for_review"))["run"], "false")
        self.assertIn("gate:revoke is on this PR", self.notices)
        self.admit_as(501, revoke, attempt="2")
        self.assertEqual(self.server.pr["labels"], [])
        self.complete(500, 501)
        self.assertEqual(self.admit_as(503, self.event("ready_for_review"))["run"], "true")

    def test_a_non_maintainer_revoke_label_is_removed_and_stops_nothing(self) -> None:
        self.assertEqual(self.admit_as(500, self.event("opened"))["run"], "true")
        self.server.writes.clear()
        with self.assertRaises(ValueError):
            self.admit_as(501, self.labeled(REVOKE_LABEL, sender=OUTSIDER), actor=OUTSIDER["login"])
        self.assertEqual(self.server.writes, ["label:" + REVOKE_LABEL])
        self.assertEqual(self.server.pr["labels"], [])
        self.assertEqual(set(self.states().values()), {"pending"})

    def test_a_stop_survives_a_burst_of_status_failures(self) -> None:
        self.assertEqual(self.admit_as(500, self.event("opened"))["run"], "true")
        with self.finishing():
            self.finish()
        self.complete(500)
        self.server.fail("POST", "/statuses/", 503, times=4)
        self.admit_as(501, self.labeled(REVOKE_LABEL))
        self.assertEqual(self.sleeps, [1, 2, 4, 8])
        self.assertEqual(set(self.states().values()), {"failure"})

    def test_a_failed_cancel_does_not_leave_the_revoked_approval_standing(self) -> None:
        self.assertEqual(self.admit_as(500, self.labeled(APPROVE_LABEL))["run"], "true")
        self.server.add_run(499, "in_progress")
        self.server.fail("POST", "/actions/runs/499/cancel", 403)
        with self.assertRaises(urllib.error.HTTPError):
            self.admit_as(501, self.labeled(REVOKE_LABEL))
        self.assertEqual(self.approved(), [])
        self.assertEqual(set(self.states().values()), {"failure"})

    def test_the_approval_is_bound_to_the_labelled_head_even_if_the_head_moves_during_the_call(self) -> None:
        self.server.pr["user"] = copy.deepcopy(OUTSIDER)
        self.server.on("POST", "/pulls/1/reviews", lambda: self.server.pr["head"].update(sha="d" * 40))
        self.admit_as(500, self.labeled(APPROVE_LABEL))
        self.assertEqual({review["commit_id"] for review in self.server.reviews}, {SHA})


class CommandTests(GateCase):
    def run_main(self, *args: str) -> tuple[int, str]:
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["governance.py", *args]), contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                governance.main()
            except SystemExit as stop:
                return int(stop.code or 0), err.getvalue()
        return 0, err.getvalue()

    def write_event(self, event: Any) -> None:
        Path(os.environ["GITHUB_EVENT_PATH"]).write_text(json.dumps(event))

    def test_a_rejected_status_write_stops_admission_with_a_clean_line_and_no_run(self) -> None:
        self.write_event(self.event("opened"))
        self.server.fail("POST", "/statuses/", 403)
        code, err = self.run_main("admit")
        self.assertEqual(code, 1)
        self.assertEqual(err, "Governance stopped: HTTPError: HTTP Error 403: injected\n")
        self.assertEqual(self.outputs(), {"run": "false"})

    def test_malformed_events_and_payloads_exit_cleanly(self) -> None:
        event = self.event("opened")
        del event["pull_request"]["head"]
        payloads: list[Any] = [event, [], {"action": "opened", "pull_request": {"number": 1, "head": {"sha": "nope"}}},
                                {"action": "opened", "pull_request": {"number": "1", "head": {"sha": SHA}}}]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.write_event(payload)
                code, err = self.run_main("admit")
                self.assertEqual(code, 1)
                self.assertTrue(err.startswith("Governance stopped: "), err)

    def test_unknown_operations_and_unadopted_repositories_are_refused(self) -> None:
        self.assertEqual(self.run_main("bogus")[0], 1)
        self.assertEqual(self.run_main()[0], 1)
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "someone/else"}):
            code, err = self.run_main("verify")
        self.assertEqual((code, err), (1, "Governance stopped: ValueError: Repository has not adopted the ejmlabs policy\n"))

    def test_the_commands_run_end_to_end(self) -> None:
        self.write_event(self.event("opened"))
        self.assertEqual(self.run_main("admit")[0], 0)
        with self.finishing():
            self.assertEqual(self.run_main("verify")[0], 0)
            self.assertEqual(self.run_main("finish")[0], 0)
        self.assertEqual(set(self.states().values()), {"success"})


class TransportTests(GateCase):
    def test_get_retries_rate_limits_server_errors_and_network_errors_with_backoff(self) -> None:
        cases: tuple[tuple[int | OSError, ...], ...] = (
            (429,), (502, urllib.error.URLError("reset")), (500, TimeoutError("slow")), (503, ConnectionResetError()))
        for failures in cases:
            with self.subTest(failures=failures):
                self.setUp()
                for failure in failures:
                    self.server.fail("GET", "/pulls/1", failure, times=1)
                self.assertEqual(self.api.request("/pulls/1")["number"], 1)
                self.assertEqual(self.sleeps, [1, 2][:len(failures)])
                self.assertEqual(self.server.calls[-1], ("GET", "/pulls/1"))
                self.assertEqual(len(self.server.calls), len(failures) + 1)

    def test_three_attempts_in_all_then_the_error_surfaces(self) -> None:
        self.server.fail("GET", "/pulls/1", 502)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.api.request("/pulls/1")
        self.assertEqual(raised.exception.code, 502)
        self.assertEqual((len(self.server.calls), self.sleeps), (3, [1, 2]))

    def test_network_errors_surface_after_three_attempts(self) -> None:
        self.server.fail("GET", "/pulls/1", urllib.error.URLError("down"))
        with self.assertRaises(urllib.error.URLError):
            self.api.request("/pulls/1")
        self.assertEqual(len(self.server.calls), 3)

    def test_client_errors_are_not_retried(self) -> None:
        for code in (400, 401, 403, 404, 409, 422):
            with self.subTest(code=code):
                self.setUp()
                self.server.fail("GET", "/pulls/1", code)
                with self.assertRaises(urllib.error.HTTPError):
                    self.api.request("/pulls/1")
                self.assertEqual((len(self.server.calls), self.sleeps), (1, []))

    def test_a_review_is_never_posted_twice_but_statuses_and_cancels_are_retried(self) -> None:
        self.server.fail("POST", "/pulls/1/reviews", 502)
        with self.assertRaises(urllib.error.HTTPError):
            self.api.request("/pulls/1/reviews", "POST", {"event": "APPROVE"})
        self.assertEqual(len(self.server.calls), 1)
        self.server.calls.clear()
        self.server.fail("POST", "/statuses/", 502, times=2)
        self.api.status(SHA, "Quality", "pending", "queued")
        self.assertEqual((len(self.server.calls), self.sleeps), (3, [1, 2]))
        self.assertEqual(self.states(), {"Quality": "pending"})
        self.server.add_run(401, "in_progress")
        self.server.fail("POST", "/actions/runs/401/cancel", 500, times=1)
        self.api.request("/actions/runs/401/cancel", "POST", retry=True)
        self.assertEqual(self.server.cancelled, [401])

    def test_deletes_and_dismissals_are_retried(self) -> None:
        self.server.reviews.append({"id": 1, "state": "APPROVED", "user": {"login": "github-actions[bot]"}, "commit_id": SHA})
        self.server.fail("PUT", "/pulls/1/reviews/1", 503, times=1)
        self.server.fail("DELETE", "/issues/1/labels/", 502, times=1)
        governance.dismiss_bot_approvals(self.api, 1, SHA, "stop")
        governance.remove_label(self.api, 1, APPROVE_LABEL)
        self.assertEqual(self.server.writes, ["dismiss:1", "label:" + APPROVE_LABEL])
        self.assertEqual(self.sleeps, [1, 1])

    def test_requests_are_bounded_in_size(self) -> None:
        with mock.patch.object(governance, "MAX_RESPONSE_BYTES", 20), self.assertRaises(ValueError):
            self.api.request("/pulls/1")

    def test_a_missing_collaborator_has_no_permission_and_unsafe_logins_are_never_sent(self) -> None:
        self.assertEqual(self.api.permission("maintainer"), "maintain")
        self.assertEqual(self.api.permission("stranger"), "none")
        self.server.calls.clear()
        for login in ("", "a/b", "a b", "../x", "x\n"):
            self.assertEqual(self.api.permission(login), "none")
        self.assertEqual(self.server.calls, [])
        self.server.fail("GET", "/collaborators/", 403)
        with self.assertRaises(urllib.error.HTTPError):
            self.api.permission("maintainer")

    def test_the_combined_status_is_read_in_pages_with_the_newest_status_of_each_context(self) -> None:
        self.server.add_status("pending", "Quality", run_url(1))
        for index in range(149):
            self.server.add_status("success", f"other-{index}", run_url(2))
        self.server.add_status("failure", "Quality", run_url(3))
        found = self.api.statuses(SHA)
        self.assertEqual(len(found), 150)
        self.assertEqual((found["Quality"]["state"], found["Quality"]["target_url"]), ("failure", run_url(3)))
        self.assertEqual([path for _, path in self.server.calls], [f"/commits/{SHA}/status?per_page=100&page=1", f"/commits/{SHA}/status?per_page=100&page=2"])

    def test_pages_collect_every_page_and_stop_at_the_limit(self) -> None:
        self.server.reviews.extend({"id": index + 1, "state": "COMMENTED"} for index in range(250))
        self.assertEqual(len(self.api.pages("/pulls/1/reviews")), 250)
        with self.assertRaises(ValueError):
            self.api.pages("/pulls/1/reviews", limit=2)

    def test_the_run_url_comes_from_the_repository_and_run_id(self) -> None:
        self.assertEqual(self.api.run_url, run_url(RUN))

    def test_only_adopted_repositories_use_the_client(self) -> None:
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "ejmlabs/other"}), self.assertRaises(ValueError):
            GitHub()


if __name__ == "__main__":
    unittest.main()
