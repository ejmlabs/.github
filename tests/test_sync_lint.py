import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/sync_lint.py"
TEMPLATES = Path(__file__).resolve().parents[1] / "templates/lint"


def sync(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), str(root), *args], capture_output=True, text=True, check=False)


def manifest(**overrides: str) -> str:
    """Render the template tables with some levels replaced."""
    text = (TEMPLATES / "cargo-lints.toml").read_text()
    for name, replacement in overrides.items():
        text = text.replace(f'{name} = "deny"', f'{name} = "{replacement}"')
    return text


class SyncLintTests(unittest.TestCase):
    def test_copy_then_check_passes_and_drift_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ["eslint.strict.mjs", "ruff.strict.toml", ".shellcheckrc"]
            self.assertEqual(sync(root, *names).returncode, 0)
            self.assertEqual(sync(root, *names, "--check").returncode, 0)
            (root / "eslint.strict.mjs").write_text("export default [];\n")
            result = sync(root, *names, "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("eslint.strict.mjs", result.stderr)

    def test_missing_copy_and_unknown_template_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertNotEqual(sync(root, "ruff.strict.toml", "--check").returncode, 0)
            self.assertIn("Unknown template", sync(root, "cargo-lints.toml").stderr)

    def test_symlinked_target_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "elsewhere").write_text("x\n")
            (root / ".shellcheckrc").symlink_to(root / "elsewhere")
            for flag in ([], ["--check"]):
                result = sync(root, ".shellcheckrc", *flag)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("symlink", result.stderr)
            self.assertEqual((root / "elsewhere").read_text(), "x\n")

    def test_symlinked_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            real.mkdir()
            link = Path(directory) / "link"
            link.symlink_to(real)
            self.assertIn("symlink", sync(link, ".shellcheckrc").stderr)

    def test_rust_tables_accept_the_template_and_stricter_levels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").write_text(manifest())
            self.assertEqual(sync(root, "cargo-lints:Cargo.toml", "--check").returncode, 0)
            (root / "Cargo.toml").write_text(manifest(unsafe_code="forbid"))
            self.assertEqual(sync(root, "cargo-lints:Cargo.toml", "--check").returncode, 0)

    def test_rust_tables_accept_the_single_crate_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").write_text(manifest().replace("workspace.lints", "lints"))
            self.assertEqual(sync(root, "cargo-lints:Cargo.toml", "--check").returncode, 0)

    def test_rust_tables_refuse_looser_or_missing_lints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").write_text(manifest(unwrap_used="warn"))
            result = sync(root, "cargo-lints:Cargo.toml", "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("clippy::unwrap_used is looser", result.stderr)
            (root / "Cargo.toml").write_text(manifest().replace('exit = "deny"\n', ""))
            self.assertIn("clippy::exit is missing", sync(root, "cargo-lints:Cargo.toml", "--check").stderr)
            (root / "Cargo.toml").write_text('[package]\nname = "x"\n')
            self.assertNotEqual(sync(root, "cargo-lints:Cargo.toml", "--check").returncode, 0)

    def test_check_reports_every_difference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ["eslint.strict.mjs", "ruff.strict.toml", ".shellcheckrc"]
            self.assertEqual(sync(root, *names).returncode, 0)
            (root / "eslint.strict.mjs").write_text("export default [];\n")
            (root / ".shellcheckrc").unlink()
            (root / "Cargo.toml").write_text(manifest(unwrap_used="warn").replace('exit = "deny"\n', ""))
            result = sync(root, *names, "cargo-lints:Cargo.toml", "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("eslint.strict.mjs", result.stderr)
            self.assertIn(".shellcheckrc", result.stderr)
            self.assertNotIn("ruff.strict.toml", result.stderr)
            self.assertIn("clippy::unwrap_used is looser", result.stderr)
            self.assertIn("clippy::exit is missing", result.stderr)

    def test_unknown_template_stops_the_run_before_any_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = sync(root, "ruff.strict.toml", "nope.toml", "cargo-lints:Cargo.toml")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unknown template: nope.toml", result.stderr)
            self.assertIn("pasted into Cargo.toml by hand", result.stderr)
            self.assertEqual(list(root.iterdir()), [])

    def test_symlinked_target_later_in_the_list_stops_the_run_before_any_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "elsewhere").write_text("x\n")
            (root / ".shellcheckrc").symlink_to(root / "elsewhere")
            result = sync(root, "ruff.strict.toml", ".shellcheckrc")
            self.assertIn("symlink", result.stderr)
            self.assertFalse((root / "ruff.strict.toml").exists())
            self.assertEqual((root / "elsewhere").read_text(), "x\n")

    def test_missing_and_unreadable_manifests_are_reported_with_the_other_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Broken.toml").write_text("this is [not toml\n")
            result = sync(root, "ruff.strict.toml", "cargo-lints:Missing.toml", "cargo-lints:Broken.toml", "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Lint layer differs", result.stderr)
            self.assertIn("Missing.toml: the file is missing", result.stderr)
            self.assertIn("Broken.toml", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_rust_tables_are_never_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertNotEqual(sync(Path(directory), "cargo-lints:Cargo.toml").returncode, 0)


if __name__ == "__main__":
    unittest.main()
