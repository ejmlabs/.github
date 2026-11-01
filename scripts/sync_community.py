#!/usr/bin/env python3
"""Refresh the uniform community files of a consumer from the shared templates, or report drift with --check.

The Repository standards check only requires these files to exist and be non-empty. This tool keeps them
in step with the templates on demand, and `--check` prints what differs without changing anything.
"""
import argparse
import difflib
import sys
from collections.abc import Sequence
from itertools import islice
from pathlib import Path

from standards import PROFILES

TEMPLATES = Path(__file__).resolve().parents[1] / "templates/community"
MAX_DIFF_LINES = 40


def render(template: Path, repository: str) -> str:
    return template.read_text().replace("{{repository}}", "ejmlabs/" + repository).replace("{{development_guide}}", PROFILES[repository].guide)


def drift(root: Path, repository: str) -> list[str]:
    """Describe every community file that is missing or differs from its rendered template, with a bounded diff."""
    reports = []
    for template in sorted(TEMPLATES.glob("*.md")):
        expected = render(template, repository)
        target = root / template.name
        if target.is_symlink() or not target.is_file():
            reports.append(f"{template.name}: missing or not a regular file")
            continue
        actual = target.read_text()
        if actual != expected:
            diff = list(islice(difflib.unified_diff(expected.splitlines(), actual.splitlines(), "template/" + template.name, "actual/" + template.name, lineterm="", n=1), MAX_DIFF_LINES + 1))
            reports.append(f"{template.name}: differs from the template\n" + "\n".join(diff[:MAX_DIFF_LINES]) + ("\n..." if len(diff) > MAX_DIFF_LINES else ""))
    return reports


def sync(root: Path, repository: str) -> list[Path]:
    """Write every rendered template into root, refusing to replace a symlink; return the files written."""
    targets = [(root / template.name, render(template, repository)) for template in sorted(TEMPLATES.glob("*.md"))]
    for target, _text in targets:
        if target.is_symlink():
            raise SystemExit("Refusing to replace a symlink: " + str(target))
    for target, text in targets:
        target.write_text(text)
    return [target for target, _text in targets]


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("repository", choices=PROFILES)
    parser.add_argument("--check", action="store_true", help="report drift and exit 1 instead of writing")
    args = parser.parse_args(arguments)
    if args.check:
        reports = drift(args.root, args.repository)
        if reports:
            print("Community files differ from the templates:\n" + "\n".join(reports), file=sys.stderr)
            return 1
        return 0
    sync(args.root, args.repository)
    return 0


if __name__ == "__main__":
    sys.exit(main())
