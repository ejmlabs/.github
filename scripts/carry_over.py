#!/usr/bin/env python3
"""Carry a batch approval over a merge of the base branch only when the PR's own patch is unchanged."""
import json
import subprocess
import sys
from pathlib import Path

from batch import item_for, load, sha


def git(repo, *args, data=None):
    result = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, text=True, check=True)
    return result.stdout


def patch_id(repo, base, head):
    """The verbatim patch id of the PR's own changes: what `head` adds on top of its merge base with `base`.

    Verbatim, so a whitespace or indentation change counts as a different patch.
    """
    diff = git(repo, "diff", "--binary", f"{base}...{head}")
    if not diff:
        raise ValueError("The PR has no changes against its base")
    return git(repo, "patch-id", "--verbatim", data=diff).split()[0]


def changed_files(repo, base, head):
    return set(git(repo, "diff", "--name-only", f"{base}...{head}").splitlines())


def review_request(repo, pr, head):
    """What the fresh security review must cover: the exact head and its tree."""
    return {"pr": pr, "head": head, "tree": git(repo, "rev-parse", head + "^{tree}").strip()}


def overlapping(changes):
    """Files changed by more than one PR in a batch; disjoint files keep merges from moving each other's heads."""
    owners = {}
    for pr, files in changes.items():
        for name in files:
            owners.setdefault(name, []).append(pr)
    return {name: prs for name, prs in sorted(owners.items()) if len(prs) > 1}


def carry(batch, repo, pr, new_head, new_pass, base="origin/main"):
    """Carry an item to a new head; refuse unless its patch is identical and a fresh review names the new head and its tree.

    The patch id and the tree are computed here from the repository, against `origin/main` (fetch it first); the caller cannot choose the base.
    Returns the record of the new head and review, or the reason the item must be approved again. A record approves nothing: `carried_batch` turns it into a new batch file that the owner signs again.
    """
    item = item_for(batch, pr)
    sha(new_head, "head")
    if not item.get("patch_id"):
        return None, f"{pr} needs a new approval: no patch id was recorded at approval"
    if patch_id(repo, base, new_head) != item["patch_id"]:
        return None, f"{pr} needs a new approval: the patch changed"
    if not new_pass or not new_pass.get("id") or new_pass.get("head") != new_head or new_pass.get("tree") != git(repo, "rev-parse", new_head + "^{tree}").strip():
        return None, f"{pr} needs a new approval: no fresh review names the new head and tree"
    return {"pr": pr, "head": new_head, "patch_id": item["patch_id"], "pass": {"id": new_pass["id"], "head": new_head, "tree": new_pass["tree"]}}, None


def carried_batch(batch, record):
    """A copy of `batch` with the carried item at its new head and review; it is a proposal until the owner signs it."""
    items = [{**item, "head": record["head"], "pass": record["pass"]} if item["pr"] == record["pr"] else item for item in batch["items"]]
    return {**batch, "items": items}


def main(argv):
    if len(argv) == 4 and argv[0] == "request":
        print(json.dumps(review_request(argv[1], argv[2], argv[3])))
    elif len(argv) == 7 and argv[0] == "carry":
        # Arguments: BATCH REPO PR NEW_HEAD PASS_JSON OUT. The approved file is never rewritten and OUT is a new, unsigned file.
        batch = load(Path(argv[1]).read_text())
        record, reason = carry(batch, *argv[2:5], json.loads(argv[5]))
        if reason:
            print(reason, file=sys.stderr)
            sys.exit(1)
        out = Path(argv[6])
        if out.exists():
            raise SystemExit("Refused: " + str(out) + " already exists; a carried batch is a new file")
        text = json.dumps(carried_batch(batch, record), sort_keys=True, indent=2)
        load(text)
        out.write_text(text + "\n")
    elif len(argv) == 4 and argv[0] == "patch-id":
        print(patch_id(*argv[1:]))
    else:
        raise SystemExit("usage: carry_over.py patch-id REPO BASE HEAD | request REPO PR HEAD | carry BATCH REPO PR NEW_HEAD PASS_JSON OUT")


if __name__ == "__main__":
    main(sys.argv[1:])
