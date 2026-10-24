import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from standards import uniform_guidance


class CommunityPolicyTests(unittest.TestCase):
    def test_ui_sync_targets_its_current_public_development_guide(self):
        script = Path(__file__).resolve().parents[1] / "scripts/sync_community.py"
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, str(script), directory, "ejm-ui"], check=True, capture_output=True)
            subprocess.run([sys.executable, str(script), directory, "ejm-ui", "--check"], check=True, capture_output=True)
            text = (Path(directory) / "CONTRIBUTING.md").read_text()
            self.assertIn("README.md#development", text)
            support = (Path(directory) / "SUPPORT.md").read_text()
            self.assertIn("https://github.com/ejmlabs/ejm-ui/issues", support)

    def test_chess_sync_targets_its_readme_development_guide(self):
        script = Path(__file__).resolve().parents[1] / "scripts/sync_community.py"
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, str(script), directory, "ejm-chess"], check=True, capture_output=True)
            subprocess.run([sys.executable, str(script), directory, "ejm-chess", "--check"], check=True, capture_output=True)
            text = (Path(directory) / "CONTRIBUTING.md").read_text()
            self.assertIn("README.md#development", text)
            support = (Path(directory) / "SUPPORT.md").read_text()
            self.assertIn("https://github.com/ejmlabs/ejm-chess/issues", support)

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
