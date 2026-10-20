#!/usr/bin/env python3
"""Validate bounded AI output before publication or a required status."""
import argparse
import json
import sys
from pathlib import Path


def unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate review fields")
    return result


def validate(file, head, number):
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 64_000:
        raise ValueError("Missing, unsafe, or oversized review output")
    raw = file.read_bytes()
    # Fail closed before the artifact is uploaded. Do not include the match.
    if b"sk-" in raw:
        raise ValueError("Review output matches a key-like pattern")
    result = json.loads(raw, object_pairs_hook=unique_fields)
    if "sk-" in json.dumps(result, ensure_ascii=False):
        raise ValueError("Review output matches a key-like pattern")
    if set(result) != {"head", "pass", "complete", "summary", "findings"}:
        raise ValueError("Invalid review fields")
    if result["head"] != head or type(result["pass"]) is not int or result["pass"] != number:
        raise ValueError("Review is for another head or pass")
    if not isinstance(result["summary"], str) or not 1 <= len(result["summary"]) <= 4000:
        raise ValueError("Missing or oversized review summary")
    if type(result["complete"]) is not bool:
        raise ValueError("Review completeness must be a boolean")
    if not result["complete"]:
        raise ValueError("Review is incomplete")
    findings = result["findings"]
    if not isinstance(findings, list) or len(findings) > 50:
        raise ValueError("Invalid findings")
    for item in findings:
        if not isinstance(item, dict) or set(item) != {"severity", "file", "line", "title", "reason"}:
            raise ValueError("Invalid finding fields")
        if item["severity"] not in {"critical", "high", "medium", "low"}:
            raise ValueError("Invalid severity")
        path = Path(item["file"])
        if path.is_absolute() or ".." in path.parts or not item["file"]:
            raise ValueError("Invalid finding path")
        if type(item["line"]) is not int or item["line"] < 1:
            raise ValueError("Invalid finding line")
        if any(not isinstance(item[key], str) or not 1 <= len(item[key]) <= 4000 for key in ("file", "title", "reason")):
            raise ValueError("Invalid finding text")
    return result, any(item["severity"] != "low" for item in findings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("head")
    parser.add_argument("number", type=int)
    parser.add_argument("--github-output", type=Path,
                        help="Mark valid output safe for upload; enforce the blocking verdict after upload")
    args = parser.parse_args()
    try:
        result, blocked = validate(args.file, args.head, args.number)
        print(f"Review pass {result['pass']}: {len(result['findings'])} finding(s); " + ("blocked" if blocked else "passed"))
        if args.github_output is not None:
            with args.github_output.open("a") as output:
                output.write(f"safe=true\nblocked={str(blocked).lower()}\n")
            return 0
        # Full bounded JSON remains an artifact. Never execute or interpolate model text.
        return 1 if blocked else 0
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f"Invalid review output: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
