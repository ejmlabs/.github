#!/usr/bin/env python3
"""Copy the shared strict lint layer into a repository checkout, or report every difference from it."""
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


def refusal(path: Path) -> str:
    return "Refusing to use a symlink: " + str(path)


def level(value: Any) -> int:  # noqa: ANN401 - TOML values are untyped until checked here
    """Rank a lint level given as a string or as a table with a `level` key."""
    name = value.get("level") if isinstance(value, dict) else value
    if not isinstance(name, str) or name not in LEVELS:
        raise ValueError("Unknown lint level: " + repr(value))
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


def manifest_path(root: Path, name: str) -> Path:
    return root / name.split(":", 1)[1]


def usage_errors(root: Path, names: list[str], *, check: bool) -> list[str]:
    """Name every argument that cannot be used, so a run stops before it writes anything."""
    errors = []
    for name in names:
        if name.startswith(CARGO + ":"):
            if not check:
                errors.append("Rust lint tables are pasted into Cargo.toml by hand; use --check")
            elif manifest_path(root, name).is_symlink():
                errors.append(refusal(manifest_path(root, name)))
        elif name not in copyable():
            errors.append("Unknown template: " + name)
        elif (root / name).is_symlink():
            errors.append(refusal(root / name))
    return errors


def drift(root: Path, names: list[str]) -> list[str]:
    """Name every copy that differs from its template and every Rust lint table that is missing or looser."""
    errors = []
    for name in names:
        if name.startswith(CARGO + ":"):
            manifest = manifest_path(root, name)
            if not manifest.is_file():
                errors.append(f"Rust lint tables differ in {manifest}: the file is missing")
                continue
            try:
                missing = cargo_drift(manifest)
            except (ValueError, tomllib.TOMLDecodeError) as error:
                errors.append(f"Rust lint tables differ in {manifest}: {error}")
                continue
            if missing:
                errors.append(f"Rust lint tables differ in {manifest}: " + "; ".join(missing))
        else:
            target = root / name
            if not target.is_file() or target.read_bytes() != (TEMPLATES / name).read_bytes():
                errors.append("Lint layer differs: " + str(target))
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("names", nargs="+", help=f"template file names, or {CARGO}:<path to Cargo.toml> (check only)")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.root.is_symlink():
        raise SystemExit(refusal(args.root))
    errors = usage_errors(args.root, args.names, check=args.check)
    if not errors and args.check:
        errors = drift(args.root, args.names)
    if errors:
        raise SystemExit("\n".join(errors))
    if not args.check:
        for name in args.names:
            shutil.copyfile(TEMPLATES / name, args.root / name)


if __name__ == "__main__":
    main()
