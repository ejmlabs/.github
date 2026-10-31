#!/usr/bin/env python3
"""Bind built release files to the draft release of the commit, attach them, and confirm them for attestation."""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from governance import GitHub
    from versioning import semver

# The workflow generator embeds the governance.py (GitHub) and versioning.py (semver) libraries first.
ARTIFACT = "release-files"
MANIFEST = "build-sha256.txt"
SUMS = "SHA256SUMS"


def verify_run(api: "GitHub", workflow: str, run_id: str, sha: str) -> None:
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


def verify_draft(api: "GitHub", tag: str, sha: str) -> dict[str, Any]:
    """The tag names exactly one release, an unpublished draft that targets the release commit, and no tag exists yet.

    GitHub creates the tag only when a human publishes the draft, so a tag ref now means something else made it.
    """
    drafts = [release for release in api.pages("/releases") if release["tag_name"] == tag]
    if len(drafts) != 1 or not drafts[0]["draft"]:
        raise ValueError("Attach needs exactly one draft release for the tag")
    if drafts[0].get("target_commitish") != sha:
        raise ValueError("Draft release does not target the release commit")
    try:
        api.request("/git/ref/tags/" + tag)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        raise ValueError("The tag exists before the draft was published")
    return drafts[0]


def read_digests(text: str) -> dict[str, str]:
    digests: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if not match or match[2] in (MANIFEST, SUMS) or match[2] in digests:
            raise ValueError("Malformed or duplicate digest line")
        digests[match[2]] = match[1]
    if not digests:
        raise ValueError("Build manifest lists no files")
    return digests


def verify_files(directory: Path) -> dict[str, str]:
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


def digests(directory: Path) -> dict[str, str]:
    """Verified SHA-256 of every file in the build output, the manifest included: exactly what attestation covers."""
    verified = verify_files(directory)
    return {**verified, MANIFEST: hashlib.sha256((directory / MANIFEST).read_bytes()).hexdigest()}


def merge_sums(existing: str, built: dict[str, str]) -> str:
    lines = existing.splitlines()
    names = {line.split("  ", 1)[1] for line in lines if "  " in line}
    if names & set(built):
        raise ValueError("A built file would replace an existing release asset")
    return "".join(line + "\n" for line in lines) + "".join(f"{digest}  {name}\n" for name, digest in sorted(built.items()))


def gh(*args: str) -> None:
    subprocess.run(["gh", *args], check=True)


def attach(api: "GitHub", directory: Path, tag: str, sha: str, release: dict[str, Any], run_gh: "Callable[..., None]") -> dict[str, str]:
    """Upload the verified files, then the extended checksum list, and return the digests of everything in the build output."""
    attested = digests(directory)
    built = {name: digest for name, digest in attested.items() if name != MANIFEST}
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
    # Right before the first write: still the same unpublished draft for this commit, with the assets seen above.
    again = verify_draft(api, tag, sha)
    if again.get("id") != release.get("id") or {asset["name"] for asset in again["assets"]} != assets:
        raise ValueError("The draft release changed while the files were checked")
    # Files first, so a failure never leaves a checksum list naming files that are absent.
    run_gh("release", "upload", tag, "--repo", api.repo, *[str(directory / name) for name in sorted(built)])
    run_gh("release", "upload", tag, "--repo", api.repo, "--clobber", str(sums))
    return attested


def confirm(directory: Path, attached: str) -> None:
    """The files to attest must be exactly the files the attach job verified and attached: recompute every digest and compare."""
    if digests(directory) != json.loads(attached):
        raise ValueError("Build files differ from the files the attach job attached")


def write_output(name: str, value: dict[str, str]) -> None:
    """Pass a verified digest map to later jobs. JSON on one line, so a name or digest cannot add an output."""
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(name + "=" + json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> None:
    api = GitHub()
    sha, workflow, run_id = os.environ["RELEASE_COMMIT"], os.environ["BUILD_WORKFLOW"], os.environ["BUILD_RUN_ID"]
    mode = sys.argv[1]
    if mode not in ("verify", "check", "attach", "confirm"):
        raise ValueError("Unknown operation")
    verify_run(api, workflow, run_id, sha)
    if mode == "verify":
        return
    if mode == "confirm":
        confirm(Path("built"), os.environ["ATTACHED_DIGESTS"])
        return
    if not semver(os.environ["RELEASE_VERSION"]):
        raise ValueError("Supply a SemVer version")
    tag = "v" + os.environ["RELEASE_VERSION"]
    release = verify_draft(api, tag, sha)
    if mode == "attach":
        write_output("digests", attach(api, Path("built"), tag, sha, release, gh))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        print(f"Attach stopped: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
