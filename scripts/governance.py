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

REPOS = {"ejmlabs/" + name for name in (".github", "ejmlabs", "ejm-cli", "ejm-harness", "ejm-ide", "ejm-ui")}
REQUIRED_CONTEXTS = ("Quality", "Repository standards")
APPROVE_LABEL = "gate:approve"
REVOKE_LABEL = "gate:revoke"
GATE_LABELS = (APPROVE_LABEL, REVOKE_LABEL)
ACTIONS = ("opened", "reopened", "synchronize", "ready_for_review", "converted_to_draft", "labeled")
RETRY_DELAYS = (1, 2)
MAX_RESPONSE_BYTES = 8_000_000
FULL_SHA = re.compile(r"[0-9a-f]{40}")
NETWORK_ERRORS = (OSError, http.client.HTTPException)
# Failures a command reports as one clean line: bad input, an unexpected payload shape, or an API or network error.
HANDLED = (ValueError, KeyError, TypeError, *NETWORK_ERRORS)
STALE_HEAD = "The PR head changed, or the PR is closed, a draft, or no longer targets main; a newer event handles it"


def human(user: dict[str, Any], permission: str) -> bool:
    return bool(user.get("type") == "User" and permission in {"admin", "maintain"})


def same_repository(pr: dict[str, Any]) -> bool:
    head_repo = pr["head"].get("repo") or {}
    return bool(head_repo.get("full_name") == pr["base"]["repo"]["full_name"])


def current_head(pr: dict[str, Any], sha: str) -> bool:
    return bool(pr["state"] == "open" and not pr.get("draft") and pr["base"]["ref"] == "main" and pr["head"]["sha"] == sha)


class GitHub:
    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self.repo = os.environ["GITHUB_REPOSITORY"]
        if self.repo not in REPOS:
            raise ValueError("Repository has not adopted the ejmlabs policy")
        self.token = os.environ["GH_TOKEN"]
        self.root = "https://api.github.com/repos/" + self.repo
        self.sleep = sleep

    @property
    def run_url(self) -> str:
        return f"https://github.com/{self.repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    def request(self, path: str, method: str = "GET", data: dict[str, Any] | None = None, *, retry: bool | None = None) -> dict[str, Any]:
        """Call the API once, or up to three times on 429, 5xx and network errors when the call is safe to repeat.

        GET, PUT and DELETE repeat by default. A POST repeats only when the caller says it is idempotent (statuses, cancel),
        so a review is never posted twice.
        """
        url = path if path.startswith("https://api.github.com/") else self.root + path
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method=method, headers={  # noqa: S310 - url is always https://api.github.com/
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
        })
        last = len(RETRY_DELAYS) if (method != "POST" if retry is None else retry) else 0
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - url is always https://api.github.com/
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
            self.sleep(RETRY_DELAYS[attempt])
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
        }, retry=True)


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


def cancel_runs(api: GitHub, sha: str) -> None:
    """Cancel this workflow's queued and in-progress runs for a head, except this run and any newer one.

    A newer run is a later decision for the same head, for example Ready after a draft conversion. List errors surface;
    a run that finished or cannot be cancelled (409, 422) is fine.
    """
    current = int(os.environ["GITHUB_RUN_ID"])
    workflow = int(api.request(f"/actions/runs/{current}")["workflow_id"])
    for state in ("queued", "in_progress"):
        listing = api.request(f"/actions/workflows/{workflow}/runs?head_sha={sha}&status={state}&per_page=100")
        for item in listing["workflow_runs"]:
            if int(item["id"]) >= current:
                continue
            try:
                api.request(f"/actions/runs/{int(item['id'])}/cancel", "POST", retry=True)
            except urllib.error.HTTPError as error:
                if error.code not in (409, 422):
                    raise


def cancel_superseded(api: GitHub, before: object) -> None:
    """Cancel the runs of the head a push replaced. This saves runner time only: finish still checks ownership and the live head."""
    if not isinstance(before, str) or not FULL_SHA.fullmatch(before):
        notice("The event names no previous head, so no runs are cancelled")
        return
    try:
        cancel_runs(api, before)
    except NETWORK_ERRORS as error:
        # A read-only token (for example a Dependabot push) cannot cancel; the old run stops at its own ownership check.
        print(f"::warning::Could not cancel runs for the previous head: {type(error).__name__}")


def fail_checks(api: GitHub, sha: str, reason: str) -> None:
    for context in REQUIRED_CONTEXTS:
        api.status(sha, context, "failure", reason)


def stop(api: GitHub, number: int, sha: str, reason: str) -> None:
    """Authoritative stop: fail the checks, cancel runs, dismiss approvals, then fail the checks again as the last write.

    The last write goes out even when a step above fails, so a finish job that wrote success while this ran cannot win.
    """
    fail_checks(api, sha, reason)
    try:
        cancel_runs(api, sha)
        dismiss_bot_approvals(api, number, sha, reason)
    finally:
        fail_checks(api, sha, reason)


def check_history(api: GitHub, sha: str) -> list[dict[str, Any]]:
    """The required checks' statuses on a head, newest first, as GitHub lists them."""
    return [status for status in api.pages(f"/commits/{sha}/statuses") if status.get("context") in REQUIRED_CONTEXTS]


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


def other_run_is_live(api: GitHub, found: dict[str, dict[str, Any]]) -> bool:
    """True when another run that has not completed wrote the newest status of any required context, in any state.

    A run holds its head from admission until it completes, including while finish has written one result and not
    the other, so a second admission cannot start beside it. Statuses of a completed or missing run, or with no run
    URL for this repository, are stale, as are this run's own (a rerun of the admission job).
    """
    prefix = re.escape(f"https://github.com/{api.repo}/actions/runs/")
    owners = set()
    for context in REQUIRED_CONTEXTS:
        match = re.fullmatch(prefix + "([0-9]{1,20})", found.get(context, {}).get("target_url") or "")
        if match is not None:
            owners.add(int(match[1]))
    owners.discard(int(os.environ["GITHUB_RUN_ID"]))
    for owner in owners:
        try:
            if api.request(f"/actions/runs/{owner}")["status"] != "completed":
                return True
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    return False


def admit_head(api: GitHub, number: int, sha: str, base: str) -> None:
    if stopped(check_history(api, sha), api.run_url):
        notice("A maintainer stopped this run for this head; mark the PR Ready or add gate:approve to admit it again")
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
    outputs(run="true", pr=number, head=sha, base=checked_sha(base), profile=api.repo.split("/")[1])


def require_live_head(api: GitHub, number: int, sha: str) -> dict[str, Any]:
    pr = api.request(f"/pulls/{number}")
    if not current_head(pr, sha):
        raise ValueError("PR head changed, PR is a draft or closed, or PR no longer targets main")
    return pr


def rerun_allowed(api: GitHub) -> bool:
    """A rerun replays an old event, so whoever started the rerun must be a current human maintainer."""
    if os.environ.get("GITHUB_RUN_ATTEMPT", "1") == "1":
        return True
    actor = urllib.parse.quote(os.environ.get("GITHUB_TRIGGERING_ACTOR", ""), safe="")
    return bool(actor) and is_maintainer(api, api.request("https://api.github.com/users/" + actor))


def handle_label(api: GitHub, event: dict[str, Any], number: int, sha: str) -> None:
    label = (event.get("label") or {}).get("name")
    if label not in GATE_LABELS:
        notice("Not a gate label; nothing to do")
        return
    sender = event.get("sender") or {}
    remove_label(api, number, label)
    if not is_maintainer(api, sender):
        raise ValueError("Only a current human maintainer may apply gate labels")
    live = api.request(f"/pulls/{number}")
    if not current_head(live, sha):
        notice(STALE_HEAD)
        return
    if label == REVOKE_LABEL:
        stop(api, number, sha, "Revoked by a current human maintainer")
        return
    # The approval is bound to the event head, which the live check above just matched.
    api.request(f"/pulls/{number}/reviews", "POST", {
        "commit_id": sha, "event": "APPROVE",
        "body": f"Maintainer self-approve by @{sender['login']} via label `{APPROVE_LABEL}` for `{sha}`. Required checks still apply.",
    })
    admit_head(api, number, sha, live["base"]["sha"])


def handle_admission(api: GitHub, event: dict[str, Any], number: int, sha: str) -> None:
    action = event["action"]
    if action == "synchronize":
        cancel_superseded(api, event.get("before"))
    live = api.request(f"/pulls/{number}")
    if not current_head(live, sha):
        notice(STALE_HEAD)
        return
    # A maintainer's own PR admits itself. Any other PR waits for a maintainer to mark it Ready or add gate:approve.
    if is_maintainer(api, live.get("user") or {}) or (action == "ready_for_review" and is_maintainer(api, event.get("sender") or {})):
        admit_head(api, number, sha, live["base"]["sha"])
    else:
        notice("This PR is not admitted yet; a maintainer marks it Ready or adds gate:approve")


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
        live = api.request(f"/pulls/{number}")
        if live["state"] == "open" and not live.get("draft") and live["head"]["sha"] == sha:
            # A delayed draft event must not stop a head that a later Ready admitted again.
            notice("The PR is Ready again at this head, so this draft event is out of date; nothing to stop")
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
