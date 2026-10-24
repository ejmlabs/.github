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
from pr_agent_result import Incomplete, check_sanitized, sanitize


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

    def test_real_block_scalar_output_has_one_normalized_medium_finding(self):
        fixtures = Path(__file__).parent / "fixtures"
        self.review.write_bytes((fixtures / "real-0.48-review.json").read_bytes())
        self.markdown.write_bytes((fixtures / "real-0.48-review.md").read_bytes())
        result, _ = self.run_adapter(write_review=False)
        self.assertTrue(self.complete(result))
        self.assertEqual(result["findings"], [{
            "severity": "medium", "file": "src/app.py", "line": 3, "title": "Possible Bug",
            "reason": "LEAKMARKER-7Q3Z the loop never terminates when n is negative",
        }])

    def test_model_strings_are_stripped_before_path_checks_and_severity_matching(self):
        self.payload["review"]["key_issues_to_review"] = [self.issue(
            relevant_file=" \tsrc/main.py\n", issue_header=" \nSQL injection\n", issue_content=" \tA query uses raw input.\n")]
        result, _ = self.run_adapter()
        self.complete(result)
        self.assertEqual(result["findings"], [{"severity": "high", "file": "src/main.py", "line": 7,
                                              "title": "SQL injection", "reason": "A query uses raw input."}])
        for file in (" /etc/passwd\n", " ../outside\n"):
            with self.subTest(file=file):
                self.payload["review"]["key_issues_to_review"] = [self.issue(relevant_file=file)]
                result, _ = self.run_adapter()
                self.incomplete(result)

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
        for name in ("Cargo.lock", "folder/uv.lock", "path with spaces/file.csv", "a..b.svg", "café.svg"):
            with self.subTest(name=name):
                self.manifest(self.file(name))
                self.skipped.write_text(json.dumps([name]))
                old, new = "a/" + name, "b/" + name
                if name == "café.svg":
                    old, new = '"a/caf\\303\\251.svg"', '"b/caf\\303\\251.svg"'
                self.patch.write_text(f"diff --git {old} {new}\n--- {old}\n+++ {new}\n@@ -1 +1 @@\n-old\n+new\n")
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
            relevant_file="src/" + "f" * 4000, issue_header="t" * 4001, issue_content="r" * 4001)]
        result, _ = self.run_adapter()
        self.complete(result)
        self.assertEqual([len(result["findings"][0][key]) for key in ("file", "title", "reason")], [4000] * 3)
        self.payload["review"]["key_issues_to_review"] *= 50
        result, _ = self.run_adapter()
        self.incomplete(result)

    def test_key_like_strings_are_redacted_in_all_model_text(self):
        keys = [prefix + "Example1234567890" for prefix in ("sk" + "-", "sk" + "-ant-", "ghp" + "_", "gho" + "_",
                                                         "ghu" + "_", "ghs" + "_", "ghr" + "_",
                                                         "github" + "_pat_", "xox" + "b-")]
        keys.extend(["AK" + "IA" + "A1" * 8, "ey" + "JhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiJ0ZXN0In0" + "." + "signature"])
        for kind in ("", "RSA ", "EC ", "OPENSSH ", "ENCRYPTED "):
            keys.append("-----BE" + "GIN " + kind + "PRIVATE KEY-----\nExampleBase64Data\n-----EN" + "D " + kind + "PRIVATE KEY-----")
        secret_text = " ".join(keys)
        self.payload["review"]["key_issues_to_review"] = [self.issue(
            relevant_file="src/" + keys[0], issue_header=secret_text, issue_content=secret_text)]
        result, stdout = self.run_adapter()
        self.complete(result)
        serialized = self.output.read_text()
        for key in keys:
            self.assertNotIn(key, serialized + stdout)
        finding = result["findings"][0]
        for field in ("file", "title", "reason"):
            self.assertIn("[redacted]", finding[field])
        self.payload["review"]["key_issues_to_review"] = []
        self.payload["review"]["security_concerns"] = secret_text
        result, _ = self.run_adapter()
        self.complete(result)
        self.assertEqual(result["findings"][0]["reason"], " ".join(["[redacted]"] * len(keys)))

    def test_ordinary_words_containing_sk_are_not_redacted(self):
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

    def test_all_finding_fields_and_summary_are_sanitized_before_output(self):
        self.payload["summary"] = "https://example.invalid/summary @user <b>bad</b>"
        self.payload["review"]["key_issues_to_review"] = [self.issue(
            relevant_file="src/@team/<b>app</b>.py", issue_header="Fix [visible](javascript:alert(1)) @@user",
            issue_content="Details <b>bold</b> HTTPS://example.invalid/path <img src=ftp://example.invalid/image> @org/team")]
        result, _ = self.run_adapter()
        self.complete(result)
        self.assertEqual(result["findings"][0]["file"], "src/team/app.py")
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


if __name__ == "__main__":
    unittest.main()
