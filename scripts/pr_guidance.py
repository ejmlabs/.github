#!/usr/bin/env python3
"""Render advisory next steps from live pull request metadata."""
import os
from typing import Any

from governance import REQUIRED_CONTEXTS, GitHub, checked_sha, same_repository

START = "<!-- ejm-next-action:start -->"
END = "<!-- ejm-next-action:end -->"


def render(pr: dict[str, Any], statuses: dict[str, dict[str, Any]]) -> str:
    sha = checked_sha(pr["head"]["sha"])
    states = [statuses.get(name, {}).get("state") for name in REQUIRED_CONTEXTS]
    if pr["state"] != "open":
        action = "This PR is merged." if pr.get("merged") else "This PR is closed."
    elif pr.get("draft"):
        action = "Finish the draft. A human maintainer can mark it Ready to admit checks."
    elif pr["base"]["ref"] != "main":
        action = "Merge the predecessor and retarget this PR to main."
    elif not same_repository(pr):
        action = "A maintainer must review the fork and push the change to a branch in this repository."
    elif any(label.get("name") == "gate:revoke" for label in pr.get("labels") or []):
        action = "The stop is pending. Wait for gate:revoke to be removed before requesting admission again."
    elif any(state in ("failure", "error") for state in states):
        action = ("Inspect the failed checks. Fix code failures in a new commit; a human maintainer can rerun a job once "
                  "for an infrastructure failure. To admit a stopped head again, a maintainer can add gate:approve, or convert it to draft and mark it Ready.")
    elif not all(state == "success" for state in states):
        action = ("Wait for Quality and Repository standards. If they have not started, a human maintainer can mark the PR "
                  "Ready after converting it to draft, or add gate:approve to admit this head.")
    else:
        action = ("Quality and Repository standards passed. Review the current head and obtain an approving review. "
                  "A human maintainer can add gate:approve to approve it. Check all other results, including CodeQL when configured, before merging.")
    return (f"{START}\n## Next action\n\n{action}\n\nCurrent head: `{sha}`. "
            f"This guidance is advisory; GitHub's live checks and review requirements remain authoritative.\n{END}")


def update_body(body: str | None, section: str) -> str:
    body = body or ""
    starts, ends = body.count(START), body.count(END)
    if starts == ends == 0:
        result = section + "\n\n" + body
    elif starts == ends == 1 and body.index(START) < body.index(END):
        result = body[:body.index(START)] + section + body[body.index(END) + len(END):]
    else:
        raise ValueError("Ambiguous guidance markers; preserve the description and repair the markers")
    if len(result.encode("utf-8")) > 60000:
        raise ValueError("PR description is too large to add guidance safely")
    return result


def refresh(api: GitHub, number: int) -> None:
    if number <= 0:
        raise ValueError("Invalid PR number")
    path = f"/pulls/{number}"
    for _ in range(3):
        pr = api.request(path)
        body = update_body(pr.get("body"), render(pr, api.statuses(checked_sha(pr["head"]["sha"]))))
        if body == (pr.get("body") or ""):
            return
        latest = api.request(path)
        if any(latest.get(key) != pr.get(key) for key in ("head", "base", "body", "state", "draft", "merged", "labels")):
            continue
        api.request(path, "PATCH", {"body": body})
        return
    raise ValueError("PR changed during guidance update; retry on the next gate event")


def main() -> None:
    refresh(GitHub(), int(os.environ["PR_NUMBER"]))


if __name__ == "__main__":
    main()
