#!/usr/bin/env python3
"""Validate bounded AI output before it is used in a required status."""
import html
import json
import os
import re
import stat
import sys
from pathlib import Path


SUMMARY_LIMIT = 16 * 1024
SUMMARY_MARKER = "[truncated]\n"
CREDENTIAL = re.compile(
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]+|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|"
    r"xox[a-z]-[A-Za-z0-9_-]+|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|"
    r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    re.I,
)
SCHEME = re.compile(r"(?i)(https?|hxxps?|ftp|file|javascript|data|mailto)\s*:\s*[/\\]\s*[/\\]")
FIELDS = ("severity", "file", "line", "title", "reason")


def validate(file, head, number):
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 64_000:
        raise ValueError("Missing, unsafe, or oversized review output")
    result = json.loads(file.read_text())
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


def longest_backtick_run(value):
    longest = run = 0
    for char in value:
        if char == "`":
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return longest


def fence_for(value):
    return "`" * max(3, longest_backtick_run(value) + 1)


def inert(value):
    if not isinstance(value, str):
        value = str(value)
    value = CREDENTIAL.sub("[redacted]", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    value = value.replace("@", "(at)")
    value = value.replace("](", "] (").replace("][", "] [").replace("![", "! [")
    value = SCHEME.sub(lambda match: match.group(1) + ": //", value)
    value = re.sub(r"(?i)www\.", "www .", value)
    return html.escape(value, quote=True)


def fenced_field(key, value, budget=None):
    body = inert(value)
    fence = fence_for(body)
    prefix = f"{key}\n\n{fence}\n"
    suffix = f"\n{fence}\n\n"
    if budget is None:
        return prefix + body + suffix
    fixed = len(prefix.encode("utf-8")) + len(suffix.encode("utf-8"))
    if fixed > budget or budget < 0:
        return ""
    raw = body.encode("utf-8")
    room = budget - fixed
    if len(raw) > room:
        body = raw[:room].decode("utf-8", errors="ignore")
    text = prefix + body + suffix
    if len(text.encode("utf-8")) > budget:
        return ""
    return text


def render_finding(index, item, budget=None):
    heading = f"### Finding {index}\n\n"
    if budget is None:
        return heading + "".join(fenced_field(key, item[key]) for key in FIELDS)
    heading_len = len(heading.encode("utf-8"))
    if heading_len > budget:
        return ""
    parts = [heading]
    size = heading_len
    for key in FIELDS:
        field = fenced_field(key, item[key])
        field_len = len(field.encode("utf-8"))
        if size + field_len <= budget:
            parts.append(field)
            size += field_len
            continue
        partial = fenced_field(key, item[key], budget - size)
        if partial:
            parts.append(partial)
        break
    return "".join(parts)


def render_blocking_summary(findings):
    blocking = sum(item["severity"] != "low" for item in findings)
    header = f"\n## Blocking review findings\n\n{blocking} blocking finding(s).\n\n"
    rendered = [render_finding(index, item) for index, item in enumerate(findings, 1)]
    full = header + "".join(rendered)
    if len(full.encode("utf-8")) <= SUMMARY_LIMIT:
        text = full
    else:
        budget = SUMMARY_LIMIT - len(SUMMARY_MARKER.encode("utf-8"))
        parts = [header]
        size = len(header.encode("utf-8"))
        if size > budget:
            text = SUMMARY_MARKER
        else:
            for index, item in enumerate(findings, 1):
                block = rendered[index - 1]
                block_len = len(block.encode("utf-8"))
                if size + block_len <= budget:
                    parts.append(block)
                    size += block_len
                    continue
                partial = render_finding(index, item, budget - size)
                if partial:
                    parts.append(partial)
                parts.append(SUMMARY_MARKER)
                break
            else:
                parts.append(SUMMARY_MARKER)
            text = "".join(parts)
    if len(text.encode("utf-8")) > SUMMARY_LIMIT or any(char in text for char in "<>@"):
        return SUMMARY_MARKER
    return text


def summary_destination():
    raw = os.environ.get("GITHUB_STEP_SUMMARY")
    if not isinstance(raw, str) or not raw or any(char in raw for char in "\n\r\x00"):
        return None
    path = Path(raw)
    try:
        info = path.lstat()
    except OSError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return None
    return path


def publish_blocking_findings(result):
    # Validated finding fields only. Do not publish the result summary or other inputs.
    text = render_blocking_summary(result["findings"])
    path = summary_destination()
    if path is None:
        return
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return
    data = text.encode("utf-8")
    try:
        while data:
            written = os.write(fd, data)
            if written <= 0:
                break
            data = data[written:]
    except OSError:
        return
    finally:
        os.close(fd)


def main():
    try:
        result, blocked = validate(Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]))
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f"Invalid review output: {error}", file=sys.stderr)
        sys.exit(1)
    print(f"Review pass {result['pass']}: {len(result['findings'])} finding(s); " + ("blocked" if blocked else "passed"))
    # Stdout stays a count. Blocking findings are appended only as inert summary text.
    if blocked:
        try:
            publish_blocking_findings(result)
        except Exception:
            pass
    sys.exit(1 if blocked else 0)


if __name__ == "__main__":
    main()
