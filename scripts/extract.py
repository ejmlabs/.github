#!/usr/bin/env python3
"""Validate the prepared source archives and extract them as data into the workspace."""
import tarfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path

# prepare.py writes each archive with exactly one top-level directory, named here.
PREFIXES = {"product.tar": "product", "harness.tar": "ejm-harness", "ui.tar": "ejm-ui"}
# Files, directories and symlinks only. Hard links, devices, and FIFOs never appear in a Git export.
MEMBER_TYPES = (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE)


def unsafe(kind: str, name: str) -> ValueError:
    # ascii() escapes control characters, so a hostile name cannot start a workflow command line.
    return ValueError(f"Unsafe archive {kind}: {ascii(name)[:200]}")


def member_parts(name: str, prefix: str) -> list[str]:
    """Split a member name into parts, requiring a plain relative path inside the archive prefix."""
    parts = name.removesuffix("/").split("/")
    if name.startswith("/") or "\\" in name or "\0" in name or parts[0] != prefix or any(part in ("", ".", "..") for part in parts):
        raise unsafe("member", name)
    return parts


def check_link(directory: list[str], target: str, links: set[str]) -> None:
    """Allow a symlink only when its relative target stays inside the prefix without passing through another link.

    Every link on the way would have to be resolved to prove containment, so none is allowed:
    `a/b -> ..` followed by `c -> a/b/..` would otherwise walk out of the prefix.
    """
    if not target or target.startswith("/") or "\\" in target or "\0" in target:
        raise unsafe("symlink target", target)
    current = list(directory)
    steps = target.split("/")
    for index, step in enumerate(steps):
        if step in ("", "."):
            continue
        if step == "..":
            current.pop()
        else:
            current.append(step)
        if not current or (index < len(steps) - 1 and "/".join(current) in links):
            raise unsafe("symlink target", target)


def validate(members: Sequence[tarfile.TarInfo], prefix: str) -> None:
    """Reject any member that could write or point outside its archive's prefix directory."""
    paths: dict[str, tarfile.TarInfo] = {}
    for member in members:
        if member.type not in MEMBER_TYPES:
            raise unsafe("member type", member.name)
        path = "/".join(member_parts(member.name, prefix))
        if path in paths:
            raise unsafe("duplicate member", member.name)
        paths[path] = member
    if prefix in paths and not paths[prefix].isdir():
        raise unsafe("prefix member", prefix)
    links = {path for path, member in paths.items() if member.issym()}
    for path, member in paths.items():
        parts = path.split("/")
        # Extraction would write through a link, so no member may sit below one.
        if any("/".join(parts[:count]) in links for count in range(1, len(parts))):
            raise unsafe("member below a symlink", member.name)
        if member.issym():
            check_link(parts[:-1], member.linkname, links)


def fresh(now: float) -> Callable[[tarfile.TarInfo, str], tarfile.TarInfo]:
    """Return an extraction filter: the standard data filter, then the extraction time as every mtime.

    Admitted sources must be newer than any restored build, so Cargo rebuilds every local crate.
    """
    def apply(member: tarfile.TarInfo, destination: str) -> tarfile.TarInfo:
        return tarfile.data_filter(member, destination).replace(mtime=now, deep=False)
    return apply


def extract(prepared: Path, destination: Path) -> None:
    """Extract product.tar and the optional harness.tar and ui.tar from `prepared` into `destination`."""
    if prepared.is_symlink() or not prepared.is_dir():
        raise ValueError("Prepared sources must be an ordinary directory")
    names = sorted(entry.name for entry in prepared.iterdir())
    if "product.tar" not in names or any(name not in PREFIXES for name in names):
        raise ValueError("Prepared sources must be product.tar with optional harness.tar and ui.tar")
    now = time.time()
    for name in names:
        file = prepared / name
        if file.is_symlink() or not file.is_file():
            raise unsafe("archive file", name)
        with tarfile.open(file, "r:") as archive:
            members = archive.getmembers()
            validate(members, PREFIXES[name])
            archive.extractall(destination, members=members, filter=fresh(now))  # noqa: S202 - every member was validated above and the data filter checks each again


def main() -> None:
    extract(Path("prepared"), Path())


if __name__ == "__main__":
    main()
