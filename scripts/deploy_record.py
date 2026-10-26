#!/usr/bin/env python3
"""Decide whether a merged `main` may deploy, and record each deploy for rollback."""
import json
import subprocess
import sys
from pathlib import Path

from batch import Refused, load_approved, sha
from carry_over import git
from flow_metrics import moment


def merged_tree(repo, base, head):
    """The tree `base` would hold after merging `head`: the tree the pre-merge security review must cover."""
    return git(repo, "merge-tree", "--write-tree", base, head).split()[0]


def decide(batch, repo, checkout, commit, siblings=None, main_ref="origin/main"):
    """Allow a deploy only when the batch names it with a review, `main` is exactly `commit`, that commit holds the reviewed tree and sibling inputs sit at their protected pins.

    The tree is computed from `commit` in `checkout`, never taken from the caller. Fetch `origin` first.
    """
    deploy = batch.get("deploy")
    if not deploy or deploy["repo"] != repo:
        raise Refused("The approved batch does not name a deploy of " + repo)
    if not deploy.get("pass") or not deploy["pass"].get("id") or deploy["pass"]["tree"] != deploy["tree"]:
        raise Refused("No review covers the reviewed tree " + deploy["tree"])
    sha(commit, "commit")
    if git(checkout, "rev-parse", main_ref).strip() != commit:
        raise Refused(f"{commit} is not the current {main_ref}")
    tree = git(checkout, "rev-parse", commit + "^{tree}").strip()
    if tree != deploy["tree"]:
        raise Refused(f"The main tree {tree} is not the reviewed tree {deploy['tree']}")
    if (siblings or {}) != deploy.get("siblings", {}):
        raise Refused("Sibling inputs are not at their protected pins")
    return deploy


def decide_approved(path, signers, identity, *args):
    """Check the owner's signature on the approved file, then decide on exactly what was signed."""
    return decide(load_approved(path, signers, identity), *args)


def record_deploy(path, repo, commit, tree, previous, at):
    """Append the deployed commit, tree, time and the previous version, so the previous one can be restored."""
    entry = {"repo": repo, "commit": sha(commit, "commit"), "tree": sha(tree, "tree"),
             "at": moment(at).isoformat(), "previous": None if previous is None else sha(previous, "previous")}
    with Path(path).open("a") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


def main(argv):
    try:
        if len(argv) >= 7 and argv[1] == "decide":
            decide_approved(argv[0], argv[2], argv[3], *argv[4:7], dict(pair.split("=", 1) for pair in argv[7:]))
        elif len(argv) == 7 and argv[0] == "record":
            record_deploy(argv[1], *argv[2:5], None if argv[5] == "none" else argv[5], argv[6])
        elif len(argv) == 4 and argv[0] == "tree":
            print(merged_tree(*argv[1:4]))
        else:
            raise SystemExit("usage: deploy_record.py BATCH decide ALLOWED_SIGNERS IDENTITY REPO CHECKOUT COMMIT [NAME=SHA...] | record LOG REPO COMMIT TREE PREVIOUS|none TIME | tree REPO BASE HEAD")
    except (Refused, ValueError, KeyError, OSError, subprocess.CalledProcessError) as refusal:
        print("Refused: " + str(refusal), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
