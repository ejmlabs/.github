import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/sync_agents.py"
TEMPLATES = Path(__file__).resolve().parents[1] / "templates/agents"
MARKERS = "<!-- ejmlabs:house-rules:start -->\n<!-- ejmlabs:house-rules:end -->\n"


def sync(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), str(root), *args], capture_output=True, text=True, check=False)


def repository(directory: str, routed: tuple[str, ...] = ()) -> Path:
    """Make a checkout whose AGENTS.md has empty house rules markers and routes every shared skill."""
    root = Path(directory)
    names = sorted(path.name for path in (TEMPLATES / "skills").iterdir()) + list(routed)
    rows = "".join(f"- .agents/skills/{name}/SKILL.md\n" for name in names)
    (root / "AGENTS.md").write_text("# repo\n\n" + MARKERS + "\n## Skills\n\n" + rows)
    return root


class SyncAgentsTests(unittest.TestCase):
    def test_copy_then_check_passes_and_links_every_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory, ("repo-own",))
            own = root / ".agents/skills/repo-own"
            own.mkdir(parents=True)
            (own / "SKILL.md").write_text("---\nname: repo-own\ndescription: Test.\n---\n")
            copied = sync(root, "ejmlabs-rust")
            self.assertEqual(copied.returncode, 0, copied.stderr)
            checked = sync(root, "--check")
            self.assertEqual(checked.returncode, 0, checked.stderr)
            for name in ("ejmlabs-workflow", "ejmlabs-rust", "repo-own"):
                link = root / ".claude/skills" / name
                self.assertTrue(link.is_symlink())
                self.assertTrue((link / "SKILL.md").is_file())
            self.assertIn("## House rules", (root / "AGENTS.md").read_text())

    def test_resync_keeps_installed_stack_skills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            sync(root, "ejmlabs-python")
            (root / ".agents/skills/ejmlabs-python/SKILL.md").write_text("edited\n")
            self.assertEqual(sync(root).returncode, 0)
            self.assertEqual(sync(root, "--check").returncode, 0)

    def test_drift_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            sync(root)
            (root / ".agents/skills/ejmlabs-writing/extra.md").write_text("x\n")
            agents = root / "AGENTS.md"
            agents.write_text(agents.read_text().replace("## House rules", "## Rules"))
            result = sync(root, "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ejmlabs-writing: differs", result.stderr)
            self.assertIn("house rules differ", result.stderr)

    def test_unknown_shared_skill_and_missing_routing_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            sync(root)
            stale = root / ".agents/skills/ejmlabs-retired"
            stale.mkdir()
            (stale / "SKILL.md").write_text("---\nname: ejmlabs-retired\n---\n")
            result = sync(root, "--check")
            self.assertIn("not a shared skill", result.stderr)
            self.assertIn("route .agents/skills/ejmlabs-retired/SKILL.md", result.stderr)

    def test_missing_markers_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("# repo\n")
            self.assertIn("house-rules start and end markers", sync(root).stderr)

    def test_a_real_directory_in_claude_skills_is_kept_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            copy = root / ".claude/skills/ejmlabs-testing"
            copy.mkdir(parents=True)
            (copy / "SKILL.md").write_text("old copy\n")
            result = sync(root)
            self.assertIn("must be a symlink", result.stderr)
            self.assertEqual((copy / "SKILL.md").read_text(), "old copy\n")

    def test_dangling_links_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            sync(root)
            (root / ".claude/skills/gone").symlink_to("../../.agents/skills/gone")
            self.assertIn("dangling", sync(root, "--check").stderr)
            self.assertEqual(sync(root).returncode, 0)
            self.assertFalse((root / ".claude/skills/gone").is_symlink())

    def test_symlinked_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            real.mkdir()
            link = Path(directory) / "link"
            link.symlink_to(real)
            self.assertIn("symlink", sync(link).stderr)


class SharedSkillTests(unittest.TestCase):
    """Hold the shared skills to the authoring rules every consumer's policy gate applies."""

    def test_skills_follow_the_authoring_rules(self) -> None:
        for skill in sorted((TEMPLATES / "skills").glob("*/SKILL.md")):
            with self.subTest(skill=skill.parent.name):
                text = skill.read_text()
                header, separator, body = text.removeprefix("---\n").partition("\n---\n")
                self.assertTrue(text.startswith("---\n") and separator)
                metadata = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
                self.assertEqual(metadata.get("name"), skill.parent.name)
                description = metadata.get("description", "")
                self.assertTrue(0 < len(description) <= 300 and "<" not in description and ">" not in description)
                self.assertLessEqual(len(body.splitlines()), 100)
                for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", body):
                    if "://" not in target and not target.startswith("#"):
                        linked = (skill.parent / target.split("#", 1)[0]).resolve()
                        self.assertTrue(linked.is_relative_to(skill.parent) and linked.exists(), target)

    def test_no_dashes_as_punctuation(self) -> None:
        for path in sorted(TEMPLATES.rglob("*.md")):
            with self.subTest(path=path.relative_to(TEMPLATES).as_posix()):
                self.assertNotRegex(path.read_text(), "[\\u2013\\u2014]")


if __name__ == "__main__":
    unittest.main()
