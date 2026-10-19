import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from standards import uniform_guidance


class CommunityPolicyTests(unittest.TestCase):
    def test_rendered_guidance_accepts_only_the_pinned_policy(self):
        template = "See {{development_guide}} in {{repository}}.\nHuman approval is required.\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "CONTRIBUTING.md"
            file.write_text("See docs/development.md in ejmlabs/ejm-ide.\nHuman approval is required.\n")
            uniform_guidance(root, "ejm-ide", {file.name: template})
            file.write_text("Human approval is optional.\n")
            with self.assertRaisesRegex(ValueError, "pinned standard"):
                uniform_guidance(root, "ejm-ide", {file.name: template})


if __name__ == "__main__":
    unittest.main()
