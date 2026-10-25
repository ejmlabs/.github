import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import review_result


def longest_backtick_run(value):
    longest = run = 0
    for char in value:
        if char == "`":
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return longest


class ReviewResultSummaryTests(unittest.TestCase):
    HEAD = "a" * 40
    SCRIPT = Path(__file__).resolve().parents[1] / "scripts/review_result.py"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def finding(self, **changes):
        item = {"severity": "high", "file": "src/main.py", "line": 4,
                "title": "Missing check", "reason": "The request skips the check."}
        item.update(changes)
        return item

    def result(self, findings, **changes):
        value = {"head": self.HEAD, "pass": 2, "complete": True,
                 "summary": "SUMMARY_NOT_FOR_PUBLICATION", "findings": findings}
        value.update(changes)
        return value

    def invoke(self, payload, summary=None, use_summary=True, raw=None, number=2, head=None):
        path = self.root / "review-result.json"
        path.write_text(raw if raw is not None else json.dumps(payload))
        env = os.environ.copy()
        env.pop("GITHUB_STEP_SUMMARY", None)
        if use_summary:
            env["GITHUB_STEP_SUMMARY"] = "" if summary is None else str(summary)
        completed = subprocess.run(
            [sys.executable, str(self.SCRIPT), str(path), self.HEAD if head is None else head, str(number)],
            cwd=self.root, env=env, capture_output=True, text=True)
        return completed

    def assert_fences_hold(self, text):
        lines = text.splitlines()
        index = 0
        opened = 0
        while index < len(lines):
            if re.fullmatch(r"`{3,}", lines[index]):
                fence = lines[index]
                opened += 1
                index += 1
                body = []
                while index < len(lines) and lines[index] != fence:
                    self.assertFalse(re.fullmatch(r"`{%d,}" % len(fence), lines[index]))
                    body.append(lines[index])
                    index += 1
                self.assertLess(index, len(lines))
                self.assertLess(longest_backtick_run("\n".join(body)), len(fence))
            index += 1
        self.assertGreater(opened, 0)
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)
        self.assertNotIn("@", text)
        self.assertNotIn("](", text)
        self.assertNotIn("![", text)
        self.assertNotRegex(text, r"(?i)https?://|www\.")

    def test_blocked_result_publishes_inert_bounded_findings(self):
        secret = "sk" + "-Example1234567890"
        token = "ey" + "JhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiJ0ZXN0In0" + "." + "signature"
        title = (
            "```\n@maintainer [click](https://evil.example/a) ![img](https://evil.example/i)\n"
            "<script>alert(1)</script> <img src=x onerror=alert(1)>\n"
            "[ref]: https://evil.example/x www.evil.example @@team\n```"
        )
        findings = [
            self.finding(severity="low", title="Advisory note", reason="Low detail."),
            self.finding(severity="medium", file="src/<x>@y.py", title=title, reason=f"leaked {secret} {token}"),
            self.finding(severity="critical", title="`" * 15 + "\n@still", reason="Backtick fence"),
        ]
        summary = self.root / "summary.md"
        summary.write_text("EARLIER\n")
        completed = self.invoke(self.result(findings), summary)
        text = summary.read_text()
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "Review pass 2: 3 finding(s); blocked\n")
        self.assertEqual(completed.stderr, "")
        self.assertNotIn("SUMMARY_NOT_FOR_PUBLICATION", completed.stdout + completed.stderr + text)
        self.assertNotIn(self.HEAD, text)
        self.assertNotIn(secret, text)
        self.assertNotIn(token, text)
        self.assertNotIn(title, text)
        self.assertTrue(text.startswith("EARLIER\n"))
        self.assertIn("Advisory note", text)
        self.assertIn("(at)maintainer", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("(at)(at)team", text)
        self.assertIn("[redacted]", text)
        self.assertIn("`" * 16, text)
        self.assertIn("(at)still", text)
        self.assertNotIn("[truncated]", text)
        self.assertLessEqual(len(text.encode("utf-8")), 16 * 1024)
        self.assert_fences_hold(text)
        for severity in ("critical", "medium", "low"):
            self.assertIn(severity, text)

    def test_oversized_summary_is_truncated_with_closed_fences(self):
        findings = [self.finding(title="T" * 4000, reason="R" * 4000, file="f" * 80) for _ in range(4)]
        summary = self.root / "summary.md"
        summary.write_text("EARLIER\n")
        completed = self.invoke(self.result(findings), summary)
        text = summary.read_text()
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "Review pass 2: 4 finding(s); blocked\n")
        self.assertEqual(completed.stderr, "")
        self.assertNotIn("T" * 40, completed.stdout + completed.stderr)
        self.assertTrue(text.startswith("EARLIER\n"))
        self.assertTrue(text.endswith("[truncated]\n"))
        self.assertLessEqual(len(text.encode("utf-8")), len("EARLIER\n".encode()) + 16 * 1024)
        self.assert_fences_hold(text.split("EARLIER\n", 1)[1])

    def test_passed_incomplete_and_invalid_results_publish_nothing(self):
        summary = self.root / "summary.md"
        summary.write_text("KEEP\n")
        cases = (
            ("empty", self.result([]), 0, "passed"),
            ("low", self.result([self.finding(severity="low", title="HIDDEN_LOW")]), 0, "passed"),
            ("incomplete", self.result([self.finding(title="HIDDEN_FINDING")], complete=False), 1, None),
            ("wrong-head", self.result([self.finding(title="HIDDEN_FINDING")], head="b" * 40), 1, None),
            ("wrong-pass", self.result([self.finding(title="HIDDEN_FINDING")], **{"pass": 9}), 1, None),
            ("bad-severity", self.result([self.finding(severity="huge", title="HIDDEN_FINDING")]), 1, None),
            ("extra", {**self.result([self.finding(title="HIDDEN_FINDING")]), "extra": True}, 1, None),
        )
        for name, payload, code, status in cases:
            with self.subTest(name=name):
                summary.write_text("KEEP\n")
                completed = self.invoke(payload, summary)
                self.assertEqual(completed.returncode, code)
                self.assertEqual(summary.read_text(), "KEEP\n")
                self.assertNotIn("HIDDEN_FINDING", completed.stdout + completed.stderr)
                self.assertNotIn("HIDDEN_LOW", completed.stdout + completed.stderr)
                self.assertNotIn("SUMMARY_NOT_FOR_PUBLICATION", completed.stdout + completed.stderr)
                if status == "passed":
                    self.assertEqual(completed.stderr, "")
                    self.assertIn("passed", completed.stdout)
                else:
                    self.assertEqual(completed.stdout, "")
                    self.assertTrue(completed.stderr.startswith("Invalid review output:"))
        summary.write_text("KEEP\n")
        completed = self.invoke(None, summary, raw='{"HIDDEN_PARSE')
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(summary.read_text(), "KEEP\n")
        self.assertEqual(completed.stdout, "")
        self.assertNotIn("HIDDEN_PARSE", completed.stderr)
        link = self.root / "linked.json"
        target = self.root / "review-result.json"
        target.write_text(json.dumps(self.result([self.finding(title="HIDDEN_FINDING")])))
        link.symlink_to(target)
        env = os.environ.copy()
        env["GITHUB_STEP_SUMMARY"] = str(summary)
        completed = subprocess.run(
            [sys.executable, str(self.SCRIPT), str(link), self.HEAD, "2"],
            cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(summary.read_text(), "KEEP\n")
        self.assertNotIn("HIDDEN_FINDING", completed.stdout + completed.stderr)

    def test_missing_or_unsafe_summary_path_still_blocks(self):
        payload = self.result([self.finding(title="HIDDEN_TITLE")])
        summary = self.root / "summary.md"
        summary.write_text("KEEP\n")
        completed = self.invoke(payload, use_summary=False)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "Review pass 2: 1 finding(s); blocked\n")
        self.assertEqual(completed.stderr, "")
        self.assertNotIn("HIDDEN_TITLE", completed.stdout + completed.stderr)
        self.assertEqual(summary.read_text(), "KEEP\n")

        missing = self.root / "missing.md"
        completed = self.invoke(payload, missing)
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(missing.exists())
        self.assertEqual(completed.stdout, "Review pass 2: 1 finding(s); blocked\n")
        self.assertEqual(completed.stderr, "")

        completed = self.invoke(payload, summary=self.root / "summary.md\n")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(summary.read_text(), "KEEP\n")

        completed = self.invoke(payload, summary="")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")

        directory = self.root / "as-dir"
        directory.mkdir()
        completed = self.invoke(payload, directory)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(list(directory.iterdir()), [])
        self.assertEqual(completed.stdout, "Review pass 2: 1 finding(s); blocked\n")

        target = self.root / "target.md"
        target.write_text("KEEP\n")
        link = self.root / "summary-link.md"
        link.symlink_to(target)
        completed = self.invoke(payload, link)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(target.read_text(), "KEEP\n")
        self.assertEqual(link.read_text(), "KEEP\n")
        self.assertEqual(completed.stderr, "")

        summary.chmod(0o444)
        self.addCleanup(lambda: summary.chmod(0o644))
        completed = self.invoke(payload, summary)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(summary.read_text(), "KEEP\n")
        self.assertEqual(completed.stdout, "Review pass 2: 1 finding(s); blocked\n")
        self.assertEqual(completed.stderr, "")
        self.assertNotIn("HIDDEN_TITLE", completed.stdout + completed.stderr)
