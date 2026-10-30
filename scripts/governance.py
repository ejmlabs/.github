#!/usr/bin/env python3
"""Trusted admission and approval for ejmlabs repositories."""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

REPOS = {"ejmlabs/" + name for name in (".github", "ejmlabs", "ejm-cli", "ejm-harness", "ejm-ide", "ejm-ui")}
REQUIRED_CONTEXTS = ("Quality", "Repository standards")
APPROVE_LABEL = "gate:approve"
REVOKE_LABEL = "gate:revoke"
GATE_LABELS = (APPROVE_LABEL, REVOKE_LABEL)


def human(user: dict[str, Any], permission: str) -> bool:
    return bool(user.get("type") == "User" and permission in {"admin", "maintain"})


def same_repository(pr: dict[str, Any]) -> bool:
    head_repo = pr["head"].get("repo") or {}
    return bool(head_repo.get("full_name") == pr["base"]["repo"]["full_name"])


def current_head(pr: dict[str, Any], sha: str) -> bool:
    return bool(pr["state"] == "open" and not pr.get("draft") and pr["base"]["ref"] == "main" and pr["head"]["sha"] == sha)


def current_pr(pr: dict[str, Any], sha: str) -> bool:
    return current_head(pr, sha) and same_repository(pr)


class GitHub:
    def __init__(self) -> None:
        self.repo = os.environ["GITHUB_REPOSITORY"]
        if self.repo not in REPOS:
            raise ValueError("Repository has not adopted the ejmlabs policy")
        self.token = os.environ["GH_TOKEN"]
        self.root = "https://api.github.com/repos/" + self.repo

    def request(self, path: str, method: str = "GET", data: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path if path.startswith("https://api.github.com/") else self.root + path
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method=method, headers={  # noqa: S310 - url is always https://api.github.com/
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - url is always https://api.github.com/
            return cast("dict[str, Any]", json.loads(response.read() or "null"))

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
        role = self.request(f"/collaborators/{login}/permission")
        return cast("str", role.get("role_name", role["permission"]))

    def statuses(self, sha: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for status in self.pages(f"/commits/{sha}/statuses"):
            result.setdefault(status["context"], status)
        return result

    def status(self, sha: str, context: str, state: str, description: str) -> None:
        self.request(f"/statuses/{sha}", "POST", {
            "context": context, "state": state, "description": description[:140],
            "target_url": f"https://github.com/{self.repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
        })


def outputs(**items: str | int) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as out:
        out.writelines(f"{key}={value}\n" for key, value in items.items())


def first_attempt() -> None:
    if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        raise ValueError("Workflow reruns cannot replay admission; convert to draft and Ready again, or push a new commit")


def author_login(pr: dict[str, Any]) -> str:
    return cast("str", (pr.get("user") or {}).get("login") or "")


def is_maintainer(api: GitHub, user: dict[str, Any]) -> bool:
    login = user.get("login") or ""
    return human(user, api.permission(login))


def dismiss_bot_approvals(api: GitHub, number: int | str, sha: str, reason: str) -> None:
    for review in api.pages(f"/pulls/{number}/reviews"):
        if review["user"]["login"] == "github-actions[bot]" and review["state"] == "APPROVED" and review["commit_id"] == sha:
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


def cancel_runs_for_head(api: GitHub, sha: str) -> None:
    """Cancel in-progress gate runs for this head using the Actions API."""
    path = f"/actions/runs?status=in_progress&per_page=20&head_sha={sha}"
    try:
        payload = api.request(path)
    except urllib.error.HTTPError:
        return
    for run in payload.get("workflow_runs") or []:
        if str(run.get("id")) == os.environ["GITHUB_RUN_ID"]:
            continue
        try:
            api.request(f"/actions/runs/{run['id']}/cancel", "POST")
        except urllib.error.HTTPError as error:
            if error.code not in (409, 422):
                raise


def queue_checks(api: GitHub, sha: str) -> None:
    for context in REQUIRED_CONTEXTS:
        api.status(sha, context, "pending", "Admitted checks queued")


def publish_admission(api: GitHub, pr: dict[str, Any], number: int, sha: str) -> None:
    if pr["changed_files"] > 200 or pr["additions"] + pr["deletions"] > 12000:
        raise ValueError("PR exceeds review limits; split it before admission")
    pending = all(api.statuses(sha).get(context, {}).get("state") == "pending" for context in REQUIRED_CONTEXTS)
    success = all(api.statuses(sha).get(context, {}).get("state") == "success" for context in REQUIRED_CONTEXTS)
    if pending or success:
        # Already admitted or finished for this head in a live run; do not start a duplicate.
        if pending:
            raise ValueError("This commit is already admitted; revoke or wait for the current run")
        raise ValueError("This commit already has successful checks; push a new commit to re-run")
    queue_checks(api, sha)
    outputs(run="true", pr=number, head=sha, base=pr["base"]["sha"], admission=os.environ["GITHUB_RUN_ID"],
            profile=api.repo.split("/")[1])


def require_live_head(api: GitHub, number: int | str, sha: str) -> dict[str, Any]:
    pr = api.request(f"/pulls/{number}")
    if not current_head(pr, sha):
        raise ValueError("PR head changed, PR is a draft, or PR no longer targets main")
    return pr


def live_ready(api: GitHub, number: int | str, sha: str, admission: str) -> dict[str, Any]:
    """Re-validate the admitted head from the Pull Request API and job outputs."""
    first_attempt()
    if not admission or admission != os.environ["GITHUB_RUN_ID"]:
        # finish/verify run in the same workflow as admission; the output must be this run.
        raise ValueError("Admission output does not match this workflow run")
    return require_live_head(api, number, sha)


def handle_label(api: GitHub, event: dict[str, Any]) -> None:
    label = (event.get("label") or {}).get("name")
    if label not in GATE_LABELS:
        return
    pr_meta = event.get("pull_request") or {}
    number = int(pr_meta.get("number") or event.get("number") or 0)
    if number <= 0:
        return
    pr = api.request(f"/pulls/{number}")
    sha = pr["head"]["sha"]
    sender = event.get("sender") or {}
    remove_label(api, number, label)
    if not is_maintainer(api, sender):
        raise ValueError("Only a current human maintainer may apply gate labels")
    if not current_head(pr, sha):
        raise ValueError("Gate labels require the current non-draft PR head targeting main")
    if label == REVOKE_LABEL:
        dismiss_bot_approvals(api, number, sha, "Revoked by a current human maintainer")
        cancel_runs_for_head(api, sha)
        for context in REQUIRED_CONTEXTS:
            api.status(sha, context, "failure", "Revoked by a current human maintainer")
        return
    # Record a bot approval for the current head.
    api.request(f"/pulls/{number}/reviews", "POST", {
        "commit_id": sha, "event": "APPROVE",
        "body": f"Maintainer self-approve by @{sender.get('login')} via label `{APPROVE_LABEL}` for `{sha}`. Required checks still apply.",
    })


def handle_pull_request(api: GitHub, event: dict[str, Any]) -> None:
    action = event.get("action")
    number = int((event.get("pull_request") or {}).get("number") or event.get("number") or 0)
    if number <= 0:
        return
    live = api.request(f"/pulls/{number}")
    sha = live["head"]["sha"]
    sender = event.get("sender") or {}
    if action == "converted_to_draft":
        dismiss_bot_approvals(api, number, sha, "PR converted to draft")
        cancel_runs_for_head(api, sha)
        for context in REQUIRED_CONTEXTS:
            if api.statuses(sha).get(context, {}).get("state") == "pending":
                api.status(sha, context, "failure", "PR converted to draft; mark Ready to admit again")
        return
    if action == "labeled":
        handle_label(api, event)
        return
    if action not in {"opened", "reopened", "synchronize", "ready_for_review"}:
        return
    if live.get("draft"):
        return
    if not current_head(live, sha):
        return
    author = {"type": "User", "login": author_login(live)}
    maintainer_author = same_repository(live) and is_maintainer(api, author)
    maintainer_actor = is_maintainer(api, sender)
    if maintainer_author:
        publish_admission(api, live, number, sha)
        return
    if action == "ready_for_review" and maintainer_actor:
        publish_admission(api, live, number, sha)
        return


def admit(api: GitHub, event: dict[str, Any]) -> None:
    outputs(run="false")
    first_attempt()
    handle_pull_request(api, event)


def finish(api: GitHub) -> None:
    first_attempt()
    number, sha, admission = os.environ["PR_NUMBER"], os.environ["PR_HEAD"], os.environ["ADMISSION_ID"]
    try:
        live_ready(api, number, sha, admission)
    except (ValueError, KeyError, urllib.error.URLError):
        for context in REQUIRED_CONTEXTS:
            api.status(sha, context, "failure", "Admission no longer valid for this head")
        dismiss_bot_approvals(api, number, sha, "Admission no longer valid")
        raise
    results = json.loads(os.environ["JOB_RESULTS"])
    quality = all(results.get(job, {}).get("result") == "success" for job in ("quality", "registry"))
    standards = results.get("standards", {}).get("result") == "success"
    for context, ok in (("Quality", quality), ("Repository standards", standards)):
        api.status(sha, context, "success" if ok else "failure", "Passed for admitted commit" if ok else "Failed, cancelled, missing, or incomplete")


def main() -> None:
    api = GitHub()
    mode = sys.argv[1]
    if mode == "admit":
        admit(api, json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()))
    elif mode == "verify":
        live_ready(api, os.environ["PR_NUMBER"], os.environ["PR_HEAD"], os.environ["ADMISSION_ID"])
    elif mode == "finish":
        finish(api)
    else:
        raise ValueError("Unknown operation")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, urllib.error.URLError) as error:
        # Do not print untrusted response bodies, label text beyond names we compare, or credentials.
        print(f"Governance stopped: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
