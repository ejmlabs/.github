import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sync_agents

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/sync_agents.py"
TEMPLATES = ROOT / "templates/agents"
RULES_MARKERS = "<!-- ejmlabs:house-rules:start -->\n<!-- ejmlabs:house-rules:end -->\n"
SKILLS_MARKERS = "<!-- ejmlabs:skills:start -->\n<!-- ejmlabs:skills:end -->\n"
SKILL_BYTES = 5000


def sync(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), str(root), *args], capture_output=True, text=True, check=False)


def repository(directory: str, own: tuple[str, ...] = (), *, routing: bool = True) -> Path:
    """Make a checkout whose AGENTS.md has empty marker blocks and routes the repository's own skills by hand."""
    root = Path(directory)
    rows = "".join(f"- [{name}](.agents/skills/{name}/SKILL.md)\n" for name in own)
    (root / "AGENTS.md").write_text("# repo\n\n" + RULES_MARKERS + "\n## Skills\n\n" + (SKILLS_MARKERS if routing else "") + rows)
    return root


def snapshot(root: Path) -> dict[str, str]:
    """Record every path under a checkout: file bytes, link targets and directories."""
    state = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            state[name] = "link:" + str(path.readlink())
        elif path.is_dir():
            state[name] = "dir"
        else:
            state[name] = path.read_text()
    return state


def first_sentence(name: str) -> str:
    header = (TEMPLATES / "skills" / name / "SKILL.md").read_text().removeprefix("---\n").partition("\n---\n")[0]
    description = next(line for line in header.splitlines() if line.startswith("description: ")).removeprefix("description: ")
    return re.split(r"(?<=\.)\s", description, maxsplit=1)[0]


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
            self.assertIn("ejmlabs-python", (root / "AGENTS.md").read_text())

    def test_drift_is_named_for_every_part(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            sync(root)
            (root / ".agents/skills/ejmlabs-writing/extra.md").write_text("x\n")
            (root / ".claude/skills/ejmlabs-testing").unlink()
            agents = root / "AGENTS.md"
            agents.write_text(agents.read_text().replace("## House rules", "## Rules"))
            result = sync(root, "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ejmlabs-writing: differs", result.stderr)
            self.assertIn("house rules differ", result.stderr)
            self.assertIn(".claude/skills/ejmlabs-testing: must be a symlink", result.stderr)

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

    def test_this_repository_is_in_sync(self) -> None:
        result = sync(ROOT, "--check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_templates_option_syncs_and_checks_against_another_revision(self) -> None:
        # The shared gate passes the templates at the caller's pin, so the check follows the pin, not this checkout.
        with tempfile.TemporaryDirectory() as directory:
            templates = Path(directory) / "pinned"
            shutil.copytree(TEMPLATES, templates)
            rules = templates / "house-rules.md"
            rules.write_text(rules.read_text().replace("## House rules\n", "## House rules\n\nA newer rule.\n", 1))
            root = Path(directory) / "repo"
            root.mkdir()
            repository(str(root))
            self.assertEqual(sync(root).returncode, 0)
            stale = sync(root, "--check", "--templates", str(templates))
            self.assertEqual(stale.returncode, 1)
            self.assertIn("house rules differ from the shared block", stale.stderr)
            self.assertEqual(sync(root, "--templates", str(templates)).returncode, 0)
            self.assertIn("A newer rule.", (root / "AGENTS.md").read_text())
            self.assertEqual(sync(root, "--check", "--templates", str(templates)).returncode, 0)
            self.assertEqual(sync(root, "--check").returncode, 1)

    def test_a_missing_or_linked_templates_directory_is_refused_and_nothing_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            before = snapshot(root)
            linked = Path(directory) / "linked"
            linked.symlink_to(TEMPLATES)
            for templates in (Path(directory) / "missing", linked):
                with self.subTest(templates=templates.name):
                    for args in ((), ("--check",)):
                        result = sync(root, *args, "--templates", str(templates))
                        self.assertEqual(result.returncode, 1)
                        self.assertIn("not a shared templates directory", result.stderr)
            linked.unlink()
            self.assertEqual(snapshot(root), before)


class RoutingBlockTests(unittest.TestCase):
    def test_block_is_built_from_frontmatter_and_leaves_repository_rows_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory, ("repo-own",))
            own = root / ".agents/skills/repo-own"
            own.mkdir(parents=True)
            (own / "SKILL.md").write_text("---\nname: repo-own\ndescription: Test.\n---\n")
            self.assertEqual(sync(root, "ejmlabs-rust").returncode, 0)
            text = (root / "AGENTS.md").read_text()
            block = text.split("<!-- ejmlabs:skills:start -->")[1].split("<!-- ejmlabs:skills:end -->")[0]
            self.assertTrue(block.strip().splitlines()[0].startswith("- [ejmlabs-workflow]"))
            for name in ("ejmlabs-workflow", "ejmlabs-engineering", "ejmlabs-rust"):
                self.assertIn(f"- [{name}](.agents/skills/{name}/SKILL.md): {first_sentence(name)}\n", block)
            self.assertNotIn("repo-own", block)
            self.assertTrue(text.endswith("- [repo-own](.agents/skills/repo-own/SKILL.md)\n"))

    def test_missing_block_is_reported_by_check_and_added_by_sync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory, routing=False)
            self.assertIn("skills routing block is missing", sync(root, "--check").stderr)
            self.assertEqual(sync(root).returncode, 0)
            text = (root / "AGENTS.md").read_text()
            self.assertEqual(text.count("<!-- ejmlabs:skills:start -->"), 1)
            self.assertEqual(text.count("## Skills"), 1)
            self.assertLess(text.index("ejmlabs:house-rules:end"), text.index("ejmlabs:skills:start"))
            self.assertEqual(sync(root, "--check").returncode, 0)
            self.assertEqual(sync(root).returncode, 0)
            self.assertEqual((root / "AGENTS.md").read_text(), text)

    def test_first_sync_puts_the_block_inside_an_existing_skills_section(self) -> None:
        intro = "Load the skill whose trigger matches the work before you start it.\n"
        table = "| Work | Skill |\n| --- | --- |\n| Repository work | [repo-own](.agents/skills/repo-own/SKILL.md) |\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            own = root / ".agents/skills/repo-own"
            own.mkdir(parents=True)
            (own / "SKILL.md").write_text("---\nname: repo-own\ndescription: Test.\n---\n")
            agents = root / "AGENTS.md"
            agents.write_text("# repo\n\n" + RULES_MARKERS + "\n## Skills\n\n" + intro + "\n" + table + "\n## Done means\n\nShipped.\n")
            self.assertEqual(sync(root).returncode, 0)
            text = agents.read_text()
            self.assertEqual(text.count("## Skills"), 1)
            self.assertLess(text.index(intro), text.index("<!-- ejmlabs:skills:start -->"))
            self.assertLess(text.index("<!-- ejmlabs:skills:end -->"), text.index(table))
            self.assertTrue(text.endswith(table + "\n## Done means\n\nShipped.\n"))
            self.assertEqual(sync(root, "--check").returncode, 0)
            self.assertEqual(sync(root).returncode, 0)
            self.assertEqual(agents.read_text(), text)

    def test_stale_block_is_named_and_repaired_without_touching_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory, ("repo-own",))
            own = root / ".agents/skills/repo-own"
            own.mkdir(parents=True)
            (own / "SKILL.md").write_text("---\nname: repo-own\ndescription: Test.\n---\n")
            sync(root)
            agents = root / "AGENTS.md"
            good = agents.read_text()
            agents.write_text(good.replace("- [ejmlabs-writing]", "- [ejmlabs-writing-old]"))
            self.assertIn("skills routing differs", sync(root, "--check").stderr)
            self.assertEqual(sync(root).returncode, 0)
            self.assertEqual(agents.read_text(), good)

    def test_end_markers_may_close_the_file(self) -> None:
        for order in ("rules last", "skills last"):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                rules, skills = RULES_MARKERS.rstrip("\n"), SKILLS_MARKERS.rstrip("\n")
                first, last = (skills, rules) if order == "rules last" else (rules, skills)
                text = f"# repo\n\n{first}\n\n{last}"
                (root / "AGENTS.md").write_text(text)
                first_run = sync(root)
                self.assertEqual(first_run.returncode, 0, first_run.stderr)
                self.assertEqual(sync(root, "--check").returncode, 0)
                self.assertFalse((root / "AGENTS.md").read_text().endswith("\n"))
                self.assertEqual(sync(root).returncode, 0)

    def test_a_missing_block_is_added_when_the_house_rules_close_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("# repo\n\n" + RULES_MARKERS.rstrip("\n"))
            self.assertEqual(sync(root).returncode, 0)
            self.assertEqual(sync(root, "--check").returncode, 0)
            self.assertIn("<!-- ejmlabs:house-rules:end -->\n\n## Skills", (root / "AGENTS.md").read_text())

    def test_two_blocks_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            agents = root / "AGENTS.md"
            agents.write_text(agents.read_text() + SKILLS_MARKERS)
            result = sync(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("at most one block", result.stderr)

    def test_a_marker_without_its_partner_is_refused_and_nothing_is_written(self) -> None:
        for marker in ("<!-- ejmlabs:skills:start -->\n", "<!-- ejmlabs:skills:end -->\n"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                root = repository(directory, routing=False)
                agents = root / "AGENTS.md"
                agents.write_text(agents.read_text() + marker)
                before = snapshot(root)
                result = sync(root, "ejmlabs-rust")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("at most one block", result.stderr)
                self.assertEqual(snapshot(root), before)

    def test_a_repository_skill_that_nothing_routes_is_reported_after_the_sync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            own = root / ".agents/skills/repo-own"
            own.mkdir(parents=True)
            (own / "SKILL.md").write_text("---\nname: repo-own\ndescription: Test.\n---\n")
            result = sync(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("route .agents/skills/repo-own/SKILL.md", result.stderr)
            self.assertTrue((root / ".agents/skills/ejmlabs-workflow/SKILL.md").is_file())


class SafetyTests(unittest.TestCase):
    def test_unknown_name_is_refused_before_anything_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            before = snapshot(root)
            result = sync(root, "ejmlabs-rust", "ejmlabs-nope")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ejmlabs-nope: not a shared skill", result.stderr)
            self.assertEqual(snapshot(root), before)

    def test_missing_house_rules_markers_write_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("# repo\n")
            before = snapshot(root)
            self.assertNotEqual(sync(root, "ejmlabs-rust").returncode, 0)
            self.assertEqual(snapshot(root), before)

    def test_symlinked_skill_directory_is_refused_and_nothing_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            elsewhere = Path(directory) / "elsewhere"
            elsewhere.mkdir()
            (elsewhere / "SKILL.md").write_text("mine\n")
            (root / ".agents/skills").mkdir(parents=True)
            (root / ".agents/skills/ejmlabs-testing").symlink_to(elsewhere)
            before = snapshot(root)
            for flags in ([], ["--check"]):
                result = sync(root, *flags)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("symlink", result.stderr)
            self.assertEqual(snapshot(root), before)
            self.assertEqual((elsewhere / "SKILL.md").read_text(), "mine\n")

    def test_symlinked_claude_skills_is_refused_and_nothing_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            elsewhere = Path(directory) / "elsewhere"
            elsewhere.mkdir()
            (root / ".claude").mkdir()
            (root / ".claude/skills").symlink_to(elsewhere)
            before = snapshot(root)
            result = sync(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)
            self.assertEqual(snapshot(root), before)
            self.assertEqual(list(elsewhere.iterdir()), [])

    def test_a_blocking_link_problem_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            copy = root / ".claude/skills/ejmlabs-testing"
            copy.mkdir(parents=True)
            (copy / "SKILL.md").write_text("old copy\n")
            before = snapshot(root)
            self.assertIn("must be a symlink", sync(root).stderr)
            self.assertEqual(snapshot(root), before)

    def test_symlink_inside_a_skill_is_drift_and_is_replaced_without_following_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            sync(root)
            outside = Path(directory) / "outside.md"
            outside.write_text("keep\n")
            (root / ".agents/skills/ejmlabs-writing/leak.md").symlink_to(outside)
            result = sync(root, "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ejmlabs-writing: differs", result.stderr)
            self.assertEqual(sync(root).returncode, 0)
            self.assertFalse((root / ".agents/skills/ejmlabs-writing/leak.md").exists())
            self.assertEqual(outside.read_text(), "keep\n")
            self.assertEqual(sync(root, "--check").returncode, 0)

    def test_replacement_keeps_the_old_copy_when_the_new_one_cannot_be_made(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "skills/ejmlabs-testing"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old\n")
            source = Path(directory) / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new\n")
            with patch("shutil.copytree", side_effect=OSError("disk full")), self.assertRaises(OSError):
                sync_agents.replace_directory(source, target)
            self.assertEqual((target / "SKILL.md").read_text(), "old\n")
            self.assertEqual([path.name for path in target.parent.iterdir()], ["ejmlabs-testing"])

    def test_replacement_swaps_in_the_new_copy_and_leaves_nothing_behind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "skills/ejmlabs-testing"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old\n")
            (target / "gone.md").write_text("old\n")
            source = Path(directory) / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new\n")
            sync_agents.replace_directory(source, target)
            self.assertEqual(sorted(path.name for path in target.iterdir()), ["SKILL.md"])
            self.assertEqual((target / "SKILL.md").read_text(), "new\n")
            self.assertEqual([path.name for path in target.parent.iterdir()], ["ejmlabs-testing"])

    def test_replacement_restores_the_old_copy_when_the_swap_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "skills/ejmlabs-testing"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old\n")
            source = Path(directory) / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new\n")
            real = Path.rename

            def fail_second(self: Path, destination: Path) -> Path:
                if self.name.startswith(".ejmlabs-testing.new-"):
                    raise OSError("rename failed")
                return real(self, destination)

            with patch.object(Path, "rename", fail_second), self.assertRaises(OSError):
                sync_agents.replace_directory(source, target)
            self.assertEqual((target / "SKILL.md").read_text(), "old\n")
            self.assertEqual([path.name for path in target.parent.iterdir()], ["ejmlabs-testing"])


class SharedSkillTests(unittest.TestCase):
    """Hold the shared skills to the authoring rules this repository's tests enforce, since consumers receive only the copies."""

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
                # plain YAML scalars: ": " or " #" would break strict frontmatter loaders
                self.assertFalse(": " in description or " #" in description or description[0] in "'\"[]{}&*!|>%@`")
                self.assertLessEqual(len(skill.read_bytes()), SKILL_BYTES)
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
