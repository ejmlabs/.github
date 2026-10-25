import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_workflows import python, source
from review_result import validate
from pr_agent_result import Incomplete, check_sanitized, path, sanitize


class ReviewerResultTests(unittest.TestCase):
    HEAD = "a" * 40
    SCRIPT = Path(__file__).resolve().parents[1] / "scripts/pr_agent_result.py"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.review = self.root / "review.json"
        self.markdown = self.root / "review.md"
        self.code = self.root / "exit-code"
        self.context = self.root / "context.json"
        self.patch = self.root / "change.patch"
        self.skipped = self.root / "reviewer-skipped.txt"
        self.output = self.root / "review-result.json"
        self.payload = {"review": {"key_issues_to_review": [], "security_concerns": "No"},
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
        self.review.write_text(json.dumps(self.payload))
        self.markdown.write_text("## Review\nNo issues found.\n")
        self.code.write_text("0\n")
        self.skipped.write_text("[]")
        self.termination = self.root / "reviewer-finish-reasons.txt"
        self.termination.write_text("stop\n")
        self.context.write_text(json.dumps({"head": self.HEAD, "base": "b" * 40}))
        self.manifest(self.file("src/main.py"))
        self.patch.write_text("diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-old\n+new\n")

    def file(self, name, **changes):
        return {"source": name, "target": name, "status": "modified", "additions": 1, "deletions": 1,
                "has_patch": True, **changes}

    def manifest(self, *files):
        context = json.loads(self.context.read_text())
        context["files"] = list(files)
        self.context.write_text(json.dumps(context))

    def repository(self, name):
        context = json.loads(self.context.read_text())
        context["repository"] = name
        self.context.write_text(json.dumps(context))

    def issue(self, **changes):
        return {"relevant_file": "src/main.py", "start_line": 7, "end_line": 9,
                "issue_header": "Missing return value", "issue_content": "The caller receives None and crashes.", **changes}

    def run_adapter(self, raw=None, exit_arg=None, embedded=False, write_review=True):
        if write_review:
            self.review.write_text(json.dumps(self.payload) if raw is None else raw)
        args = [str(item) for item in (self.review, self.markdown, self.code if exit_arg is None else exit_arg,
                                      self.context, self.patch, self.skipped, self.HEAD, 2, self.output)]
        command = (["bash", "-c", python(source("pr_agent_result.py"), shlex.join(args))] if embedded
                   else [sys.executable, str(self.SCRIPT), *args])
        completed = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertRegex(completed.stdout, r"\AReview: [0-9]+ finding\(s\); (?:complete|incomplete)\n\Z")
        result = json.loads(self.output.read_text())
        self.assertEqual(set(result), {"head", "pass", "complete", "summary", "findings"})
        self.assertEqual(result["head"], self.HEAD)
        self.assertEqual(result["pass"], 2)
        self.assertLessEqual(self.output.stat().st_size, 64_000)
        return result, completed.stdout

    def complete(self, result):
        self.assertIs(result["complete"], True)
        validated, blocked = validate(self.output, self.HEAD, 2)
        self.assertEqual(validated, result)
        return blocked

    def incomplete(self, result):
        self.assertIs(result["complete"], False)
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["summary"].startswith("Incomplete review:"))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            validate(self.output, self.HEAD, 2)
        # The completeness flag is the only schema failure.
        schema_check = self.root / "schema-check.json"
        schema_check.write_text(json.dumps({**result, "complete": True}))
        validate(schema_check, self.HEAD, 2)

    def test_clean_review_uses_only_the_trusted_identity(self):
        self.payload.update(head="c" * 40, **{"pass": 99, "complete": False})
        result, _ = self.run_adapter()
        self.assertFalse(self.complete(result))
        self.assertEqual(result["findings"], [])

    def test_one_finding_is_mapped_and_blocks(self):
        self.payload["review"]["key_issues_to_review"] = [self.issue()]
        result, _ = self.run_adapter()
        self.assertTrue(self.complete(result))
        self.assertEqual(result["findings"], [{"severity": "medium", "file": "src/main.py", "line": 7,
                                              "title": "Missing return value", "reason": "The caller receives None and crashes."}])

    def test_real_block_scalar_path_completes_with_the_manifest_path(self):
        fixtures = Path(__file__).parent / "fixtures"
        self.review.write_bytes((fixtures / "real-0.48-review.json").read_bytes())
        self.markdown.write_bytes((fixtures / "real-0.48-review.md").read_bytes())
        self.manifest(self.file("src/app.py"))
        self.patch.write_text(self.patch.read_text().replace("src/main.py", "src/app.py"))
        result, _ = self.run_adapter(write_review=False)
        self.assertTrue(self.complete(result))
        self.assertEqual(result["findings"], [{
            "severity": "medium", "file": "src/app.py", "line": 3, "title": "Possible Bug",
            "reason": "LEAKMARKER-7Q3Z the loop never terminates when n is negative",
        }])

    def test_block_and_folded_scalar_paths_accept_only_trailing_line_breaks(self):
        self.manifest(self.file("app.py"))
        self.patch.write_text(self.patch.read_text().replace("src/main.py", "app.py"))
        # Single-line literal (|) and folded (>) scalars both parse to "app.py\n".
        for ending in ("\n", "\r\n", "\n\n", "\r\n\r\n"):
            with self.subTest(ending=ending):
                self.payload["review"]["key_issues_to_review"] = [self.issue(relevant_file="app.py" + ending)]
                result, _ = self.run_adapter()
                self.assertTrue(self.complete(result))
                self.assertEqual(result["findings"][0]["file"], "app.py")
        for unmatched in (" app.py", "app.py ", "app.py \n", "app.py\t\n", "app.py\r", "app.py\v",
                          "app.py\u2028", "app.\npy\n", "App.py\n", "ａｐｐ.py\n"):
            with self.subTest(unmatched=unmatched):
                self.payload["review"]["key_issues_to_review"] = [self.issue(relevant_file=unmatched)]
                self.incomplete(self.run_adapter()[0])

    def test_exact_newline_filename_precedes_serialization_fallback(self):
        for ending in ("\n", "\r\n"):
            with self.subTest(ending=ending):
                name = "app.py" + ending
                self.assertEqual(path(name, [self.file("app.py"), self.file(name)]), name)

    def test_prose_is_stripped_before_severity_matching_but_paths_must_match(self):
        self.payload["review"]["key_issues_to_review"] = [self.issue(
            issue_header=" \nSQL injection\n", issue_content=" \tA query uses raw input.\n")]
        result, _ = self.run_adapter()
        self.complete(result)
        self.assertEqual(result["findings"], [{"severity": "high", "file": "src/main.py", "line": 7,
                                              "title": "SQL injection", "reason": "A query uses raw input."}])
        for file in (" \tsrc/main.py\n", " /etc/passwd\n", " ../outside\n", "src/./main.py", "src\\main.py"):
            with self.subTest(file=file):
                self.payload["review"]["key_issues_to_review"] = [self.issue(relevant_file=file)]
                result, _ = self.run_adapter()
                self.incomplete(result)

    def test_finding_paths_preserve_exact_manifest_identity(self):
        for name in ("pkg/v1.2/module.py", "v1.2/module.py", "src/Kelvin.py", "src/Ａpp.py", " src/space.py ",
                     "app.py\n", "app.py\r\n"):
            with self.subTest(name=name):
                self.manifest(self.file(name))
                quoted = lambda prefix: json.dumps(prefix + name, ensure_ascii=False)
                self.patch.write_text(f"diff --git {quoted('a/')} {quoted('b/')}\n"
                                      f"--- {quoted('a/')}\n+++ {quoted('b/')}\n@@ -1 +1 @@\n-old\n+new\n")
                self.payload["review"]["key_issues_to_review"] = [self.issue(relevant_file=name)]
                result, _ = self.run_adapter()
                self.complete(result)
                self.assertEqual(result["findings"][0]["file"].encode(), name.encode())
                self.payload["review"]["key_issues_to_review"] = []
                self.payload["review"]["security_concerns"] = "A security concern."
                result, _ = self.run_adapter()
                self.complete(result)
                self.assertEqual(result["findings"][0]["file"].encode(), name.encode())
                self.payload["review"]["security_concerns"] = "No"
                for unmatched in ("unmatched.py", name.replace("K", "K").replace("Ａ", "A").strip()):
                    if unmatched == name:
                        continue
                    self.payload["review"]["key_issues_to_review"] = [self.issue(relevant_file=unmatched)]
                    self.incomplete(self.run_adapter()[0])

    def test_whitespace_only_required_model_strings_fail_closed(self):
        for field in ("relevant_file", "issue_header", "issue_content"):
            with self.subTest(field=field):
                self.payload["review"]["key_issues_to_review"] = [self.issue(**{field: " \t\n"})]
                result, _ = self.run_adapter()
                self.incomplete(result)

    def test_invalid_start_lines_default_to_one(self):
        issues = [self.issue(start_line=line) for line in (0, -4, None, "7", True)]
        issues.append({key: value for key, value in self.issue().items() if key != "start_line"})
        self.payload["review"]["key_issues_to_review"] = issues
        result, _ = self.run_adapter()
        self.complete(result)
        self.assertEqual([item["line"] for item in result["findings"]], [1] * len(issues))

    def test_security_concern_creates_a_high_finding_at_the_first_changed_file(self):
        for concern in ("Credential disclosure is possible.", "Credential disclosure is possible.\n"):
            with self.subTest(concern=concern):
                self.payload["review"]["security_concerns"] = concern
                result, _ = self.run_adapter()
                self.assertTrue(self.complete(result))
                self.assertEqual(result["findings"], [{"severity": "high", "file": "src/main.py", "line": 1,
                                                      "title": "Security concern", "reason": concern.strip()}])

    def test_normalized_negative_security_concerns_add_no_finding(self):
        for concern in ("No\n", " no. ", "", " \t\n", "NO", "NO.\n", "no"):
            with self.subTest(concern=concern):
                self.payload["review"]["security_concerns"] = concern
                result, _ = self.run_adapter()
                self.assertFalse(self.complete(result))
                self.assertEqual(result["findings"], [])

    def test_security_issue_in_header_or_content_is_high_without_duplicate(self):
        for changes in ({"issue_header": "SQL injection"}, {"issue_content": "An attacker can bypass authorization."}):
            with self.subTest(changes=changes):
                self.payload["review"]["key_issues_to_review"] = [self.issue(**changes)]
                self.payload["review"]["security_concerns"] = "The same issue affects security."
                result, _ = self.run_adapter()
                self.complete(result)
                self.assertEqual(len(result["findings"]), 1)
                self.assertEqual(result["findings"][0]["severity"], "high")

    def test_security_fallback_handles_spaces_renames_and_deletions(self):
        self.payload["review"]["security_concerns"] = "A security concern."
        for patch, expected in (
                ('diff --git a/old name b/new name\nsimilarity index 100%\nrename from old name\nrename to new name\n', "new name"),
                ('diff --git "a/old name" "b/new name"\nsimilarity index 100%\nrename from "old name"\nrename to "new name"\n', "new name"),
                ('diff --git a/old name b/old name\n--- a/old name\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n', "old name"),
                ('diff --git a/image.png b/image.png\nBinary files a/image.png and b/image.png differ\n', "image.png")):
            with self.subTest(expected=expected):
                self.manifest(self.file(expected, source="old name", status="renamed", additions=0, deletions=0, has_patch=False)
                              if expected == "new name" else self.file(expected, target=None, status="removed", additions=0)
                              if expected == "old name" else self.file(expected, additions=0, deletions=0, has_patch=False))
                self.patch.write_text(patch)
                result, _ = self.run_adapter()
                self.complete(result)
                self.assertEqual(result["findings"][0]["file"], expected)

    def test_coverage_warnings_fail_closed(self):
        for warning in ("**Review coverage:** The following files were not included in this review because of the token budget",
                        "Some files had patches clipped before analysis to fit the token budget",
                        "2 chunk(s) failed and are not covered"):
            with self.subTest(warning=warning):
                self.markdown.write_text(warning)
                result, _ = self.run_adapter()
                self.incomplete(result)

    def test_every_model_call_must_have_normal_termination(self):
        for reasons in ("", "length\n", "content_filter\n", "missing\n", "stop\nlength\n", "error\nstop\n", "stop\fstop\n", '["stop"]'):
            with self.subTest(reasons=reasons):
                self.termination.write_text(reasons)
                self.incomplete(self.run_adapter()[0])
        self.termination.write_text("stop\nstop\n")
        self.complete(self.run_adapter()[0])

    def test_output_token_limit_fails_closed(self):
        for tokens in (16000, 16001, -1, True, "20", None):
            with self.subTest(tokens=tokens):
                self.payload["usage"]["completion_tokens"] = tokens
                self.incomplete(self.run_adapter()[0])
        self.payload["usage"]["completion_tokens"] = 15999
        self.complete(self.run_adapter()[0])
        # The pinned CLI emits an empty usage map when callback usage is absent.
        self.payload["usage"] = {}
        self.complete(self.run_adapter()[0])

    def test_missing_files_header_only_tail_and_line_count_mismatch_fail_closed(self):
        original = self.patch.read_text()
        self.manifest(self.file("src/main.py"), self.file("hidden.py"))
        for patch in (original, original + "diff --git a/hidden.py b/hidden.py\n--- a/hidden.py\n+++ b/hidden.py\n"):
            with self.subTest(patch=patch):
                self.patch.write_text(patch)
                self.incomplete(self.run_adapter()[0])
        self.manifest(self.file("src/main.py"))
        for patch in (original.split("@@")[0], original.replace("+new\n", ""), original + original,
                      original.replace("@@ -1 +1 @@", "Binary files a/src/main.py and b/src/main.py differ\n@@ -1 +1 @@")):
            with self.subTest(patch=patch):
                self.patch.write_text(patch)
                self.incomplete(self.run_adapter()[0])
        self.patch.write_text(original)
        self.manifest(self.file("src/main.py", additions=2))
        self.incomplete(self.run_adapter()[0])

    def test_metadata_cannot_hide_missing_text_hunks(self):
        cases = (
            (self.file("new.py", source="old.py", status="renamed"),
             "diff --git a/old.py b/new.py\nrename from old.py\nrename to new.py\n"),
            (self.file("new.py", source=None, status="added", deletions=0, new_mode="100644"),
             "diff --git a/new.py b/new.py\nnew file mode 100644\n"),
            (self.file("src/main.py"), "diff --git a/src/main.py b/src/main.py\nold mode 100644\nnew mode 100755\n"),
        )
        for file, patch in cases:
            with self.subTest(file=file):
                self.manifest(file)
                self.patch.write_text(patch)
                self.incomplete(self.run_adapter()[0])

    def test_verified_mode_change_and_empty_file_are_complete(self):
        for file, patch in (
            (self.file("script", additions=0, deletions=0, has_patch=False, old_mode="100644", new_mode="100755"),
             "diff --git a/script b/script\nold mode 100644\nnew mode 100755\n"),
            (self.file("empty", source=None, status="added", additions=0, deletions=0, has_patch=False, new_mode="100644"),
             "diff --git a/empty b/empty\nnew file mode 100644\n"),
        ):
            with self.subTest(file=file):
                self.manifest(file)
                self.patch.write_text(patch)
                self.complete(self.run_adapter()[0])

    def test_unicode_separators_and_carriage_returns_are_source_data(self):
        for separator in ("\f", "\v", "\r", "\x85", "\u2028", "\u2029"):
            with self.subTest(separator=repr(separator)):
                self.patch.write_text("diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n"
                                      "@@ -1 +1 @@\n-old\n+print('before" + separator + "after')\n")
                self.complete(self.run_adapter()[0])

    def test_all_patch_path_representations_are_validated_without_findings(self):
        original = self.patch.read_text()
        for value in ("../outside", "/absolute", "C:/outside", "x\x00y", "a/../outside", 'bad\\377', 'nul\\000path'):
            with self.subTest(value=value):
                old, new = '"a/' + value + '"', '"b/' + value + '"'
                self.patch.write_text(original.replace("a/src/main.py", old).replace("b/src/main.py", new))
                self.incomplete(self.run_adapter()[0])
        for encoded in (original.encode("utf-16"), original.encode().replace(b"src/main.py", b"bad\xff")):
            self.patch.write_bytes(encoded)
            self.incomplete(self.run_adapter()[0])
        for metadata in ("rename from ../outside\nrename to src/main.py\n", "copy from /absolute\ncopy to src/main.py\n",
                         "Binary files a/../outside and b/src/main.py differ\n"):
            self.patch.write_text(original.replace("--- a/", metadata + "--- a/", 1))
            self.incomplete(self.run_adapter()[0])

    def test_punctuation_unicode_and_bare_domain_urls_are_removed(self):
        urls = ("https://evil.invalid/p", "hxxp://evil.invalid/p", "javascript:alert(1)", "data:text/html,x",
                "mailto:person@evil.invalid", "www.", "evil.com/phish", "evil.xn--p1ai/phish", "evil.рф/phish",
                "evil.com./phish", "//evil.invalid/p", "https:/evil.invalid/p",
                "ｈｔｔｐｓ：／／evil.invalid/p", "h\u034fttps://evil.invalid/p", "ht\ufe0ftps://evil.invalid/p",
                "ht\u200btps://evil.invalid/p", "＠person", "﹤b﹥label﹤/b﹥")
        for prefix in (".", "+", "-", "(", '"', "'", "`", " "):
            for url in urls:
                with self.subTest(prefix=prefix, url=url):
                    output = sanitize("Reason " + prefix + url)
                    check_sanitized(output)
                    self.assertNotRegex(output, r"(?i)https?|hxxp|javascript:|data:|mailto:|www\.|evil\.|@|[<>]")
        with self.assertRaises(Incomplete):
            check_sanitized("Reason .https://evil.invalid/p")

    def test_clipped_text_in_a_finding_is_not_a_coverage_warning(self):
        self.markdown.write_text("## Review\nThe text is clipped in a narrow viewport.")
        self.payload["review"]["key_issues_to_review"] = [self.issue(issue_content="The text is clipped in a narrow viewport.")]
        result, _ = self.run_adapter()
        self.complete(result)

    def test_skipped_text_changes_fail_closed(self):
        for name in ("Cargo.lock", "folder/uv.lock", "path with spaces/file.csv"):
            with self.subTest(name=name):
                self.manifest(self.file(name))
                self.skipped.write_text(json.dumps([name]))
                old, new = "a/" + name, "b/" + name
                self.patch.write_text(f"diff --git {old} {new}\n--- {old}\n+++ {new}\n@@ -1 +1 @@\n-old\n+new\n")
                result, _ = self.run_adapter()
                self.incomplete(result)
                self.assertIn("skipped changed text", result["summary"])

    def test_skipped_binary_assets_without_text_hunks_complete(self):
        name = "icons/logo.png"
        self.manifest(self.file(name, additions=0, deletions=0, has_patch=False))
        self.skipped.write_text(json.dumps([name]))
        self.patch.write_text(f"diff --git a/{name} b/{name}\nBinary files a/{name} and b/{name} differ\n")
        result, _ = self.run_adapter()
        self.complete(result)

    def test_skipped_non_svg_asset_text_hunks_fail_closed(self):
        for name in ("icons/logo.png", "evil.py.png", "tool.so"):
            with self.subTest(name=name):
                self.manifest(self.file(name, additions=1, deletions=0, has_patch=True, new_mode="100644",
                                        source=None, status="added"))
                self.skipped.write_text(json.dumps([name]))
                self.patch.write_text(
                    f"diff --git a/{name} b/{name}\nnew file mode 100644\n"
                    f"--- /dev/null\n+++ b/{name}\n@@ -0,0 +1 @@\n+payload\n"
                )
                result, _ = self.run_adapter()
                self.incomplete(result)
                self.assertIn("skipped changed text", result["summary"])

    def test_skipped_deletions_and_renames_with_text_fail_closed(self):
        for target, name in (("/dev/null", "Cargo.lock"), ("b/renamed.lock", "renamed.lock")):
            with self.subTest(target=target):
                self.manifest(self.file(name, source="Cargo.lock", target=None if target == "/dev/null" else name,
                                        status="removed" if target == "/dev/null" else "renamed", additions=0))
                self.skipped.write_text(json.dumps([name]))
                header_target = "b/Cargo.lock" if target == "/dev/null" else target
                self.patch.write_text(f"diff --git a/Cargo.lock {header_target}\n--- a/Cargo.lock\n+++ {target}\n@@ -1 +0,0 @@\n-old\n")
                result, _ = self.run_adapter()
                self.incomplete(result)

    def test_skipped_binary_changes_do_not_hide_unrelated_text_changes(self):
        binary = self.file("logo.png", additions=0, deletions=0, has_patch=False)
        self.manifest(binary, self.file("src/main.py"))
        self.skipped.write_text(json.dumps(["logo.png"]))
        self.patch.write_text("diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n" + self.patch.read_text())
        result, _ = self.run_adapter()
        self.complete(result)
        self.patch.write_text("diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n")
        self.manifest(binary)
        result, _ = self.run_adapter()
        self.complete(result)
        # A duplicate file section with text must still fail after a binary section.
        self.patch.write_text(self.patch.read_text() + "diff --git a/logo.png b/logo.png\n--- a/logo.png\n+++ b/logo.png\n@@ -1 +1 @@\n-old\n+new\n")
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_skipped_file_input_is_required_and_must_match_the_patch(self):
        for value in ("invalid JSON", "null", "{}", '[null]', '["unmatched.lock"]'):
            with self.subTest(value=value):
                self.skipped.write_text(value)
                result, _ = self.run_adapter()
                self.incomplete(result)
        self.skipped.unlink()
        result, _ = self.run_adapter()
        self.incomplete(result)
        self.skipped.mkdir()
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_hunk_contents_cannot_impersonate_file_headers(self):
        self.manifest(self.file("Cargo.lock"))
        self.skipped.write_text(json.dumps(["Cargo.lock"]))
        self.patch.write_text("diff --git a/Cargo.lock b/Cargo.lock\n--- a/Cargo.lock\n+++ b/Cargo.lock\n"
                              "@@ -1 +1 @@\n--- a/innocent.py\n+++ b/innocent.py\n")
        result, _ = self.run_adapter()
        self.incomplete(result)
        self.assertIn("skipped changed text", result["summary"])

    def test_invalid_patch_paths_fail_even_without_security_findings(self):
        self.patch.write_text('diff --git "a/unusual\\377" "b/unusual\\377"\n')
        self.payload["review"]["key_issues_to_review"] = [self.issue(relevant_file="src/a..b.py")]
        result, _ = self.run_adapter()
        self.incomplete(result)
        self.payload["review"]["security_concerns"] = "A concern requiring a fallback."
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_missing_security_concerns_fails_closed(self):
        del self.payload["review"]["security_concerns"]
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_nonzero_missing_and_malformed_exit_codes_fail_closed(self):
        for value in ("1", "124", "-9", "", "unexpected"):
            with self.subTest(value=value):
                self.code.write_text(value)
                result, _ = self.run_adapter()
                self.incomplete(result)
        self.code.unlink()
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_exit_code_can_be_an_integer_argument(self):
        result, _ = self.run_adapter(exit_arg=0)
        self.complete(result)
        result, _ = self.run_adapter(exit_arg=1)
        self.incomplete(result)

    def test_malformed_and_unexpected_json_fail_closed(self):
        for raw in ("not JSON", "{", "null", "[]", "{}", '{"review": []}',
                    '{"review": {}}', '{"review": {"key_issues_to_review": {}}}',
                    '{"review": {"key_issues_to_review": []}, "usage": NaN}',
                    '{"review": {}, "review": {"key_issues_to_review": []}}'):
            with self.subTest(raw=raw):
                result, _ = self.run_adapter(raw=raw)
                self.incomplete(result)

    def test_missing_unreadable_or_unsafe_inputs_fail_closed(self):
        for file in (self.review, self.markdown, self.context, self.patch, self.skipped, self.termination):
            with self.subTest(file=file.name):
                original = file.read_bytes()
                file.unlink()
                result, _ = self.run_adapter(write_review=False)
                self.incomplete(result)
                # A directory is unreadable as an input file, including as root.
                file.mkdir()
                result, _ = self.run_adapter(write_review=False)
                self.incomplete(result)
                file.rmdir()
                file.write_bytes(original)
        self.markdown.unlink()
        self.markdown.symlink_to(self.patch)
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_more_than_fifty_issues_fails_closed(self):
        self.payload["review"]["key_issues_to_review"] = [self.issue()] * 51
        result, _ = self.run_adapter()
        self.incomplete(result)
        self.assertIn("50", result["summary"])

    def test_fifty_issues_fit_unless_a_security_finding_exceeds_the_limit(self):
        self.payload["review"]["key_issues_to_review"] = [self.issue()] * 50
        result, _ = self.run_adapter()
        self.complete(result)
        self.payload["review"]["security_concerns"] = "A separate security concern."
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_unsafe_finding_paths_fail_closed(self):
        for file in ("/etc/passwd", "../outside", "src/../outside", "C:/outside", "\\\\server\\share", "", "x\x00y",
                     "src/" + "x" * 4000 + "/../outside"):
            with self.subTest(file=file[:40]):
                self.payload["review"]["key_issues_to_review"] = [self.issue(relevant_file=file)]
                result, _ = self.run_adapter()
                self.incomplete(result)

    def test_surprising_finding_shapes_fail_closed(self):
        for issue in (None, [], {}, self.issue(issue_header=9), self.issue(issue_content=""), self.issue(relevant_file=[])):
            with self.subTest(issue=issue):
                self.payload["review"]["key_issues_to_review"] = [issue]
                result, _ = self.run_adapter()
                self.incomplete(result)
        self.payload["review"] = {"key_issues_to_review": [], "security_concerns": None}
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_context_mismatch_fails_closed(self):
        for context in ({"head": "b" * 40}, {"head": self.HEAD, "pass": 1}, {"head": self.HEAD, "pass": True}):
            with self.subTest(context=context):
                self.context.write_text(json.dumps(context))
                result, _ = self.run_adapter()
                self.incomplete(result)

    def test_text_fields_are_truncated_and_large_results_fail_closed(self):
        self.payload["review"]["key_issues_to_review"] = [self.issue(
            issue_header="t" * 4001, issue_content="r" * 4001)]
        result, _ = self.run_adapter()
        self.complete(result)
        self.assertEqual([len(result["findings"][0][key]) for key in ("title", "reason")], [4000] * 2)
        self.payload["review"]["key_issues_to_review"] *= 50
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_key_like_strings_are_redacted_in_prose(self):
        keys = [prefix + "Example1234567890" for prefix in ("sk" + "-", "sk" + "-ant-", "ghp" + "_", "gho" + "_",
                                                         "ghu" + "_", "ghs" + "_", "ghr" + "_",
                                                         "github" + "_pat_", "xox" + "b-")]
        keys.extend(["AK" + "IA" + "A1" * 8, "ey" + "JhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiJ0ZXN0In0" + "." + "signature"])
        for kind in ("", "RSA ", "EC ", "OPENSSH ", "ENCRYPTED "):
            keys.append("-----BE" + "GIN " + kind + "PRIVATE KEY-----\nExampleBase64Data\n-----EN" + "D " + kind + "PRIVATE KEY-----")
        secret_text = " ".join(keys)
        self.payload["review"]["key_issues_to_review"] = [self.issue(
            issue_header=secret_text, issue_content=secret_text)]
        result, stdout = self.run_adapter()
        self.complete(result)
        serialized = self.output.read_text()
        for key in keys:
            self.assertNotIn(key, serialized + stdout)
        finding = result["findings"][0]
        for field in ("title", "reason"):
            self.assertIn("[redacted]", finding[field])
        self.payload["review"]["key_issues_to_review"] = []
        self.payload["review"]["security_concerns"] = secret_text
        result, _ = self.run_adapter()
        self.complete(result)
        self.assertEqual(result["findings"][0]["reason"], " ".join(["[redacted]"] * len(keys)))

    def test_ordinary_words_containing_sk_are_not_redacted(self):
        self.manifest(self.file("src/task-runner.ts"))
        self.patch.write_text(self.patch.read_text().replace("src/main.py", "src/task-runner.ts"))
        self.payload["review"]["key_issues_to_review"] = [self.issue(
            relevant_file="src/task-runner.ts", issue_header="task-runner failure", issue_content="The task-runner crashes.")]
        result, _ = self.run_adapter()
        self.complete(result)
        self.assertEqual(result["findings"][0]["file"], "src/task-runner.ts")
        self.assertEqual(result["findings"][0]["title"], "task-runner failure")
        self.assertEqual(result["findings"][0]["reason"], "The task-runner crashes.")

    def test_sanitizer_removes_urls_links_images_html_entities_and_mentions(self):
        cases = {
            "HTTPS://example.invalid/path": "",
            "ftp://example.invalid/path": "",
            "custom+scheme://example.invalid/path": "",
            "www.example.invalid/path": "",
            "[visible](javascript:alert(1))": "visible",
            "[outer [inner](https://example.invalid)](javascript:alert(1))": "outer inner",
            "[visible][reference]": "visible",
            "See [reference].\n\n[reference]: javascript:alert(1)": "See reference.",
            "![hidden](https://example.invalid/image)": "",
            "![hidden][reference]": "",
            '<img src="https://example.invalid/image" onerror="alert(1)">': "",
            "<b>visible <i>nested</i></b>": "visible nested",
            "&amp;lt;img src=HTTPS://example.invalid/image&amp;gt;": "",
            "h&#116;tps://example.invalid/path": "",
            "HT\u200bTPS://example.invalid/path": "",
            "http@://example.invalid/path": "",
            "[visible]&unknown;(javascript:alert(1))": "visible",
            "[http](ignored)://example.invalid/path": "",
            "[visible]![drop](unused)(javascript:alert(1))": "visible",
            "@@user @org/team &#64;other": "user org/team other",
            "visible &unknownentity;": "visible",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(sanitize(value), expected)

    def test_finding_prose_and_summary_are_sanitized_before_output(self):
        self.payload["summary"] = "https://example.invalid/summary @user <b>bad</b>"
        self.payload["review"]["key_issues_to_review"] = [self.issue(
            issue_header="Fix [visible](javascript:alert(1)) @@user",
            issue_content="Details <b>bold</b> HTTPS://example.invalid/path <img src=ftp://example.invalid/image> @org/team")]
        result, _ = self.run_adapter()
        self.complete(result)
        self.assertEqual(result["findings"][0]["file"], "src/main.py")
        self.assertEqual(result["findings"][0]["title"], "Fix visible user")
        self.assertNotRegex(self.output.read_text(), r"(?i)[a-z][a-z0-9+.-]*://|www\.|@|<|>|&(?:#|[a-z])")

    def test_sanitization_cannot_hide_unsafe_paths_or_drop_a_finding(self):
        for file in ("&#47;etc/passwd", "src/&#46;&#46;/outside"):
            with self.subTest(file=file):
                self.payload["review"]["key_issues_to_review"] = [self.issue(relevant_file=file)]
                result, _ = self.run_adapter()
                self.incomplete(result)
        self.payload["review"]["key_issues_to_review"] = [self.issue(issue_header="![image](https://example.invalid)")]
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_stdout_never_contains_summary_finding_or_parse_error_text(self):
        marker = "PRIVATE_REVIEW_SENTINEL"
        self.payload["review"]["key_issues_to_review"] = [self.issue(issue_header=marker, issue_content=marker)]
        result, stdout = self.run_adapter()
        self.complete(result)
        self.assertNotIn(marker, stdout)
        self.assertNotIn(result["summary"], stdout)
        result, stdout = self.run_adapter(raw='{"' + marker)
        self.incomplete(result)
        self.assertNotIn(marker, stdout + result["summary"])

    def test_script_is_self_contained_when_embedded_in_the_workflow(self):
        result, _ = self.run_adapter(embedded=True)
        self.assertFalse(self.complete(result))

    def test_generated_workflow_paths_missing_from_patch_are_not_model_reviewed(self):
        # Shape from ejmlabs/.github reviews: compare-diff text omitted from the
        # model patch after precheck strip; manifest still lists the files.
        self.repository("ejmlabs/.github")
        text = self.file("scripts/governance.py")
        generated = [
            self.file(".github/workflows/governance.yml", additions=7, deletions=7, has_patch=False),
            self.file(".github/workflows/draft-release.yml", additions=1, deletions=1, has_patch=False),
        ]
        self.manifest(text, *generated)
        self.skipped.write_text(json.dumps([
            ".github/workflows/governance.yml", ".github/workflows/draft-release.yml",
        ]))
        self.patch.write_text(
            "diff --git a/scripts/governance.py b/scripts/governance.py\n"
            "--- a/scripts/governance.py\n+++ b/scripts/governance.py\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        )
        result, _ = self.run_adapter()
        self.complete(result)
        # Other profiles keep generated paths model-reviewed (fail closed if missing).
        self.repository("ejmlabs/ejm-ui")
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_removed_and_added_binaries_without_text_patches_complete(self):
        # Shapes from ejmlabs#13 (removed PNG) and ejm-ui#21 (added PNG/ICO).
        removed = self.file("design-kit/motifs/grid-ink.png", target=None, status="removed",
                            additions=0, deletions=0, has_patch=False, old_mode="100644")
        added = self.file("packages/tokens/assets/icon.ico", source=None, status="added",
                          additions=0, deletions=0, has_patch=False, new_mode="100644")
        text = self.file("CHANGELOG.md", additions=1, deletions=0)
        self.manifest(removed, added, text)
        self.skipped.write_text(json.dumps([
            "design-kit/motifs/grid-ink.png", "packages/tokens/assets/icon.ico",
        ]))
        self.patch.write_text(
            "diff --git a/design-kit/motifs/grid-ink.png b/design-kit/motifs/grid-ink.png\n"
            "deleted file mode 100644\n"
            "Binary files a/design-kit/motifs/grid-ink.png and /dev/null differ\n"
            "diff --git a/packages/tokens/assets/icon.ico b/packages/tokens/assets/icon.ico\n"
            "new file mode 100644\n"
            "Binary files /dev/null and b/packages/tokens/assets/icon.ico differ\n"
            "diff --git a/CHANGELOG.md b/CHANGELOG.md\n"
            "--- a/CHANGELOG.md\n+++ b/CHANGELOG.md\n"
            "@@ -1,0 +1 @@\n+note\n"
        )
        result, _ = self.run_adapter()
        self.complete(result)

    def test_skipped_svg_assets_with_text_hunks_do_not_fail_closed(self):
        # Shape from ejmlabs#13: removal-only SVG text.
        asset = self.file("design-kit/motifs/grid.svg", target=None, status="removed",
                          additions=0, deletions=1, has_patch=True, old_mode="100644")
        text = self.file("CHANGELOG.md", additions=1, deletions=0)
        self.manifest(asset, text)
        self.skipped.write_text(json.dumps(["design-kit/motifs/grid.svg"]))
        self.patch.write_text(
            "diff --git a/design-kit/motifs/grid.svg b/design-kit/motifs/grid.svg\n"
            "deleted file mode 100644\n"
            "--- a/design-kit/motifs/grid.svg\n+++ /dev/null\n"
            "@@ -1 +0,0 @@\n-<svg/>\n"
            "diff --git a/CHANGELOG.md b/CHANGELOG.md\n"
            "--- a/CHANGELOG.md\n+++ b/CHANGELOG.md\n"
            "@@ -1,0 +1 @@\n+note\n"
        )
        result, _ = self.run_adapter()
        self.complete(result)

    def test_coverage_footer_on_reviewable_text_still_fails_closed(self):
        self.markdown.write_text(
            "## Review\nNo issues found.\n\n"
            "**Review coverage:** The following files were not included in this review "
            "because of the token budget:\n- src/main.py\n"
        )
        result, _ = self.run_adapter()
        self.incomplete(result)
        self.assertIn("coverage", result["summary"])

    def test_delta_e_and_f_probes_fail_closed_except_removal_svg(self):
        # Probe tables from completeness security reviews Delta E and F.
        probes = []

        # Rename src/auth.py → src/auth.png with text hunks
        probes.append(("rename-to-png", False, {
            "files": [self.file("src/auth.png", source="src/auth.py", status="renamed",
                                additions=1, deletions=1)],
            "skipped": ["src/auth.png"],
            "patch": (
                "diff --git a/src/auth.py b/src/auth.png\n"
                "similarity index 50%\nrename from src/auth.py\nrename to src/auth.png\n"
                "--- a/src/auth.py\n+++ b/src/auth.png\n@@ -1 +1 @@\n-old\n+new\n"
            ),
        }))
        # New tool.png mode 100755 with script text
        probes.append(("exec-png", False, {
            "files": [self.file("tool.png", source=None, status="added", additions=1, deletions=0,
                                has_patch=True, new_mode="100755")],
            "skipped": ["tool.png"],
            "patch": (
                "diff --git a/tool.png b/tool.png\nnew file mode 100755\n"
                "--- /dev/null\n+++ b/tool.png\n@@ -0,0 +1 @@\n+#!/bin/sh\n"
            ),
        }))
        # New public/logo.svg mode 120000 symlink
        probes.append(("svg-symlink", False, {
            "files": [self.file("public/logo.svg", source=None, status="added", additions=1, deletions=0,
                                has_patch=True, new_mode="120000")],
            "skipped": ["public/logo.svg"],
            "patch": (
                "diff --git a/public/logo.svg b/public/logo.svg\nnew file mode 120000\n"
                "--- /dev/null\n+++ b/public/logo.svg\n@@ -0,0 +1 @@\n+../../.env\n"
            ),
        }))
        # New SVG with onload= and <script>
        probes.append(("svg-script", False, {
            "files": [self.file("icon.svg", source=None, status="added", additions=1, deletions=0,
                                has_patch=True, new_mode="100644")],
            "skipped": ["icon.svg"],
            "patch": (
                "diff --git a/icon.svg b/icon.svg\nnew file mode 100644\n"
                "--- /dev/null\n+++ b/icon.svg\n@@ -0,0 +1 @@\n+"
                "<svg onload=\"x()\"><script>alert(1)</script></svg>\n"
            ),
        }))
        # New evil.py.png holding Python text
        probes.append(("double-ext", False, {
            "files": [self.file("evil.py.png", source=None, status="added", additions=1, deletions=0,
                                has_patch=True, new_mode="100644")],
            "skipped": ["evil.py.png"],
            "patch": (
                "diff --git a/evil.py.png b/evil.py.png\nnew file mode 100644\n"
                "--- /dev/null\n+++ b/evil.py.png\n@@ -0,0 +1 @@\n+print(1)\n"
            ),
        }))
        # LOGO.SVG text change (case folded) with additions → incomplete
        probes.append(("logo-svg-case", False, {
            "files": [self.file("LOGO.SVG", additions=1, deletions=1, has_patch=True,
                                old_mode="100644", new_mode="100644")],
            "skipped": ["LOGO.SVG"],
            "patch": (
                "diff --git a/LOGO.SVG b/LOGO.SVG\n"
                "--- a/LOGO.SVG\n+++ b/LOGO.SVG\n@@ -1 +1 @@\n-old\n+"
                "<svg><script>x</script></svg>\n"
            ),
        }))
        # Rename scripts/x.py → .github/workflows/governance.yml with hunks
        probes.append(("rename-into-generated", False, {
            "repo": "ejmlabs/.github",
            "files": [self.file(".github/workflows/governance.yml", source="scripts/x.py",
                                status="renamed", additions=1, deletions=1)],
            "skipped": [".github/workflows/governance.yml"],
            "patch": (
                "diff --git a/scripts/x.py b/.github/workflows/governance.yml\n"
                "similarity index 50%\nrename from scripts/x.py\n"
                "rename to .github/workflows/governance.yml\n"
                "--- a/scripts/x.py\n+++ b/.github/workflows/governance.yml\n"
                "@@ -1 +1 @@\n-old\n+new\n"
            ),
        }))
        # Cargo.lock control
        probes.append(("cargo-lock", False, {
            "files": [self.file("Cargo.lock")],
            "skipped": ["Cargo.lock"],
            "patch": (
                "diff --git a/Cargo.lock b/Cargo.lock\n"
                "--- a/Cargo.lock\n+++ b/Cargo.lock\n@@ -1 +1 @@\n-old\n+new\n"
            ),
        }))
        # Added SVG (any '+') incomplete under removal-only exemption
        probes.append(("added-svg", False, {
            "files": [self.file("mark.svg", source=None, status="added", additions=1, deletions=0,
                                has_patch=True, new_mode="100644")],
            "skipped": ["mark.svg"],
            "patch": (
                "diff --git a/mark.svg b/mark.svg\nnew file mode 100644\n"
                "--- /dev/null\n+++ b/mark.svg\n@@ -0,0 +1 @@\n+"
                "<svg xmlns=\"http://www.w3.org/2000/svg\"><path d=\"M0 0\"/></svg>\n"
            ),
        }))
        # Modified SVG with additions incomplete
        probes.append(("modified-svg-with-add", False, {
            "files": [self.file("edit.svg", additions=1, deletions=1, has_patch=True,
                                old_mode="100644", new_mode="100644")],
            "skipped": ["edit.svg"],
            "patch": (
                "diff --git a/edit.svg b/edit.svg\n"
                "--- a/edit.svg\n+++ b/edit.svg\n@@ -1 +1 @@\n-<svg/>\n+<svg><path/></svg>\n"
            ),
        }))
        # Removal-only SVG (allowed)
        probes.append(("removal-svg", True, {
            "files": [self.file("gone.svg", target=None, status="removed", additions=0, deletions=1,
                                has_patch=True, old_mode="100644")],
            "skipped": ["gone.svg"],
            "patch": (
                "diff --git a/gone.svg b/gone.svg\ndeleted file mode 100644\n"
                "--- a/gone.svg\n+++ /dev/null\n@@ -1 +0,0 @@\n-<svg/>\n"
            ),
        }))
        # Modified SVG with only '-' hunk lines (allowed)
        probes.append(("modified-removal-only-svg", True, {
            "files": [self.file("trim.svg", additions=0, deletions=1, has_patch=True,
                                old_mode="100644", new_mode="100644")],
            "skipped": ["trim.svg"],
            "patch": (
                "diff --git a/trim.svg b/trim.svg\n"
                "--- a/trim.svg\n+++ b/trim.svg\n@@ -1,2 +1 @@\n <svg/>\n-<path/>\n"
            ),
        }))
        # Delta F bypass probes (all incomplete under removal-only)
        probes.append(("f-plusplus-script", False, {
            "files": [self.file("pp.svg", source=None, status="added", additions=1, deletions=0,
                                has_patch=True, new_mode="100644")],
            "skipped": ["pp.svg"],
            "patch": (
                "diff --git a/pp.svg b/pp.svg\nnew file mode 100644\n"
                "--- /dev/null\n+++ b/pp.svg\n@@ -0,0 +1 @@\n++<script>alert(1)</script>\n"
            ),
        }))
        probes.append(("f-namespaced-script", False, {
            "files": [self.file("ns.svg", source=None, status="added", additions=1, deletions=0,
                                has_patch=True, new_mode="100644")],
            "skipped": ["ns.svg"],
            "patch": (
                "diff --git a/ns.svg b/ns.svg\nnew file mode 100644\n"
                "--- /dev/null\n+++ b/ns.svg\n@@ -0,0 +1 @@\n+"
                "<x:script xmlns:x=\"http://www.w3.org/2000/svg\">x</x:script>\n"
            ),
        }))
        probes.append(("f-split-onload", False, {
            "files": [self.file("on.svg", source=None, status="added", additions=2, deletions=0,
                                has_patch=True, new_mode="100644")],
            "skipped": ["on.svg"],
            "patch": (
                "diff --git a/on.svg b/on.svg\nnew file mode 100644\n"
                "--- /dev/null\n+++ b/on.svg\n@@ -0,0 +1,2 @@\n+<svg onload\n+=\"alert(1)\"/>\n"
            ),
        }))
        probes.append(("f-entity-set-href", False, {
            "files": [self.file("ent.svg", source=None, status="added", additions=1, deletions=0,
                                has_patch=True, new_mode="100644")],
            "skipped": ["ent.svg"],
            "patch": (
                "diff --git a/ent.svg b/ent.svg\nnew file mode 100644\n"
                "--- /dev/null\n+++ b/ent.svg\n@@ -0,0 +1 @@\n+"
                "<svg><a><set attributeName=\"href\" to=\"&#106;avascript:alert(1)\"/></a></svg>\n"
            ),
        }))
        probes.append(("f-split-external-href", False, {
            "files": [self.file("use.svg", source=None, status="added", additions=2, deletions=0,
                                has_patch=True, new_mode="100644")],
            "skipped": ["use.svg"],
            "patch": (
                "diff --git a/use.svg b/use.svg\nnew file mode 100644\n"
                "--- /dev/null\n+++ b/use.svg\n@@ -0,0 +1,2 @@\n+<svg><use href\n"
                "+=\"https://evil.invalid/x.svg#a\"/></svg>\n"
            ),
        }))

        for label, expect_complete, case in probes:
            with self.subTest(label=label):
                self.repository(case.get("repo", "ejmlabs/ejm-ui"))
                self.manifest(*case["files"])
                self.skipped.write_text(json.dumps(case["skipped"]))
                self.patch.write_text(case["patch"])
                result, _ = self.run_adapter()
                if expect_complete:
                    self.complete(result)
                else:
                    self.incomplete(result)

    def test_added_svg_with_any_plus_content_fails_closed(self):
        self.manifest(self.file("ok.svg", source=None, status="added", additions=1, deletions=0,
                                has_patch=True, new_mode="100644"))
        self.skipped.write_text(json.dumps(["ok.svg"]))
        self.patch.write_text(
            "diff --git a/ok.svg b/ok.svg\nnew file mode 100644\n"
            "--- /dev/null\n+++ b/ok.svg\n@@ -0,0 +1 @@\n+"
            "<svg><use href=\"#a\" xlink:href=\"#b\"/><rect fill=\"url(#g)\"/></svg>\n"
        )
        result, _ = self.run_adapter()
        self.incomplete(result)


if __name__ == "__main__":
    unittest.main()
