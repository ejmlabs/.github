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
            if path == "packages/tokens":
                package["files"] = ["src", "!src/**/*.test.*", "assets/fonts", "assets/brand", "./assets/icons/", "LICENSE"]
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

    def make_public(self, path, **changes):
        manifest = path + "/package.json"
        package = json.loads(standards.read(self.root, manifest))
        package.pop("private", None)
        for field in ("main", "browser", "bin"):
            package.pop(field, None)
        package["publishConfig"] = {"access": "public", "provenance": True}
        self.write(manifest, json.dumps({**package, **changes}))

    def test_exactly_the_owner_public_set_may_publish_with_the_exact_configuration(self):
        for path in standards.UI_PUBLIC:
            self.make_public(path)
        standards.licenses(self.root, "ejm-ui")
        self.assertEqual(standards.UI_PUBLIC, ("packages/core", "packages/ssg", "packages/tokens", "packages/ui"))
        for path in standards.UI_PUBLIC:
            original = standards.read(self.root, path + "/package.json")
            for name, changes in (("private false", {"private": False}),
                                  ("no config", {"publishConfig": None}),
                                  ("restricted", {"publishConfig": {"access": "restricted", "provenance": True}}),
                                  ("no provenance", {"publishConfig": {"access": "public"}}),
                                  ("extra key", {"publishConfig": {"access": "public", "provenance": True, "tag": "x"}}),
                                  ("string provenance", {"publishConfig": {"access": "public", "provenance": "true"}}),
                                  ("integer provenance", {"publishConfig": {"access": "public", "provenance": 1}}),
                                  ("float provenance", {"publishConfig": {"access": "public", "provenance": 1.0}}),
                                  ("changed license", {"license": "MIT"})):
                with self.subTest(package=path, change=name):
                    package = json.loads(original)
                    package.update(changes)
                    if changes.get("publishConfig", 0) is None:
                        del package["publishConfig"]
                    self.write(path + "/package.json", json.dumps(package))
                    with self.assertRaises(ValueError):
                        standards.licenses(self.root, "ejm-ui")
            self.write(path + "/package.json", original)

    def test_other_packages_and_the_root_must_stay_private(self):
        private_only = ("", *(path for path in standards.UI_PACKAGES if path not in standards.UI_PUBLIC))
        self.assertEqual(private_only, ("", "packages/demos", "packages/ink", "packages/shots", "packages/site"))
        for path in private_only:
            manifest = (path + "/" if path else "") + "package.json"
            original = json.loads(standards.read(self.root, manifest))
            del original["private"]
            original["publishConfig"] = {"access": "public", "provenance": True}
            with self.subTest(package=path):
                self.write(manifest, json.dumps(original))
                with self.assertRaisesRegex(ValueError, "must remain private"):
                    standards.licenses(self.root, "ejm-ui")
                self.write(manifest, json.dumps({**original, "private": True}))
                standards.licenses(self.root, "ejm-ui")

    def test_published_tokens_cannot_ship_brand_logos_or_artwork(self):
        self.make_public("packages/tokens")
        base = ["src", "!src/**/*.test.*", "generated", "theme.json", "LICENSE"]
        for files in (base, base + ["assets/fonts", "assets/brand", "assets/icons", "assets/fonts/Manrope-OFL.txt", "./assets/icons/", "!assets/icons/x.svg"]):
            self.make_public("packages/tokens", files=files)
            standards.licenses(self.root, "ejm-ui")
        for entry in ("assets", "assets/", "assets/logos", "./assets", "././assets/logos", "assets/fonts/../logos", "assets/*", "assets/{logos,fonts}",
                      "assets/fonts/*", "*", "**/logos", "{assets}", ".", "", "./", "../assets", "assets\\logos", "assets/brandx", "assetsx/../assets",
                      "!!assets", "!!assets/logos", "!!!!assets", "!!**", "!!"):
            with self.subTest(entry=entry):
                self.make_public("packages/tokens", files=base + [entry])
                with self.assertRaisesRegex(ValueError, "brand logos and artwork"):
                    standards.licenses(self.root, "ejm-ui")
        # An odd number of leading `!` only excludes, so it cannot add files.
        for entry in ("!assets", "!!!assets", "!assets/logos"):
            self.make_public("packages/tokens", files=base + [entry])
            standards.licenses(self.root, "ejm-ui")
        for field, value in (("main", "assets/logos/x.svg"), ("main", "./assets/logos/x.svg"), ("browser", "assets/logos/x.svg"),
                             ("bin", "assets/logos/x.svg"), ("bin", {"x": "./assets/logos/x.svg"}), ("main", "assets"),
                             ("main", 1), ("bin", {"x": 1})):
            with self.subTest(field=field, value=value):
                self.make_public("packages/tokens", files=base, **{field: value})
                with self.assertRaisesRegex(ValueError, "brand logos and artwork"):
                    standards.licenses(self.root, "ejm-ui")
        for field, value in (("main", "./src/index.ts"), ("browser", "assets/icons/x.svg"), ("bin", {"x": "bin/x.js"}), ("bin", "bin/x.js")):
            with self.subTest(field=field, value=value):
                self.make_public("packages/tokens", files=base, **{field: value})
                standards.licenses(self.root, "ejm-ui")
        for files in (None, "assets/fonts", [1], {"assets": True}):
            with self.subTest(files=files):
                self.make_public("packages/tokens", files=files)
                if files is None:
                    package = json.loads(standards.read(self.root, "packages/tokens/package.json"))
                    del package["files"]
                    self.write("packages/tokens/package.json", json.dumps(package))
                with self.assertRaisesRegex(ValueError, "brand logos and artwork"):
                    standards.licenses(self.root, "ejm-ui")

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

    def test_original_public_font_notices_pass_the_unpatched_hash_allowlist(self):
        self.hashes.stop()
        fixtures = Path(__file__).parent / "fixtures" / "font-notices"
        for name in ("Manrope", "IBMPlexMono"):
            original = (fixtures / (name + "-OFL.txt")).read_bytes().decode("utf-8")
            self.write("packages/tokens/assets/fonts/" + name + "-OFL.txt", original)
            self.write("packages/ui/src/fonts/" + name + "-OFL.txt", original)
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
