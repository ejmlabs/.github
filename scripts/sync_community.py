#!/usr/bin/env python3
"""Refresh uniform consumer guidance from a reviewed standards checkout."""
import argparse
from pathlib import Path
from standards import COMMUNITY_GUIDES

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("root", type=Path)
parser.add_argument("repository", choices=COMMUNITY_GUIDES)
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
guide = COMMUNITY_GUIDES[args.repository]
templates = Path(__file__).resolve().parents[1] / "templates/community"
for file in sorted(templates.glob("*.md")):
    target = args.root / file.name
    if target.is_symlink():
        raise SystemExit("Refusing to replace a symlink: " + str(target))
    text = file.read_text().replace("{{repository}}", "ejmlabs/" + args.repository).replace("{{development_guide}}", guide)
    if args.check:
        if not target.exists() or target.read_text() != text:
            raise SystemExit("Community guidance differs: " + str(target))
    else:
        target.write_text(text)
