import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import standards
from governance import GitHub

# The recorded digests before any test patches them.
RECORDED_PACKING = dict(standards.UI_PACKING_SHA256)


class UIStandardsTests(unittest.TestCase):
    def setUp(self) -> None:
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
        lock: dict[str, Any] = {"version": "0.1.0", "packages": {}}
        for path in ("", *standards.UI_PACKAGES):
            prefix = path + "/" if path else ""
            package: dict[str, Any] = {"version": "0.1.0", "private": True, "license": "SEE LICENSE IN LICENSE"}
            if path:
                package.update(name="@ejm/" + path.split("/")[1], files=["src", "!src/**/*.test.*", "LICENSE"],
                               main="./src/index.ts", exports={".": "./src/index.ts"})
                if path == "packages/tokens":
                    package["files"] = ["src", "!src/**/*.test.*", "assets/fonts", "assets/brand", "assets/icons", "LICENSE"]
                package["repository"] = {"type": "git", "url": "git+https://github.com/ejmlabs/ejm-ui.git", "directory": path}
                self.write(prefix + "LICENSE", self.license)
                self.write(prefix + "THIRD_PARTY_NOTICES.md", "# Third-party notices\nSee LICENSE.\n")
            self.write(prefix + "package.json", json.dumps(package))
            lock["packages"][path] = {"version": "0.1.0"}
        self.write("package-lock.json", json.dumps(lock))
        self.private = {path: standards.read(self.root, path + "/package.json") for path in standards.UI_PACKAGES}
        reviewed = {path: standards.ui_packing(json.loads(standards.read(self.root, path + "/package.json")))
                    for path in standards.UI_PUBLIC}
        packing = patch.dict(standards.UI_PACKING_SHA256, reviewed)
        packing.start()
        self.addCleanup(packing.stop)
        self.write("crates/ejm-tui/Cargo.toml", '[package]\nname="ejm-tui"\nversion="0.1.0"\nlicense="MIT"\npublish=false\n')
        self.write("crates/ejm-tui/Cargo.lock", '[[package]]\nname="ejm-tui"\nversion="0.1.0"\n')
        for path in standards.UI_FONT_NOTICES:
            self.write(path, self.font)

    def write(self, name: str, value: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode())

    def test_ui_versions_accept_scoped_licenses_and_preserve_notice_bytes(self) -> None:
        self.assertEqual(standards.versions(self.root, "ejm-ui"), "0.1.0")
        self.assertEqual(standards.read(self.root, standards.UI_FONT_NOTICES[0], preserve_newlines=True), self.font)
        self.assertEqual(standards.read(self.root, standards.UI_FONT_NOTICES[0]), self.font.replace("\r\n", "\n"))

    def test_owned_package_and_lock_versions_cannot_drift(self) -> None:
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

    def test_new_owned_package_requires_policy_review(self) -> None:
        self.write("packages/unreviewed/package.json", '{"version":"0.1.0"}')
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            standards.versions(self.root, "ejm-ui")

    def test_license_cannot_expand_to_reserved_material_or_lose_software_terms(self) -> None:
        for changed in ("MIT License\nCopyright 2026 Example\n" + standards.MIT_TERMS,
                        self.license.replace(standards.MIT_TERMS, "Incomplete terms.")):
            with self.subTest(license=changed[:40]):
                self.write("LICENSE", changed)
                with self.assertRaisesRegex(ValueError, "reserved brand rights"):
                    standards.licenses(self.root, "ejm-ui")

    def test_package_identity_privacy_and_notices_are_required(self) -> None:
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

    def make_public(self, path: str, **changes: Any) -> None:
        """Make a package public with the reviewed packing fields, then apply changes (None removes a field)."""
        manifest = path + "/package.json"
        package = json.loads(self.private[path])
        package.pop("private", None)
        package["publishConfig"] = {"access": "public", "provenance": True}
        package.update(changes)
        self.write(manifest, json.dumps({key: value for key, value in package.items() if value is not None}))

    def test_exactly_the_owner_public_set_may_publish_with_the_exact_configuration(self) -> None:
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

    def test_other_packages_and_the_root_must_stay_private(self) -> None:
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

    def test_public_packages_must_match_the_reviewed_packing_fields_exactly(self) -> None:
        for path in standards.UI_PUBLIC:
            self.make_public(path)
        standards.licenses(self.root, "ejm-ui")
        tokens = json.loads(standards.read(self.root, "packages/tokens/package.json"))
        base = tokens["files"]
        deviations = {
            "name": ("@ejm/other", "ejm-tokens", "@EJM/tokens", ""),
            "files": ([*base, "assets"], [*base, "assets/logos"], [*base, "./assets"], [*base, "assets/*"], [*base, "!!assets"],
                      [*base, "Assets"], [*base, "assets/fonts"], base[::-1], base[:-1], [*base, "README.md"], ["assets"], [], "assets/fonts"),
            "main": ("assets/logos/x.svg", "Assets/logos/x.svg", "ASSETS/LOGOS/X.SVG", "./src/other.ts", 1),
            "types": ("Assets/logos/x.svg", "./src/other.d.ts"),
            "typings": ("./src/index.ts",),
            "exports": ({".": "./assets/logos/x.svg"}, {}, "./src/index.ts"),
            "bin": ("assets/logos/x.svg", "Assets/logos/x.svg", {"x": "ASSETS/LOGOS/X.SVG"}, {"x": "./src/index.ts"}),
            "browser": ("assets/logos/x.svg", "Assets/logos/x.svg", {"./src/index.ts": False}),
            "module": ("./src/index.ts",),
            "directories": ({"bin": "assets"}, {"bin": "assets/logos"}, {"bin": "Assets"}, {"man": "man"}, {}, "assets"),
            "man": ("assets/logos/x.1", ["x.1"]),
            "bundleDependencies": (True, []),
            "bundledDependencies": (True, []),
            "workspaces": (["assets"],),
            "scripts": ({"prepack": "cp -r assets/logos assets/icons"}, {"prepare": "node x.mjs"}, {"postinstall": "node x.mjs"},
                        {"preprepare": "x"}, {"postprepare": "x"}, {"postpack": "x"}, {"prepublish": "x"}, {"prepublishOnly": "x"},
                        {"publish": "x"}, {"postpublish": "x"}, {"preinstall": "x"}, {"install": "x"}, "prepack", ["prepack"]),
        }
        for path in standards.UI_PUBLIC:
            for field, values in deviations.items():
                for value in values:
                    with self.subTest(package=path, field=field, value=value):
                        self.make_public(path, **{field: value})
                        with self.assertRaisesRegex(ValueError, "differ from the reviewed values"):
                            standards.licenses(self.root, "ejm-ui")
            for field in ("name", "files", "main", "exports"):
                with self.subTest(package=path, removed=field):
                    self.make_public(path, **{field: None})
                    with self.assertRaisesRegex(ValueError, "differ from the reviewed values"):
                        standards.licenses(self.root, "ejm-ui")
            self.make_public(path)
            standards.licenses(self.root, "ejm-ui")

    def test_packing_digest_is_exact_about_types_order_and_field_set(self) -> None:
        package = {"name": "@ejm/x", "files": ["src"], "main": "./src/index.ts"}
        digest = standards.ui_packing(package)
        self.assertEqual(digest, standards.ui_packing({"main": "./src/index.ts", "files": ["src"], "name": "@ejm/x", "version": "1"}))
        self.assertEqual(digest, standards.ui_packing({**package, "scripts": {"build": "x", "check": "y"}}))
        self.assertNotEqual(digest, standards.ui_packing({**package, "scripts": {"build": "x", "prepack": "y"}}))
        for changed in ({**package, "files": ["src", "src"]}, {**package, "files": [["src"]]}, {**package, "main": "./SRC/index.ts"},
                        {**package, "directories": {}}, {**package, "bin": None}, {"files": ["src"], "name": "@ejm/x"}):
            self.assertNotEqual(digest, standards.ui_packing(changed), changed)

    def test_reviewed_values_for_public_packages_match_the_recorded_digests(self) -> None:
        reviewed = {
            "packages/tokens": {
                "name": "@ejm/tokens", "main": "./src/index.ts", "types": "./src/index.ts",
                "exports": {".": "./src/index.ts", "./tailwind.css": "./generated/tailwind.css", "./window.css": "./generated/window.css",
                            "./neutral.css": "./generated/neutral.css", "./theme.css": "./generated/theme.css", "./theme.json": "./theme.json",
                            "./generated/*": "./generated/*", "./assets/*": "./assets/*", "./rust/*": "./rust/*"},
                "files": ["src", "!src/**/*.test.*", "generated", "rust", "theme.json", "README.md", "assets/fonts", "assets/brand",
                          "assets/icons", "LICENSE", "THIRD_PARTY_NOTICES.md"]},
            "packages/core": {
                "name": "@ejm/core", "main": "./src/index.ts", "types": "./src/index.ts",
                "exports": {".": "./src/index.ts", "./contract.json": "./contract.json"},
                "files": ["src", "!src/**/*.test.*", "contract.json", "LICENSE", "THIRD_PARTY_NOTICES.md"]},
            "packages/ssg": {
                "name": "@ejm/ssg", "main": "./src/index.ts", "types": "./src/index.ts", "bin": {"ejm-ssg": "./bin/ejm-ssg.mjs"},
                "exports": {".": "./src/index.ts", "./server": "./src/server.ts", "./vite": "./src/vite.mjs",
                            "./ssg.css": "./src/ssg.css"},
                "files": ["bin", "src", "!src/**/*.test.*", "!src/perf", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"]},
            "packages/ui": json.loads("""
            {
    "name": "@ejm/ui",
                "main": "./src/index.ts",
                "types": "./src/index.ts",
                "exports": {
                    ".": "./src/index.ts",
                    "./styles.css": "./src/styles.css",
                    "./styles-docs.css": "./src/styles-docs.css",
                    "./styles-app.css": "./src/styles-app.css",
                    "./styles-terminal.css": "./src/styles-terminal.css",
                    "./theme-boot.js": "./public/theme-boot.js",
                    "./font-preloads": "./src/font-preloads.ts",
                    "./catalog.json": "./src/catalog.json",
                    "./fonts/*": "./src/fonts/*",
                    "./art/*": "./src/art/*",
                    "./app": "./src/app/index.ts",
                    "./app/messages": "./src/app/messages.ts",
                    "./app/scale": "./src/app/scale.ts",
                    "./app/useBox": "./src/app/useBox.ts",
                    "./app/*": "./src/app/*.tsx",
                    "./docs": "./src/docs/index.ts",
                    "./docs/highlight": "./src/docs/highlight.ts",
                    "./docs/highlight-all": "./src/docs/highlight-all.ts",
                    "./docs/hooks": "./src/docs/hooks.ts",
                    "./docs/*": "./src/docs/*.tsx",
                    "./motion": "./src/motion/index.ts",
                    "./motion/useDrawOn": "./src/motion/useDrawOn.ts",
                    "./motion/useReveal": "./src/motion/useReveal.ts",
                    "./motion/*": "./src/motion/*.tsx",
                    "./layout": "./src/layout/index.ts",
                    "./layout/*": "./src/layout/*.tsx",
                    "./shell": "./src/shell/index.ts",
                    "./shell/*": "./src/shell/*.tsx",
                    "./hooks": "./src/hooks/index.ts",
                    "./hooks/*": "./src/hooks/*.ts",
                    "./components/TerminalWorkspace": "./src/terminal/TerminalWorkspace.tsx",
                    "./components/*": "./src/components/*.tsx",
                    "./lib/utils": "./src/lib/utils.ts",
                    "./styles-static.css": "./src/styles-static.css",
                    "./components/NativeCheckbox": "./src/static/NativeCheckbox.tsx",
                    "./shell/Disclosure": "./src/static/Disclosure.tsx",
                    "./layout/ActionRows": "./src/static/ActionRows.tsx",
                    "./layout/DocumentContent": "./src/static/DocumentContent.tsx",
                    "./styles-site.css": "./src/styles-site.css",
                    "./static.css": "./public/static.css",
                    "./control-recipes": {
                        "types": "./src/control-recipes.d.mts",
                        "import": "./src/control-recipes.mjs",
                        "default": "./src/control-recipes.mjs"
                    }
                },
                "files": [
                    "src",
                    "!src/**/*.test.*",
                    "!src/components/test-setup.tsx",
                    "!src/**/README.md",
                    "public/theme-boot.js",
                    "THEME.md",
                    "COMPONENTS.md",
                    "LICENSE",
                    "THIRD_PARTY_NOTICES.md",
                    "public/static.css"
                ]
            }"""),
        }
        for path, package in reviewed.items():
            with self.subTest(package=path):
                self.assertEqual(standards.ui_packing(package), RECORDED_PACKING[path])
        self.assertEqual(sorted(RECORDED_PACKING), sorted(standards.UI_PUBLIC))

    def test_font_licenses_must_be_original_and_match_the_ui_package(self) -> None:
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

    def test_original_public_font_notices_pass_the_unpatched_hash_allowlist(self) -> None:
        self.hashes.stop()
        fixtures = Path(__file__).parent / "fixtures" / "font-notices"
        for name in ("Manrope", "IBMPlexMono"):
            original = (fixtures / (name + "-OFL.txt")).read_bytes().decode("utf-8")
            self.write("packages/tokens/assets/fonts/" + name + "-OFL.txt", original)
            self.write("packages/ui/src/fonts/" + name + "-OFL.txt", original)
        standards.licenses(self.root, "ejm-ui")

    def test_ui_repository_is_explicit_and_other_owners_remain_rejected(self) -> None:
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "ejmlabs/ejm-ui", "GH_TOKEN": "fixture"}, clear=True):
            self.assertEqual(GitHub().repo, "ejmlabs/ejm-ui")
        for repository in ("attacker/ejm-ui", "ejmlabs/ejm-ui-other", "ejmlabs/unreviewed"):
            with (
                self.subTest(repository=repository),
                patch.dict(os.environ, {"GITHUB_REPOSITORY": repository}, clear=True),
                self.assertRaisesRegex(ValueError, "has not adopted"),
            ):
                GitHub()


if __name__ == "__main__":
    unittest.main()
