import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sync_community
from repo_tree import RepoTree
from standards import PROFILES, standards

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_NAMES = sorted(path.name for path in (ROOT / "templates/community").glob("*.md"))


class CommunitySyncTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def check(self, repository: str = "ejm-ui") -> tuple[int, str]:
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = sync_community.main([str(self.root), repository, "--check"])
        return code, errors.getvalue()

    def test_ui_sync_targets_its_current_public_development_guide(self) -> None:
        script = ROOT / "scripts/sync_community.py"
        subprocess.run([sys.executable, str(script), str(self.root), "ejm-ui"], check=True, capture_output=True)
        subprocess.run([sys.executable, str(script), str(self.root), "ejm-ui", "--check"], check=True, capture_output=True)
        self.assertIn("README.md#development", (self.root / "CONTRIBUTING.md").read_text())
        self.assertIn("https://github.com/ejmlabs/ejm-ui/issues", (self.root / "SUPPORT.md").read_text())

    def test_the_template_set_is_the_six_community_files(self) -> None:
        self.assertEqual(TEMPLATE_NAMES, ["CODE_OF_CONDUCT.md", "CONTRIBUTING.md", "RELEASING.md", "SECURITY.md", "SUPPORT.md", "THIRD_PARTY_NOTICES.md"])

    def test_every_profile_renders_its_own_repository_and_guide(self) -> None:
        for repository, profile in PROFILES.items():
            with self.subTest(repository=repository):
                self.assertEqual(sync_community.main([str(self.root), repository]), 0)
                for name in TEMPLATE_NAMES:
                    self.assertNotIn("{{", (self.root / name).read_text())
                self.assertIn(profile.guide, (self.root / "CONTRIBUTING.md").read_text())
                self.assertIn("ejmlabs/" + repository, "".join((self.root / name).read_text() for name in TEMPLATE_NAMES))
                self.assertEqual(self.check(repository), (0, ""))

    def test_check_reports_every_missing_or_changed_file_with_a_bounded_diff(self) -> None:
        sync_community.main([str(self.root), "ejm-cli"])
        (self.root / "SECURITY.md").unlink()
        (self.root / "SUPPORT.md").write_text("Changed.\n")
        (self.root / "CONTRIBUTING.md").write_text("".join(f"line {index}\n" for index in range(200)))
        code, report = self.check("ejm-cli")
        self.assertEqual(code, 1)
        self.assertIn("SECURITY.md: missing or not a regular file", report)
        self.assertIn("SUPPORT.md: differs from the template", report)
        self.assertIn("CONTRIBUTING.md: differs from the template", report)
        self.assertIn("+Changed.", report)
        self.assertIn("--- template/SUPPORT.md", report)
        self.assertLess(len(report.splitlines()), 150)
        self.assertNotIn("CODE_OF_CONDUCT.md: ", report)
        self.assertFalse((self.root / "SECURITY.md").exists(), "--check must not write")
        self.assertEqual((self.root / "SUPPORT.md").read_text(), "Changed.\n")

    def test_check_reports_a_symlinked_file_as_not_regular(self) -> None:
        sync_community.main([str(self.root), "ejm-cli"])
        (self.root / "SECURITY.md").unlink()
        (self.root / "SECURITY.md").symlink_to(self.root / "SUPPORT.md")
        code, report = self.check("ejm-cli")
        self.assertEqual(code, 1)
        self.assertIn("SECURITY.md: missing or not a regular file", report)

    def test_sync_refuses_a_symlink_and_writes_nothing(self) -> None:
        outside = self.root / "outside.md"
        outside.write_text("keep\n")
        (self.root / "SUPPORT.md").symlink_to(outside)
        with self.assertRaisesRegex(SystemExit, "Refusing to replace a symlink"):
            sync_community.sync(self.root, "ejm-cli")
        self.assertEqual(outside.read_text(), "keep\n")
        self.assertEqual([path.name for path in self.root.iterdir() if path.name.endswith(".md") and path.name != "outside.md"], ["SUPPORT.md"])

    def test_sync_returns_the_files_it_wrote(self) -> None:
        written = sync_community.sync(self.root, "ejmlabs")
        self.assertEqual(sorted(path.name for path in written), TEMPLATE_NAMES)
        self.assertIn("site/README.md", (self.root / "CONTRIBUTING.md").read_text())

    def test_an_unknown_repository_is_rejected_by_the_parser(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            sync_community.main([str(self.root), "unknown"])

    def test_the_standards_check_requires_the_community_files_but_not_their_exact_text(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        tree = RepoTree(".github", Path(directory.name))
        for name in TEMPLATE_NAMES:
            tree.write(name, "Local wording that differs from every template.\n")
        self.assertEqual(standards(tree.root, ".github"), "0.1.0")
        drifted = io.StringIO()
        with redirect_stderr(drifted):
            self.assertEqual(sync_community.main([str(tree.root), ".github", "--check"]), 1)
        self.assertEqual(drifted.getvalue().count("differs from the template"), len(TEMPLATE_NAMES))
        (tree.root / "SUPPORT.md").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or unsafe file: SUPPORT.md"):
            standards(tree.root, ".github")

    def test_this_repository_matches_its_own_templates_or_the_drift_is_visible(self) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = sync_community.main([str(ROOT), ".github", "--check"])
        # The report is on demand and may legitimately show drift; it must never crash and must name only template files.
        self.assertIn(code, (0, 1))
        for line in errors.getvalue().splitlines():
            if ": differs from the template" in line or ": missing" in line:
                self.assertIn(line.split(":", 1)[0], TEMPLATE_NAMES)


if __name__ == "__main__":
    unittest.main()
