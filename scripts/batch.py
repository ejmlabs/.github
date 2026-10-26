#!/usr/bin/env python3
"""Check external writes against the owner's approved batch file."""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
PR_URL = re.compile(r"https://github\.com/ejmlabs/([A-Za-z0-9._-]+)/pull/([1-9][0-9]*)")
NAMESPACE = "ejmlabs-batch"
IDENTITY = re.compile(r"[A-Za-z0-9._@-]+")
PROTECTED_BRANCHES = ("main", "master")
SSH_KEYGEN = "/usr/bin/ssh-keygen"


class Refused(ValueError):
    """A write the batch file does not allow."""


def sha(value, name):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError(f"{name} must be a full lowercase 40-character commit SHA")
    return value


def load(text):
    """Parse and validate a batch file.

    Shape: {"items": [{"pr": url, "branch": str, "head": sha, "pass": {"id": str, "head": sha}}]}.

    An optional "deploy" is {"repo": "ejmlabs/NAME", "tree": sha, "pass": {"id": str, "tree": sha}, "siblings": {name: sha}}: the reviewed tree of `main` after the merges, the review that covered it and the protected pins of its sibling inputs.
    An item may also record `patch_id` (its own patch, for the carry-over rule) and `pass.tree` (the tree the review covered).
    """
    batch = json.loads(text)
    if not isinstance(batch, dict) or not isinstance(batch.get("items", []), list):
        raise ValueError("A batch is an object with a list of items")
    seen = set()
    for item in batch.get("items", []):
        if not isinstance(item, dict):
            raise ValueError("Each item is an object")
        match = PR_URL.fullmatch(item.get("pr", ""))
        if not match or item["pr"] in seen:
            raise ValueError("Each item names one distinct ejmlabs pull request URL")
        seen.add(item["pr"])
        sha(item.get("head"), "head")
        if not isinstance(item.get("branch"), str) or not item["branch"] or item["branch"] in PROTECTED_BRANCHES:
            raise ValueError("Each item names its own branch, never a default branch")
        if item.get("pass") is not None:
            if not isinstance(item["pass"], dict) or not isinstance(item["pass"].get("id"), str) or not item["pass"]["id"]:
                raise ValueError("A review needs a report id")
            sha(item["pass"].get("head"), "pass head")
            if item["pass"].get("tree") is not None:
                sha(item["pass"]["tree"], "pass tree")
        if item.get("patch_id") is not None:
            sha(item["patch_id"], "patch id")
    deploy = batch.get("deploy")
    if deploy is not None:
        if not re.fullmatch(r"ejmlabs/[A-Za-z0-9._-]+", deploy.get("repo", "")):
            raise ValueError("A deploy names one ejmlabs repository")
        sha(deploy.get("tree"), "deploy tree")
        if deploy.get("pass") is not None:
            if not isinstance(deploy["pass"], dict) or not isinstance(deploy["pass"].get("id"), str) or not deploy["pass"]["id"]:
                raise ValueError("A deploy review needs a report id")
            sha(deploy["pass"].get("tree"), "deploy pass tree")
        for name, pin in deploy.get("siblings", {}).items():
            sha(pin, "sibling pin " + name)
    return batch


def item_for(batch, pr):
    for item in batch.get("items", []):
        if item["pr"] == pr:
            return item
    raise Refused("Pull request is not in the approved batch: " + pr)


def passed(item):
    """The item's review, only when it names the exact head that would ship."""
    found = item.get("pass")
    if not found:
        raise Refused("No review recorded for " + item["pr"])
    if found["head"] != item["head"]:
        raise Refused(f"The review covers {found['head']}, not the batch head {item['head']}")
    return found


def push(batch, repo, branch, commit, force=False):
    """Allow pushing exactly the commit the batch lists for that branch of that repository; never a force-push or a deletion."""
    if force:
        raise Refused("Force-push is never allowed")
    if not SHA.fullmatch(commit) or set(commit) == {"0"}:
        raise Refused("Only a full commit SHA may be pushed; deleting a branch is not allowed")
    if branch in PROTECTED_BRANCHES:
        raise Refused("A default branch is never pushed directly")
    for item in batch.get("items", []):
        if repo == "ejmlabs/" + PR_URL.fullmatch(item["pr"]).group(1) and item["branch"] == branch:
            passed(item)
            if item["head"] != commit:
                raise Refused(f"The batch lists {item['head']} for {repo}:{branch}, not {commit}")
            return item
    raise Refused(f"The batch lists no push to {repo}:{branch}")


def reconcile(batch, live_heads):
    """Report every item whose live head is not its approved head; the file is never rewritten, and the write checks already refuse them."""
    kept, dropped = [], []
    for item in batch["items"]:
        live = live_heads.get(item["pr"])
        if live == item["head"]:
            kept.append(item)
        else:
            dropped.append(f"{item['pr']} left the batch: head is {live or 'unknown'}, approved {item['head']}")
    return {**batch, "items": kept}, dropped


def canonical(batch):
    """The exact bytes the owner reads and signs: the items and the deploy, in a canonical form."""
    approved = {"items": batch.get("items", []), "deploy": batch.get("deploy")}
    return json.dumps(approved, sort_keys=True, separators=(",", ":")).encode()


def digest(batch):
    """The SHA-256 of the canonical bytes; a short name for the batch, never what is signed."""
    return hashlib.sha256(canonical(batch)).hexdigest()


def verify_signature(batch, signers, identity, signature):
    """Refuse unless `signature` is the owner's SSH signature over this batch's canonical bytes.

    Runs `/usr/bin/ssh-keygen -Y verify -f SIGNERS -I IDENTITY -n ejmlabs-batch -s SIGNATURE` with the bytes on stdin; the tool path is fixed, never looked up on PATH. SIGNERS is the allowed_signers file of the install directory, which the operator cannot write.
    """
    if not Path(SSH_KEYGEN).is_file():
        raise Refused("ssh-keygen is not available to check the approval")
    if not IDENTITY.fullmatch(identity):
        raise Refused("The owner identity is not a plain name")
    for name in (signers, signature):
        if not Path(name).is_file():
            raise Refused("The approval needs " + str(name))
    result = subprocess.run([SSH_KEYGEN, "-Y", "verify", "-f", str(signers), "-I", identity, "-n", NAMESPACE, "-s", str(signature)],
                            input=canonical(batch), capture_output=True)
    if result.returncode:
        raise Refused("The batch is not signed by the owner: expected a signature over the canonical batch (batch.py FILE canonical)")


def load_approved(path, signers, identity):
    """The batch file exactly as the owner signed it (PATH.sig)."""
    batch = load(Path(path).read_text())
    verify_signature(batch, signers, identity, str(path) + ".sig")
    return batch


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: batch.py BATCH.json canonical | verify SIGNERS IDENTITY | reconcile SIGNERS IDENTITY PR=HEAD... | push SIGNERS IDENTITY REPO BRANCH SHA [--force]")
    try:
        if argv[1] == "canonical" and len(argv) == 2:
            sys.stdout.buffer.write(canonical(load(Path(argv[0]).read_text())))
            return
        if argv[1] not in ("verify", "reconcile", "push") or len(argv) < 4:
            raise SystemExit("unknown operation")
        # Every operation reads the file through the signature check, so an unsigned or badly signed batch is refused for all callers.
        batch = load_approved(argv[0], *argv[2:4])
        rest = argv[4:]
        if argv[1] == "reconcile":
            print("\n".join(reconcile(batch, dict(pair.split("=", 1) for pair in rest))[1]))
        elif argv[1] == "push" and (len(rest) == 3 or rest[3:] == ["--force"]):
            push(batch, *rest[:3], force=len(rest) == 4)
        elif argv[1] != "verify" or rest:
            raise SystemExit("unknown operation")
    except (Refused, ValueError, KeyError, TypeError, OSError) as refusal:
        print("Refused: " + str(refusal), file=sys.stderr)
        if os.environ.get("BATCH_WRITE_LOG"):
            sys.path.insert(0, str(Path(__file__).resolve().parent))  # isolated mode (-I) leaves the script directory off the path
            from flow_metrics import log_write
            log_write(os.environ["BATCH_WRITE_LOG"], argv[1], " ".join(argv[4:]), "refused", datetime.now(timezone.utc).isoformat())
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
