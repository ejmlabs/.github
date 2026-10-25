#!/usr/bin/env python3
"""Apply and read back the requested repository controls using authenticated gh."""
import argparse
import base64
import json
import re
import subprocess
import urllib.parse

from governance import SECURITY_LABEL


NAMES = (".github", "ejmlabs", "ejm-cli", "ejm-harness", "ejm-ide")
SUPPORTED_NAMES = (*NAMES, "ejm-ui")
CONTEXTS = ("Human readiness", "Maintainer approval", "Quality", "Repository standards", "AI review")


def api(path, method="GET", body=None, optional=False):
    args = ["gh", "api", "--method", method, path]
    if body is not None:
        args += ["--input", "-"]
    result = subprocess.run(args, input=None if body is None else json.dumps(body), capture_output=True, text=True)
    if result.returncode:
        if optional:
            return {"unavailable": result.stderr.strip()}
        raise RuntimeError(path + ": " + result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else {"applied": True}


def collaborators(name):
    """Only human maintainers may write workflows or publish Actions statuses."""
    people = []
    for page in range(1, 11):
        batch = api(f"repos/ejmlabs/{name}/collaborators?per_page=100&page={page}")
        people.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError("Collaborator list exceeds inspection limit")
    unsafe = [person["login"] for person in people
              if person.get("permissions", {}).get("push")
              and (person.get("type") != "User" or person.get("role_name") not in ("maintain", "admin"))]
    if unsafe:
        raise ValueError(name + ": workflow writers must be human maintainers: " + ", ".join(unsafe))
    return [{"login": person["login"], "type": person["type"], "role": person["role_name"]} for person in people]


def installed_consumers(name, revision):
    """Never enable Actions until trusted callers are installed on main."""
    from standards import consumer_workflows

    if not re.fullmatch(r"[0-9a-f]{40}", revision or ""):
        raise ValueError("Activation requires --standards-revision with a full immutable SHA")
    root = "repos/ejmlabs/" + name + "/contents/.github/workflows"
    entries = api(root + "?ref=main")
    expected = consumer_workflows(revision)
    allowed = set(expected) | ({"governance.yml", "draft-release.yml"} if name == ".github" else set())
    if {entry["name"] for entry in entries} != allowed:
        raise ValueError(name + ": unexpected or missing workflows on main")
    for filename, content in expected.items():
        remote = api(root + "/" + filename + "?ref=main")
        if remote.get("encoding") != "base64" or base64.b64decode(remote["content"]).decode() != content:
            raise ValueError(name + ": main does not contain the approved caller: " + filename)


def configure(name, protect, hold, revision=None):
    root = "repos/ejmlabs/" + name
    api(root, "PATCH", {"allow_squash_merge": True, "allow_merge_commit": False, "allow_rebase_merge": False,
                             "delete_branch_on_merge": True, "allow_auto_merge": False, "has_issues": True,
                             "has_wiki": False, "squash_merge_commit_title": "PR_TITLE", "squash_merge_commit_message": "PR_BODY"})
    if hold:
        # GitHub rejects allowed_actions when enabled is false. Do not enable old workflows.
        api(root + "/actions/permissions", "PUT", {"enabled": False})
    else:
        installed_consumers(name, revision)
        api(root + "/actions/permissions", "PUT", {"enabled": True, "allowed_actions": "selected", "sha_pinning_required": True})
        api(root + "/actions/permissions/selected-actions", "PUT", {
            "github_owned_allowed": False, "verified_allowed": False,
            "patterns_allowed": ["actions/*@*", "astral-sh/setup-uv@*", "ejmlabs/.github/*@*"],
        })
    workflow_update = api(root + "/actions/permissions/workflow", "PUT", {
        "default_workflow_permissions": "read", "can_approve_pull_request_reviews": True,
    }, optional=hold)
    fork = api(root + "/actions/permissions/fork-pr-workflows-private-repos", "PUT", {
        "run_workflows_from_fork_pull_requests": False, "send_write_tokens_to_workflows": False,
        "send_secrets_and_variables": False, "require_approval_for_fork_pr_workflows": True,
    }, optional=True)
    api(root + "/vulnerability-alerts", "PUT")
    # The review token may be unable to create labels; an existing label is the override path.
    api(root + "/labels", "POST", {"name": SECURITY_LABEL, "color": "d73a4a",
                                   "description": "Blocks AI review until a maintainer removes it"}, optional=True)
    fixes = api(root + "/automated-security-fixes", "PUT", optional=True)
    immutable = api(root + "/immutable-releases", "PUT", optional=True)
    # These APIs are public-only or depend on installed security products. No paid enrollment.
    reporting = api(root + "/private-vulnerability-reporting", "PUT", optional=True)
    external = api(root + "/actions/permissions/fork-pr-contributor-approval", "PUT", {"approval_policy": "all_external_contributors"}, optional=True)
    if protect:
        api(root + "/branches/main/protection", "PUT", {
            "required_status_checks": {"strict": True, "checks": [{"context": context, "app_id": 15368} for context in CONTEXTS]},
            "enforce_admins": True,
            "required_pull_request_reviews": {"dismiss_stale_reviews": True, "require_code_owner_reviews": False,
                                              "required_approving_review_count": 1, "require_last_push_approval": False},
            "restrictions": None, "required_linear_history": True, "allow_force_pushes": False,
            "allow_deletions": False, "block_creations": False, "required_conversation_resolution": True,
            "lock_branch": False, "allow_fork_syncing": False,
        })
        rules = api(root + "/rulesets")
        existing = next((rule for rule in rules if rule["name"] == "Immutable semantic version tags"), None)
        rule = {"name": "Immutable semantic version tags", "target": "tag", "enforcement": "active", "bypass_actors": [],
                "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
                "rules": [{"type": "update"}, {"type": "deletion"}]}
        api(root + "/rulesets" + ("/" + str(existing["id"]) if existing else ""), "PUT" if existing else "POST", rule)
    result = {"repository": "ejmlabs/" + name,
              "workflow_update": workflow_update,
              "actions": api(root + "/actions/permissions"), "workflow": api(root + "/actions/permissions/workflow"),
              "allowed_actions": api(root + "/actions/permissions/selected-actions", optional=hold), "fork": api(root + "/actions/permissions/fork-pr-workflows-private-repos", optional=True),
              "dependency_alerts": api(root + "/vulnerability-alerts"), "security_updates": api(root + "/automated-security-fixes", optional=True),
              "immutable_releases": api(root + "/immutable-releases", optional=True),
              "private_reporting": reporting, "external_approval": external,
              "metadata": api(root), "rulesets": api(root + "/rulesets"),
              "security_label": api(root + "/labels/" + urllib.parse.quote(SECURITY_LABEL))}
    if protect:
        result["main_protection"] = api(root + "/branches/main/protection")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protect-main", action="store_true", help="Only after trusted callers are installed on main")
    parser.add_argument("--hold-actions", action="store_true", help="Disable automatic workflows during bootstrap")
    parser.add_argument("--standards-revision", help="Tested shared workflow SHA, required to enable Actions")
    parser.add_argument("--repository", choices=SUPPORTED_NAMES, action="append")
    args = parser.parse_args()
    names = args.repository or NAMES
    # Audit the entire requested scope before any mutation.
    access = {name: collaborators(name) for name in names}
    if not args.hold_actions:
        for name in names:
            installed_consumers(name, args.standards_revision)
    for name in names:
        result = configure(name, args.protect_main, args.hold_actions, args.standards_revision)
        result["collaborators"] = access[name]
        print(json.dumps(result), flush=True)
