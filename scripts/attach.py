#!/usr/bin/env python3
"""Bind built release files to the tagged commit and attach them to the draft release."""
import hashlib
import os
import re
import subprocess
import sys
import urllib.error
from pathlib import Path

# The workflow generator embeds the governance.py (GitHub) and standards.py (semver) libraries first.
ARTIFACT = "release-files"
MANIFEST = "build-sha256.txt"
SUMS = "SHA256SUMS"


def verify_run(api, workflow, run_id, sha):
    """Accept only a finished, successful run of the named build workflow on this commit."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.ya?ml", workflow) or not re.fullmatch(r"[1-9][0-9]{0,15}", run_id) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Supply a build workflow file name, a run id and a full commit SHA")
    run = api.request("/actions/runs/" + run_id)
    path = (run.get("path") or "").split("@", 1)[0]
    if path != ".github/workflows/" + workflow:
        raise ValueError("Run belongs to a different workflow")
    if run.get("event") not in ("workflow_dispatch", "push"):
        raise ValueError("Run was not started by workflow_dispatch or a push")
    if run.get("head_branch") != "main" or (run.get("head_repository") or {}).get("full_name") != api.repo:
        raise ValueError("Run was not built from main in this repository")
    if run.get("head_sha") != sha:
        raise ValueError("Run was built from a different commit than the release")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError("Build run has not completed successfully")
    # head_branch also names a tag; a tag called main must not pass as the branch.
    try:
        api.request("/git/ref/tags/main")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        raise ValueError("A tag named main makes the run's branch ambiguous")
    found = [item for item in api.request(f"/actions/runs/{run_id}/artifacts?name={ARTIFACT}")["artifacts"] if item["name"] == ARTIFACT and not item["expired"]]
    if len(found) != 1:
        raise ValueError("Build run must upload exactly one artifact named " + ARTIFACT)


def verify_draft(api, tag, sha):
    """The tag must be a lightweight ref to the release commit and its release an unpublished draft."""
    ref = api.request("/git/ref/tags/" + tag)
    if ref.get("object", {}).get("type") != "commit" or ref["object"]["sha"] != sha:
        raise ValueError("Tag does not point at the release commit")
    drafts = [release for release in api.pages("/releases") if release["tag_name"] == tag]
    if len(drafts) != 1 or not drafts[0]["draft"]:
        raise ValueError("Attach needs exactly one draft release for the tag")
    return drafts[0]


def read_digests(text):
    digests = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if not match or match[2] in (MANIFEST, SUMS) or match[2] in digests:
            raise ValueError("Malformed or duplicate digest line")
        digests[match[2]] = match[1]
    if not digests:
        raise ValueError("Build manifest lists no files")
    return digests


def verify_files(directory):
    """Recompute every digest; the file set must equal the manifest exactly. Returns the verified files."""
    entries = {entry.name: entry for entry in directory.iterdir()}
    manifest = entries.pop(MANIFEST, None)
    if manifest is None or manifest.is_symlink():
        raise ValueError("Build output has no digest manifest")
    expected = read_digests(manifest.read_text())
    if set(entries) != set(expected):
        raise ValueError("Build output files differ from the manifest")
    for name, entry in entries.items():
        if entry.is_symlink() or not entry.is_file():
            raise ValueError("Build output must be regular files: " + name)
        if hashlib.sha256(entry.read_bytes()).hexdigest() != expected[name]:
            raise ValueError("Digest changed after the build: " + name)
    return expected


def merge_sums(existing, built):
    lines = existing.splitlines()
    names = {line.split("  ", 1)[1] for line in lines if "  " in line}
    if names & set(built):
        raise ValueError("A built file would replace an existing release asset")
    return "".join(line + "\n" for line in lines) + "".join(f"{digest}  {name}\n" for name, digest in sorted(built.items()))


def gh(*args):
    subprocess.run(["gh", *args], check=True)


def attach(api, directory, tag, release, run_gh):
    built = verify_files(directory)
    assets = {asset["name"] for asset in release["assets"]}
    if assets & set(built):
        raise ValueError("A built file would replace an existing release asset")
    existing = ""
    if SUMS in assets:
        scratch = directory.parent / "sums"
        run_gh("release", "download", tag, "--repo", api.repo, "--pattern", SUMS, "--dir", str(scratch))
        existing = (scratch / SUMS).read_text()
    sums = directory.parent / SUMS
    sums.write_text(merge_sums(existing, built))
    # Files first, so a failure never leaves a checksum list naming files that are absent.
    run_gh("release", "upload", tag, "--repo", api.repo, *[str(directory / name) for name in sorted(built)])
    run_gh("release", "upload", tag, "--repo", api.repo, "--clobber", str(sums))


def main():
    api = GitHub()
    sha, workflow, run_id = os.environ["RELEASE_COMMIT"], os.environ["BUILD_WORKFLOW"], os.environ["BUILD_RUN_ID"]
    mode = sys.argv[1]
    if mode not in ("verify", "check", "attach"):
        raise ValueError("Unknown operation")
    verify_run(api, workflow, run_id, sha)
    if mode == "verify":
        return
    if not semver(os.environ["RELEASE_VERSION"]):
        raise ValueError("Supply a SemVer version")
    tag = "v" + os.environ["RELEASE_VERSION"]
    release = verify_draft(api, tag, sha)
    if mode == "attach":
        attach(api, Path("built"), tag, release, gh)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        print(f"Attach stopped: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
