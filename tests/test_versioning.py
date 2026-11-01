import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from versioning import semver


class SemverTests(unittest.TestCase):
    def test_semver_boundaries(self) -> None:
        for value in ("0.1.0", "1.0.0-rc.1", "1.2.3+build.04", "9.0.1-alpha.0", "1.0.0-0", "1.0.0-alpha-1"):
            self.assertTrue(semver(value), value)
        for value in ("v1.0.0", "01.0.0", "1.0", "1.0.0-01", "1.0.0-", "1.2.3\n", "", "1.0.0-rc.01", "1.0.0+", "1.0.0-rc..1"):
            self.assertFalse(semver(value), value)


if __name__ == "__main__":
    unittest.main()
