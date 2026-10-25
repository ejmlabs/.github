#!/usr/bin/env python3
"""Adapt file-only reviewer output to the trusted, bounded review schema."""
import codecs
import html
import json
import re
import sys
import unicodedata
import xml.parsers.expat as expat
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
# Build-generated workflows verified by scripts/build_workflows.py --check.
# Exclusion applies only for ejmlabs/.github (see github_profile).
EXCLUDED_REVIEW_PATHS = frozenset({
    ".github/workflows/governance.yml",
    ".github/workflows/draft-release.yml",
})
def github_profile(repository):
    return repository == "ejmlabs/.github"


def is_svg_name(name):
    base = name.rsplit("/", 1)[-1]
    return "." in base and base.rsplit(".", 1)[-1].lower() == "svg"


# Fixed public codes. They do not mean the skipped file was model-reviewed.
LOCK_COVERAGE = "covered by check: lock-manifest-mirror v1"
SVG_COVERAGE = "covered by check: svg-allowlist v1"
ASSET_SVG_DIR = "packages/tokens/assets/"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
SVG_ELEMENTS = frozenset("svg g path rect circle ellipse line polyline polygon text tspan title desc".split())
# Minimal set that covers the asset SVGs shipped with a one-line lock mirror.
SVG_ATTRS = frozenset(
    "aria-label d fill font-family font-size font-weight height role rx transform viewBox width x y".split()
)
SVG_TEXT = frozenset("text tspan title desc".split())
DEP_MAPS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
SVG_BYTE_LIMIT = 131072
BLOB_BYTE_LIMIT = 4_000_000


class _NoArchive(Exception):
    """The head archive directory is not present, so blob reads are unavailable."""


def excluded_manifest_item(item):
    """True when a manifest entry is an exact generated-path add/remove/modify."""
    source, target = item.get("source"), item.get("target")
    status = item.get("status")
    if status == "modified":
        return source == target and source in EXCLUDED_REVIEW_PATHS
    if status == "added":
        return source is None and target in EXCLUDED_REVIEW_PATHS
    if status == "removed":
        return target is None and source in EXCLUDED_REVIEW_PATHS
    return False


def strip_excluded_review_paths(patch, repository=None):
    """Remove exact build-generated paths for the .github profile only."""
    if not github_profile(repository):
        return patch, []
    blocks = re.split(r"(?m)(?=^diff --git )", patch)
    kept = [blocks[0]]
    excluded = []
    for block in blocks[1:]:
        lines = block.splitlines()
        header = re.fullmatch(r'diff --git ("(?:[^"\\]|\\.)*"|a/.*?) ("(?:[^"\\]|\\.)*"|b/.*)', lines[0])
        if not header:
            raise Incomplete("unsupported change header")
        old, new = patch_path(header[1], "a/"), patch_path(header[2], "b/")
        metadata = []
        for line in lines[1:]:
            if line.startswith("@@"):
                break
            metadata.append(line)
        renamed_or_copied = any(line.startswith(("rename from ", "rename to ", "copy from ", "copy to "))
                                for line in metadata)
        touches = {name for name in (old, new) if name in EXCLUDED_REVIEW_PATHS}
        if renamed_or_copied and touches:
            raise Incomplete("unsupported change to a generated review path")
        if renamed_or_copied:
            kept.append(block)
            continue
        # Exact modified (old == new == path), or pure add/remove of that path
        # (git headers name a/path and b/path even for add/remove).
        if old is not None and old == new and old in EXCLUDED_REVIEW_PATHS:
            excluded.append(old)
            continue
        if touches:
            raise Incomplete("unsupported change to a generated review path")
        kept.append(block)
    return "".join(kept), excluded


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
    # Preserve exact Git names first; retry only YAML block/folded scalar line breaks.
    if isinstance(value, str) and 1 <= len(value) <= 4000:
        for candidate in (value, re.sub(r"(?:\r?\n)+\Z", "", value)):
            for item in manifest:
                for name in (item["source"], item["target"]):
                    if candidate == name:
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


def check_patch(patch, manifest, repository=None):
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
    missing = set(expected) - seen
    allowed_missing = set()
    if github_profile(repository):
        for name in missing:
            item = expected[name]
            if excluded_manifest_item(item):
                allowed_missing.add(name)
    if seen != set(expected) - allowed_missing:
        raise Incomplete("changed files are missing from the patch")


def check_termination(skipped_file):
    reasons = read(Path(skipped_file).with_name("reviewer-finish-reasons.txt"), 64_000)
    if not re.fullmatch(r"(?:stop\n)+", reasons):
        raise Incomplete("model termination was missing or incomplete")


def svg_skip_allowed(lines, item):
    """Allow skipped SVG text only for deleted 100644 files (no rename/copy, no '+' hunk lines)."""
    if not isinstance(item, dict) or item.get("status") != "removed":
        return False
    metadata, hunk_body = [], []
    in_hunk = False
    for line in lines[1:]:
        if line.startswith("@@"):
            in_hunk = True
            continue
        if in_hunk:
            hunk_body.append(line)
        else:
            metadata.append(line)
    if any(line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")) for line in metadata):
        return False
    # Count only hunk-body lines so '+++ ' file headers cannot be confused with content.
    if any(line.startswith("+") for line in hunk_body):
        return False
    if item.get("old_mode") != "100644" or "deleted file mode 100644" not in metadata:
        return False
    return True


def read_blob(root, name, limit):
    """Read one archive blob. Refuse links, escapes, and oversize files."""
    safe_patch_path(name)
    root = Path(root)
    if not root.exists() and not root.is_symlink():
        raise _NoArchive()
    if root.is_symlink() or not root.is_dir():
        raise Incomplete("missing head blob")
    path = root
    for part in name.split("/"):
        path = path / part
        if path.is_symlink():
            raise Incomplete("missing head blob")
    if not path.is_file():
        raise Incomplete("missing head blob")
    if path.stat().st_size > limit:
        raise Incomplete("oversized head blob")
    data = path.read_bytes()
    if len(data) > limit:
        raise Incomplete("oversized head blob")
    return data


def parse_hunks(lines):
    hunks, current = [], None
    for line in lines:
        if line.startswith("@@"):
            match = re.fullmatch(r"@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@.*", line)
            if not match:
                raise Incomplete("unsupported change hunk")
            current = {"old_start": int(match[1]), "old_len": int(match[2]) if match[2] is not None else 1,
                       "new_start": int(match[3]), "new_len": int(match[4]) if match[4] is not None else 1, "lines": []}
            hunks.append(current)
        elif current is None or not line.startswith(("+", "-", " ", "\\")):
            raise Incomplete("unsupported change hunk")
        else:
            current["lines"].append(line)
    if not hunks:
        raise Incomplete("unsupported change hunk")
    return hunks


def hunk_records(hunk):
    records = []
    for line in hunk["lines"]:
        if line.startswith("\\"):
            if line != "\\ No newline at end of file" or not records or records[-1][2]:
                raise Incomplete("unsupported change hunk")
            kind, text, _flag = records[-1]
            records[-1] = (kind, text, True)
        elif line[:1] in "+- ":
            records.append((line[0], line[1:], False))
        else:
            raise Incomplete("unsupported change hunk")
    new_count = sum(kind != "-" for kind, _text, _flag in records)
    old_count = sum(kind != "+" for kind, _text, _flag in records)
    if new_count != hunk["new_len"] or old_count != hunk["old_len"]:
        raise Incomplete("invalid change hunk")
    return records


def reverse_apply(data, hunks):
    """Rebuild base bytes by reversing a unified diff that matches this head blob."""
    text = data.decode("utf-8")
    if text == "":
        lines, ends = [], False
    else:
        ends = text.endswith("\n")
        lines = text[:-1].split("\n") if ends else text.split("\n")
    index, base = 0, []
    for hunk in hunks:
        records = hunk_records(hunk)
        end = hunk["new_start"] if hunk["new_len"] == 0 else hunk["new_start"] - 1
        if end < index or end > len(lines):
            raise Incomplete("patch does not match head blob")
        for cursor in range(index, end):
            base.append((lines[cursor], cursor == len(lines) - 1 and not ends))
        index = end
        for kind, content, nonl in records:
            if kind in "+ ":
                last = index == len(lines) - 1
                if index >= len(lines) or lines[index] != content or nonl != (last and not ends):
                    raise Incomplete("patch does not match head blob")
                index += 1
            if kind in "- ":
                base.append((content, nonl))
    if index > len(lines):
        raise Incomplete("patch does not match head blob")
    for cursor in range(index, len(lines)):
        base.append((lines[cursor], cursor == len(lines) - 1 and not ends))
    if any(nonl for _content, nonl in base[:-1]):
        raise Incomplete("patch does not match head blob")
    if not base:
        return b""
    merged = "\n".join(content for content, _nonl in base)
    if not base[-1][1]:
        merged += "\n"
    return merged.encode("utf-8")


def reconstruct_new(hunks, added):
    """Full new file from one hunk. Used only when the head archive is absent."""
    if len(hunks) != 1:
        raise Incomplete("partial svg")
    hunk, records = hunks[0], hunk_records(hunks[0])
    if any(kind == " " for kind, _text, _flag in records):
        raise Incomplete("partial svg")
    pluses = [(text, nonl) for kind, text, nonl in records if kind == "+"]
    if added:
        if (hunk["old_start"], hunk["old_len"], hunk["new_start"]) != (0, 0, 1):
            raise Incomplete("partial svg")
        if any(kind != "+" for kind, _text, _flag in records):
            raise Incomplete("partial svg")
    elif hunk["old_start"] != 1 or hunk["new_start"] != 1 or not pluses or not any(kind == "-" for kind, _t, _f in records):
        raise Incomplete("partial svg")
    if not pluses or any(nonl for _text, nonl in pluses[:-1]):
        raise Incomplete("partial svg")
    merged = "\n".join(text for text, _nonl in pluses)
    if not pluses[-1][1]:
        merged += "\n"
    data = merged.encode("utf-8")
    if len(data) > SVG_BYTE_LIMIT:
        raise Incomplete("oversized head blob")
    return data


def load_json_object(data):
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=json_object, parse_constant=invalid_constant)
    except Incomplete:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise Incomplete("invalid json")
    if not isinstance(value, dict):
        raise Incomplete("invalid json")
    return value


def string_map(value):
    return isinstance(value, dict) and all(isinstance(key, str) and isinstance(item, str) for key, item in value.items())


def mirror_lock(base, head, package_json):
    for key in ("name", "version", "lockfileVersion", "requires"):
        if (key in base) != (key in head) or base.get(key) != head.get(key):
            raise Incomplete("lock changed")
    packages = base.get("packages")
    head_packages = head.get("packages")
    if not isinstance(packages, dict) or not isinstance(head_packages, dict):
        raise Incomplete("lock shape")
    if not isinstance(packages.get(""), dict) or not isinstance(head_packages.get(""), dict):
        raise Incomplete("lock shape")
    base_rest = {key: item for key, item in base.items() if key != "packages"}
    head_rest = {key: item for key, item in head.items() if key != "packages"}
    base_rest["packages"] = {key: item for key, item in packages.items() if key != ""}
    head_rest["packages"] = {key: item for key, item in head_packages.items() if key != ""}
    if base_rest != head_rest:
        raise Incomplete("lock changed")
    base_root, head_root = packages[""], head_packages[""]
    if not isinstance(package_json, dict):
        raise Incomplete("manifest mismatch")
    static = set(base_root) - set(DEP_MAPS)
    if static != set(head_root) - set(DEP_MAPS):
        raise Incomplete("lock changed")
    for key in static:
        if base_root[key] != head_root[key]:
            raise Incomplete("lock changed")
    for key in DEP_MAPS:
        if (key in head_root) != (key in package_json):
            raise Incomplete("manifest mismatch")
        if key in head_root and (not string_map(head_root[key]) or head_root[key] != package_json[key]):
            raise Incomplete("manifest mismatch")
        if key in base_root and not string_map(base_root[key]):
            raise Incomplete("lock changed")


def sibling_manifest(manifest, name):
    parent, _slash, base = name.rpartition("/")
    if base != "package-lock.json":
        return None, None
    sibling = parent + "/package.json" if parent else "package.json"
    if not isinstance(manifest, list):
        return None, sibling
    for item in manifest:
        if not isinstance(item, dict) or item.get("target") != sibling or item.get("status") not in ("added", "modified"):
            continue
        if item.get("status") == "modified" and item.get("source") != sibling:
            continue
        if item.get("status") == "added" and item.get("source") is not None:
            continue
        return item, sibling
    return None, sibling


def block_hunks(patch, wanted):
    for block in re.split(r"(?m)(?=^diff --git )", patch):
        if not block.startswith("diff --git "):
            continue
        lines = block.splitlines()
        source = target = None
        hunk_at = None
        for index, line in enumerate(lines[1:], 1):
            if line.startswith("@@ "):
                hunk_at = index
                break
            if line.startswith("--- "):
                source = line[4:].split("\t", 1)[0]
            elif line.startswith("+++ "):
                target = line[4:].split("\t", 1)[0]
        value = source if target == "/dev/null" else target
        if value is None:
            continue
        name = git_path(value)
        if name.startswith(("a/", "b/")) and name[2:] == wanted and hunk_at is not None:
            return parse_hunks(lines[hunk_at:])
    return None


def metadata_lines(lines):
    meta = []
    for line in lines[1:]:
        if line.startswith("@@"):
            break
        meta.append(line)
    return meta


def modes_are_plain(meta):
    for line in meta:
        if line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            return False
        for prefix in ("old mode ", "new mode ", "new file mode ", "deleted file mode "):
            if line.startswith(prefix) and line[len(prefix):] != "100644":
                return False
        if line.startswith("index ") and len(line.split()) >= 3 and line.split()[-1] != "100644":
            return False
    return True


def asset_svg_path(name):
    if not isinstance(name, str) or not name.endswith(".svg") or "\\" in name or "\x00" in name:
        return False
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    return name.startswith(ASSET_SVG_DIR)


def parse_svg(data):
    if not isinstance(data, (bytes, bytearray)) or len(data) > SVG_BYTE_LIMIT or data.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise Incomplete("svg rejected")
    text = data.decode("utf-8")
    parser, stack, seen_root = expat.ParserCreate(), [], False

    def reject():
        raise Incomplete("svg rejected")

    def start(name, attrs):
        nonlocal seen_root
        if name not in SVG_ELEMENTS or ":" in name:
            reject()
        for key, value in attrs.items():
            if key == "xmlns":
                if stack or value != SVG_NAMESPACE:
                    reject()
                continue
            if key == "xmlns:xlink":
                if value != XLINK_NAMESPACE:
                    reject()
                continue
            lowered = key.lower()
            if key not in SVG_ATTRS or ":" in key or lowered in ("href", "style"):
                reject()
            folded = value.lower()
            if "url(" in folded or "javascript:" in folded or "data:" in folded:
                reject()
        if not stack:
            if name != "svg" or attrs.get("xmlns") != SVG_NAMESPACE:
                reject()
            seen_root = True
        stack.append(name)

    def end(name):
        if not stack or stack.pop() != name:
            reject()

    def chars(value):
        if value.strip() and (not stack or stack[-1] not in SVG_TEXT):
            reject()

    def bad(*_args):
        reject()

    def xml_decl(_version, encoding, _standalone):
        if encoding and encoding.lower() not in ("utf-8", "utf8"):
            reject()

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.ProcessingInstructionHandler = bad
    parser.CommentHandler = bad
    parser.StartCdataSectionHandler = bad
    parser.EndCdataSectionHandler = bad
    parser.StartDoctypeDeclHandler = bad
    parser.EndDoctypeDeclHandler = bad
    parser.EntityDeclHandler = bad
    parser.ExternalEntityRefHandler = bad
    parser.UnparsedEntityDeclHandler = bad
    parser.NotationDeclHandler = bad
    parser.XmlDeclHandler = xml_decl
    parser.Parse(text, True)
    if stack or not seen_root:
        reject()


def lock_eligible(name, item, rename_from):
    base = name.rsplit("/", 1)[-1] if isinstance(name, str) else ""
    return (rename_from is None and base == "package-lock.json" and isinstance(item, dict)
            and item.get("status") == "modified" and item.get("source") == name and item.get("target") == name)


def hunk_slice(lines):
    for index, line in enumerate(lines):
        if line.startswith("@@"):
            return parse_hunks(lines[index:])
    raise Incomplete("missing change hunks")


def accept_lock(name, lines, item, rename_from, manifest, patch, archive):
    if not lock_eligible(name, item, rename_from):
        return False
    _item, sibling = sibling_manifest(manifest, name)
    if _item is None or sibling is None:
        raise Incomplete("reviewer skipped changed text files")
    try:
        lock_bytes = read_blob(archive, name, BLOB_BYTE_LIMIT)
        package_bytes = read_blob(archive, sibling, BLOB_BYTE_LIMIT)
        package_hunks = block_hunks(patch, sibling)
        if not package_hunks:
            raise Incomplete("manifest not in diff")
        base_bytes = reverse_apply(lock_bytes, hunk_slice(lines))
        reverse_apply(package_bytes, package_hunks)
        mirror_lock(load_json_object(base_bytes), load_json_object(lock_bytes), load_json_object(package_bytes))
    except (Incomplete, _NoArchive, OSError, UnicodeError, json.JSONDecodeError):
        raise Incomplete("reviewer skipped changed text files")
    return True


def svg_eligible(name, item, rename_from, lines):
    if rename_from is not None or not asset_svg_path(name) or not isinstance(item, dict):
        return False
    meta, status = metadata_lines(lines), item.get("status")
    if not modes_are_plain(meta):
        return False
    if status == "added":
        return (item.get("source") is None and item.get("target") == name and item.get("new_mode") == "100644"
                and "new file mode 100644" in meta)
    if status == "modified":
        forbidden = ("new file mode ", "deleted file mode ", "rename from ", "rename to ", "copy from ", "copy to ")
        return (item.get("source") == name and item.get("target") == name and item.get("old_mode") == "100644"
                and item.get("new_mode") == "100644" and not any(line.startswith(forbidden) for line in meta))
    return False


def svg_head(archive, name, status, hunks):
    # Head archive is the non-executing export. Without it, only a full hunk reconstruction is accepted.
    try:
        data = read_blob(archive, name, SVG_BYTE_LIMIT)
    except _NoArchive:
        return reconstruct_new(hunks, status == "added")
    reverse_apply(data, hunks)
    return data


def accept_svg(name, lines, item, rename_from, archive):
    if not svg_eligible(name, item, rename_from, lines):
        return False
    try:
        parse_svg(svg_head(archive, name, item.get("status"), hunk_slice(lines)))
    except (Incomplete, _NoArchive, OSError, UnicodeError, expat.ExpatError):
        raise Incomplete("reviewer skipped changed text files")
    return True


def check_skipped(patch, skipped_file, manifest=None, repository=None, archive=None):
    skipped = read_json(skipped_file)
    if not isinstance(skipped, list) or any(not isinstance(name, str) or not name for name in skipped):
        raise Incomplete("invalid skipped-file list")
    if not skipped:
        return []
    if not isinstance(manifest, list):
        raise Incomplete("missing or invalid changed-file manifest")
    by_key = {}
    for item in manifest:
        if not isinstance(item, dict):
            raise Incomplete("invalid changed-file manifest")
        key = item.get("target") if item.get("target") is not None else item.get("source")
        if isinstance(key, str):
            by_key[key] = item
    unmatched = set(skipped)
    if github_profile(repository):
        for name in list(unmatched):
            item = by_key.get(name)
            if name in EXCLUDED_REVIEW_PATHS and item is not None and excluded_manifest_item(item):
                unmatched.discard(name)
    saw_lock = saw_svg = False
    for block in re.split(r"(?m)(?=^diff --git )", patch):
        if not block.startswith("diff --git "):
            continue
        lines = block.splitlines()
        source = target = None
        hunks = False
        rename_or_copy_from = None
        for line in lines[1:]:
            if line.startswith("@@ "):
                hunks = True
                break
            if line.startswith("--- "):
                source = line[4:].split("\t", 1)[0]
            elif line.startswith("+++ "):
                target = line[4:].split("\t", 1)[0]
            elif line.startswith(("rename from ", "copy from ")):
                marker = "rename from " if line.startswith("rename from ") else "copy from "
                rename_or_copy_from = safe_patch_path(git_path(line[len(marker):]))
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
            if rename_or_copy_from is not None and rename_or_copy_from not in skipped:
                raise Incomplete("reviewer skipped changed text files")
            if hunks:
                item = by_key.get(name)
                if is_svg_name(name) and svg_skip_allowed(lines, item):
                    pass
                elif accept_lock(name, lines, item, rename_or_copy_from, manifest, patch, archive):
                    saw_lock = True
                elif accept_svg(name, lines, item, rename_or_copy_from, archive):
                    saw_svg = True
                else:
                    raise Incomplete("reviewer skipped changed text files")
            unmatched.discard(name)
    if unmatched:
        raise Incomplete("skipped-file list does not match the change")
    codes = []
    if saw_lock:
        codes.append(LOCK_COVERAGE)
    if saw_svg:
        codes.append(SVG_COVERAGE)
    return codes


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
        check_patch(patch, identity.get("files"), identity.get("repository"))
        covered = check_skipped(
            patch, skipped_file, identity.get("files"), identity.get("repository"), Path(context).parent / "product")
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
        summary = f"Reviewed the supplied change; {len(findings)} finding(s)."
        if covered:
            summary += " " + " ".join(covered)
        result.update(complete=True, summary=summary, findings=findings)
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
