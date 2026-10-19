#!/usr/bin/env python3
"""Export two exact shared revisions as bounded, static review data."""
import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_EXPORT_BYTES = 750_000
SOURCE_PATHS = (
    ".github/workflows/governance.yml",
    ".github/workflows/draft-release.yml",
    "scripts/build_workflows.py",
    "scripts/governance.py",
    "scripts/prepare.py",
    "scripts/release.py",
    "scripts/review_result.py",
    "scripts/standards.py",
    "review/prompt.md",
    "review/schema.json",
    "templates/community/CODE_OF_CONDUCT.md",
    "templates/community/CONTRIBUTING.md",
    "templates/community/RELEASING.md",
    "templates/community/SECURITY.md",
    "templates/community/SUPPORT.md",
    "templates/community/THIRD_PARTY_NOTICES.md",
)


def git(root, *args):
    # Do not honor replacement objects or fetch missing partial-clone objects.
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        check=True, capture_output=True,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": ""},
    ).stdout


def revision(root, sha):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Revisions must be full lowercase commit SHAs")
    if git(root, "rev-parse", "--verify", sha + "^{commit}").decode().strip() != sha:
        raise ValueError("Revision must name the exact commit, not a tag object")
    tree = git(root, "rev-parse", "--verify", sha + "^{tree}").decode().strip()
    entries = git(root, "ls-tree", "-l", "-z", sha, "--", *SOURCE_PATHS)
    files = []
    for entry in entries.rstrip(b"\0").split(b"\0") if entries else []:
        metadata, path = entry.split(b"\t", 1)
        mode, kind, blob, size = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("Review sources must be ordinary blobs: " + path.decode())
        files.append({"path": path.decode(), "mode": mode.decode(), "blob": blob.decode(), "size": int(size)})
    if {item["path"] for item in files} != set(SOURCE_PATHS) or len(files) != len(SOURCE_PATHS):
        raise ValueError("Revision is missing a required shared review source")
    return {"commit": sha, "tree": tree, "files": files}


def write_file(root_fd, relative, data):
    """Create a static file under the new destination without following links."""
    directory = os.dup(root_fd)
    try:
        for part in Path(relative).parts[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=directory)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(Path(relative).name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
    finally:
        os.close(directory)


def write_destination(destination, files):
    path = Path(destination)
    if ".." in path.parts:
        raise ValueError("Destination must not contain parent traversal")
    if not path.is_absolute():
        path = Path.cwd() / path
    if path == Path(path.anchor):
        raise ValueError("Destination must be a new directory")
    parent = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        os.mkdir(path.name, 0o700, dir_fd=parent)
        directory = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            for relative, data in files.items():
                write_file(directory, relative, data)
        finally:
            os.close(directory)
    finally:
        os.close(parent)


def export_context(repository, old, new, destination):
    revisions = {"old": revision(repository, old), "new": revision(repository, new)}
    if sum(item["size"] for rev in revisions.values() for item in rev["files"]) > MAX_EXPORT_BYTES:
        raise ValueError("Shared review sources exceed the total byte limit")
    files = {}
    for rev in revisions.values():
        for item in rev["files"]:
            data = git(repository, "cat-file", "blob", item["blob"])
            if len(data) != item["size"]:
                raise ValueError("Git blob size differs from tree metadata")
            item["sha256"] = hashlib.sha256(data).hexdigest()
            files[rev["commit"] + "/" + item["path"]] = data
    manifest = {"repository": "ejmlabs/.github", "revisions": revisions}
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    if sum(map(len, files.values())) > MAX_EXPORT_BYTES:
        raise ValueError("Shared review sources and manifest exceed the total byte limit")
    write_destination(destination, files)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=ROOT, help="local ejmlabs/.github Git checkout")
    parser.add_argument("--old", required=True, help="old full lowercase commit SHA")
    parser.add_argument("--new", required=True, help="new full lowercase commit SHA")
    parser.add_argument("--destination", type=Path, required=True, help="new directory below existing nonsymlink directories")
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("Run this export on macOS, Linux, or WSL")
    try:
        export_context(args.repository, args.old, args.new, args.destination)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
