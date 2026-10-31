#!/usr/bin/env python3
"""Apply the repository controls through authenticated gh, or read them back with --check."""
import argparse
import base64
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import standards

OWNER = "ejmlabs"
NAMES = (".github", "ejmlabs", "ejm-cli", "ejm-harness", "ejm-ide")
SUPPORTED_NAMES = (*NAMES, "ejm-ui", "ejm-calm")
CONTEXTS = ("Quality", "Repository standards")
# GitHub Actions. Pinning the required checks to it keeps another app from publishing them.
ACTIONS_APP_ID = 15368
GATE_LABELS = (
    {"name": "gate:approve", "color": "0E8A16", "description": "Maintainer approval that also admits the current head"},
    {"name": "gate:revoke", "color": "B60205", "description": "Stop the current head: fail checks, cancel runs, dismiss bot approvals"},
)
ALLOWED_ACTIONS = {"github_owned_allowed": False, "verified_allowed": False,
                   "patterns_allowed": ["actions/*@*", "astral-sh/setup-uv@*", "ejmlabs/.github/*@*"]}
# Settings for runs from fork pull requests, which only private repositories expose.
FORK_RUNS = {"run_workflows_from_fork_pull_requests": False, "send_write_tokens_to_workflows": False,
             "send_secrets_and_variables": False, "require_approval_for_fork_pr_workflows": True}
FORK_APPROVAL = "all_external_contributors"
TAG_RULESET = {"name": "Immutable semantic version tags", "target": "tag", "enforcement": "active", "bypass_actors": [],
               "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
               "rules": [{"type": "update"}, {"type": "deletion"}]}
ENVIRONMENTS = ("staging", "production")
# Only main may deploy. A reviewer is optional: this tool keeps one a human added and never sets one.
ENVIRONMENT_POLICY = {"protected_branches": False, "custom_branch_policies": True}
DEPLOY_BRANCH = {"name": "main", "type": "branch"}
MAX_WORKFLOW_FILES = 50
MAX_WORKFLOW_BYTES = 1_000_000
FULL_SHA = re.compile(r"[0-9a-f]{40}")
PIN = re.compile(r"^    uses: ejmlabs/\.github/\.github/workflows/governance\.yml@([0-9a-f]{40})$", re.MULTILINE)
WORKFLOW_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


class ApiError(RuntimeError):
    """A failed gh api call. status is the HTTP status gh reported, if any."""

    def __init__(self, path: str, stderr: str) -> None:
        super().__init__(path + ": " + stderr)
        match = re.search(r"\(HTTP (\d{3})\)", stderr)
        self.status = int(match[1]) if match else None


def api(path: str, method: str = "GET", body: dict[str, Any] | None = None, *, optional: bool = False) -> Any:  # noqa: ANN401 - the decoded GitHub response has no fixed shape
    args = ["gh", "api", "--method", method, path]
    if body is not None:
        args += ["--input", "-"]
    try:
        result = subprocess.run(args, input=None if body is None else json.dumps(body), capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ApiError(path, "cannot run gh: " + type(error).__name__) from error
    if result.returncode:
        if optional:
            return {"unavailable": result.stderr.strip()}
        raise ApiError(path, result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else {"applied": True}


def unavailable(value: Any) -> bool:  # noqa: ANN401 - any api() result
    """True for the placeholder that api(..., optional=True) returns on failure. It is truthy, so never test it as a flag."""
    return isinstance(value, dict) and set(value) == {"unavailable"}


def find(path: str) -> Any:  # noqa: ANN401 - the decoded GitHub response has no fixed shape
    """GET a path that may not exist: None for 404, an error for anything else."""
    try:
        return api(path)
    except ApiError as error:
        if error.status == 404:
            return None
        raise


def pages(path: str, *, limit: int = 10) -> list[Any]:
    """Read a list endpoint 100 entries at a time and fail rather than miss entries past the limit."""
    joiner = "&" if "?" in path else "?"
    items: list[Any] = []
    for page in range(1, limit + 1):
        batch = api(f"{path}{joiner}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise ValueError(path + ": expected a list")  # noqa: TRY004 - callers expect ValueError for every unreadable response
        items.extend(batch)
        if len(batch) < 100:
            return items
    raise ValueError(f"{path}: more than {limit * 100} entries exceeds the inspection limit")


def dig(value: Any, *keys: str) -> Any:  # noqa: ANN401 - walks decoded GitHub JSON of any shape
    """Follow keys through nested objects; None when any step is missing or not an object."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def collaborators(name: str) -> list[dict[str, Any]]:
    """Only human maintainers may write workflows or publish Actions statuses."""
    people = pages(f"repos/{OWNER}/{name}/collaborators")
    unsafe = [person["login"] for person in people
              if person.get("permissions", {}).get("push")
              and (person.get("type") != "User" or person.get("role_name") not in ("maintain", "admin"))]
    if unsafe:
        raise ValueError(name + ": workflow writers must be human maintainers: " + ", ".join(unsafe))
    return [{"login": person["login"], "type": person["type"], "role": person["role_name"]} for person in people]


@dataclass
class Findings:
    """What a read-only check found for one repository."""

    failures: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)

    def expect(self, message: str, *, ok: bool) -> None:
        if not ok:
            self.failures.append(message)

    def expect_value(self, label: str, actual: Any, wanted: Any) -> None:  # noqa: ANN401 - compares decoded GitHub values
        if comparable(actual) != comparable(wanted):
            self.failures.append(f"{label}: expected {wanted!r}, found {actual!r}")


def comparable(value: Any) -> Any:  # noqa: ANN401 - compares decoded GitHub values
    """Lists compare without order, because GitHub does not promise one."""
    return sorted(value, key=str) if isinstance(value, list) else value


@contextmanager
def main_workflows(name: str) -> Iterator[tuple[Path, str]]:
    """Copy the workflow files of main's current commit to <tmp>/.github/workflows and yield (tmp, commit).

    Only regular files within the size bounds are copied; a link, directory or submodule is an error.
    """
    root = f"repos/{OWNER}/{name}"
    commit = dig(api(f"{root}/branches/main"), "commit", "sha")
    if not isinstance(commit, str) or not FULL_SHA.fullmatch(commit):
        raise ValueError(name + ": cannot resolve the main commit")
    directory = f"{root}/contents/.github/workflows"
    entries = api(f"{directory}?ref={commit}")
    if not isinstance(entries, list) or len(entries) > MAX_WORKFLOW_FILES:
        raise ValueError(f"{name}: .github/workflows must be a directory of at most {MAX_WORKFLOW_FILES} files")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp, ".github/workflows")
        target.mkdir(parents=True)
        for entry in entries:
            fetch_workflow(name, directory, commit, entry, target)
        yield Path(tmp), commit


def fetch_workflow(name: str, directory: str, commit: str, entry: Any, target: Path) -> None:  # noqa: ANN401 - one untrusted directory entry
    filename = dig(entry, "name")
    if not isinstance(filename, str) or not WORKFLOW_FILE.fullmatch(filename):
        raise ValueError(name + ": unsafe workflow file name")
    # A symlink, directory or submodule is not a workflow file.
    if dig(entry, "type") != "file":
        raise ValueError(f"{name}: {filename} is not a regular file")
    size = dig(entry, "size")
    if not isinstance(size, int) or size > MAX_WORKFLOW_BYTES:
        raise ValueError(f"{name}: {filename} exceeds {MAX_WORKFLOW_BYTES} bytes")
    remote = api(f"{directory}/{filename}?ref={commit}")
    content = dig(remote, "content")
    # Fetching a symlink can return its target's file, whose blob id differs from the listed entry.
    if dig(remote, "type") != "file" or dig(remote, "encoding") != "base64" or dig(remote, "sha") != dig(entry, "sha") or not isinstance(content, str):
        raise ValueError(f"{name}: cannot read {filename} as the committed file")
    data = base64.b64decode(content)
    if len(data) != size:
        raise ValueError(f"{name}: {filename} differs from its listed size")
    (target / filename).write_bytes(data)


def reviewed(pin: str) -> bool:
    """A pin is reviewed when it is on ejmlabs/.github main or is the commit a workflow-pins ref retains."""
    try:
        comparison = api(f"repos/{OWNER}/.github/compare/{pin}...main?per_page=1")
    except ApiError as error:
        # GitHub answers 404 or 422 for a commit it does not know on this repository.
        if error.status not in (404, 422):
            raise
    else:
        if dig(comparison, "status") in ("ahead", "identical"):
            return True
    refs = pages(f"repos/{OWNER}/.github/git/matching-refs/heads/workflow-pins/")
    return any(dig(ref, "object", "sha") == pin for ref in refs)


def check_installed(name: str, expected_pin: str | None, found: Findings) -> None:
    """Main must hold only the approved callers, pinned to a reviewed shared revision."""
    try:
        with main_workflows(name) as (tree, commit):
            found.facts["commit"] = commit
            try:
                standards.workflows(tree, name)
            except ValueError as error:
                found.failures.append(f"workflows on main: {error}")
            pr = tree / ".github/workflows/pr.yml"
            match = PIN.search(pr.read_text(encoding="utf-8", errors="replace")) if pr.is_file() else None
    except (ValueError, RuntimeError) as error:
        found.failures.append(f"workflows on main: {error}")
        return
    if match is None:
        found.failures.append("governance pin: pr.yml does not pin governance.yml to a full commit SHA")
        return
    pin = match[1]
    found.facts["pin"] = pin
    found.expect(f"governance pin {pin} is not the expected {expected_pin}", ok=expected_pin in (None, pin))
    try:
        on_main_or_retained = reviewed(pin)
    except (ValueError, RuntimeError) as error:
        found.failures.append(f"governance pin {pin}: {error}")
        return
    found.expect(f"governance pin {pin} is neither on {OWNER}/.github main nor a workflow-pins ref", ok=on_main_or_retained)


def require_installed(name: str, expected_pin: str | None) -> None:
    """Never enable Actions until reviewed callers are installed on main."""
    found = Findings()
    check_installed(name, expected_pin, found)
    if found.failures:
        raise ValueError(name + ": " + "; ".join(found.failures))


def deploys_site(name: str) -> bool:
    """Only a site repository that has deploy.yml on main uses the staging and production environments."""
    if name not in standards.SITE_DEPLOY:
        return False
    entries = find(f"repos/{OWNER}/{name}/contents/.github/workflows?ref=main")
    return isinstance(entries, list) and any(dig(entry, "name") == "deploy.yml" and dig(entry, "type") == "file" for entry in entries)


def branch_policies(path: str) -> list[dict[str, Any]]:
    """The deployment branch policies of one environment path."""
    listing = find(f"{path}/deployment-branch-policies?per_page=100")
    entries = dig(listing, "branch_policies")
    if listing is not None and (not isinstance(entries, list) or dig(listing, "total_count") != len(entries)):
        raise ValueError(path + ": cannot read every deployment branch policy")
    return entries or []


def read_environment(root: str, environment: str) -> dict[str, Any] | None:
    """What the check asserts about one environment, or None when it does not exist."""
    path = f"{root}/environments/{environment}"
    found = find(path)
    if found is None:
        return None
    return {"deployment_branch_policy": dig(found, "deployment_branch_policy"),
            "branch_policies": sorted(({"name": dig(policy, "name"), "type": dig(policy, "type")} for policy in branch_policies(path)), key=str)}


def reviewer_reference(entry: Any) -> dict[str, Any]:  # noqa: ANN401 - one decoded reviewer
    kind, identifier = dig(entry, "type"), dig(entry, "reviewer", "id")
    if kind not in ("User", "Team") or not isinstance(identifier, int):
        raise ValueError("Cannot carry an existing environment reviewer over safely")
    return {"type": kind, "id": identifier}


def environment_body(existing: Any) -> dict[str, Any]:  # noqa: ANN401 - one decoded environment or None
    """The branch policy plus whatever a human already set. A PUT may drop protection rules it omits."""
    body: dict[str, Any] = {"deployment_branch_policy": dict(ENVIRONMENT_POLICY)}
    rules = dig(existing, "protection_rules")
    for rule in rules if isinstance(rules, list) else []:
        if dig(rule, "type") == "wait_timer" and isinstance(dig(rule, "wait_timer"), int):
            body["wait_timer"] = dig(rule, "wait_timer")
        if dig(rule, "type") == "required_reviewers":
            body["prevent_self_review"] = dig(rule, "prevent_self_review") is True
            body["reviewers"] = [reviewer_reference(entry) for entry in dig(rule, "reviewers") or []]
    return body


def configure_environment(root: str, environment: str) -> dict[str, Any]:
    """Allow deploys from exactly one branch, main. Any other policy goes first, so no other branch is ever allowed."""
    path = f"{root}/environments/{environment}"
    api(path, "PUT", environment_body(find(path)))
    keep = False
    for policy in branch_policies(path):
        identifier = dig(policy, "id")
        if not keep and dig(policy, "name") == DEPLOY_BRANCH["name"] and dig(policy, "type") == DEPLOY_BRANCH["type"]:
            keep = True
        elif isinstance(identifier, int):
            api(f"{path}/deployment-branch-policies/{identifier}", "DELETE")
        else:
            raise ValueError(path + ": deployment branch policy without an id")
    if not keep:
        api(f"{path}/deployment-branch-policies", "POST", DEPLOY_BRANCH)
    state = read_environment(root, environment)
    if state is None:
        raise RuntimeError(path + ": missing after it was configured")
    return state


def configure(name: str, *, protect: bool, hold: bool, expected_pin: str | None = None) -> dict[str, Any]:
    root = f"repos/{OWNER}/{name}"
    if not hold:
        require_installed(name, expected_pin)
    api(root, "PATCH", {"allow_squash_merge": True, "allow_merge_commit": False, "allow_rebase_merge": False,
                        "delete_branch_on_merge": True, "allow_auto_merge": True, "has_issues": True,
                        "has_wiki": False, "squash_merge_commit_title": "PR_TITLE", "squash_merge_commit_message": "PR_BODY"})
    if hold:
        # GitHub rejects allowed_actions when enabled is false. Do not enable old workflows.
        api(root + "/actions/permissions", "PUT", {"enabled": False})
    else:
        api(root + "/actions/permissions", "PUT", {"enabled": True, "allowed_actions": "selected", "sha_pinning_required": True})
        api(root + "/actions/permissions/selected-actions", "PUT", ALLOWED_ACTIONS)
    workflow_update = api(root + "/actions/permissions/workflow", "PUT", {
        "default_workflow_permissions": "read", "can_approve_pull_request_reviews": True,
    }, optional=hold)
    api(root + "/actions/permissions/fork-pr-workflows-private-repos", "PUT", FORK_RUNS, optional=True)
    api(root + "/vulnerability-alerts", "PUT")
    api(root + "/automated-security-fixes", "PUT", optional=True)
    api(root + "/immutable-releases", "PUT", optional=True)
    # These APIs are public-only or depend on installed security products. No paid enrollment.
    reporting = api(root + "/private-vulnerability-reporting", "PUT", optional=True)
    external = api(root + "/actions/permissions/fork-pr-contributor-approval", "PUT", {"approval_policy": FORK_APPROVAL}, optional=True)
    if protect:
        api(root + "/branches/main/protection", "PUT", {
            "required_status_checks": {"strict": True, "checks": [{"context": context, "app_id": ACTIONS_APP_ID} for context in CONTEXTS]},
            "enforce_admins": True,
            "required_pull_request_reviews": {"dismiss_stale_reviews": True, "require_code_owner_reviews": False,
                                              "required_approving_review_count": 1, "require_last_push_approval": False},
            "restrictions": None, "required_linear_history": True, "allow_force_pushes": False,
            "allow_deletions": False, "block_creations": False, "required_conversation_resolution": True,
            "lock_branch": False, "allow_fork_syncing": False,
        })
        rules = pages(root + "/rulesets?includes_parents=false")
        existing = next((rule for rule in rules if rule["name"] == TAG_RULESET["name"]), None)
        api(root + "/rulesets" + ("/" + str(existing["id"]) if existing else ""), "PUT" if existing else "POST", TAG_RULESET)
    for label in GATE_LABELS:
        encoded = urllib.parse.quote(label["name"], safe="")
        # api(optional=True) returns a truthy placeholder on failure, so only find() may decide whether the label exists.
        if find(root + "/labels/" + encoded) is None:
            api(root + "/labels", "POST", label)
        else:
            api(root + "/labels/" + encoded, "PATCH", {"new_name": label["name"], "color": label["color"], "description": label["description"]})
    result: dict[str, Any] = {"repository": f"{OWNER}/{name}",
                              "workflow_update": workflow_update,
                              "actions": api(root + "/actions/permissions"), "workflow": api(root + "/actions/permissions/workflow"),
                              "allowed_actions": api(root + "/actions/permissions/selected-actions", optional=hold), "fork": api(root + "/actions/permissions/fork-pr-workflows-private-repos", optional=True),
                              "dependency_alerts": api(root + "/vulnerability-alerts"), "security_updates": api(root + "/automated-security-fixes", optional=True),
                              "immutable_releases": api(root + "/immutable-releases", optional=True),
                              "private_reporting": reporting, "external_approval": external,
                              "metadata": api(root), "rulesets": api(root + "/rulesets")}
    if protect:
        result["main_protection"] = api(root + "/branches/main/protection")
    if deploys_site(name):
        result["environments"] = {environment: configure_environment(root, environment) for environment in ENVIRONMENTS}
    result["unavailable"] = sorted(key for key, value in result.items() if unavailable(value))
    return result


def check_settings(name: str, found: Findings) -> None:
    repository = api(f"repos/{OWNER}/{name}")
    for key, wanted in (("allow_squash_merge", True), ("allow_merge_commit", False), ("allow_rebase_merge", False),
                        ("allow_auto_merge", True), ("delete_branch_on_merge", True)):
        found.expect_value("repository " + key, dig(repository, key), wanted)


def check_protection(name: str, found: Findings) -> None:
    protection = api(f"repos/{OWNER}/{name}/branches/main/protection")
    checks = dig(protection, "required_status_checks", "checks")
    pairs = [(dig(check, "context"), dig(check, "app_id")) for check in checks] if isinstance(checks, list) else []
    found.expect(f"main protection: required checks must be exactly {' and '.join(CONTEXTS)} from GitHub Actions (app {ACTIONS_APP_ID}), found {pairs!r}",
                 ok=len(pairs) == len(CONTEXTS) and set(pairs) == {(context, ACTIONS_APP_ID) for context in CONTEXTS})
    for label, keys, wanted in (
        ("strict required checks", ("required_status_checks", "strict"), True),
        ("enforce_admins", ("enforce_admins", "enabled"), True),
        ("approving review count", ("required_pull_request_reviews", "required_approving_review_count"), 1),
        ("stale review dismissal", ("required_pull_request_reviews", "dismiss_stale_reviews"), True),
        ("linear history", ("required_linear_history", "enabled"), True),
        ("conversation resolution", ("required_conversation_resolution", "enabled"), True),
        ("force pushes allowed", ("allow_force_pushes", "enabled"), False),
        ("deletions allowed", ("allow_deletions", "enabled"), False),
    ):
        found.expect_value("main protection " + label, dig(protection, *keys), wanted)


def check_tag_ruleset(name: str, found: Findings) -> None:
    root = f"repos/{OWNER}/{name}"
    summary = next((rule for rule in pages(root + "/rulesets?includes_parents=false") if dig(rule, "name") == TAG_RULESET["name"]), None)
    identifier = dig(summary, "id")
    if not isinstance(identifier, int):
        found.failures.append(f"ruleset {TAG_RULESET['name']} is missing")
        return
    ruleset = api(f"{root}/rulesets/{identifier}")
    rules = dig(ruleset, "rules")
    for label, actual, wanted in (
        ("target", dig(ruleset, "target"), TAG_RULESET["target"]),
        ("enforcement", dig(ruleset, "enforcement"), TAG_RULESET["enforcement"]),
        ("bypass actors", dig(ruleset, "bypass_actors"), []),
        ("included refs", dig(ruleset, "conditions", "ref_name", "include"), dig(TAG_RULESET, "conditions", "ref_name", "include")),
        ("excluded refs", dig(ruleset, "conditions", "ref_name", "exclude"), []),
        ("rules", [dig(rule, "type") for rule in rules] if isinstance(rules, list) else rules, ["update", "deletion"]),
    ):
        found.expect_value("immutable tag ruleset " + label, actual, wanted)


def check_actions(name: str, found: Findings) -> None:
    actions = api(f"repos/{OWNER}/{name}/actions/permissions")
    for key, wanted in (("enabled", True), ("allowed_actions", "selected"), ("sha_pinning_required", True)):
        found.expect_value("actions " + key, dig(actions, key), wanted)


def check_allowlist(name: str, found: Findings) -> None:
    allowed = api(f"repos/{OWNER}/{name}/actions/permissions/selected-actions")
    for key, wanted in ALLOWED_ACTIONS.items():
        found.expect_value("actions allowlist " + key, dig(allowed, key), wanted)


def check_workflow_permissions(name: str, found: Findings) -> None:
    permissions = api(f"repos/{OWNER}/{name}/actions/permissions/workflow")
    found.expect_value("default workflow permissions", dig(permissions, "default_workflow_permissions"), "read")
    found.expect_value("workflows may approve pull requests", dig(permissions, "can_approve_pull_request_reviews"), True)


def check_fork_policy(name: str, found: Findings) -> None:
    """The fork settings exist only for some repositories. Assert what can be read and list what cannot."""
    root = f"repos/{OWNER}/{name}/actions/permissions/"
    runs = api(root + "fork-pr-workflows-private-repos", optional=True)
    approval = api(root + "fork-pr-contributor-approval", optional=True)
    for label, value in (("fork-pr-workflows-private-repos", runs), ("fork-pr-contributor-approval", approval)):
        if unavailable(value):
            found.unreadable.append(f"{label}: {value['unavailable']}")
    if not unavailable(runs):
        for key, wanted in FORK_RUNS.items():
            found.expect_value("fork pull request runs " + key, dig(runs, key), wanted)
    if not unavailable(approval):
        found.expect_value("fork pull request approval policy", dig(approval, "approval_policy"), FORK_APPROVAL)


def check_labels(name: str, found: Findings) -> None:
    for label in GATE_LABELS:
        found.expect(f"gate label {label['name']} is missing",
                     ok=find(f"repos/{OWNER}/{name}/labels/{urllib.parse.quote(label['name'], safe='')}") is not None)


def check_environments(name: str, found: Findings) -> None:
    if not deploys_site(name):
        found.facts["environments"] = "not applicable: no deploy.yml on main"
        return
    found.facts["environments"] = "checked"
    for environment in ENVIRONMENTS:
        state = read_environment(f"repos/{OWNER}/{name}", environment)
        if state is None:
            found.failures.append(f"environment {environment} is missing")
            continue
        found.expect_value(f"environment {environment} deployment branch policy", state["deployment_branch_policy"], ENVIRONMENT_POLICY)
        found.expect_value(f"environment {environment} branch policies", state["branch_policies"], [DEPLOY_BRANCH])


def check_access(name: str, found: Findings) -> None:
    try:
        collaborators(name)
    except ValueError as error:
        found.failures.append(str(error))


def check_repository(name: str, expected_pin: str | None = None) -> dict[str, Any]:
    """Read every control for one repository. Nothing here writes."""
    found = Findings()
    sections: tuple[Callable[[str, Findings], None], ...] = (
        check_settings, check_protection, check_tag_ruleset, check_actions, check_allowlist, check_workflow_permissions,
        check_fork_policy, check_labels, check_environments, check_access)
    for section in sections:
        try:
            section(name, found)
        except (RuntimeError, ValueError) as error:
            found.failures.append(f"{section.__name__}: {error}")
    check_installed(name, expected_pin, found)
    return {"ok": not found.failures, "failures": found.failures, "unreadable": found.unreadable, **found.facts}


def check_all(names: Sequence[str], expected_pin: str | None = None) -> dict[str, Any]:
    repositories = {name: check_repository(name, expected_pin) for name in names}
    return {"mode": "check", "ok": all(report["ok"] for report in repositories.values()), "repositories": repositories}


def apply(names: Sequence[str], *, protect: bool, hold: bool, expected_pin: str | None = None) -> None:
    # Audit the entire requested scope before any mutation. configure() checks again right before
    # it enables Actions, because main can change while earlier repositories are being configured.
    access = {name: collaborators(name) for name in names}
    if not hold:
        for name in names:
            require_installed(name, expected_pin)
    for name in names:
        result = configure(name, protect=protect, hold=hold, expected_pin=expected_pin)
        result["collaborators"] = access[name]
        print(json.dumps(result), flush=True)


def revision(value: str) -> str:
    if not FULL_SHA.fullmatch(value):
        raise argparse.ArgumentTypeError("must be a full lowercase commit SHA")
    return value


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Change nothing; print a JSON report and exit 1 if any control is wrong")
    parser.add_argument("--protect-main", action="store_true", help="Only after trusted callers are installed on main")
    parser.add_argument("--hold-actions", action="store_true", help="Disable automatic workflows during bootstrap")
    parser.add_argument("--standards-revision", type=revision, help="Also require every governance pin on main to be exactly this full SHA")
    parser.add_argument("--repository", choices=SUPPORTED_NAMES, action="append")
    args = parser.parse_args(argv)
    if args.check and (args.protect_main or args.hold_actions):
        parser.error("--check only reads; do not combine it with --protect-main or --hold-actions")
    names = list(dict.fromkeys(args.repository or NAMES))
    try:
        if args.check:
            report = check_all(names, args.standards_revision)
            print(json.dumps(report, indent=2), flush=True)
            for name, repository in report["repositories"].items():
                for failure in repository["failures"]:
                    print(f"FAIL {name}: {failure}", file=sys.stderr)
                for setting in repository["unreadable"]:
                    print(f"UNREADABLE {name}: {setting}", file=sys.stderr)
            if not report["ok"]:
                raise SystemExit(1)
        else:
            apply(names, protect=args.protect_main, hold=args.hold_actions, expected_pin=args.standards_revision)
    except (ValueError, RuntimeError) as error:
        raise SystemExit("error: " + str(error)) from error


if __name__ == "__main__":
    main()
