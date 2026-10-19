import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import standards
from governance import GitHub


class UIStandardsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.font = "Copyright fixture\r\nOriginal OFL fixture bytes.\r\n"
        self.hashes = patch.dict(standards.UI_FONT_HASHES, {
            name: hashlib.sha256(self.font.encode()).hexdigest() for name in ("Manrope", "IBMPlexMono")
        })
        self.hashes.start()
        self.addCleanup(self.hashes.stop)
        self.license = "ejm-ui license scope\n\n" + standards.UI_LICENSE_SCOPE + "\n\nMIT License\nCopyright (c) 2026 Example\n" + standards.MIT_TERMS
        self.write("LICENSE", self.license)
        self.write("VERSION", "0.1.0\n")
        self.write("CHANGELOG.md", "## [0.1.0] - 2026-10-19\nInitial source.\n")
        lock = {"version": "0.1.0", "packages": {}}
        for path in ("", *standards.UI_PACKAGES):
            prefix = path + "/" if path else ""
            package = {"version": "0.1.0", "private": True, "license": "SEE LICENSE IN LICENSE"}
            if path:
                package["repository"] = {"type": "git", "url": "git+https://github.com/ejmlabs/ejm-ui.git", "directory": path}
                self.write(prefix + "LICENSE", self.license)
                self.write(prefix + "THIRD_PARTY_NOTICES.md", "# Third-party notices\nSee LICENSE.\n")
            self.write(prefix + "package.json", json.dumps(package))
            lock["packages"][path] = {"version": "0.1.0"}
        self.write("package-lock.json", json.dumps(lock))
        self.write("crates/ejm-tui/Cargo.toml", '[package]\nname="ejm-tui"\nversion="0.1.0"\nlicense="MIT"\npublish=false\n')
        self.write("crates/ejm-tui/Cargo.lock", '[[package]]\nname="ejm-tui"\nversion="0.1.0"\n')
        for path in standards.UI_FONT_NOTICES:
            self.write(path, self.font)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode())

    def test_ui_versions_accept_scoped_licenses_and_preserve_notice_bytes(self):
        self.assertEqual(standards.versions(self.root, "ejm-ui"), "0.1.0")
        self.assertEqual(standards.read(self.root, standards.UI_FONT_NOTICES[0], preserve_newlines=True), self.font)
        self.assertEqual(standards.read(self.root, standards.UI_FONT_NOTICES[0]), self.font.replace("\r\n", "\n"))

    def test_owned_package_and_lock_versions_cannot_drift(self):
        paths = ("package.json", *(path + "/package.json" for path in standards.UI_PACKAGES))
        for path in paths:
            original = (self.root / path).read_bytes()
            changed = json.loads(original)
            changed["version"] = "0.2.0"
            with self.subTest(path=path):
                self.write(path, json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "differs from VERSION"):
                    standards.versions(self.root, "ejm-ui")
                (self.root / path).write_bytes(original)
        original = json.loads(standards.read(self.root, "package-lock.json"))
        for path in ("", *standards.UI_PACKAGES):
            changed = copy.deepcopy(original)
            changed["packages"][path]["version"] = "0.2.0"
            with self.subTest(lock=path):
                self.write("package-lock.json", json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "npm lock package"):
                    standards.versions(self.root, "ejm-ui")
        self.write("package-lock.json", json.dumps(original))
        self.write("crates/ejm-tui/Cargo.lock", '[[package]]\nname="ejm-tui"\nversion="0.2.0"\n')
        with self.assertRaisesRegex(ValueError, "Cargo lock package"):
            standards.versions(self.root, "ejm-ui")

    def test_new_owned_package_requires_policy_review(self):
        self.write("packages/unreviewed/package.json", '{"version":"0.1.0"}')
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            standards.versions(self.root, "ejm-ui")

    def test_license_cannot_expand_to_reserved_material_or_lose_software_terms(self):
        for changed in ("MIT License\nCopyright 2026 Example\n" + standards.MIT_TERMS,
                        self.license.replace(standards.MIT_TERMS, "Incomplete terms.")):
            with self.subTest(license=changed[:40]):
                self.write("LICENSE", changed)
                with self.assertRaisesRegex(ValueError, "reserved brand rights"):
                    standards.licenses(self.root, "ejm-ui")

    def test_package_identity_privacy_and_notices_are_required(self):
        for path in standards.UI_PACKAGES:
            manifest_path = path + "/package.json"
            original = json.loads(standards.read(self.root, manifest_path))
            for field, changed in (("license", "MIT"), ("private", False), ("repository", {"url": "https://example.com"})):
                with self.subTest(package=path, field=field):
                    self.write(manifest_path, json.dumps({**original, field: changed}))
                    with self.assertRaises(ValueError):
                        standards.licenses(self.root, "ejm-ui")
            self.write(manifest_path, json.dumps(original))
            notice = path + "/THIRD_PARTY_NOTICES.md"
            self.write(notice, "")
            with self.subTest(package=path, field="notice"), self.assertRaisesRegex(ValueError, "third-party notices"):
                standards.licenses(self.root, "ejm-ui")
            self.write(notice, "# Third-party notices\nSee LICENSE.\n")

    def test_font_licenses_must_be_original_and_match_the_ui_package(self):
        source, copied = standards.UI_FONT_NOTICES[0], standards.UI_FONT_NOTICES[2]
        self.write(source, self.font + "Changed terms.\n")
        with self.assertRaisesRegex(ValueError, "original OFL"):
            standards.licenses(self.root, "ejm-ui")
        self.write(source, self.font)
        self.write(copied, self.font.replace("\r\n", "\n"))
        standards.licenses(self.root, "ejm-ui")
        self.write(copied, self.font + "Changed terms.\n")
        with self.assertRaisesRegex(ValueError, "differs from the token owner"):
            standards.licenses(self.root, "ejm-ui")

    def test_ui_repository_is_explicit_and_other_owners_remain_rejected(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "ejmlabs/ejm-ui", "GH_TOKEN": "fixture"}, clear=True):
            self.assertEqual(GitHub().repo, "ejmlabs/ejm-ui")
        for repository in ("attacker/ejm-ui", "ejmlabs/ejm-ui-other", "ejmlabs/unreviewed"):
            with self.subTest(repository=repository), patch.dict(os.environ, {"GITHUB_REPOSITORY": repository}, clear=True):
                with self.assertRaisesRegex(ValueError, "has not adopted"):
                    GitHub()


if __name__ == "__main__":
    unittest.main()
