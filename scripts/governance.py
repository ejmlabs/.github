#!/usr/bin/env python3
"""Trusted admission and approval for ejmlabs repositories."""
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

REPOS = {"ejmlabs/" + name for name in (".github", "ejmlabs", "ejm-calm", "ejm-cli", "ejm-harness", "ejm-ide", "ejm-ui")}
REQUIRED_CONTEXTS = ("Quality", "Repository standards")
APPROVE_LABEL = "gate:approve"
REVOKE_LABEL = "gate:revoke"
GATE_LABELS = (APPROVE_LABEL, REVOKE_LABEL)
ACTIONS = ("opened", "reopened", "synchronize", "ready_for_review", "converted_to_draft", "labeled")
RETRY_DELAYS = (1, 2)
# A status write is the gate's only way to stop or publish a head, so it gets a longer budget than the other calls.
STATUS_RETRY_DELAYS = (1, 2, 4, 8)
# Seconds a request may block. A status answers in well under a second, so a hung one is retried instead of waited for.
REQUEST_TIMEOUT = 30
STATUS_TIMEOUT = 10
# A stop ends within STOP_STEPS_SECONDS + FINAL_WRITE_SECONDS whatever GitHub does: the first write, the cancels, the
# dismissals and the wait share the first, the last write has the second. The admission job has 3 minutes in all.
STOP_STEPS_SECONDS = 80
FINAL_WRITE_SECONDS = 40
# After the cancels, wait up to RUN_POLLS * RUN_POLL_SECONDS (45) seconds for the cancelled runs to complete.
RUN_POLL_SECONDS = 3
RUN_POLLS = 15
MAX_RESPONSE_BYTES = 8_000_000
FULL_SHA = re.compile(r"[0-9a-f]{40}")
NETWORK_ERRORS = (OSError, http.client.HTTPException)
# Failures a command reports as one clean line: bad input, an unexpected payload shape, or an API or network error.
HANDLED = (ValueError, KeyError, TypeError, *NETWORK_ERRORS)
STALE_HEAD = "The PR head changed, or the PR is closed, a draft, or no longer targets main; a newer event handles it"
SUPERSEDED = "A newer run already decided this head; nothing to do"
REVOKE_PENDING = "gate:revoke is on this PR; remove it to admit again"


def human(user: dict[str, Any], permission: str) -> bool:
    return bool(user.get("type") == "User" and permission in {"admin", "maintain"})


def same_repository(pr: dict[str, Any]) -> bool:
    head_repo = pr["head"].get("repo") or {}
    return bool(head_repo.get("full_name") == pr["base"]["repo"]["full_name"])


def current_head(pr: dict[str, Any], sha: str) -> bool:
    return bool(pr["state"] == "open" and not pr.get("draft") and pr["base"]["ref"] == "main" and pr["head"]["sha"] == sha)


class GitHub:
    def __init__(self, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        self.repo = os.environ["GITHUB_REPOSITORY"]
        if self.repo not in REPOS:
            raise ValueError("Repository has not adopted the ejmlabs policy")
        self.token = os.environ["GH_TOKEN"]
        self.root = "https://api.github.com/repos/" + self.repo
        self.sleep = sleep
        self.clock = clock
        # Set while a stop runs. No request or sleep goes past it, so the stop's total time is bounded by construction.
        self.deadline: float | None = None

    @property
    def run_url(self) -> str:
        return f"https://github.com/{self.repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    def pause(self, seconds: float) -> None:
        """Sleep, but never past the deadline."""
        if self.deadline is not None:
            seconds = min(seconds, max(self.deadline - self.clock(), 0))
        self.sleep(seconds)

    def request(self, path: str, method: str = "GET", data: dict[str, Any] | None = None, *, retry: bool | None = None,
                delays: tuple[int, ...] = RETRY_DELAYS, timeout: float = REQUEST_TIMEOUT) -> dict[str, Any]:
        """Call the API once, or again after each delay on 429, 5xx and network errors when the call is safe to repeat.

        GET, PUT and DELETE repeat by default. A POST repeats only when the caller says it is idempotent (statuses, cancel),
        so a review is never posted twice. Past the deadline, if one is set, no attempt starts and a TimeoutError is raised.
        """
        url = path if path.startswith("https://api.github.com/") else self.root + path
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method=method, headers={  # noqa: S310 - url is always https://api.github.com/
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
        })
        last = len(delays) if (method != "POST" if retry is None else retry) else 0
        attempt = 0
        while True:
            budget = timeout if self.deadline is None else min(timeout, self.deadline - self.clock())
            if budget <= 0:
                raise TimeoutError("The time budget for this step is spent")
            try:
                with urllib.request.urlopen(req, timeout=budget) as response:  # noqa: S310 - url is always https://api.github.com/
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
            except urllib.error.HTTPError as error:
                if attempt == last or not (error.code == 429 or 500 <= error.code <= 599):
                    raise
            except NETWORK_ERRORS:
                if attempt == last:
                    raise
            else:
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("GitHub response exceeds the size limit")
                return cast("dict[str, Any]", json.loads(raw or b"null"))
            self.pause(delays[attempt])
            attempt += 1

    def pages(self, path: str, limit: int = 10) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for page in range(1, limit + 1):
            batch = cast("list[dict[str, Any]]", self.request(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}"))
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise ValueError("Metadata limit exceeded; maintainer triage is required")

    def permission(self, login: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9-]+", login):
            return "none"
        try:
            role = self.request(f"/collaborators/{login}/permission")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return "none"
            raise
        return cast("str", role.get("role_name", role["permission"]))

    def statuses(self, sha: str) -> dict[str, dict[str, Any]]:
        """Return the newest status of each context from the combined status, one read for up to 100 contexts."""
        result: dict[str, dict[str, Any]] = {}
        for page in range(1, 11):
            batch = cast("list[dict[str, Any]]", self.request(f"/commits/{sha}/status?per_page=100&page={page}")["statuses"])
            for status in batch:
                result.setdefault(status["context"], status)
            if len(batch) < 100:
                return result
        raise ValueError("Metadata limit exceeded; maintainer triage is required")

    def status(self, sha: str, context: str, state: str, description: str) -> None:
        # The target URL names the run that wrote the status; ownership checks compare it with the current run.
        self.request(f"/statuses/{sha}", "POST", {
            "context": context, "state": state, "description": description[:140], "target_url": self.run_url,
        }, retry=True, delays=STATUS_RETRY_DELAYS, timeout=STATUS_TIMEOUT)


def outputs(**items: str | int) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as out:
        out.writelines(f"{key}={value}\n" for key, value in items.items())


def notice(message: str) -> None:
    """Report a no-op as an annotation. Callers pass fixed text, never PR content."""
    print("::notice::" + message)


def checked_sha(value: object) -> str:
    if not isinstance(value, str) or not FULL_SHA.fullmatch(value):
        raise ValueError("Expected a full lowercase commit SHA")
    return value


def is_maintainer(api: GitHub, user: dict[str, Any]) -> bool:
    return bool(user.get("type") == "User" and human(user, api.permission(user.get("login") or "")))


def dismiss_bot_approvals(api: GitHub, number: int | str, sha: str, reason: str) -> None:
    for review in api.pages(f"/pulls/{number}/reviews"):
        if (review.get("user") or {}).get("login") == "github-actions[bot]" and review["state"] == "APPROVED" and review["commit_id"] == sha:
            path = f"/pulls/{number}/reviews/{review['id']}"
            try:
                api.request(path + "/dismissals", "PUT", {"message": reason})
            except urllib.error.HTTPError as error:
                if error.code not in (403, 422) or api.request(path)["state"] == "APPROVED":
                    raise


def remove_label(api: GitHub, number: int | str, name: str) -> None:
    try:
        api.request(f"/issues/{int(number)}/labels/{urllib.parse.quote(name)}", "DELETE")
    except urllib.error.HTTPError as error:
        if error.code not in (404, 422):
            raise


def older_runs(api: GitHub, sha: str) -> list[int]:
    """Ids of this workflow's queued and in-progress runs for a head, except this run and any newer one.

    A newer run is a later decision for the same head, for example Ready after a draft conversion. List errors surface.
    """
    current = int(os.environ["GITHUB_RUN_ID"])
    workflow = int(api.request(f"/actions/runs/{current}")["workflow_id"])
    found: list[int] = []
    for state in ("queued", "in_progress"):
        listing = api.request(f"/actions/workflows/{workflow}/runs?head_sha={sha}&status={state}&per_page=100")
        for item in listing["workflow_runs"]:
            run = int(item["id"])
            if run < current and run not in found:
                found.append(run)
    return found


def cancel_runs(api: GitHub, runs: list[int]) -> None:
    """Ask GitHub to cancel each run. A run that finished or cannot be cancelled (409, 422) is fine."""
    for run in runs:
        try:
            api.request(f"/actions/runs/{run}/cancel", "POST", retry=True)
        except urllib.error.HTTPError as error:
            if error.code not in (409, 422):
                raise


def run_completed(api: GitHub, run: int) -> bool:
    """True when the run has completed or no longer exists. A run that cannot be read counts as still running."""
    try:
        return bool(api.request(f"/actions/runs/{run}")["status"] == "completed")
    except HANDLED as error:
        return isinstance(error, urllib.error.HTTPError) and error.code == 404


def wait_for_runs(api: GitHub, runs: list[int]) -> None:
    """Poll, for a bounded time, until every listed run has completed; warn naming the ones that have not.

    A cancelled run's finish job can still be running, and its success status would land after the stop's last write.
    Waiting for the run to complete closes that. This never raises: the stop's last write matters more than the wait.
    """
    pending = runs
    for poll in range(RUN_POLLS + 1):
        pending = [run for run in pending if not run_completed(api, run)]
        if not pending or poll == RUN_POLLS:
            break
        api.pause(RUN_POLL_SECONDS)
    if pending:
        print("::warning::Runs not confirmed completed after the stop, so a finish job in one may still write a status: "
              + ", ".join(str(run) for run in pending))


def cancel_superseded(api: GitHub, before: object) -> None:
    """Cancel the runs of the head a push replaced. This saves runner time only: finish still checks ownership and the live head."""
    if not isinstance(before, str) or not FULL_SHA.fullmatch(before):
        notice("The event names no previous head, so no runs are cancelled")
        return
    try:
        cancel_runs(api, older_runs(api, before))
    except NETWORK_ERRORS as error:
        # A read-only token (for example a Dependabot push) cannot cancel; the old run stops at its own ownership check.
        print(f"::warning::Could not cancel runs for the previous head: {type(error).__name__}")


def fail_checks(api: GitHub, sha: str, reason: str) -> None:
    for context in REQUIRED_CONTEXTS:
        api.status(sha, context, "failure", reason)


def stop(api: GitHub, number: int, sha: str, reason: str) -> None:
    """Authoritative stop: fail the checks, cancel runs, dismiss approvals, wait for the runs, then fail the checks as the last write.

    Approvals are dismissed even when cancelling fails, and the last write goes out even when a step above fails. The wait
    lets a finish job that was already running when its cancel landed write, and then end, before the last write, so its
    success cannot come after it. If a run is still going after the wait, the last write goes out anyway with a warning.
    The whole stop shares one clock: STOP_STEPS_SECONDS for the steps and FINAL_WRITE_SECONDS for the last write. If that
    write fails, the head may still read an earlier success: the job fails with an error and its label stays.
    """
    runs: list[int] = []
    api.deadline = api.clock() + STOP_STEPS_SECONDS
    try:
        try:
            try:
                try:
                    fail_checks(api, sha, reason)
                except HANDLED as error:
                    # The last write has its own time and fences the head on its own, so a first write that fails or
                    # spends the steps' time skips nothing: the cancels, the dismissals and the last write still run.
                    print(f"::warning::The first failure status could not be written ({type(error).__name__}); the stop goes on")
                runs = older_runs(api, sha)
                cancel_runs(api, runs)
            finally:
                dismiss_bot_approvals(api, number, sha, reason)
        finally:
            wait_for_runs(api, runs)
            api.deadline = api.clock() + FINAL_WRITE_SECONDS
            try:
                fail_checks(api, sha, reason)
            except HANDLED:
                print("::error::The final failure status could not be written, so this head may still read success. "
                      "Do not merge it until this job is rerun and passes, or the gate runs again.")
                raise
    finally:
        api.deadline = None


# Every status the gate writes comes from a workflow token, which GitHub records as this account.
GATE_WRITER = "github-actions[bot]"


def check_history(api: GitHub, sha: str) -> list[dict[str, Any]]:
    """The gate's own required-check statuses on a head, newest first, as GitHub lists them.

    A status another account or app created for the same context never counts for ownership, stops or ordering.
    """
    return [status for status in api.pages(f"/commits/{sha}/statuses")
            if status.get("context") in REQUIRED_CONTEXTS and (status.get("creator") or {}).get("login") == GATE_WRITER]


def stopped(history: list[dict[str, Any]], run_url: str) -> bool:
    """True when another run wrote a required check after this run's first status on the head.

    That write is a stop or a later admission, and it ends this run's claim for good: neither this run's own later
    writes nor a rerun of it can take the head back, so a stop is never undone by the run it stopped.
    """
    mine = [index for index, status in enumerate(history) if status.get("target_url") == run_url]
    return bool(mine) and any(status.get("target_url") != run_url for status in history[: max(mine)])


def owns(history: list[dict[str, Any]], run_url: str) -> bool:
    """True when this run wrote the newest status of each required check and nobody else wrote one since its first."""
    newest: dict[str, dict[str, Any]] = {}
    for status in history:
        newest.setdefault(status["context"], status)
    return all(newest.get(context, {}).get("target_url") == run_url for context in REQUIRED_CONTEXTS) and not stopped(history, run_url)


def owns_checks(api: GitHub, sha: str) -> bool:
    return owns(check_history(api, sha), api.run_url)


def run_id(api: GitHub, url: object) -> int | None:
    """The id of the run of this repository that a status URL names, or None for any other URL."""
    match = re.fullmatch(re.escape(f"https://github.com/{api.repo}/actions/runs/") + "([0-9]{1,20})", url if isinstance(url, str) else "")
    return None if match is None else int(match[1])


def superseded(api: GitHub, sha: str) -> bool:
    """True when a run newer than this one has written a required status for the head, so this event is an older decision.

    Run ids grow with the order events were created, so a higher id is a later decision. That is an assumption: queueing and
    delivery are not strictly ordered, and a rerun keeps its old id. A skipped decision is safe, because a newer run writing
    a status already ends the claim of every older run, and a maintainer can act again.
    """
    current = int(os.environ["GITHUB_RUN_ID"])
    newer = {owner for status in check_history(api, sha) if (owner := run_id(api, status.get("target_url"))) is not None and owner > current}
    if not newer:
        return False
    # Only a real run of this same workflow counts, so a status naming a made-up or unrelated run cannot skip a stop.
    workflow = api.request(f"/actions/runs/{current}")["workflow_id"]
    for owner in sorted(newer):
        try:
            if api.request(f"/actions/runs/{owner}").get("workflow_id") == workflow:
                return True
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    return False


def revoked(pr: dict[str, Any]) -> bool:
    """True when the live PR carries gate:revoke, which stays until a stop has completed."""
    return any((label or {}).get("name") == REVOKE_LABEL for label in pr.get("labels") or [])


def other_run_is_live(api: GitHub, found: dict[str, dict[str, Any]]) -> bool:
    """True when another run that has not completed wrote the newest status of any required context, in any state.

    A run holds its head from admission until it completes, including while finish has written one result and not
    the other, so a second admission cannot start beside it. Statuses of a completed or missing run, or with no run
    URL for this repository, are stale, as are this run's own (a rerun of the admission job).
    """
    owners = {owner for context in REQUIRED_CONTEXTS if (owner := run_id(api, found.get(context, {}).get("target_url"))) is not None}
    owners.discard(int(os.environ["GITHUB_RUN_ID"]))
    for owner in owners:
        try:
            if api.request(f"/actions/runs/{owner}")["status"] != "completed":
                return True
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    return False


def admit_head(api: GitHub, number: int, sha: str, live: dict[str, Any]) -> None:
    if stopped(check_history(api, sha), api.run_url):
        notice("A maintainer stopped this run for this head; mark the PR Ready or add gate:approve to admit it again")
        return
    if revoked(live):
        notice(REVOKE_PENDING)
        return
    found = api.statuses(sha)
    if all(found.get(context, {}).get("state") == "success" for context in REQUIRED_CONTEXTS):
        notice("This commit already passed its checks; push a new commit to run them again")
        return
    if other_run_is_live(api, found):
        notice("This commit is already admitted by a running workflow; gate:revoke stops it")
        return
    for context in REQUIRED_CONTEXTS:
        api.status(sha, context, "pending", "Admitted checks queued")
    outputs(run="true", pr=number, head=sha, base=checked_sha(live["base"]["sha"]), profile=api.repo.split("/")[1])


def require_live_head(api: GitHub, number: int, sha: str) -> dict[str, Any]:
    pr = api.request(f"/pulls/{number}")
    if not current_head(pr, sha):
        raise ValueError("PR head changed, PR is a draft or closed, or PR no longer targets main")
    if revoked(pr):
        raise ValueError("gate:revoke is on this PR")
    return pr


def rerun_allowed(api: GitHub) -> bool:
    """A rerun replays an old event, so whoever started the rerun must be a current human maintainer."""
    if os.environ.get("GITHUB_RUN_ATTEMPT", "1") == "1":
        return True
    actor = urllib.parse.quote(os.environ.get("GITHUB_TRIGGERING_ACTOR", ""), safe="")
    return bool(actor) and is_maintainer(api, api.request("https://api.github.com/users/" + actor))


def approve_head(api: GitHub, number: int, sha: str, live: dict[str, Any], sender: dict[str, Any]) -> None:
    if revoked(live):
        notice(REVOKE_PENDING)
        return
    # The approval is bound to the event head, which the live check in the caller just matched.
    api.request(f"/pulls/{number}/reviews", "POST", {
        "commit_id": sha, "event": "APPROVE",
        "body": f"Maintainer self-approve by @{sender['login']} via label `{APPROVE_LABEL}` for `{sha}`. Required checks still apply.",
    })
    admit_head(api, number, sha, live)


def handle_label(api: GitHub, event: dict[str, Any], number: int, sha: str) -> None:
    label = (event.get("label") or {}).get("name")
    if label not in GATE_LABELS:
        notice("Not a gate label; nothing to do")
        return
    sender = event.get("sender") or {}
    approve = label == APPROVE_LABEL
    if approve:
        remove_label(api, number, label)
    if not is_maintainer(api, sender):
        if not approve:
            remove_label(api, number, label)
        raise ValueError("Only a current human maintainer may apply gate labels")
    live = api.request(f"/pulls/{number}")
    if not current_head(live, sha):
        notice(STALE_HEAD)
    elif superseded(api, sha):
        notice(SUPERSEDED)
    elif approve:
        approve_head(api, number, sha, live, sender)
    else:
        stop(api, number, sha, "Revoked by a current human maintainer")
    if not approve:
        # gate:revoke stays on the PR until its stop has completed, so a stop that fails, or whose job never runs,
        # still blocks admission and finish. Every path that settles it, including a stale or superseded one, ends here.
        remove_label(api, number, label)


def handle_admission(api: GitHub, event: dict[str, Any], number: int, sha: str) -> None:
    action = event["action"]
    if action == "synchronize":
        cancel_superseded(api, event.get("before"))
    live = api.request(f"/pulls/{number}")
    if not current_head(live, sha):
        notice(STALE_HEAD)
        return
    # A maintainer's own PR admits itself on an event by a maintainer. Any other PR waits for a maintainer to mark it
    # Ready or add gate:approve. Nobody else's reopen, push or Ready admits a head.
    if not ((action == "ready_for_review" or is_maintainer(api, live.get("user") or {})) and is_maintainer(api, event.get("sender") or {})):
        notice("This PR is not admitted yet; a maintainer marks it Ready or adds gate:approve")
    elif superseded(api, sha):
        notice(SUPERSEDED)
    else:
        admit_head(api, number, sha, live)


def admit(api: GitHub, event: dict[str, Any]) -> None:
    outputs(run="false")
    pull = event.get("pull_request")
    action = event.get("action")
    if action not in ACTIONS or not isinstance(pull, dict):
        notice("Not a pull request admission event; nothing to do")
        return
    number, sha = pull["number"], checked_sha(pull["head"]["sha"])
    if not isinstance(number, int) or number <= 0:
        raise ValueError("Pull request event has no valid number")
    if not same_repository(pull):
        # A fork's token is read-only, so nothing could be written. A maintainer who reviewed the change pushes it to a branch here.
        notice("Pull requests from forks are not admitted; push the reviewed change to a branch in this repository")
        return
    if not rerun_allowed(api):
        notice("Only a current human maintainer can rerun an admission")
        return
    if action == "converted_to_draft":
        if superseded(api, sha):
            # A delayed draft event must not stop a head that a later Ready admitted again.
            notice(SUPERSEDED)
            return
        stop(api, number, sha, "PR converted to draft; mark Ready to admit again")
    elif action == "labeled":
        handle_label(api, event, number, sha)
    else:
        handle_admission(api, event, number, sha)


def pull_request_from_environment() -> tuple[int, str]:
    number = os.environ["PR_NUMBER"]
    if not re.fullmatch(r"[1-9][0-9]{0,9}", number):
        raise ValueError("Expected a pull request number")
    return int(number), checked_sha(os.environ["PR_HEAD"])


def verify(api: GitHub) -> None:
    number, sha = pull_request_from_environment()
    if not owns_checks(api, sha):
        raise ValueError("Another run now owns the checks for this head")
    require_live_head(api, number, sha)


def finish(api: GitHub) -> None:
    """Publish the results, checking ownership right before writing and the status history again right after.

    A stop by another run ends this run's ownership for good, so every ordering of finish and a stop ends in failure:
    before the check, finish writes nothing; in the gap, finish fails the checks it just wrote; after it, the stop's own
    write is the newest. A history that cannot be read after the write fails closed.
    """
    number, sha = pull_request_from_environment()
    try:
        require_live_head(api, number, sha)
        results = json.loads(os.environ["JOB_RESULTS"])
        quality = all(results.get(job, {}).get("result") == "success" for job in ("quality", "registry"))
        standards = results.get("standards", {}).get("result") == "success"
    except HANDLED:
        if owns_checks(api, sha):
            fail_checks(api, sha, "Admission could not be revalidated for this head")
            dismiss_bot_approvals(api, number, sha, "Admission no longer valid")
        raise
    if not owns_checks(api, sha):
        notice("Another run owns the checks for this head; nothing is published")
        return
    for context, ok in (("Quality", quality), ("Repository standards", standards)):
        api.status(sha, context, "success" if ok else "failure", "Passed for admitted commit" if ok else "Failed, cancelled, missing, or incomplete")
    try:
        after = check_history(api, sha)
    except HANDLED:
        # A result that cannot be confirmed fails closed. A stop stays in the history, so a rerun of this job cannot undo it.
        fail_checks(api, sha, "Could not confirm the result; rerun the failed job")
        raise
    if stopped(after, api.run_url):
        # A stop landed before this run's write. Fail only the checks whose newest status is this run's, so a later
        # writer's status stands.
        newest: dict[str, dict[str, Any]] = {}
        for status in after:
            newest.setdefault(status["context"], status)
        for context in REQUIRED_CONTEXTS:
            if newest.get(context, {}).get("target_url") == api.run_url:
                api.status(sha, context, "failure", "Stopped by a maintainer while results were published")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        api = GitHub()
        if mode == "admit":
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
            if not isinstance(event, dict):
                raise ValueError("Event payload is not an object")
            admit(api, event)
        elif mode == "verify":
            verify(api)
        elif mode == "finish":
            finish(api)
        else:
            raise ValueError("Unknown operation")
    except HANDLED as error:
        # Print only our own text and the error type, never a response body, label text or credential.
        print(f"Governance stopped: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
