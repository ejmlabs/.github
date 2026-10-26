#!/usr/bin/env python3
"""Turn a saved branch-protection read into the bodies used to write it back.

GitHub's read shape differs from its write shape: booleans come back wrapped as
``{"enabled": ...}``, people, teams and Apps come back as objects instead of
logins and slugs, ``url`` fields are added, and required signatures are not part
of the full-replace write at all. A restore built by copying the read body would
be refused or would silently change settings, so every restore goes through
these functions and is checked field by field against the saved read.

Every block is checked against its own list of known keys, so a field this
module does not understand is refused instead of being dropped from the write
and missed by the read-back.
"""
import copy

FLAGS = ("required_linear_history", "allow_force_pushes", "allow_deletions", "block_creations",
         "required_conversation_resolution", "lock_branch", "allow_fork_syncing")
# Settings the full-replace write cannot carry; they need their own endpoint.
SEPARATE = ("required_signatures",)
KNOWN = {"url", "required_status_checks", "enforce_admins", "required_pull_request_reviews", "restrictions",
         *FLAGS, *SEPARATE}
# Known keys of each nested block. ``enforcement_level`` is derived by GitHub from
# ``enforce_admins``; it is compared on read-back but never written.
STATUS_KEYS = {"url", "strict", "contexts", "contexts_url", "checks", "enforcement_level"}
CHECK_KEYS = {"context", "app_id"}
REVIEW_KEYS = {"url", "dismissal_restrictions", "dismiss_stale_reviews", "require_code_owner_reviews",
               "required_approving_review_count", "require_last_push_approval", "bypass_pull_request_allowances"}
ACTOR_KEYS = {"url", "users_url", "teams_url", "apps_url", "users", "teams", "apps"}
ENABLED_KEYS = {"url", "enabled"}
ANY_APP = -1


def _refuse_unknown(block, known, where):
    if block is None:
        return
    if not isinstance(block, dict):
        raise ValueError("unhandled protection shape at " + where)
    unknown = set(block) - known
    if unknown:
        raise ValueError("unhandled protection fields at " + where + ": " + ", ".join(sorted(unknown)))


def check_known(saved):
    """Refuse any field, at any level, that the write and the read-back do not handle."""
    _refuse_unknown(saved, KNOWN, "top level")
    status = saved.get("required_status_checks")
    _refuse_unknown(status, STATUS_KEYS, "required_status_checks")
    for entry in (status or {}).get("checks") or []:
        _refuse_unknown(entry, CHECK_KEYS, "required_status_checks.checks")
    reviews = saved.get("required_pull_request_reviews")
    _refuse_unknown(reviews, REVIEW_KEYS, "required_pull_request_reviews")
    for name in ("dismissal_restrictions", "bypass_pull_request_allowances"):
        _refuse_unknown((reviews or {}).get(name), ACTOR_KEYS, "required_pull_request_reviews." + name)
    _refuse_unknown(saved.get("restrictions"), ACTOR_KEYS, "restrictions")
    for name in ("enforce_admins", *FLAGS, *SEPARATE):
        if isinstance(saved.get(name), dict):
            _refuse_unknown(saved[name], ENABLED_KEYS, name)


def _enabled(value):
    if isinstance(value, dict):
        return bool(value.get("enabled"))
    return bool(value)


def _actors(block):
    block = block or {}
    return {"users": sorted(user["login"] for user in block.get("users", [])),
            "teams": sorted(team["slug"] for team in block.get("teams", [])),
            "apps": sorted(app["slug"] for app in block.get("apps", []))}


def checks(saved):
    """Each required check with its app binding; an unbound check stays explicitly unbound."""
    status = saved.get("required_status_checks") or {}
    entries = status.get("checks")
    if entries is None:
        raise ValueError("saved protection has no checks list; a contexts-only restore would drop app binding")
    result = []
    for entry in entries:
        app_id = entry.get("app_id")
        # Omitting app_id lets GitHub pick whichever App last posted the context.
        result.append({"context": entry["context"], "app_id": ANY_APP if app_id is None else app_id})
    return sorted(result, key=lambda item: item["context"])


def status_checks_body(saved, without=None):
    """Body for the required-status-checks update; ``without`` drops one context for a lift."""
    status = saved.get("required_status_checks")
    if status is None:
        raise ValueError("saved protection has no required status checks")
    entries = [entry for entry in checks(saved) if entry["context"] != without]
    if without is not None and len(entries) != len(checks(saved)) - 1:
        raise ValueError("lifted context is not in the saved protection: " + without)
    return {"strict": bool(status.get("strict")), "checks": entries}


def put_body(saved, lock=False):
    """Full-replace write body built only from the saved read."""
    check_known(saved)
    body = {"required_status_checks": None if saved.get("required_status_checks") is None
            else status_checks_body(saved),
            "enforce_admins": _enabled(saved.get("enforce_admins")),
            "required_pull_request_reviews": None, "restrictions": None}
    reviews = saved.get("required_pull_request_reviews")
    if reviews is not None:
        body["required_pull_request_reviews"] = {
            "dismiss_stale_reviews": bool(reviews.get("dismiss_stale_reviews")),
            "require_code_owner_reviews": bool(reviews.get("require_code_owner_reviews")),
            "required_approving_review_count": int(reviews.get("required_approving_review_count", 0)),
            "require_last_push_approval": bool(reviews.get("require_last_push_approval")),
        }
        for name in ("dismissal_restrictions", "bypass_pull_request_allowances"):
            if reviews.get(name) is not None:
                body["required_pull_request_reviews"][name] = _actors(reviews[name])
    if saved.get("restrictions") is not None:
        body["restrictions"] = _actors(saved["restrictions"])
    for name in FLAGS:
        body[name] = _enabled(saved.get(name))
    if lock:
        body["lock_branch"] = True
    return body


def normalize(read):
    """Comparable form of a protection read: the write shape plus the separate settings."""
    result = put_body(read)
    for name in SEPARATE:
        result[name] = _enabled(read.get(name))
    status = read.get("required_status_checks")
    if status is not None:
        result["required_status_checks"]["enforcement_level"] = status.get("enforcement_level")
    return result


def differences(saved, current):
    """Paths whose values differ between two reads; nothing is excused.

    A lift is read back against ``expected_after_lift(saved, context)``, so any
    change other than the one lifted context is reported.
    """
    left, right = normalize(saved), normalize(current)
    found = []

    def walk(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                walk(a.get(key), b.get(key), path + (key,))
        elif a != b:
            found.append(".".join(path))

    walk(left, right, ())
    return found


def signature_repair(saved, current):
    """The separate call that puts required signatures back, or None when they match.

    The full replace cannot carry this setting, so a restore that finds it changed
    makes this call (POST enables, DELETE disables) and reads back again; the
    automation's runner, which does not hold this call, locks the branch and pages.
    """
    want, have = _enabled(saved.get("required_signatures")), _enabled(current.get("required_signatures"))
    if want == have:
        return None
    return ("POST" if want else "DELETE", "required_signatures")


def expected_after_lift(saved, context):
    """The read expected while one context is lifted: everything else unchanged."""
    lifted = copy.deepcopy(saved)
    status = lifted["required_status_checks"]
    kept = [entry for entry in status["checks"] if entry["context"] != context]
    if len(kept) != len(status["checks"]) - 1:
        raise ValueError("lifted context is not in the saved protection: " + context)
    status["checks"] = kept
    status["contexts"] = [entry["context"] for entry in status["checks"]]
    return lifted
