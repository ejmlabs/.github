import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS = """
PASSWORD = "placeholder"


def connect(password: str = "placeholder") -> str:
    return password


CONNECTION = connect(password="placeholder")
"""
HOUSE_LOGGING = """
import logging

logger = logging.getLogger(__name__)


def run() -> None:
    try:
        int("x")
    except Exception as error:
        logger.error("failed: %s", type(error).__name__)
"""


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

    def test_layer_allows_the_house_logging_form_and_test_credentials(self) -> None:
        """Run the shared ruff layer on sample files: the ignores it promises hold, and the rest still applies."""
        uv = shutil.which("uv")
        if uv is None:
            self.fail("uv is required to run the locked strict tools")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            shutil.copy(ROOT / "templates/lint/ruff.strict.toml", work / "ruff.strict.toml")
            (work / "ruff.toml").write_text('extend = "ruff.strict.toml"\ntarget-version = "py312"\n')
            (work / "tests").mkdir()
            (work / "module.py").write_text(HOUSE_LOGGING + CREDENTIALS)
            (work / "tests/test_module.py").write_text(CREDENTIALS)
            args = [uv, "run", "--locked", "--group", "dev", "ruff", "check", "--no-cache", "--config", str(work / "ruff.toml"), "--output-format", "json", str(work)]
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
            found: dict[str, set[str]] = {}
            for finding in json.loads(result.stdout):
                found.setdefault(Path(finding["filename"]).name, set()).add(finding["code"])
            self.assertEqual(found.get("module.py", set()) & {"BLE001", "TRY400"}, set(), result.stdout)
            self.assertEqual(found.get("module.py", set()) & {"S105", "S106", "S107"}, {"S105", "S106", "S107"}, result.stdout)
            self.assertEqual(found.get("test_module.py", set()) & {"S105", "S106", "S107"}, set(), result.stdout)


if __name__ == "__main__":
    unittest.main()
