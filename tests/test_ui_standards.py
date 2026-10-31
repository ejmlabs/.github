import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import standards
from governance import GitHub
from repo_tree import FONTS, UI_DIRS, UI_LICENSE, RepoTree, TreeCase

# The manifests reviewed when the packing digests were retired, with packages/ui as ejm-ui PR #59 packs it
# (no public/static.css). The structural rules must accept all of them.
REVIEWED: dict[str, dict[str, Any]] = {
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
        "exports": {".": "./src/index.ts", "./server": "./src/server.ts", "./vite": "./src/vite.mjs", "./ssg.css": "./src/ssg.css"},
        "files": ["bin", "src", "!src/**/*.test.*", "!src/perf", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"]},
    "packages/ui": {
        "name": "@ejm/ui", "main": "./src/index.ts", "types": "./src/index.ts",
        "exports": {".": "./src/index.ts", "./styles.css": "./src/styles.css", "./theme-boot.js": "./public/theme-boot.js", "./fonts/*": "./src/fonts/*",
                    "./art/*": "./src/art/*", "./tsconfig.json": "./src/consumer.tsconfig.json",
                    "./vite": {"types": "./src/vite.d.mts", "import": "./src/vite.mjs", "default": "./src/vite.mjs"},
                    "./control-recipes": {"types": "./src/control-recipes.d.mts", "import": "./src/control-recipes.mjs", "default": "./src/control-recipes.mjs"}},
        "files": ["src", "!src/**/*.test.*", "!src/components/test-setup.tsx", "!src/**/README.md", "public/theme-boot.js", "THEME.md", "COMPONENTS.md",
                  "LICENSE", "THIRD_PARTY_NOTICES.md"]},
}


def edit(tree: RepoTree, path: str, **changes: Any) -> None:
    """Change fields of path/package.json; a value of None removes the field."""
    def change(data: dict[str, Any]) -> None:
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value

    tree.change_json((path + "/" if path else "") + "package.json", change)


class UIStandardsTests(TreeCase):
    def test_ui_versions_accept_scoped_licenses_and_preserve_notice_bytes(self) -> None:
        tree = self.tree("ejm-ui")
        self.assertEqual(standards.versions(tree.root, "ejm-ui"), "0.1.0")
        original = (FONTS / "Manrope-OFL.txt").read_bytes().decode()
        self.assertEqual(standards.read(tree.root, standards.UI_FONT_NOTICES[0], preserve_newlines=True), original)
        self.assertEqual(standards.read(tree.root, standards.UI_FONT_NOTICES[0]), original.replace("\r\n", "\n"))
        tree.check()

    def test_owned_package_and_lock_versions_cannot_drift(self) -> None:
        tree = self.tree("ejm-ui")
        for path in ("", *("packages/" + name for name in UI_DIRS)):
            with self.subTest(package=path):
                tree = self.tree("ejm-ui")
                edit(tree, path, version="0.2.0")
                self.fails(tree, re.escape((path + "/" if path else "") + "package.json") + ": .*differs from VERSION")
        for path in ("", *("packages/" + name for name in UI_DIRS)):
            with self.subTest(lock=path):
                tree = self.tree("ejm-ui")
                tree.change_json("package-lock.json", lambda data: data["packages"][path].update(version="0.2.0"))  # noqa: B023 - run before the next iteration
                self.fails(tree, "Owned UI npm lock package differs from VERSION: " + re.escape(path or "<root>"))
        tree = self.tree("ejm-ui")
        tree.write("crates/ejm-tui/Cargo.lock", '[[package]]\nname="ejm-tui"\nversion="0.2.0"\n')
        self.fails(tree, "Owned UI Cargo lock package differs from VERSION")
        tree.write("crates/ejm-tui/Cargo.lock", '[[package]]\nname="other"\nversion="0.1.0"\n')
        self.fails(tree, "Owned UI Cargo lock package differs from VERSION")
        tree.write("crates/ejm-tui/Cargo.lock", '[[package]]\nname="ejm-tui"\nversion="0.1.0"\n[[package]]\nname="ejm-tui"\nversion="0.1.0"\n')
        self.fails(tree, "Owned UI Cargo lock package differs from VERSION")

    def test_a_new_private_package_needs_no_shared_change(self) -> None:
        tree = self.tree("ejm-ui")
        tree.add_ui_package("extra")
        tree.change_json("package-lock.json", lambda data: data["packages"].update({"packages/extra": {"version": "0.1.0"}}))
        tree.check()
        # Its version, lock entry, privacy and notices are still checked through the glob.
        edit(tree, "packages/extra", version="0.2.0")
        self.fails(tree, "packages/extra/package.json: version differs from VERSION")
        edit(tree, "packages/extra", version="0.1.0")
        tree.change_json("package-lock.json", lambda data: data["packages"].pop("packages/extra"))
        self.fails(tree, r"package-lock.json: missing key packages\.packages/extra\.version")
        tree.change_json("package-lock.json", lambda data: data["packages"].update({"packages/extra": {"version": "0.1.0"}}))
        for name, changes in (("not private", {"private": None}), ("public config", {"private": None, "publishConfig": {"access": "public", "provenance": True}}),
                              ("private false", {"private": False}), ("another license", {"license": "MIT"}),
                              ("other repository", {"repository": {"type": "git", "url": "https://example.com/x.git", "directory": "packages/extra"}})):
            with self.subTest(name):
                tree.add_ui_package("extra", **changes)
                self.fails(tree, "packages/extra|must remain private|repository metadata")
        tree.add_ui_package("extra")
        tree.write("packages/extra/THIRD_PARTY_NOTICES.md", "")
        self.fails(tree, "UI package needs complete scoped license and third-party notices: packages/extra")
        tree.add_ui_package("extra")
        (tree.root / "packages/extra/LICENSE").unlink()
        self.fails(tree, "Missing or unsafe file: packages/extra/LICENSE")

    def test_the_glob_lists_directories_with_a_package_json_and_follows_no_symlink(self) -> None:
        tree = self.tree("ejm-ui")
        self.assertEqual(standards.ui_packages(tree.root), sorted("packages/" + name for name in UI_DIRS))
        (tree.root / "packages/notes").mkdir()
        tree.write("packages/README.md", "text\n")
        self.assertEqual(standards.ui_packages(tree.root), sorted("packages/" + name for name in UI_DIRS))
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "package.json").write_text("{}")
        (tree.root / "packages/linked").symlink_to(outside.name, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "packages/linked must not be a symlink"):
            standards.ui_packages(tree.root)
        self.fails(tree, "packages/linked must not be a symlink")
        (tree.root / "packages/linked").unlink()
        (tree.root / "packages/broken").mkdir()
        (tree.root / "packages/broken/package.json").symlink_to(Path(outside.name, "package.json"))
        self.assertIn("packages/broken", standards.ui_packages(tree.root))
        self.fails(tree, "Missing or unsafe file: packages/broken/package.json")

    def test_a_symlinked_packages_directory_is_rejected(self) -> None:
        tree = self.tree("ejm-ui")
        (tree.root / "packages").rename(tree.root / "moved")
        (tree.root / "packages").symlink_to(tree.root / "moved", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "packages must not be a symlink"):
            standards.ui_packages(tree.root)
        self.fails(tree, "packages must not be a symlink")

    def test_too_many_packages_are_rejected(self) -> None:
        tree = self.tree("ejm-ui")
        for index in range(60):
            tree.write(f"packages/p{index}/package.json", "{}")
        with self.assertRaisesRegex(ValueError, "Too many owned UI packages"):
            standards.ui_packages(tree.root)

    def test_a_missing_public_package_is_reported(self) -> None:
        tree = self.tree("ejm-ui")
        for path in standards.UI_PUBLIC:
            (tree.root / path / "package.json").unlink()
        problems = self.fails(tree, "packages/tokens: the reviewed public UI package is missing")
        self.assertEqual(len([problem for problem in problems if "reviewed public UI package is missing" in problem]), 4)

    def test_license_cannot_expand_to_reserved_material_or_lose_software_terms(self) -> None:
        tree = self.tree("ejm-ui")
        for changed in ("MIT License\nCopyright 2026 Example\n" + standards.MIT_TERMS, UI_LICENSE.replace(standards.MIT_TERMS, "Incomplete terms."),
                        UI_LICENSE.replace("ejm-ui license scope", "license scope"), UI_LICENSE.replace(standards.UI_LICENSE_SCOPE, "All rights granted."),
                        UI_LICENSE.replace("MIT License", "License"), ""):
            with self.subTest(license=changed[:40]):
                tree.write("LICENSE", changed)
                with self.assertRaisesRegex(ValueError, "reserved brand rights"):
                    standards.licenses(tree.root, "ejm-ui")
        tree.write("LICENSE", UI_LICENSE)
        standards.licenses(tree.root, "ejm-ui")

    def test_package_identity_privacy_and_notices_are_required(self) -> None:
        for path in ("packages/" + name for name in UI_DIRS):
            tree = self.tree("ejm-ui")
            for field, changed in (("license", "MIT"), ("private", False), ("repository", {"url": "https://example.com"})):
                with self.subTest(package=path, field=field):
                    original = json.loads(tree.read(path + "/package.json"))
                    edit(tree, path, **{field: changed})
                    with self.assertRaises(ValueError):
                        standards.licenses(tree.root, "ejm-ui")
                    tree.write(path + "/package.json", json.dumps(original))
            tree.write(path + "/THIRD_PARTY_NOTICES.md", "")
            with self.subTest(package=path, field="notice"), self.assertRaisesRegex(ValueError, "third-party notices"):
                standards.licenses(tree.root, "ejm-ui")
            tree.write(path + "/THIRD_PARTY_NOTICES.md", "# Notices\n")
            tree.write(path + "/LICENSE", "MIT License\n")
            with self.subTest(package=path, field="package license"), self.assertRaisesRegex(ValueError, "complete scoped license"):
                standards.licenses(tree.root, "ejm-ui")

    def test_exactly_the_owner_public_set_may_publish_with_the_exact_configuration(self) -> None:
        tree = self.tree("ejm-ui")
        standards.licenses(tree.root, "ejm-ui")
        self.assertEqual(standards.UI_PUBLIC, ("packages/core", "packages/ssg", "packages/tokens", "packages/ui"))
        for path in standards.UI_PUBLIC:
            original = tree.read(path + "/package.json")
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
                    edit(tree, path, **changes)
                    with self.assertRaises(ValueError):
                        standards.licenses(tree.root, "ejm-ui")
                    tree.write(path + "/package.json", original)
            standards.licenses(tree.root, "ejm-ui")
        # A package in the public set may also be held back by marking it private.
        edit(tree, "packages/ui", private=True)
        standards.licenses(tree.root, "ejm-ui")

    def test_other_packages_and_the_root_must_stay_private(self) -> None:
        private_only = ("", *("packages/" + name for name in UI_DIRS if "packages/" + name not in standards.UI_PUBLIC))
        self.assertEqual(private_only, ("", "packages/demos", "packages/ink", "packages/shots", "packages/site"))
        tree = self.tree("ejm-ui")
        for path in private_only:
            with self.subTest(package=path):
                edit(tree, path, private=None, publishConfig={"access": "public", "provenance": True})
                with self.assertRaisesRegex(ValueError, "must remain private"):
                    standards.licenses(tree.root, "ejm-ui")
                edit(tree, path, private=True)
                standards.licenses(tree.root, "ejm-ui")

    def test_the_reviewed_manifests_satisfy_the_structural_rules(self) -> None:
        self.assertEqual(sorted(REVIEWED), sorted(standards.UI_PUBLIC))
        self.assertEqual(sorted(standards.UI_PACKING_PREFIXES), sorted(standards.UI_PUBLIC))
        for path, package in REVIEWED.items():
            with self.subTest(package=path):
                self.assertEqual(standards.ui_packing_problems(path, package), [])
        tree = self.tree("ejm-ui")
        for path, package in REVIEWED.items():
            tree.write(path + "/package.json", json.dumps({**package, "version": "0.1.0", "license": "SEE LICENSE IN LICENSE", "publishConfig": {"access": "public", "provenance": True},
                                                           "repository": {"type": "git", "url": "git+https://github.com/ejmlabs/ejm-ui.git", "directory": path}}))
        tree.check()

    def test_every_reviewed_prefix_is_a_reviewed_files_entry_and_nothing_more(self) -> None:
        for path, package in REVIEWED.items():
            entries = {entry for entry in package["files"] if not entry.startswith("!")}
            self.assertEqual(entries, set(standards.UI_PACKING_PREFIXES[path]), path)

    def test_routine_changes_inside_the_reviewed_prefixes_need_no_shared_change(self) -> None:
        tree = self.tree("ejm-ui")
        changes = {
            "packages/tokens": {"files": ["!src/**/*.test.*", "!**/*.map", "src", "src/new/file.ts", "./generated", "generated/**", "rust", "theme.json", "assets/fonts/*.woff2",
                                          "assets/brand/mark.svg", "assets/icons", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"],
                                "exports": {".": "./src/other.ts", "./new": "./generated/new.css", "./art/*": "./assets/logos/*"}, "main": "src/other.ts",
                                "scripts": {"build": "node build.mjs", "test": "node test.mjs", "check": "x"}},
            "packages/ssg": {"files": ["bin", "bin/extra.mjs", "src", "LICENSE", "THIRD_PARTY_NOTICES.md"], "bin": {"ejm-ssg": "bin/ejm-ssg.mjs", "other": "./bin/other.mjs"}},
            "packages/ui": {"files": ["src", "public/theme-boot.js", "THEME.md", "LICENSE", "THIRD_PARTY_NOTICES.md"], "types": "./src/other.d.ts",
                            "browser": {"./src/node.ts": False, "./src/web.ts": "./src/browser.ts"}},
            "packages/core": {"files": ["src", "contract.json", "LICENSE", "THIRD_PARTY_NOTICES.md"], "directories": {"lib": "src"}},
        }
        for path, edits in changes.items():
            with self.subTest(package=path):
                edit(tree, path, **edits)
                tree.check()

    def test_public_packages_must_keep_the_exact_name(self) -> None:
        for path in standards.UI_PUBLIC:
            for name in ("@ejm/other", "ejm-tokens", "@EJM/" + path.split("/")[1], "", None, 3, ["@ejm/" + path.split("/")[1]]):
                with self.subTest(package=path, name=name):
                    tree = self.tree("ejm-ui")
                    edit(tree, path, name=name)
                    self.fails(tree, re.escape(path) + "/package.json: name must be @ejm/" + path.split("/")[1])

    def test_public_packages_cannot_run_lifecycle_scripts_or_bundle(self) -> None:
        for path in standards.UI_PUBLIC:
            tree = self.tree("ejm-ui")
            for hook in standards.UI_LIFECYCLE_SCRIPTS:
                with self.subTest(package=path, hook=hook):
                    edit(tree, path, scripts={"build": "x", hook: "node x.mjs"})
                    self.fails(tree, "lifecycle script " + hook + " could change the packed files")
            for scripts in ("prepack", ["prepack"], 3):
                with self.subTest(package=path, scripts=scripts):
                    edit(tree, path, scripts=scripts)
                    self.fails(tree, "scripts must be an object")
            edit(tree, path, scripts={"build": "x", "prebuild": "y", "postbuild": "z", "test": "w", "pretest": "v"})
            tree.check()
            edit(tree, path, scripts=None)
            for field, value in (("bundleDependencies", True), ("bundleDependencies", []), ("bundledDependencies", ["a"]), ("workspaces", ["assets"]), ("workspaces", [])):
                with self.subTest(package=path, field=field, value=value):
                    edit(tree, path, **{field: value})
                    self.fails(tree, field + " could change the packed files")
                    edit(tree, path, **{field: None})

    def test_private_packages_are_not_subject_to_the_packing_rules(self) -> None:
        tree = self.tree("ejm-ui")
        edit(tree, "packages/demos", scripts={"prepack": "x", "postinstall": "y"}, files=["assets"], workspaces=["x"], name="anything")
        tree.check()

    def test_public_packages_must_list_what_they_pack_inside_the_reviewed_prefixes(self) -> None:
        for path in standards.UI_PUBLIC:
            tree = self.tree("ejm-ui")
            for name, files in {"missing": None, "empty": [], "string": "src", "non-string": ["src", 1], "nested": [["src"]]}.items():
                with self.subTest(package=path, files=name):
                    edit(tree, path, files=files)
                    self.fails(tree, re.escape(path) + "/package.json: files must list exactly what is packed")
            for entry in ("assets", "assets/logos", "assets/artwork/x.svg", "./assets", "assets/*", "!!assets", "../x", "/etc/passwd", "src/../assets/logos", "*", "**/*.svg", "brand",
                          "logos", "Src", "src*", "srcx/y", "src\\..\\assets", "./", ".", "", "./../x", "src//x", "assets/fonts/../logos", "node_modules", "SRC"):
                with self.subTest(package=path, entry=entry):
                    base = list(standards.UI_PACKING_PREFIXES[path])
                    edit(tree, path, files=[*base, entry])
                    self.fails(tree, re.escape(path) + "/package.json: files entry " + re.escape(repr(entry)) + " is outside the reviewed set")

    def test_the_ui_tarball_no_longer_packs_the_static_stylesheet(self) -> None:
        ui = REVIEWED["packages/ui"]
        for entry in ("public/static.css", "./public/static.css", "public", "public/*"):
            with self.subTest(entry=entry):
                problems = standards.ui_packing_problems("packages/ui", {**ui, "files": [*ui["files"], entry]})
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("files entry " + repr(entry) + " is outside the reviewed set", problems[0])

    def test_the_tokens_tarball_cannot_gain_brand_logos_or_artwork(self) -> None:
        tokens = REVIEWED["packages/tokens"]
        for entry in ("assets", "assets/*", "assets/logos", "assets/artwork", "assets/logos/x.svg", "./assets", "assets/brand/../logos", "assets/Brand"):
            with self.subTest(entry=entry):
                problems = standards.ui_packing_problems("packages/tokens", {**tokens, "files": [*tokens["files"], entry]})
                self.assertEqual(len(problems), 1, problems)
        for entry in ("assets/brand", "assets/brand/mark.svg", "assets/icons/x.svg", "assets/fonts/Manrope.woff2", "./assets/fonts"):
            with self.subTest(entry=entry):
                self.assertEqual(standards.ui_packing_problems("packages/tokens", {**tokens, "files": [*tokens["files"], entry]}), [])
        for field, value in (("main", "./assets/logos/x.svg"), ("browser", "assets/logos/x.svg"), ("bin", {"x": "./assets/logos/x.svg"}), ("man", ["assets/logos/x.1"]),
                             ("directories", {"bin": "assets/logos"}), ("main", "ASSETS/LOGOS/X.SVG"), ("bin", "assets/artwork/x.mjs"), ("man", "x.1")):
            with self.subTest(field=field):
                self.assertEqual(len(standards.ui_packing_problems("packages/tokens", {**tokens, field: value})), 1)

    def test_files_that_npm_always_packs_are_held_to_the_same_prefixes(self) -> None:
        for path in standards.UI_PUBLIC:
            tree = self.tree("ejm-ui")
            for field, value in (("main", "assets/logos/x.svg"), ("main", "./Assets/logos/x.svg"), ("main", "./other/index.js"), ("browser", "assets/logos/x.svg"),
                                 ("browser", {"./src/a.ts": "./assets/logos/x.svg"}), ("bin", "assets/logos/x.svg"), ("bin", {"x": "./assets/logos/x.svg"}),
                                 ("bin", {"x": "./src/ok.mjs", "y": "../outside.mjs"}), ("man", "x.1"), ("man", ["./src/x.1", "assets/logos/x.1"]),
                                 ("directories", {"bin": "assets"}), ("directories", {"man": "man"}), ("directories", {"bin": "assets/logos"})):
                with self.subTest(package=path, field=field, value=value):
                    edit(tree, path, **{field: value})
                    self.fails(tree, re.escape(path) + "/package.json: " + field + " .* is outside the reviewed set")
                    edit(tree, path, **{field: None})
            tree.check()

    def test_fields_that_npm_does_not_pack_are_not_restricted(self) -> None:
        tree = self.tree("ejm-ui")
        for path in standards.UI_PUBLIC:
            edit(tree, path, types="./assets/logos/x.d.ts", typings="./x", module="./assets/logos/x.mjs", exports={".": "./assets/logos/x.svg", "./x": {"import": "./y.mjs"}})
        tree.check()

    def test_strings_yields_path_leaves_not_keys(self) -> None:
        self.assertEqual(sorted(standards.strings("a")), ["a"])
        self.assertEqual(sorted(standards.strings(["a", ["b"], {"k": "c", "d": {"e": "f"}}, 1, None, True])), ["a", "b", "c", "f"])
        self.assertEqual(list(standards.strings(None)), [])
        self.assertEqual(sorted(standards.strings({"x": "y", "z": False})), ["y"])

    def test_inside_decides_by_whole_path_segments_and_allows_removals(self) -> None:
        prefixes = ("src", "assets/brand", "LICENSE")
        for entry in ("src", "src/a", "./src/a/b", "assets/brand", "assets/brand/x.svg", "LICENSE", "!anything", "!src/**/*.test.*", "!../x", "src/*.ts", "src/**"):
            with self.subTest(entry=entry):
                self.assertTrue(standards.inside(entry, prefixes))
        for entry in ("srcs", "assets", "assets/brandx", "assets/brand2/x", "LICENSES", "!!src", "..", "../src", "/src", "src/..", "src/./a", "a\\b", "", "./", "src//a"):
            with self.subTest(entry=entry):
                self.assertFalse(standards.inside(entry, prefixes))

    def test_font_licenses_must_be_original_and_match_the_ui_package(self) -> None:
        tree = self.tree("ejm-ui")
        source, copied = standards.UI_FONT_NOTICES[0], standards.UI_FONT_NOTICES[2]
        original = tree.read(source)
        tree.write(source, original + "Changed terms.\n")
        with self.assertRaisesRegex(ValueError, "UI fonts need their original OFL"):
            standards.licenses(tree.root, "ejm-ui")
        tree.write(source, original)
        tree.write(copied, original.replace("\r\n", "\n"))
        standards.licenses(tree.root, "ejm-ui")
        tree.write(copied, original + "Changed terms.\n")
        with self.assertRaisesRegex(ValueError, "UI package font notice differs from the token owner"):
            standards.licenses(tree.root, "ejm-ui")
        tree.write(copied, original)
        for path in standards.UI_FONT_NOTICES:
            with self.subTest(path=path):
                (tree.root / path).unlink()
                with self.assertRaisesRegex(ValueError, "Missing or unsafe file: " + re.escape(path)):
                    standards.licenses(tree.root, "ejm-ui")
                tree.write(path, (FONTS / (re.search(r"(Manrope|IBMPlexMono)", path)[0] + "-OFL.txt")).read_bytes())  # type: ignore[index]

    def test_original_public_font_notices_pass_the_unpatched_hash_allowlist(self) -> None:
        tree = self.tree("ejm-ui")
        for name in ("Manrope", "IBMPlexMono"):
            original = (FONTS / (name + "-OFL.txt")).read_bytes()
            tree.write("packages/tokens/assets/fonts/" + name + "-OFL.txt", original)
            tree.write("packages/ui/src/fonts/" + name + "-OFL.txt", original)
        standards.licenses(tree.root, "ejm-ui")
        self.assertEqual(set(standards.UI_FONT_HASHES), {"Manrope", "IBMPlexMono"})

    def test_the_terminal_crate_keeps_mit_terms_and_stays_unpublished(self) -> None:
        for name, text in {
            "another license": '[package]\nname = "ejm-tui"\nversion = "0.1.0"\nlicense = "GPL-3.0"\npublish = false\n',
            "no license": '[package]\nname = "ejm-tui"\nversion = "0.1.0"\npublish = false\n',
            "published": '[package]\nname = "ejm-tui"\nversion = "0.1.0"\nlicense = "MIT"\n',
            "publish true": '[package]\nname = "ejm-tui"\nversion = "0.1.0"\nlicense = "MIT"\npublish = true\n',
            "publish a registry": '[package]\nname = "ejm-tui"\nversion = "0.1.0"\nlicense = "MIT"\npublish = ["crates"]\n',
        }.items():
            with self.subTest(name):
                tree = self.tree("ejm-ui")
                tree.write("crates/ejm-tui/Cargo.toml", text)
                self.fails(tree, "UI terminal crate must retain MIT terms and remain unpublished")
        tree = self.tree("ejm-ui")
        (tree.root / "crates/ejm-tui/Cargo.toml").unlink()
        self.fails(tree, "Missing or unsafe file: crates/ejm-tui/Cargo.toml")
        tree.write("crates/ejm-tui/Cargo.toml", "[workspace]\n")
        self.fails(tree, "crates/ejm-tui/Cargo.toml: missing key package")

    def test_every_ui_problem_is_reported_together(self) -> None:
        tree = self.tree("ejm-ui")
        edit(tree, "packages/core", scripts={"prepack": "x"}, files=["assets"])
        edit(tree, "packages/demos", version="0.2.0")
        tree.write("crates/ejm-tui/Cargo.toml", '[package]\nname = "ejm-tui"\nversion = "0.1.0"\nlicense = "GPL-3.0"\n')
        problems = self.fails(tree, "lifecycle script prepack")
        joined = "\n".join(problems)
        for expected in ("files entry 'assets' is outside the reviewed set", "packages/demos/package.json: version differs from VERSION", "UI terminal crate must retain MIT terms"):
            self.assertIn(expected, joined)

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
