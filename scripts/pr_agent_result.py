#!/usr/bin/env python3
"""Adapt file-only reviewer output to the trusted, bounded review schema."""
import codecs
import html
import json
import re
import sys
import unicodedata
from pathlib import Path, PureWindowsPath


KEY = re.compile(
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]+|gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|"
    r"xox[a-z]-[A-Za-z0-9_-]+|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|"
    r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    re.I,
)
SECURITY = re.compile(
    r"\b(security|insecure|vulnerabil\w*|auth(?:entication|orization|enticate|orize|n|z)?|"
    r"unauthorized|unauthenticated|injection|xss|csrf|ssrf|rce|"
    r"secret\w*|credential\w*|password\w*|privilege\w*|permission\w*|exploit\w*|exfiltrat\w*)\b|"
    r"path traversal|access control|cross.site|(?:remote|arbitrary) code execution|data leak|"
    r"information disclosure|denial.of.service|(?:token|api key).*(?:leak|expos)",
    re.I,
)
COVERAGE = re.compile(
    r"\*\*Review coverage:\*\* The following files were not included in this review because of the token budget|"
    r"had patches clipped before analysis to fit the token budget|chunk\(s\) failed and are not covered"
)
MAX_OUTPUT_TOKENS = 16_000
URL_TOKEN = re.compile(
    r"(?:(?<!\w)[a-z][a-z0-9+.-]*\s*:\s*[/\\]\s*[/\\]|(?<!\w)(?:https?|hxxps?|ftp|file|javascript|data|mailto)\s*:\s*|"
    r"(?<!\w)[a-z][a-z0-9+.-]*:(?=\S|$)|//|www\.|(?<!\w)(?:[\w-]+\.)+[\w-]+\.?(?::[0-9]+)?[/\\])[^\s<>]*", re.I
)


def check_sanitized(value):
    # Deliberately separate from URL_TOKEN: check the actual returned text,
    # including incomplete URL prefixes and markup assembled by earlier removals.
    if (any(char in value for char in "<>@")
            or re.search(r"(?<!\w)[a-z][a-z0-9+.-]*:(?=\S|$)|(?:https?|hxxps?|ftp|file|javascript|data|mailto)\s*:|"
                         r":\s*[/\\]|www\s*\.|//|(?<!\w)(?:[\w-]+\.)+[\w-]+\.?(?::[0-9]+)?[/\\]", value, re.I)):
        raise Incomplete("unsafe sanitized text")


class Incomplete(ValueError):
    pass


def read(file, limit=4_000_000):
    file = Path(file)
    if file.is_symlink() or not file.is_file() or file.stat().st_size > limit:
        raise Incomplete("missing, unsafe, or oversized input")
    with file.open(encoding="utf-8", newline="") as source:
        return source.read()


def model_string(value):
    if not isinstance(value, str):
        raise Incomplete("invalid finding text")
    return value.strip()


def strip_markdown_links(value):
    references = set()

    def remove_definition(match):
        references.add(" ".join(match[1].split()).casefold())
        return ""

    value = re.sub(r"(?m)^[ \t]{0,3}\[([^\]\r\n]+)\]:[^\r\n]*", remove_definition, value)
    pairs, stacks = {}, {"[": [], "(": []}
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char in stacks:
            stacks[char].append(index)
        elif char in "])":
            stack = stacks["[" if char == "]" else "("]
            if stack:
                pairs[stack.pop()] = index

    def render(start, end, depth=0):
        if depth > 100:
            raise Incomplete("excessive markup nesting")
        pieces = []
        index = start
        while index < end:
            image = value.startswith("![", index)
            opening = index + 1 if image else index
            closing = pairs.get(opening)
            if value[opening:opening + 1] == "[" and closing is not None and closing < end:
                target = closing + 1
                while target < end and value[target].isspace():
                    target += 1
                target_end = pairs.get(target) if value[target:target + 1] in ("(", "[") else None
                reference = " ".join(value[opening + 1:closing].split()).casefold() in references
                if target_end is not None and target_end < end or image or reference:
                    if not image:
                        pieces.append(render(opening + 1, closing, depth + 1))
                    index = target_end + 1 if target_end is not None and target_end < end else closing + 1
                    continue
            pieces.append(value[index])
            index += 1
        return "".join(pieces)

    return render(0, len(value))


def sanitize(value):
    # Decode before removing markup so nested entities cannot hide a link or ping.
    for _ in range(8):
        decoded = html.unescape(value)
        if decoded == value:
            break
        value = decoded
    value = unicodedata.normalize("NFKC", value)
    value = "".join(char for char in value if unicodedata.category(char) != "Cf"
                    and char != "\u034f" and not "\ufe00" <= char <= "\ufe0f"
                    and not "\U000e0100" <= char <= "\U000e01ef")
    for _ in range(8):
        previous = value
        value = re.sub(r"<[^>]*>", "", value)
        value = re.sub(r"&(?:#[xX][0-9a-fA-F]+|#[0-9]+|[a-zA-Z][a-zA-Z0-9]+);?", "", value)
        value = value.translate(str.maketrans("", "", "<>@"))
        value = strip_markdown_links(value)
        if value != previous:
            continue
        value = URL_TOKEN.sub("", value)
        if value == previous:
            check_sanitized(value)
            return value.strip()
    raise Incomplete("excessive markup nesting")


def text(value):
    value = model_string(value)
    if not value:
        raise Incomplete("invalid finding text")
    value = sanitize(value)
    if not value:
        raise Incomplete("finding text removed during sanitization")
    value = KEY.sub("[redacted]", value)[:4000]
    check_sanitized(value)
    return value


def json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Incomplete("duplicate JSON fields")
        value[key] = item
    return value


def invalid_constant(value):
    raise Incomplete("invalid JSON constant")


def read_json(file, limit=4_000_000):
    return json.loads(read(file, limit), object_pairs_hook=json_object, parse_constant=invalid_constant)


def path(value, manifest):
    # File identity is never prose: do not strip, normalize, redact or truncate it.
    if isinstance(value, str) and 1 <= len(value) <= 4000:
        for item in manifest:
            for name in (item["source"], item["target"]):
                if value == name:
                    return safe_patch_path(name)
    raise Incomplete("finding path does not exactly match the changed-file manifest")


def git_path(value):
    if value.startswith('"'):
        if not re.fullmatch(r'"(?:[^"\\]|\\(?:[0-3][0-7]{2}|[abfnrtv\\"]))+"', value):
            raise Incomplete("unsupported changed-file path")
        value = codecs.escape_decode(value[1:-1].encode("utf-8"))[0].decode("utf-8")
    elif '"' in value or "\\" in value:
        raise Incomplete("unsupported changed-file path")
    return value


def safe_patch_path(value):
    if (not isinstance(value, str) or not value or "\x00" in value
            or ".." in re.split(r"[/\\]", value) or Path(value).is_absolute()
            or PureWindowsPath(value).drive or PureWindowsPath(value).root):
        raise Incomplete("unsafe changed-file path")
    value.encode("utf-8", errors="strict")
    return value


def patch_path(value, prefix):
    value = git_path(value)
    if value == "/dev/null":
        return None
    if not value.startswith(prefix):
        raise Incomplete("unsupported changed-file path")
    return safe_patch_path(value[2:])


def check_patch(patch, manifest):
    """Reconcile every raw block and hunk with independent compare-API data."""
    if not isinstance(manifest, list) or not 1 <= len(manifest) <= 200:
        raise Incomplete("missing or invalid changed-file manifest")
    expected = {}
    for item in manifest:
        if not isinstance(item, dict):
            raise Incomplete("invalid changed-file manifest")
        source, target = item.get("source"), item.get("target")
        for name in (source, target):
            if name is not None:
                safe_patch_path(name)
        status = item.get("status")
        if (status not in ("added", "removed", "modified", "renamed")
                or (source is None) != (status == "added")
                or (target is None) != (status == "removed")
                or (status == "modified" and source != target)
                or any(type(item.get(key)) is not int or item[key] < 0 for key in ("additions", "deletions"))
                or type(item.get("has_patch")) is not bool):
            raise Incomplete("invalid changed-file manifest")
        key = target if target is not None else source
        if key in expected:
            raise Incomplete("duplicate changed-file manifest entry")
        expected[key] = item
    seen = set()
    blocks = re.split(r"(?m)(?=^diff --git )", patch)
    if blocks[0].strip():
        raise Incomplete("unsupported change preamble")
    for block in blocks[1:]:
        # Git patch records use LF; other Unicode separators can be source data.
        lines = block.removesuffix("\n").split("\n")
        header = re.fullmatch(r'diff --git ("(?:[^"\\]|\\.)*"|a/.*?) ("(?:[^"\\]|\\.)*"|b/.*)', lines[0])
        if not header:
            raise Incomplete("unsupported change header")
        old, new = patch_path(header[1], "a/"), patch_path(header[2], "b/")
        key = new
        # Git deletion headers still name b/path; /dev/null occurs only in +++.
        item = expected.get(key)
        if item is None or key in seen or old != (item["source"] or item["target"]) or new != (item["target"] or item["source"]):
            raise Incomplete("change does not match the file manifest")
        seen.add(key)
        metadata, hunk_lines = [], []
        missing = object()
        source = target = missing
        for index, line in enumerate(lines[1:], 1):
            if line.startswith("@@"):
                hunk_lines = lines[index:]
                break
            if line.startswith("--- "):
                if source is not missing:
                    raise Incomplete("duplicate change header")
                source = patch_path(line[4:].split("\t", 1)[0], "a/")
            elif line.startswith("+++ "):
                if target is not missing:
                    raise Incomplete("duplicate change header")
                target = patch_path(line[4:].split("\t", 1)[0], "b/")
            else:
                metadata.append(line)
        if source is not missing or target is not missing:
            if (source, target) != (item["source"], item["target"]):
                raise Incomplete("change paths do not match the file manifest")
        for line in metadata:
            if line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
                marker = next(marker for marker in ("rename from ", "rename to ", "copy from ", "copy to ") if line.startswith(marker))
                name = safe_patch_path(git_path(line[len(marker):]))
                if not marker.startswith("rename") or name != item["source" if marker.endswith("from ") else "target"]:
                    raise Incomplete("unsupported rename metadata")
        binary = [line for line in metadata if line.startswith(("Binary files ", "GIT binary patch"))]
        if binary:
            binary_source = header[1] if item["source"] is not None else "/dev/null"
            binary_target = header[2] if item["target"] is not None else "/dev/null"
            binary_header = f"Binary files {binary_source} and {binary_target} differ"
            if (hunk_lines or item["has_patch"] or item["additions"] or item["deletions"]
                    or binary != [binary_header]):
                raise Incomplete("unsupported binary change")
        if hunk_lines:
            if (source, target) != (item["source"], item["target"]):
                raise Incomplete("missing hunk file headers")
            added = deleted = remaining_old = remaining_new = 0
            for line in hunk_lines:
                if line.startswith("@@"):
                    if remaining_old or remaining_new:
                        raise Incomplete("clipped change hunk")
                    match = re.fullmatch(r"@@ -[0-9]+(?:,([0-9]+))? \+[0-9]+(?:,([0-9]+))? @@.*", line)
                    if not match:
                        raise Incomplete("unsupported change hunk")
                    remaining_old = int(match[1]) if match[1] is not None else 1
                    remaining_new = int(match[2]) if match[2] is not None else 1
                elif line.startswith("+"):
                    added += 1
                    remaining_new -= 1
                elif line.startswith("-"):
                    deleted += 1
                    remaining_old -= 1
                elif line.startswith(" "):
                    remaining_old -= 1
                    remaining_new -= 1
                elif line != "\\ No newline at end of file":
                    raise Incomplete("unsupported change hunk content")
                if remaining_old < 0 or remaining_new < 0:
                    raise Incomplete("invalid change hunk counts")
            if remaining_old or remaining_new or (added, deleted) != (item["additions"], item["deletions"]):
                raise Incomplete("change hunks do not match the file manifest")
        else:
            renamed = (item["status"] == "renamed"
                       and sum(line.startswith("rename from ") for line in metadata) == 1
                       and sum(line.startswith("rename to ") for line in metadata) == 1)
            modes = [line for line in metadata if re.fullmatch(r"(?:old|new) mode 100(?:644|755)", line)]
            mode_change = (item["status"] == "modified" and len(modes) == 2
                           and modes[0].startswith("old ") and modes[1].startswith("new ")
                           and modes[0][9:] != modes[1][9:]
                           and modes[0][9:] == item.get("old_mode") and modes[1][9:] == item.get("new_mode"))
            empty_file = ((item["status"] == "added" and item.get("new_mode") in ("100644", "100755", "120000")
                           and f"new file mode {item['new_mode']}" in metadata)
                          or (item["status"] == "removed" and item.get("old_mode") in ("100644", "100755", "120000")
                              and f"deleted file mode {item['old_mode']}" in metadata))
            if item["additions"] or item["deletions"] or not (binary or renamed or mode_change or empty_file):
                raise Incomplete("missing change hunks or verified metadata")
    if seen != set(expected):
        raise Incomplete("changed files are missing from the patch")


def check_termination(skipped_file):
    reasons = read(Path(skipped_file).with_name("reviewer-finish-reasons.txt"), 64_000)
    if not re.fullmatch(r"(?:stop\n)+", reasons):
        raise Incomplete("model termination was missing or incomplete")


def check_skipped(patch, skipped_file):
    skipped = read_json(skipped_file)
    if not isinstance(skipped, list) or any(not isinstance(name, str) or not name for name in skipped):
        raise Incomplete("invalid skipped-file list")
    if not skipped:
        return
    unmatched = set(skipped)
    for block in re.split(r"(?m)(?=^diff --git )", patch):
        if not block.startswith("diff --git "):
            continue
        lines = block.splitlines()
        source = target = None
        hunks = False
        for line in lines[1:]:
            if line.startswith("@@ "):
                hunks = True
                break
            if line.startswith("--- "):
                source = line[4:].split("\t", 1)[0]
            elif line.startswith("+++ "):
                target = line[4:].split("\t", 1)[0]
        value = source if target == "/dev/null" else target
        if value is None:
            header = re.fullmatch(r'diff --git ("(?:[^"\\]|\\.)*"|a/.*?) ("(?:[^"\\]|\\.)*"|b/.*)', lines[0])
            if not header:
                raise Incomplete("unsupported skipped-file patch")
            value = header[2]
        name = git_path(value)
        if not name.startswith(("a/", "b/")):
            raise Incomplete("unsupported skipped-file path")
        name = name[2:]
        if name in skipped:
            if hunks:
                raise Incomplete("reviewer skipped changed text files")
            unmatched.discard(name)
    if unmatched:
        raise Incomplete("skipped-file list does not match the change")


def first_changed_file(patch, manifest):
    header = re.search(r'(?m)^diff --git ("(?:[^"\\]|\\.)*"|a/.*?) ("(?:[^"\\]|\\.)*"|b/.*)$', patch)
    if not header:
        raise Incomplete("missing or unsupported change header")
    return path(patch_path(header[2], "b/"), manifest)


def exit_code(value):
    value = str(value)
    if not re.fullmatch(r"-?[0-9]+", value):
        value = read(value, 100).strip()
    if not re.fullmatch(r"-?[0-9]+", value) or int(value) != 0:
        raise Incomplete("reviewer exit code is missing or non-zero")


def adapt(review_json, review_markdown, reviewer_exit, context, patch, skipped_file, head, number):
    result = {"head": head, "pass": number, "complete": False, "summary": "Incomplete review.", "findings": []}
    try:
        if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head) or type(number) is not int or number < 1:
            raise Incomplete("invalid trusted review identity")
        identity = read_json(context, 1_000_000)
        if (not isinstance(identity, dict) or identity.get("head") != head
                or type(identity.get("pass", number)) is not int or identity.get("pass", number) != number):
            raise Incomplete("context does not match the trusted review identity")
        exit_code(reviewer_exit)
        check_termination(skipped_file)
        markdown = read(review_markdown)
        if not markdown.strip() or COVERAGE.search(markdown):
            raise Incomplete("review coverage is missing or limited")
        patch = read(patch)
        if not re.search(r"(?m)^diff --git ", patch):
            raise Incomplete("missing change headers")
        check_patch(patch, identity.get("files"))
        check_skipped(patch, skipped_file)
        payload = read_json(review_json)
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if usage is not None:
            if (not isinstance(usage, dict) or ("completion_tokens" in usage
                    and (type(usage["completion_tokens"]) is not int or usage["completion_tokens"] < 0
                         or usage["completion_tokens"] >= MAX_OUTPUT_TOKENS))):
                raise Incomplete("model output token usage was invalid or limited")
        review = payload.get("review") if isinstance(payload, dict) else None
        if not isinstance(review, dict) or not isinstance(review.get("key_issues_to_review"), list):
            raise Incomplete("unexpected review JSON shape")
        issues = review["key_issues_to_review"]
        if len(issues) > 50:
            raise Incomplete("more than 50 findings")
        findings = []
        for issue in issues:
            if not isinstance(issue, dict):
                raise Incomplete("unexpected finding shape")
            header, content = model_string(issue.get("issue_header")), model_string(issue.get("issue_content"))
            title, reason = text(header), text(content)
            line = issue.get("start_line")
            findings.append({
                "severity": "high" if SECURITY.search(header + " " + content) else "medium",
                "file": path(issue.get("relevant_file"), identity["files"]),
                "line": line if type(line) is int and line >= 1 else 1,
                "title": title, "reason": reason,
            })
        concern = review.get("security_concerns")
        if not isinstance(concern, str):
            raise Incomplete("unexpected security concern shape")
        concern = model_string(concern)
        if concern and not re.fullmatch(r"no\.?", concern, re.I) and not any(item["severity"] == "high" for item in findings):
            findings.append({"severity": "high", "file": first_changed_file(patch, identity["files"]), "line": 1,
                             "title": "Security concern", "reason": text(concern)})
        if len(findings) > 50:
            raise Incomplete("more than 50 findings including the security concern")
        result.update(complete=True, summary=f"Reviewed the supplied change; {len(findings)} finding(s).", findings=findings)
        if len((json.dumps(result) + "\n").encode("utf-8")) > 64_000:
            raise Incomplete("review output exceeds 64000 bytes")
    except Incomplete as error:
        result.update(complete=False, summary=f"Incomplete review: {error}.", findings=[])
    except Exception:
        # Never copy exception text: parsing errors can contain model output.
        result.update(complete=False, summary="Incomplete review: missing, malformed, or unexpected input.", findings=[])
    result["summary"] = text(result["summary"])
    return result


def main():
    review_json, markdown, reviewer_exit, context, patch, skipped_file, head, number, output = sys.argv[1:]
    try:
        number = int(number)
    except ValueError:
        number = 0
    result = adapt(review_json, markdown, reviewer_exit, context, patch, skipped_file, head, number)
    Path(output).write_text(json.dumps(result) + "\n", encoding="utf-8")
    print(f"Review: {len(result['findings'])} finding(s); " + ("complete" if result["complete"] else "incomplete"))


if __name__ == "__main__":
    main()
