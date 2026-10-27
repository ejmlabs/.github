#!/usr/bin/env python3
"""Copy the shared strict lint layer into a repository checkout, or report drift from it."""
import argparse
import shutil
import tomllib
from pathlib import Path
from typing import Any

TEMPLATES = Path(__file__).resolve().parents[1] / "templates/lint"
CARGO = "cargo-lints"
LEVELS = {"allow": 0, "warn": 1, "deny": 2, "forbid": 3}
NOT_COPIED = {"README.md", "cargo-lints.toml"}


def copyable() -> list[str]:
    return sorted(path.name for path in TEMPLATES.iterdir() if path.name not in NOT_COPIED)


def refuse_symlink(path: Path) -> None:
    if path.is_symlink():
        raise SystemExit("Refusing to use a symlink: " + str(path))


def level(value: Any) -> int:  # noqa: ANN401 - TOML values are untyped until checked here
    """Rank a lint level given as a string or as a table with a `level` key."""
    name = value.get("level") if isinstance(value, dict) else value
    if not isinstance(name, str) or name not in LEVELS:
        raise SystemExit("Unknown lint level: " + repr(value))
    return LEVELS[name]


def lint_tables(text: str) -> dict[str, dict[str, Any]]:
    """Return the Rust and clippy tables from `[workspace.lints]` or `[lints]`."""
    data = tomllib.loads(text)
    lints = data.get("workspace", {}).get("lints") or data.get("lints") or {}
    return {group: dict(lints.get(group, {})) for group in ("rust", "clippy")}


def cargo_drift(manifest: Path) -> list[str]:
    """List template lints that a manifest misses or sets to a lower level."""
    expected = lint_tables((TEMPLATES / "cargo-lints.toml").read_text())
    actual = lint_tables(manifest.read_text())
    drift = []
    for group, entries in expected.items():
        for name, value in entries.items():
            if name not in actual[group]:
                drift.append(f"{group}::{name} is missing")
            elif level(actual[group][name]) < level(value):
                drift.append(f"{group}::{name} is looser than the template")
    return drift


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("names", nargs="+", help=f"template file names, or {CARGO}:<path to Cargo.toml> (check only)")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    refuse_symlink(args.root)
    for name in args.names:
        if name.startswith(CARGO + ":"):
            if not args.check:
                raise SystemExit("Rust lint tables are pasted into Cargo.toml by hand; use --check")
            manifest = args.root / name.split(":", 1)[1]
            refuse_symlink(manifest)
            drift = cargo_drift(manifest)
            if drift:
                raise SystemExit("Rust lint tables differ in " + str(manifest) + ": " + "; ".join(drift))
            continue
        if name not in copyable():
            raise SystemExit("Unknown template: " + name)
        source, target = TEMPLATES / name, args.root / name
        refuse_symlink(target)
        if args.check:
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                raise SystemExit("Lint layer differs: " + str(target))
        else:
            shutil.copyfile(source, target)


if __name__ == "__main__":
    main()
