import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StrictToolTests(unittest.TestCase):
    """The shared gate runs these tests, so the strict checks need no workflow change."""

    def check(self, tool: str) -> None:
        uv = shutil.which("uv")
        if uv is None:
            self.fail("uv is required to run the locked strict tools")
        args = [uv, "run", "--locked", "--group", "dev", tool, *(["check", "."] if tool == "ruff" else [])]
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ruff_accepts_the_repository(self) -> None:
        self.check("ruff")

    def test_mypy_accepts_the_repository(self) -> None:
        self.check("mypy")


if __name__ == "__main__":
    unittest.main()
