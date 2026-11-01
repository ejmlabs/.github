import hashlib
import importlib
import io
import random
import re
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import standards
from build_workflows import (
    attach_workflow,
    deploy_workflow,
    governance,
    libraries,
    release_workflow,
    verify_build_workflow,
    yaml,
)
from repo_tree import MIT, REVISION, TreeCase
from standards import (
    MIT_TERMS,
    PR_CALLER,
    PROFILES,
    consumer_workflows,
    lint_workflow,
    native_build,
    read,
    versions,
    workflows,
)
from test_workflows import embedded_source

ROOT = Path(__file__).resolve().parents[1]
NBSP, EN_SPACE, NEL, LINE_SEP, EM_DASH, E_ACUTE = (chr(code) for code in (0xA0, 0x2002, 0x85, 0x2028, 0x2014, 0xE9))
SHA1, SHA2 = "1" * 40, "2" * 40


class StandardTests(TreeCase):
    def test_codeql_caller_exception_is_scoped_to_its_reviewed_content_and_repository(self) -> None:
        tree = self.tree(".github")
        path = ".github/workflows/codeql.yml"
        tree.write(path, standards.CODEQL_CALLER)
        self.assertEqual(standards.workflow_problems(tree.root, ".github"), [])
        for changed in (standards.CODEQL_CALLER.replace('"security-events": "write"', '"contents": "write"'),
                        standards.CODEQL_CALLER.replace('"./.github/workflows/codeql-analysis.yml"', '"./.github/workflows/other.yml"'),
                        standards.CODEQL_CALLER + '    "secrets": "inherit"\n'):
            with self.subTest(changed=changed):
                tree.write(path, changed)
                self.assertTrue(standards.workflow_problems(tree.root, ".github"))
        consumer = self.tree("ejm-cli")
        consumer.write(path, standards.CODEQL_CALLER)
        self.assertTrue(standards.workflow_problems(consumer.root, "ejm-cli"))

    def test_the_profile_table_drives_the_repository_lists(self) -> None:
        self.assertEqual(standards.NATIVE_RELEASE, ("ejm-cli", "ejm-harness"))
        self.assertEqual(standards.WARM_CACHE, ("ejm-cli", "ejm-harness", "ejm-ide", "ejm-ui"))
        self.assertEqual(sorted(standards.SITE_DEPLOY), ["ejm-calm", "ejm-cli", "ejm-harness", "ejm-ide", "ejm-ui", "ejmlabs"])
        self.assertEqual(sorted(PROFILES), [".github", "ejm-calm", "ejm-chess", "ejm-cli", "ejm-harness", "ejm-ide", "ejm-rightkit-fs", "ejm-ui", "ejmlabs"])
        self.assertEqual({name: profile.harness_pin for name, profile in PROFILES.items()}["ejm-cli"], True)
        self.assertEqual([name for name, profile in PROFILES.items() if profile.harness_pin], ["ejm-cli", "ejm-ide"])
        self.assertEqual([name for name, profile in PROFILES.items() if profile.publish], ["ejm-ui"])

    def test_chess_profile_checks_application_versions_and_code_scan(self) -> None:
        tree = self.tree("ejm-chess")
        self.assertEqual(tree.check(), "0.1.0")
        self.assertEqual(PROFILES["ejm-chess"].guide, "README.md#local-setup")
        caller = consumer_workflows(REVISION, codeql_languages=PROFILES["ejm-chess"].codeql_languages)["code-scan.yml"]
        tree.write(".github/workflows/code-scan.yml", caller)
        self.assertEqual(standards.workflow_problems(tree.root, "ejm-chess"), [])
        tree.change_json("package-lock.json", lambda data: data["packages"][""].update(version="0.2.0"))
        self.fails(tree, "version differs from VERSION")

    def test_rightkit_profile_checks_the_single_crate_and_dual_license(self) -> None:
        tree = self.tree("ejm-rightkit-fs")
        self.assertEqual(tree.check(), "0.1.0")
        tree.replace("Cargo.toml", "MIT OR Apache-2.0", "MIT")
        self.fails(tree, "fork license must remain MIT OR Apache-2.0")
        tree.replace("Cargo.toml", "MIT", "MIT OR Apache-2.0")
        tree.replace("Cargo.lock", "0.1.0", "0.2.0")
        self.fails(tree, "owned Cargo lock package versions differ")

    def test_mismatched_version_and_missing_notes_block_release(self) -> None:
        tree = self.tree("ejmlabs")
        tree.write("site/package.json", '{"version":"0.2.0","license":"SEE LICENSE IN ../LICENSE"}')
        with self.assertRaisesRegex(ValueError, "site/package.json: version differs from VERSION"):
            versions(tree.root, "ejmlabs")
        tree.write("site/package.json", '{"version":"0.1.0","license":"SEE LICENSE IN ../LICENSE"}')
        self.assertEqual(versions(tree.root, "ejmlabs"), "0.1.0")
        tree.write("CHANGELOG.md", "## Unreleased\n")
        with self.assertRaisesRegex(ValueError, "CHANGELOG.md needs a dated entry"):
            versions(tree.root, "ejmlabs")

    def test_unknown_profile_is_rejected_everywhere(self) -> None:
        tree = self.tree(".github")
        for call in (standards.standards, standards.versions, standards.licenses, standards.workflows, standards.standards_problems):
            with self.subTest(call=call.__name__), self.assertRaisesRegex(ValueError, "Unknown repository profile"):
                call(tree.root, "unknown")

    def test_license_cannot_be_truncated_or_changed_in_manifest(self) -> None:
        tree = self.tree("ejm-cli")
        standards.licenses(tree.root, "ejm-cli")
        tree.replace("Cargo.toml", '[workspace.package]\nversion = "0.1.0"\nlicense = "MIT"', '[workspace.package]\nversion = "0.1.0"\nlicense = "Apache-2.0"')
        with self.assertRaisesRegex(ValueError, "workspace license must remain MIT"):
            standards.licenses(tree.root, "ejm-cli")
        tree = self.tree("ejm-cli")
        tree.write("LICENSE", "MIT License\nCopyright (c) 2026 Example\nOnly a fragment.")
        with self.assertRaisesRegex(ValueError, "complete MIT license terms"):
            standards.licenses(tree.root, "ejm-cli")

    def test_the_mit_license_needs_its_heading_copyright_and_full_terms(self) -> None:
        for name, text in {
            "no heading": MIT.replace("MIT License", "The MIT License", 1),
            "no copyright": "MIT License\n" + MIT_TERMS,
            "no year": MIT.replace("2026", "year"),
            "missing terms": MIT.replace("furnished to do so", "furnished"),
            "empty": "",
        }.items():
            with self.subTest(name):
                tree = self.tree("ejm-cli")
                tree.write("LICENSE", text)
                self.fails(tree, "LICENSE")

    def test_studio_keeps_its_specific_rights_notice(self) -> None:
        tree = self.tree("ejmlabs")
        tree.change_json("site/package.json", lambda data: data.update(license="MIT"))
        self.fails(tree, "Studio metadata must preserve its specific rights notice")
        tree.change_json("site/package.json", lambda data: data.pop("license"))
        self.fails(tree, "Studio metadata must preserve")

    def test_owned_manifest_licenses_must_stay_mit(self) -> None:
        for profile, path, key in (("ejm-harness", "sdk/typescript/package.json", "license"), ("ejm-ide", "package.json", "license")):
            with self.subTest(path=path):
                tree = self.tree(profile)
                tree.change_json(path, lambda data: data.update({key: "GPL-3.0"}))  # noqa: B023 - run before the next iteration
                self.fails(tree, "Owned manifest license differs from MIT: " + path)
        for profile, path in (("ejm-harness", "sdk/python/pyproject.toml"), ("ejm-harness", "registry/Cargo.toml"), ("ejm-ide", "src-tauri/Cargo.toml")):
            with self.subTest(path=path):
                tree = self.tree(profile)
                tree.replace(path, 'license = "MIT"', 'license = "GPL-3.0"')
                self.fails(tree, "Owned manifest license differs from MIT: " + path)

    def test_every_workspace_crate_must_be_mit_or_inherit_it(self) -> None:
        tree = self.tree("ejm-cli")
        tree.replace("crates/core/Cargo.toml", 'license = "MIT"', 'license = "Apache-2.0"')
        self.fails(tree, "Owned crate license differs from MIT: crates/core")
        tree = self.tree("ejm-cli")
        tree.write("crates/cli/Cargo.toml", '[package]\nname = "cli"\n')
        self.fails(tree, "Owned crate license differs from MIT: crates/cli")
        tree = self.tree("ejm-cli")
        tree.write("crates/cli/Cargo.toml", '[package]\nname = "cli"\nlicense.workspace = false\n')
        self.fails(tree, "Owned crate license differs from MIT: crates/cli")

    def test_workspace_members_are_capped_and_globs_expand_inside_the_root(self) -> None:
        tree = self.tree("ejm-harness")
        self.assertEqual(standards.workspace_members(tree.root, tomllib.loads(tree.read("Cargo.toml"))), ["crates/a", "crates/b"])
        # A directory without Cargo.toml and a symlinked directory are not members of a glob.
        (tree.root / "crates/empty").mkdir()
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "Cargo.toml").write_text(CRATE_NAMED)
        (tree.root / "crates/linked").symlink_to(outside.name, target_is_directory=True)
        self.assertEqual(standards.workspace_members(tree.root, {"workspace": {"members": ["crates/*"]}}), ["crates/a", "crates/b"])
        self.assertEqual(standards.workspace_members(tree.root, {"workspace": {"members": ["crates/*", "crates/a"], "exclude": ["crates/b"]}}), ["crates/a"])
        self.assertEqual(standards.workspace_members(tree.root, {"workspace": {"members": ["crates/[ab]", "crates/?"]}}), ["crates/a", "crates/b"])
        tree.check()
        too_many = [f"crates/m{index}" for index in range(51)]
        for name in too_many:
            tree.write(name + "/Cargo.toml", CRATE_NAMED)
        for members in (too_many, ["crates/m*"]):
            with self.subTest(members=members[0]):
                tree.set_members(members)
                self.fails(tree, "Too many owned manifests")
        tree.set_members(too_many[:50])
        tree.check()

    def test_workspace_member_paths_cannot_escape_or_use_recursive_globs(self) -> None:
        tree = self.tree("ejm-harness")
        for member in ("../outside", "/etc", "crates/**", "", "a/../.."):
            with self.subTest(member=member), self.assertRaisesRegex(ValueError, "unsupported workspace member"):
                standards.workspace_members(tree.root, {"workspace": {"members": [member]}})
        for members in ("crates/a", [1], None):
            with self.subTest(members=members), self.assertRaisesRegex(ValueError, "must be a list of paths"):
                standards.workspace_members(tree.root, {"workspace": {"members": members}})

    def test_a_symlinked_member_directory_is_not_followed(self) -> None:
        tree = self.tree("ejm-cli")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "Cargo.toml").write_text(CRATE_NAMED)
        (tree.root / "crates/linked").symlink_to(outside.name, target_is_directory=True)
        tree.replace("Cargo.toml", '["crates/core", "crates/cli"]', '["crates/core", "crates/linked"]')
        self.fails(tree, "Missing or unsafe file: crates/linked/Cargo.toml .symlink at crates/linked")

    def test_sdk_license_text_and_locks_must_match(self) -> None:
        tree = self.tree("ejm-harness")
        tree.write("sdk/python/LICENSE", MIT + "extra\n")
        self.fails(tree, "SDK license text differs from root: sdk/python/LICENSE")
        tree = self.tree("ejm-harness")
        tree.write("sdk/typescript/LICENSE", "other")
        self.fails(tree, "SDK license text differs from root: sdk/typescript/LICENSE")
        tree = self.tree("ejm-harness")
        tree.write("sdk/python/uv.lock", '[[package]]\nname = "ejm-harness"\nversion = "0.2.0"\n')
        self.fails(tree, "SDK Python lock version differs from VERSION")
        tree.write("sdk/python/uv.lock", '[[package]]\nname = "other"\nversion = "0.1.0"\n')
        self.fails(tree, "SDK Python lock version differs from VERSION")

    def test_every_versioned_file_must_equal_version(self) -> None:
        for profile, settings in PROFILES.items():
            for path, _key in settings.versions:
                with self.subTest(profile=profile, path=path):
                    tree = self.tree(profile)
                    tree.write(path, tree.read(path).replace("0.1.0", "9.9.9"))
                    self.fails(tree, re.escape(path) + ": .*differs from VERSION")

    def test_locks_that_carry_the_version_must_equal_it(self) -> None:
        for profile, settings in PROFILES.items():
            for path, keys in settings.locks:
                with self.subTest(profile=profile, path=path):
                    tree = self.tree(profile)

                    def change(data: dict[str, Any], keys: tuple[str, ...] = keys) -> None:
                        for key in keys[:-1]:
                            data = data[key]
                        data[keys[-1]] = "9.9.9"

                    tree.change_json(path, change)
                    self.fails(tree, re.escape(path) + ": .*differs from VERSION")

    def test_owned_cargo_lock_packages_must_equal_version(self) -> None:
        for profile, lock, name in (("ejm-cli", "Cargo.lock", "ejm-cli"), ("ejm-harness", "Cargo.lock", "ejm-harness"),
                                    ("ejm-harness", "Cargo.lock", "ejm-harness-core"), ("ejm-ide", "src-tauri/Cargo.lock", "ejm-ide")):
            with self.subTest(profile=profile, name=name):
                tree = self.tree(profile)
                tree.replace(lock, f'name = "{name}"\nversion = "0.1.0"', f'name = "{name}"\nversion = "0.2.0"')
                self.fails(tree, re.escape(lock) + ": owned Cargo lock package versions differ from VERSION")
        for profile, lock in (("ejm-cli", "Cargo.lock"), ("ejm-ide", "src-tauri/Cargo.lock")):
            with self.subTest(profile=profile, case="no owned package"):
                tree = self.tree(profile)
                tree.write(lock, '[[package]]\nname = "serde"\nversion = "1.0.0"\n')
                self.fails(tree, "owned Cargo lock package versions differ")

    def test_a_foreign_cargo_lock_package_may_have_any_version(self) -> None:
        self.assertEqual(self.tree("ejm-cli").check(), "0.1.0")

    def test_invalid_version_file_stops_dependent_checks_but_not_the_rest(self) -> None:
        tree = self.tree("ejm-cli")
        tree.write("VERSION", "v1.0.0\n")
        tree.write("README.md", "")
        problems = self.fails(tree, "VERSION must be valid SemVer without a v prefix")
        self.assertTrue(any("README.md: document is empty" in problem for problem in problems))
        self.assertFalse(any("differs from VERSION" in problem for problem in problems))

    def test_every_problem_is_reported_not_only_the_first(self) -> None:
        tree = self.tree("ejm-ide")
        tree.write("package.json", '{"version": "0.2.0", "license": "GPL-3.0"}')
        tree.write("SECURITY.md", "")
        tree.write("README.md", "# x\n" + EM_DASH + "\n[a](missing.md)\n")
        tree.write(".github/harness-revision", "main")
        (tree.root / ".github/CODEOWNERS").unlink()
        tree.write(".github/workflows/extra.yml", "on: [push]\n")
        problems = self.fails(tree, "package.json")
        joined = "\n".join(problems)
        for expected in ("package.json: version differs from VERSION", "Owned manifest license differs from MIT: package.json", "SECURITY.md: document is empty",
                         "README.md:2: em dash", "README.md:3: link target is missing: missing.md", "harness revision must be a full immutable commit",
                         "Missing or unsafe file: .github/CODEOWNERS", "extra.yml"):
            self.assertIn(expected, joined)

    def test_malformed_manifests_name_the_file_and_key(self) -> None:
        cases = (
            ("ejm-cli", "Cargo.toml", "[package]\nname = 'x'\n", "Cargo.toml: missing key workspace.package"),
            ("ejm-cli", "Cargo.toml", "[workspace]\n[workspace.package]\nversion = '0.1.0'\nlicense = 'MIT'\n", "Cargo.toml: missing key workspace.members"),
            ("ejm-cli", "Cargo.toml", "[workspace\n", "Cargo.toml: invalid TOML"),
            ("ejm-ide", "package.json", "{", "package.json: invalid JSON"),
            ("ejm-ide", "package.json", "[]", "package.json: expected an object or table"),
            ("ejm-ide", "package.json", '{"version": "0.1.0"}', "package.json: missing key license"),
            ("ejm-ide", "package-lock.json", '{"version": "0.1.0", "packages": {}}', r"package-lock.json: missing key packages\.<root>\.version"),
            ("ejm-cli", "Cargo.lock", "[[package]]\nversion = '0.1.0'\n", r"Cargo.lock: unexpected KeyError: 'name'"),
            ("ejm-cli", "Cargo.lock", "x = 1\n", "Cargo.lock: missing key package"),
            ("ejm-cli", "crates/core/Cargo.toml", "package = 3\n", "crates/core/Cargo.toml: package must be a table"),
            ("ejm-harness", "sdk/python/uv.lock", "x = 1\n", "sdk/python/uv.lock: missing key package"),
            ("ejm-ide", "package.json", "[" * 200_000 + "]" * 200_000, "package.json: invalid JSON: maximum recursion"),
            ("ejm-cli", "Cargo.lock", "a = " + "[" * 5_000 + "]" * 5_000 + "\n", "Cargo.lock: invalid TOML"),
            ("ejm-cli", "Cargo.lock", "[[package]\n", "Cargo.lock: invalid TOML"),
        )
        for profile, path, text, pattern in cases:
            with self.subTest(path=path, text=text[:20]):
                tree = self.tree(profile)
                tree.write(path, text)
                self.fails(tree, pattern)

    def test_required_files_must_exist(self) -> None:
        for path in (*standards.DOCS, *standards.GITHUB_FILES):
            with self.subTest(path=path):
                tree = self.tree(".github")
                (tree.root / path).unlink()
                self.fails(tree, "Missing or unsafe file: " + re.escape(path))

    def test_documents_must_not_be_empty_or_contain_an_em_dash(self) -> None:
        for path in standards.DOCS:
            with self.subTest(path=path, case="empty"):
                tree = self.tree(".github")
                tree.write(path, " \n\n")
                self.fails(tree, re.escape(path) + ": document is empty")
            with self.subTest(path=path, case="em dash"):
                tree = self.tree(".github")
                tree.write(path, "# Title\n\nA sentence " + EM_DASH + " with a pause.\n")
                self.fails(tree, re.escape(path) + ":3: em dash")

    def test_harness_revision_is_required_only_where_a_harness_is_pinned(self) -> None:
        for profile in ("ejm-cli", "ejm-ide"):
            for case, text in (("short", "a" * 39 + "\n"), ("upper", "A" * 40 + "\n"), ("branch", "main\n"), ("two lines", "a" * 40 + "\n\n"), ("empty", "")):
                with self.subTest(profile=profile, case=case):
                    tree = self.tree(profile)
                    tree.write(".github/harness-revision", text)
                    self.fails(tree, r"\.github/harness-revision: harness revision must be a full immutable commit")
            tree = self.tree(profile)
            tree.write(".github/harness-revision", "c" * 40)
            tree.check()
            (tree.root / ".github/harness-revision").unlink()
            self.fails(tree, r"Missing or unsafe file: \.github/harness-revision")
        for profile in ("ejm-harness", "ejmlabs", ".github", "ejm-ui"):
            self.assertEqual(self.tree(profile).check(), "0.1.0")

    def test_every_profile_passes_on_a_clean_tree_and_with_each_optional_caller(self) -> None:
        for profile, settings in PROFILES.items():
            with self.subTest(profile=profile):
                self.assertEqual(self.tree(profile).check(), "0.1.0")
                if settings.cache or settings.deploy:
                    tree = self.tree(profile, cache=settings.cache, deploy=settings.deploy)
                    self.assertEqual(tree.check(), "0.1.0")

    def test_the_embedded_entry_point_prints_every_problem_without_a_traceback(self) -> None:
        tree = self.tree("ejm-cli")
        tree.write("SECURITY.md", "")
        tree.write("SUPPORT.md", "")
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = standards.standards_main([str(tree.root), "ejm-cli"])
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("SECURITY.md: document is empty", errors.getvalue())
        self.assertIn("SUPPORT.md: document is empty", errors.getvalue())
        self.assertIn("2 problem(s)", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        tree.write("SECURITY.md", "Text.\n")
        tree.write("SUPPORT.md", "Text.\n")
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(standards.standards_main([str(tree.root), "ejm-cli"]), 0)
        self.assertIn("Repository standards and version 0.1.0 passed for ejm-cli", output.getvalue())
        with redirect_stderr(errors):
            self.assertEqual(standards.standards_main([str(tree.root)]), 2)
            self.assertEqual(standards.standards_main([str(tree.root), "unknown"]), 1)
        self.assertIn("Unknown repository profile", errors.getvalue())

    def test_the_problem_report_is_bounded(self) -> None:
        tree = self.tree(".github")
        for index in range(70):
            tree.write(f".github/workflows/extra{index}.yml", "on: [push]\n")
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(standards.standards_main([str(tree.root), ".github"]), 1)
        self.assertIn("more problems", errors.getvalue())
        self.assertLess(len(errors.getvalue().splitlines()), 200)

    def test_the_embedded_workflow_script_is_this_library_with_a_quiet_entry_point(self) -> None:
        steps = governance()["jobs"]["standards"]["steps"]
        step = next(step for step in steps if step.get("name") == "Validate shared public standards and version metadata")
        embedded = embedded_source(step["run"], step.get("env"))
        assert embedded is not None
        # SemVer comes from versioning.py, embedded first because a workflow has no module to import it from.
        self.assertEqual(embedded, libraries("versioning.py", "standards.py") + "\nsys.exit(standards_main(sys.argv[1:]))\n")
        self.assertNotIn("templates", embedded.rsplit("\n", 3)[-2])
        tree = self.tree("ejm-cli")
        tree.write("SECURITY.md", "")
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        script = Path(scratch.name, "embedded.py")
        script.write_text(embedded)
        failed = subprocess.run([sys.executable, "-I", str(script), str(tree.root), "ejm-cli"], capture_output=True, text=True, check=False)
        self.assertEqual(failed.returncode, 1)
        self.assertIn("SECURITY.md: document is empty", failed.stderr)
        self.assertNotIn("Traceback", failed.stderr)
        tree.write("SECURITY.md", "Text.\n")
        passed = subprocess.run([sys.executable, "-I", str(script), str(tree.root), "ejm-cli"], capture_output=True, text=True, check=False)
        self.assertEqual((passed.returncode, passed.stderr), (0, ""))
        self.assertIn("passed for ejm-cli", passed.stdout)

    def test_this_repository_passes_its_own_standards(self) -> None:
        self.assertRegex(standards.standards(ROOT, ".github"), r"^\d+\.\d+\.\d+")

    def test_the_script_runs_isolated_beside_versioning_without_the_script_directory_on_the_path(self) -> None:
        # python -I leaves the script's own directory off sys.path, and the library still finds its sibling.
        result = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/standards.py"), str(ROOT), ".github"], capture_output=True, text=True, check=False, cwd=tempfile.gettempdir())
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIn("passed for .github", result.stdout)


CRATE_NAMED = '[package]\nname = "x"\nversion = "0.1.0"\nlicense = "MIT"\n'


class ReadTests(TreeCase):
    def test_symlinked_policy_cannot_read_outside_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(ValueError, "symlink at README.md"):
                read(root, "README.md")

    def test_a_symlinked_directory_in_the_path_is_rejected_even_when_it_stays_inside(self) -> None:
        tree = self.tree(".github")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "README.md").write_text("# outside\n")
        (tree.root / "docs").rename(tree.root / "real-docs")
        (tree.root / "docs").symlink_to(outside.name, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink at docs"):
            read(tree.root, "docs/README.md")
        (tree.root / "docs").unlink()
        (tree.root / "docs").symlink_to(tree.root / "real-docs", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink at docs"):
            read(tree.root, "docs/guide.md")

    def test_a_symlinked_github_directory_is_rejected(self) -> None:
        tree = self.tree("ejm-cli")
        (tree.root / ".github").rename(tree.root / "moved-github")
        (tree.root / ".github").symlink_to(tree.root / "moved-github", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "neither .github nor workflows may be a symlink"):
            workflows(tree.root, "ejm-cli")
        self.fails(tree, "neither .github nor workflows may be a symlink")

    def test_a_symlinked_workflows_directory_is_rejected(self) -> None:
        tree = self.tree("ejm-cli")
        (tree.root / ".github/workflows").rename(tree.root / "flows")
        (tree.root / ".github/workflows").symlink_to(tree.root / "flows", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "neither .github nor workflows may be a symlink"):
            workflows(tree.root, "ejm-cli")

    def test_missing_workflows_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "Missing or unsafe .github/workflows directory"):
            workflows(Path(directory), "ejm-cli")

    def test_paths_that_leave_the_root_are_rejected(self) -> None:
        tree = self.tree(".github")
        for path in ("../README.md", "docs/../../x", "/etc/passwd", "", "."):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Missing or unsafe file"):
                read(tree.root, path)

    def test_a_dot_dot_or_absolute_path_cannot_reach_a_real_file_outside_the_root(self) -> None:
        outer = tempfile.TemporaryDirectory()
        self.addCleanup(outer.cleanup)
        (Path(outer.name) / "outside.txt").write_text("outside\n")
        root = Path(outer.name) / "repo"
        (root / "docs").mkdir(parents=True)
        (root / "inside.txt").write_text("inside\n")
        for path in ("../outside.txt", "docs/../../outside.txt", str(Path(outer.name) / "outside.txt")):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Missing or unsafe file"):
                read(root, path)
        with self.assertRaisesRegex(ValueError, "Missing or unsafe file"):
            read(root, "docs/../inside.txt")
        self.assertEqual(read(root, "inside.txt"), "inside\n")

    def test_directories_and_missing_files_are_not_files(self) -> None:
        tree = self.tree(".github")
        for path in ("docs", "nothing.md"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Missing or unsafe file"):
                read(tree.root, path)

    def test_every_read_is_capped(self) -> None:
        tree = self.tree(".github")
        tree.write("exact.txt", b"x" * 10)
        tree.write("over.txt", b"x" * 11)
        self.assertEqual(read(tree.root, "exact.txt", limit=10), "x" * 10)
        with self.assertRaisesRegex(ValueError, "exceeds validation limit of 10 bytes: over.txt"):
            read(tree.root, "over.txt", limit=10)
        with self.assertRaisesRegex(ValueError, "exceeds validation limit"):
            standards.read_bytes(tree.root, "over.txt", limit=10)
        self.assertEqual(standards.MAX_READ_BYTES, 8_000_000)
        tree.write("big.txt", b"x" * (standards.MAX_READ_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "exceeds validation limit of 8000000 bytes: big.txt"):
            read(tree.root, "big.txt")
        tree.write("README.md", b"x" * (standards.MAX_READ_BYTES + 1))
        self.fails(tree, "exceeds validation limit")

    def test_workflows_are_read_with_a_smaller_cap(self) -> None:
        tree = self.tree(".github")
        tree.write(".github/workflows/big.yml", b"#" * (standards.MAX_WORKFLOW_BYTES + 1))
        self.fails(tree, "exceeds validation limit of 1000000 bytes: .github/workflows/big.yml")

    def test_undecodable_files_name_the_file(self) -> None:
        tree = self.tree(".github")
        tree.write("CHANGELOG.md", b"\xff\xfe")
        with self.assertRaisesRegex(ValueError, "File is not valid UTF-8: CHANGELOG.md"):
            read(tree.root, "CHANGELOG.md")

    def test_newlines_are_normalized_unless_preserved(self) -> None:
        tree = self.tree(".github")
        tree.write("a.txt", b"one\r\ntwo\rthree\n")
        self.assertEqual(read(tree.root, "a.txt"), "one\ntwo\nthree\n")
        self.assertEqual(read(tree.root, "a.txt", preserve_newlines=True), "one\r\ntwo\rthree\n")


class LinkTests(TreeCase):
    def test_broken_and_outside_links_are_reported_with_their_line(self) -> None:
        tree = self.tree(".github")
        tree.write("README.md", "# x\n\n[ok](docs/guide.md) [no](docs/none.md)\n[out](../outside.md)\n![img](missing.png)\n")
        problems = self.fails(tree, "README.md:3: link target is missing: docs/none.md")
        joined = "\n".join(problems)
        self.assertIn("README.md:4: link target is outside the repository: ../outside.md", joined)
        self.assertIn("README.md:5: link target is missing: missing.png", joined)
        self.assertNotIn("docs/guide.md", joined)

    def test_every_markdown_document_is_checked_but_not_license(self) -> None:
        for path in ("CONTRIBUTING.md", "SECURITY.md", "SUPPORT.md", "CODE_OF_CONDUCT.md", "RELEASING.md", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"):
            with self.subTest(path=path):
                tree = self.tree(".github")
                tree.write(path, tree.read(path) + "\n[broken](nowhere.md)\n")
                self.fails(tree, re.escape(path) + ":.*nowhere.md")
        tree = self.tree(".github")
        tree.write("LICENSE", MIT + "\n[broken](nowhere.md)\n")
        tree.check()

    def test_fenced_code_and_inline_code_are_not_links(self) -> None:
        lines = [
            "[ok](docs/guide.md)",
            "```sh", "[a](missing-fenced.md)", "```",
            "~~~", "[b](missing-tilde.md)", "~~~",
            "````", "```", "[c](missing-long-fence.md)", "```", "````",
            "  ```text", "[d](missing-indented.md)", "  ```",
            "Inline `[e](missing-inline.md)` and ``[f](missing-double.md)`` and ```[g](missing-triple.md)```.",
            "[h](docs/guide.md) with `code` after",
            "",
        ]
        text = "\n".join(lines)
        self.assertEqual(list(standards.markdown_links(text)), [(1, "docs/guide.md"), (17, "docs/guide.md")])
        tree = self.tree(".github")
        tree.write("README.md", text)
        tree.check()

    def test_an_unclosed_fence_hides_the_rest_and_a_one_line_triple_backtick_is_not_a_fence(self) -> None:
        self.assertEqual(list(standards.markdown_links("```\n[a](x.md)\n")), [])
        self.assertEqual(list(standards.markdown_links("```code``` [a](x.md)\n[b](y.md)")), [(1, "x.md"), (2, "y.md")])
        self.assertEqual(list(standards.markdown_links("```\n~~~\n[a](x.md)\n```\n[b](y.md)")), [(5, "y.md")])

    def test_unpaired_backticks_do_not_hide_links(self) -> None:
        self.assertEqual(list(standards.markdown_links("a ` [b](x.md) ``c`` ")), [(1, "x.md")])
        self.assertEqual(list(standards.markdown_links("`` ` `` [b](x.md)")), [(1, "x.md")])
        self.assertEqual(list(standards.markdown_links("[`code`](x.md)")), [(1, "x.md")])

    def test_an_optional_title_is_accepted(self) -> None:
        for text in ('[t](docs/guide.md "Title")', "[t](docs/guide.md 'Title')", "[t](docs/guide.md (Title))", '[t](docs/guide.md   "Title with (parens)"  )',
                     '[t](<docs/guide.md> "Title")'):
            with self.subTest(text=text):
                self.assertEqual([target for _, target in standards.markdown_links(text)], ["docs/guide.md"])

    def test_parentheses_in_a_destination_are_balanced(self) -> None:
        tree = self.tree(".github")
        tree.write("docs/a_(b).md", "# x\n")
        tree.write("docs/c (d).md", "# x\n")
        tree.write("README.md", "[x](docs/a_(b).md) and ([y](docs/guide.md)) and [z](<docs/c (d).md>)\n")
        self.assertEqual([target for _, target in standards.markdown_links(tree.read("README.md"))], ["docs/a_(b).md", "docs/guide.md", "docs/c (d).md"])
        tree.check()
        tree.write("README.md", "[x](docs/a_(missing).md)\n")
        self.fails(tree, r"README.md:1: link target is missing: docs/a_\(missing\).md")

    def test_text_that_is_not_a_link_is_ignored(self) -> None:
        for text in ("[a](b c)", "[a](", "[a](<b", "[a](b", "[a](b))x\n[a](b c)"):
            with self.subTest(text=text):
                self.assertEqual([target for _, target in standards.markdown_links(text)], ["b"] if text.startswith("[a](b))") else [])
        self.assertEqual([target for _, target in standards.markdown_links("a ](b) c")], ["b"])
        # An empty destination is yielded and never flagged.
        self.assertEqual([target for _, target in standards.markdown_links("[a]( )")], [""])
        self.assertIsNone(standards.link_problem(self.tree(".github").root, "", ""))

    def test_links_resolve_against_the_document_directory_and_slash_means_the_root(self) -> None:
        tree = self.tree(".github")
        root = tree.root
        self.assertIsNone(standards.link_problem(root, "docs", "guide.md"))
        self.assertEqual(standards.link_problem(root, "", "guide.md"), "missing")
        self.assertIsNone(standards.link_problem(root, "docs", "/docs/guide.md"))
        self.assertIsNone(standards.link_problem(root, "docs", "../README.md"))
        self.assertIsNone(standards.link_problem(root, "", "docs/"))
        self.assertIsNone(standards.link_problem(root, "", "./docs/../docs/guide.md"))
        self.assertIsNone(standards.link_problem(root, "docs", "/"))
        self.assertEqual(standards.link_problem(root, "docs", "/guide.md"), "missing")
        self.assertEqual(standards.link_problem(root, "docs", "../../README.md"), "outside the repository")
        self.assertEqual(standards.link_problem(root, "", ".."), "outside the repository")
        self.assertEqual(standards.link_problem(root, "", "docs/../../x"), "outside the repository")

    def test_fragments_queries_encoding_and_external_targets(self) -> None:
        tree = self.tree(".github")
        tree.write("docs/with space.md", "# x\n")
        root = tree.root
        for target in ("docs/guide.md#top", "docs/guide.md?plain=1", "docs/guide.md?x=1#top", "docs/with%20space.md", "#anchor", "", "?query",
                       "https://example.com/x", "mailto:a@example.com", "http://example.com", "//example.com/x", "tel:123", "C:\\x"):
            with self.subTest(target=target):
                self.assertIsNone(standards.link_problem(root, "", target))
        self.assertEqual(standards.link_problem(root, "", "docs/nothing.md#top"), "missing")
        self.assertEqual(standards.link_problem(root, "", "docs/with%2Fspace.md"), "missing")

    def test_a_nul_byte_in_a_target_is_a_broken_link(self) -> None:
        self.assertEqual(standards.link_problem(self.tree(".github").root, "", "a%00b"), "missing")

    def test_a_symlink_that_leaves_the_repository_is_a_link_that_exists(self) -> None:
        tree = self.tree(".github")
        (tree.root / "docs/out").symlink_to("/etc", target_is_directory=True)
        self.assertIsNone(standards.link_problem(tree.root, "", "docs/out"))
        (tree.root / "docs/loop").symlink_to("loop")
        self.assertEqual(standards.link_problem(tree.root, "", "docs/loop"), "missing")

    def test_broken_links_per_document_are_capped(self) -> None:
        tree = self.tree(".github")
        tree.write("README.md", "".join(f"[x](missing{index}.md)\n" for index in range(25)))
        problems = self.fails(tree, "README.md:20: link target is missing: missing19.md")
        self.assertEqual(len([problem for problem in problems if "link target" in problem]), 20)
        self.assertIn("README.md: and 5 more broken links", problems)

    def test_hostile_markdown_is_bounded(self) -> None:
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, "more than 10000 links"):
            list(standards.markdown_links("](" * 200_000))
        for hostile in ("[a](" + "(" * 300_000, "`" * 300_000, "`a" * 150_000, "[" * 300_000 + "](", "\n".join("[a](" + "b" * 50 for _ in range(5_000)),
                        "`" + "``a" * 100_000, "](<" * 9_000):
            list(standards.markdown_links(hostile))
        self.assertLess(time.monotonic() - started, 10)
        tree = self.tree(".github")
        tree.write("README.md", "](" * 200_000)
        self.fails(tree, "README.md: more than 10000 links; not all were checked")

    def test_the_readme_needs_no_particular_headings(self) -> None:
        tree = self.tree(".github")
        tree.write("README.md", "Just text with no headings at all.\n")
        tree.check()


class WorkflowTests(unittest.TestCase):
    revision = REVISION
    other_revision = "a" * 40
    old_model_key = "OPENAI" + "_API_KEY"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.directory = self.root / ".github/workflows"
        self.directory.mkdir(parents=True)
        self.reset_callers()

    def reset_callers(self, revision: str | None = None) -> None:
        for name, text in consumer_workflows(revision or self.revision).items():
            (self.directory / name).write_text(text)

    def add_reusable(self, name: str, data: dict[str, Any]) -> str:
        text = "# Generated by scripts/build_workflows.py. Edit scripts and regenerate.\n" + yaml(data) + "\n"
        (self.directory / name).write_text(text)
        return text

    def reusable(self) -> str:
        data = governance()
        data["jobs"] = {"quality": {"runs-on": "ubuntu-24.04", "steps": [{"uses": "actions/checkout@" + self.revision}]}}
        return self.add_reusable("governance.yml", data)

    def test_exact_callers_accept_one_immutable_revision(self) -> None:
        workflows(self.root, "ejm-cli")
        self.reset_callers("1" * 40)
        workflows(self.root, "ejm-ide")
        self.assertIn('      standards-ref: "' + "1" * 40 + '"\n', (self.directory / "release.yml").read_text())

    def publish(self, text: str | None = None, repository: str = "ejm-ui") -> None:
        reviewed = "name: Publish\n"
        with patch.object(standards, "UI_PUBLISH_SHA256", hashlib.sha256(reviewed.encode()).hexdigest()):
            (self.directory / "publish.yml").write_text(reviewed if text is None else text)
            workflows(self.root, repository)

    def test_ui_publish_workflow_is_allowed_only_at_the_reviewed_hash_in_the_ui_repository(self) -> None:
        self.publish()
        for changed in ("name: Publish\n# changed\n", "", "name: Publish\r\n"):
            with self.subTest(content=changed), self.assertRaisesRegex(ValueError, "publish.yml differs from the reviewed"):
                self.publish(changed)
        # Anywhere else it is an ordinary product workflow and must pass the credential-free lint, which this one does not.
        for repository in ("ejm-cli", "ejm-harness", "ejm-ide", "ejmlabs", ".github"):
            with self.subTest(repository=repository), self.assertRaisesRegex(ValueError, "publish.yml: .*permissions"):
                self.publish(repository=repository)

    def test_a_publish_hash_mismatch_prints_the_actual_digest_for_a_reviewed_update(self) -> None:
        changed = "name: Publish\n# changed\n"
        with self.assertRaises(ValueError) as caught:
            self.publish(changed)
        self.assertIn(hashlib.sha256(changed.encode()).hexdigest(), str(caught.exception))
        self.assertIn(hashlib.sha256(b"name: Publish\n").hexdigest(), str(caught.exception))
        self.assertIn("set UI_PUBLISH_SHA256", str(caught.exception))

    def test_ui_publish_workflow_cannot_be_a_symlink(self) -> None:
        reviewed = "name: Publish\n"
        (self.root / "target.yml").write_text(reviewed)
        (self.directory / "publish.yml").symlink_to(self.root / "target.yml")
        with (
            patch.object(standards, "UI_PUBLISH_SHA256", hashlib.sha256(reviewed.encode()).hexdigest()),
            self.assertRaisesRegex(ValueError, "Missing or unsafe file: .github/workflows/publish.yml"),
        ):
            workflows(self.root, "ejm-ui")

    def test_the_publish_workflow_is_read_through_the_capped_reader(self) -> None:
        (self.directory / "publish.yml").write_bytes(b"x" * (standards.MAX_READ_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "exceeds validation limit"):
            workflows(self.root, "ejm-ui")

    def test_cache_warm_caller_is_exact_and_only_for_rust_gates(self) -> None:
        canonical = standards.WARM_CACHE_CALLER.replace("STANDARDS_REVISION", self.revision)
        for repository in standards.WARM_CACHE:
            with self.subTest(repository=repository):
                (self.directory / "cache.yml").write_text(canonical)
                workflows(self.root, repository)
        # A caller cannot widen permissions, add a trigger, or point at another revision than pr.yml.
        for changed in (canonical.replace("contents: read", "contents: write"), canonical.replace("push:", "pull_request_target:"),
                        canonical.replace(self.revision, self.other_revision)):
            with self.subTest(content=changed), self.assertRaisesRegex(ValueError, "differs from the canonical consumer: cache.yml"):
                (self.directory / "cache.yml").write_text(changed)
                workflows(self.root, "ejm-cli")
        # Without a cache profile it is an ordinary product workflow, and a job-level permission is not credential-free.
        for repository in ("ejmlabs", ".github"):
            with self.subTest(repository=repository), self.assertRaisesRegex(ValueError, "cache.yml: job warm sets permissions"):
                (self.directory / "cache.yml").write_text(canonical)
                workflows(self.root, repository)

    def test_code_scan_caller_is_optional_and_pinned_to_the_profile(self) -> None:
        for repository, profile in standards.PROFILES.items():
            if repository == ".github":
                continue
            with self.subTest(repository=repository):
                canonical = consumer_workflows(self.revision, codeql_languages=profile.codeql_languages)["code-scan.yml"]
                path = self.directory / "code-scan.yml"
                self.assertIn("actions: read", canonical)
                path.write_text(canonical)
                workflows(self.root, repository)
                for changed in (canonical.replace(self.revision, self.other_revision),
                                canonical.replace("      actions: read\n", ""),
                                canonical.replace("security-events: write", "contents: write"),
                                canonical.replace("languages: " + profile.codeql_languages, "languages: actions")):
                    path.write_text(changed)
                    with self.assertRaisesRegex(ValueError, "differs from the canonical consumer: code-scan.yml"):
                        workflows(self.root, repository)
                path.unlink()
        self.assertEqual(standards.PROFILES["ejm-rightkit-fs"].codeql_languages, "rust")
        self.assertEqual(standards.PROFILES["ejm-cli"].codeql_languages, "rust")
        self.assertEqual(standards.PROFILES["ejm-harness"].codeql_languages, "python")

    def test_site_deploy_caller_passes_no_secrets(self) -> None:
        canonical = standards.SITE_DEPLOY_CALLER.replace("STANDARDS_REVISION", self.revision)
        older = canonical + "    secrets: inherit\n"
        self.assertTrue(canonical.endswith("    uses: ejmlabs/.github/.github/workflows/deploy-site.yml@" + self.revision + "\n"))
        self.assertEqual(consumer_workflows(self.revision, deploy=True)["deploy.yml"], canonical)
        for repository in standards.SITE_DEPLOY:
            for text in (canonical, older):
                with self.subTest(repository=repository, inherit=text is older):
                    (self.directory / "deploy.yml").write_text(text)
                    workflows(self.root, repository)
        for changed in (canonical.replace("contents: read", "contents: write"), older + "    secrets: inherit\n", canonical + "    secrets:\n      X: y\n",
                        canonical.replace(self.revision, self.other_revision), older.replace(self.revision, self.other_revision),
                        older.replace("    secrets: inherit\n", "    secrets: inherit"), canonical.replace("actions: read", "actions: write")):
            with self.subTest(content=changed), self.assertRaisesRegex(ValueError, "differs from the canonical consumer: deploy.yml"):
                (self.directory / "deploy.yml").write_text(changed)
                workflows(self.root, "ejmlabs")
        with self.assertRaisesRegex(ValueError, "deploy.yml: job deploy sets permissions"):
            (self.directory / "deploy.yml").write_text(canonical)
            workflows(self.root, ".github")

    def test_a_caller_mismatch_prints_a_bounded_diff_against_the_canonical_text(self) -> None:
        canonical = standards.WARM_CACHE_CALLER.replace("STANDARDS_REVISION", self.revision)
        (self.directory / "cache.yml").write_text(canonical.replace("contents: read", "contents: write"))
        with self.assertRaises(ValueError) as caught:
            workflows(self.root, "ejm-cli")
        message = str(caught.exception)
        self.assertIn("--- canonical/cache.yml", message)
        self.assertIn("+++ actual/cache.yml", message)
        self.assertIn("-      contents: read", message)
        self.assertIn("+      contents: write", message)
        (self.directory / "cache.yml").write_text(canonical + "".join(f"# line {index}\n" for index in range(500)))
        with self.assertRaises(ValueError) as caught:
            workflows(self.root, "ejm-cli")
        self.assertLess(len(str(caught.exception).splitlines()), 60)
        self.assertTrue(str(caught.exception).endswith("..."))
        (self.directory / "cache.yml").write_text(canonical + "# x" * 30_000)
        with self.assertRaisesRegex(ValueError, "cache.yml .too large to diff"):
            workflows(self.root, "ejm-cli")

    def test_a_pr_caller_without_a_pin_names_the_problem_and_the_rest_is_still_checked(self) -> None:
        (self.directory / "pr.yml").write_text("name: x\n")
        (self.directory / "extra.yml").write_text("on: [push]\n")
        with self.assertRaises(standards.StandardsError) as caught:
            workflows(self.root, "ejm-cli")
        joined = "\n".join(caught.exception.problems)
        self.assertIn("pr.yml: PR workflow must pin governance.yml to a full commit SHA", joined)
        self.assertIn("extra.yml", joined)

    def test_deploy_environments_belong_only_to_the_deploy_jobs(self) -> None:
        text = "# Generated by scripts/build_workflows.py. Edit scripts and regenerate.\n" + yaml(deploy_workflow()) + "\n"
        standards._reusable_workflow(text, "deploy-site.yml")
        build = '  "build":\n    "if":'
        for changed in (text.replace(build, '  "build":\n    "environment": "production"\n    "if":'),
                        text.replace('"environment": "production"', '"environment": "staging"'),
                        text.replace('    "environment": "production"\n', "")):
            with self.subTest(changed=changed[:0]), self.assertRaisesRegex(ValueError, "staging and production deploy jobs"):
                standards._reusable_workflow(changed, "deploy-site.yml")

    def test_reviewed_ui_publish_workflow_hash_is_recorded(self) -> None:
        self.assertRegex(standards.UI_PUBLISH_SHA256, r"^[0-9a-f]{64}$")

    def test_revision_must_be_a_lowercase_full_sha(self) -> None:
        revisions: tuple[Any, ...] = (None, 1, "a" * 39, "a" * 41, "A" * 40, "a" * 40 + "\n", "main")
        for revision in revisions:
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                consumer_workflows(revision)

    def test_consumer_workflows_add_the_optional_callers_on_request(self) -> None:
        self.assertEqual(sorted(consumer_workflows(self.revision)), ["pr.yml", "release.yml"])
        self.assertEqual(sorted(consumer_workflows(self.revision, cache=True, deploy=True)), ["cache.yml", "deploy.yml", "pr.yml", "release.yml"])
        self.assertEqual(consumer_workflows(self.revision, cache=True)["cache.yml"], standards.WARM_CACHE_CALLER.replace("STANDARDS_REVISION", self.revision))
        self.assertEqual(consumer_workflows(self.revision, native=True)["release.yml"], standards.NATIVE_RELEASE_CALLER.replace("STANDARDS_REVISION", self.revision))

    def test_the_dead_shims_are_gone(self) -> None:
        for name in ("PREVIOUS_PR_CALLER", "PR_EVENT", "PR_LABELS", "missing_model_key_workflows", "uniform_guidance", "COMMUNITY_GUIDES", "HEADINGS", "UI_PACKING_SHA256", "ui_packing"):
            self.assertFalse(hasattr(standards, name), name)

    def test_pr_caller_uses_pull_request_lifecycle_events(self) -> None:
        new = consumer_workflows(self.revision)["pr.yml"]
        self.assertEqual(new, PR_CALLER.replace("STANDARDS_REVISION", self.revision))
        self.assertIn("  pull_request:\n    types: [opened, reopened, synchronize, ready_for_review, converted_to_draft, labeled]\n", new)
        for forbidden in ("issue_comment", "pull_request_target", "XAI_API_KEY", "inherit"):
            self.assertNotIn(forbidden, new)

    def test_the_previous_comment_only_caller_and_other_forms_are_rejected(self) -> None:
        new = consumer_workflows(self.revision)["pr.yml"]
        comment = "  issue_comment:\n    types: [created, edited, deleted]\n"
        previous = new.replace("  pull_request:\n    types: [opened, reopened, synchronize, ready_for_review, converted_to_draft, labeled]\n", comment).replace(
            "github.event_name == 'pull_request'", "github.event.issue.pull_request")
        key = "      XAI_API_KEY: ${{ secrets.XAI_API_KEY }}\n"
        target = "  pull_request_target:\n    types: [unlabeled]\n"
        mutations = {
            "previous comment-only form": previous,
            "new form with comment trigger": new.replace("on:\n", "on:\n" + comment, 1),
            "new form with pull_request_target": new.replace("on:\n", "on:\n" + target, 1),
            "new form with the retired key": new.replace("    secrets:\n", "    secrets:\n" + key),
            "new form with another key": new + "      " + self.old_model_key + ": ${{ secrets." + self.old_model_key + " }}\n",
            "missing harness token": new.replace("      EJM_HARNESS_TOKEN: ${{ secrets.EJM_HARNESS_TOKEN }}\n", ""),
            "inherited secrets": new.replace("    secrets:\n      EJM_HARNESS_TOKEN: ${{ secrets.EJM_HARNESS_TOKEN }}\n", "    secrets: inherit\n"),
            "missing-key fixture job": new + "  missing_model_key:\n    runs-on: ubuntu-24.04\n    steps: []\n",
        }
        for case, text in mutations.items():
            with self.subTest(case=case):
                self.assertNotEqual(text, new)
                (self.directory / "pr.yml").write_text(text)
                for profile in (".github", "ejm-cli"):
                    with self.assertRaisesRegex(ValueError, "differs from the canonical consumer: pr.yml"):
                        workflows(self.root, profile)

    def test_shared_scaffold_declares_only_the_optional_harness_token(self) -> None:
        workflows(self.root, ".github")
        original = self.reusable()
        token = '      "EJM_HARNESS_TOKEN":\n        "required": false\n'
        self.assertIn(token, original)
        self.assertNotIn("XAI_API_KEY", original)
        workflows(self.root, ".github")
        declaration = '      "XAI_API_KEY":\n        "required": false\n'
        extra = '      "' + self.old_model_key + '":\n        "required": false\n'
        mutations = {
            "the retired model key before the token": original.replace(token, declaration + token),
            "the retired model key after the token": original.replace(token, token + declaration),
            "the retired model key as the only secret": original.replace(token, declaration),
            "both model keys": original.replace(token, declaration + extra + token),
            "old model key": original.replace(token, extra + token),
            "unknown secret": original.replace(token, '      "MODEL_API_KEY":\n        "required": false\n' + token),
            "required model key": original.replace(token, declaration.replace("false", "true") + token),
            "missing harness token": original.replace(token, ""),
            "required harness token": original.replace('"EJM_HARNESS_TOKEN":\n        "required": false', '"EJM_HARNESS_TOKEN":\n        "required": true'),
        }
        for case, text in mutations.items():
            with self.subTest(case=case):
                self.assertNotEqual(text, original)
                (self.directory / "governance.yml").write_text(text)
                with self.assertRaisesRegex(ValueError, "workflow_call scaffold: governance.yml"):
                    workflows(self.root, ".github")

    def test_consumer_trigger_and_yaml_bypasses_are_rejected(self) -> None:
        original = consumer_workflows(self.revision)["pr.yml"]
        mutations = {
            "inline automatic trigger": original.replace(
                "on:\n  pull_request:\n    types: [opened, reopened, synchronize, ready_for_review, converted_to_draft, labeled]",
                "on: [push]",
            ),
            "duplicate trigger": original + "on: [push]\n",
            "extra automatic trigger": original.replace("on:\n", "on:\n  push:\n"),
            "quoted mutable uses and fake pin": original.replace("    uses: ejmlabs/.github/.github/workflows/governance.yml@" + self.revision,
                '    "uses": "ejmlabs/.github/.github/workflows/governance.yml@main"\n    # uses: ejmlabs/.github/.github/workflows/governance.yml@' + self.revision),
            "additional job": original + "  unsafe:\n    runs-on: ubuntu-24.04\n    steps: []\n",
            "alternate quoted trigger": original.replace("on:\n", '"on":\n'),
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                (self.directory / "pr.yml").write_text(text)
                with self.assertRaises(ValueError):
                    workflows(self.root, "ejm-cli")

    def test_release_must_match_the_pr_revision_and_manual_trigger(self) -> None:
        original = consumer_workflows(self.revision)["release.yml"]
        mutations = {
            "different called workflow revision": original.replace("draft-release.yml@" + self.revision, "draft-release.yml@" + self.other_revision),
            "different standards revision": original.replace('standards-ref: "' + self.revision + '"', 'standards-ref: "' + self.other_revision + '"'),
            "automatic trigger": original.replace("  workflow_dispatch:\n", "  push:\n  workflow_dispatch:\n"),
            "number standards revision": original.replace('standards-ref: "' + self.revision + '"', "standards-ref: " + self.revision),
            "number commit input": original.replace("        type: string", "        type: number", 1),
            "duplicate trigger": original + "on: [push]\n",
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                (self.directory / "release.yml").write_text(text)
                with self.assertRaisesRegex(ValueError, "differs from the canonical consumer: release.yml"):
                    workflows(self.root, "ejm-cli")

    def test_a_missing_required_caller_is_reported(self) -> None:
        (self.directory / "release.yml").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or unsafe file: .github/workflows/release.yml"):
            workflows(self.root, "ejm-cli")

    def test_non_workflow_entries_are_rejected(self) -> None:
        for name in ("notes.md", "extra", "extra.yml.bak"):
            with self.subTest(name=name):
                (self.directory / name).write_text("on: [push]\n")
                with self.assertRaisesRegex(ValueError, "only .yml and .yaml files belong"):
                    workflows(self.root, "ejm-harness")
                (self.directory / name).unlink()
        (self.directory / "sub.yml").mkdir()
        with self.assertRaisesRegex(ValueError, "sub.yml: workflow entries must be regular files"):
            workflows(self.root, "ejm-harness")

    def test_a_symlinked_extra_workflow_is_rejected(self) -> None:
        (self.root / "ci.yml").write_text(CI_WORKFLOW)
        (self.directory / "ci.yml").symlink_to(self.root / "ci.yml")
        with self.assertRaisesRegex(ValueError, "ci.yml: workflow entries must be regular files"):
            workflows(self.root, "ejm-harness")

    def test_symlinked_workflow_is_rejected(self) -> None:
        file = self.directory / "release.yml"
        original = file.read_text()
        file.unlink()
        target = self.root / "caller.yml"
        target.write_text(original)
        file.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "Missing or unsafe file: .github/workflows/release.yml"):
            workflows(self.root, "ejm-cli")

    def test_shared_profile_accepts_both_full_generated_reusables(self) -> None:
        self.add_reusable("governance.yml", governance())
        self.add_reusable("draft-release.yml", release_workflow())
        self.add_reusable("verify-build.yml", verify_build_workflow())
        self.add_reusable("attach-assets.yml", attach_workflow())
        workflows(self.root, ".github")
        with self.assertRaises(ValueError):
            workflows(self.root, "ejm-cli")

    def test_new_reusables_must_match_the_generated_scaffold(self) -> None:
        for name, data in (("verify-build.yml", verify_build_workflow()), ("attach-assets.yml", attach_workflow())):
            self.add_reusable("governance.yml", governance())
            self.add_reusable(name, data)
            workflows(self.root, ".github")
            data["on"]["workflow_call"]["inputs"]["extra"] = {"required": False, "type": "string"}
            self.add_reusable(name, data)
            with self.subTest(name), self.assertRaises(ValueError):
                workflows(self.root, ".github")
            (self.directory / name).unlink()

    def native(self, repository: str = "ejm-cli", build: str | None = None) -> None:
        self.reset_callers()
        (self.directory / "release.yml").write_text(consumer_workflows(self.revision, native=True)["release.yml"])
        (self.directory / "build.yml").write_text(NATIVE_BUILD if build is None else build)
        workflows(self.root, repository)

    def test_native_release_is_selected_by_a_build_workflow_in_an_eligible_repository(self) -> None:
        self.native()
        self.native("ejm-harness")
        with self.assertRaises(ValueError):
            self.native("ejm-ui")
        with self.assertRaises(ValueError):
            self.native("ejmlabs")
        # A plain release.yml with a build.yml, or the native one without it, is not canonical.
        self.reset_callers()
        (self.directory / "build.yml").write_text(NATIVE_BUILD)
        with self.assertRaisesRegex(ValueError, "differs from the canonical consumer: release.yml"):
            workflows(self.root, "ejm-cli")
        (self.directory / "build.yml").unlink()
        (self.directory / "release.yml").write_text(consumer_workflows(self.revision, native=True)["release.yml"])
        with self.assertRaisesRegex(ValueError, "differs from the canonical consumer: release.yml"):
            workflows(self.root, "ejm-cli")
        self.reset_callers()
        workflows(self.root, "ejm-cli")

    def test_a_build_workflow_in_a_native_repository_gets_the_build_rules(self) -> None:
        with self.assertRaisesRegex(ValueError, ".github/workflows/build.yml: a build workflow runs only on workflow_dispatch and pushes to main"):
            self.native(build=NATIVE_BUILD.replace("  workflow_dispatch:\n", "  workflow_dispatch:\n  pull_request:\n"))
        with self.assertRaisesRegex(ValueError, "must upload exactly one artifact named release-files"):
            self.native(build=NATIVE_BUILD.replace("release-files", "files"))

    def test_native_release_orders_verify_release_attach_on_one_pin_and_commit(self) -> None:
        text = consumer_workflows(self.revision, native=True)["release.yml"]
        self.assertLess(text.index("  verify:"), text.index("  release:"))
        self.assertLess(text.index("  release:"), text.index("  attach:"))
        self.assertIn("    needs: verify\n", text)
        self.assertIn("    needs: release\n", text)
        self.assertEqual(text.count("      commit: ${{ inputs.commit }}\n"), 3)
        self.assertEqual(set(re.findall(r"@([0-9a-f]{40})", text)), {self.revision})
        self.assertNotIn("secrets", text)

    def test_shared_scaffold_cannot_declare_an_environment(self) -> None:
        for case in ("none", "step input", "literal lookalike", "job", "retired review job", "mapping", "indented job", "duplicate"):
            with self.subTest(case=case):
                data = governance()
                job = data["jobs"]["quality"]
                if case == "step input":
                    job["steps"].append({"uses": "actions/example@" + self.revision, "with": {"environment": "value"}})
                elif case == "literal lookalike":
                    job["steps"].append({"run": '  "ai":\n    "environment": "legacy-review"\n'})
                elif case == "job":
                    job["environment"] = "legacy-review"
                elif case == "retired review job":
                    data["jobs"]["ai"] = {"runs-on": "ubuntu-24.04", "environment": "legacy-review", "steps": [{"run": "true"}]}
                elif case == "mapping":
                    job["environment"] = {"name": "unprotected"}
                elif case == "indented job":
                    data["jobs"]["shadow"] = {"runs-on": "ubuntu-24.04", "environment": "unprotected", "steps": [{"run": "true"}]}
                text = self.add_reusable("governance.yml", data)
                if case == "duplicate":
                    text = text.replace('  "quality":\n', '  "quality":\n    "environment": "legacy-review"\n    "environment": "legacy-review"\n', 1)
                elif case == "indented job":
                    prefix, body = text.split('  "shadow":\n')
                    text = prefix + '  "shadow":\n' + "\n".join("  " + line for line in body.splitlines()) + "\n"
                (self.directory / "governance.yml").write_text(text)
                if case in ("none", "step input", "literal lookalike"):
                    workflows(self.root, ".github")
                else:
                    with self.assertRaisesRegex(ValueError, "environment"):
                        workflows(self.root, ".github")

    def test_release_jobs_cannot_declare_an_environment(self) -> None:
        for extra_indent in (0, 2):
            with self.subTest(extra_indent=extra_indent):
                data = release_workflow()
                data["jobs"]["draft"]["environment"] = "legacy-review"
                text = self.add_reusable("draft-release.yml", data)
                if extra_indent:
                    prefix, body = text.split('  "draft":\n')
                    text = prefix + '  "draft":\n' + "\n".join(" " * extra_indent + line for line in body.splitlines()) + "\n"
                    (self.directory / "draft-release.yml").write_text(text)
                with self.assertRaisesRegex(ValueError, "environment"):
                    workflows(self.root, ".github")

    def test_reusable_trigger_bypasses_are_rejected(self) -> None:
        original = self.reusable()
        mutations = {
            "inline automatic trigger": original.replace('"on":\n  "workflow_call":', '"on": ["push"]\n"unused":\n  "workflow_call":'),
            "duplicate trigger": original + '"on": ["push"]\n',
            "nested automatic trigger": original.replace('"on":\n', '"on":\n  "push": {}\n'),
            "additional root key": original + '"env": {}\n',
            "second YAML document": original + '---\n"on": ["push"]\n',
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                (self.directory / "governance.yml").write_text(text)
                with self.assertRaises(ValueError):
                    workflows(self.root, ".github")

    def test_reusable_mutable_uses_cannot_hide_behind_yaml_syntax(self) -> None:
        original = self.reusable()
        pinned = '"uses": "actions/checkout@' + self.revision + '"'
        mutations = {
            "quoted mutable uses": original.replace(pinned, '"uses": "actions/checkout@main"'),
            "escaped uses key": original.replace(pinned, r'"u\u0073es": "actions/checkout@main"'),
            "unquoted uses key": original.replace(pinned, 'uses: "actions/checkout@main"'),
            "flow mapping": original.replace(pinned, '"uses": {"ref": "actions/checkout@main"}'),
            "alias value": original.replace(pinned, '"uses": *mutable'),
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                (self.directory / "governance.yml").write_text(text)
                with self.assertRaisesRegex(ValueError, "governance.yml"):
                    workflows(self.root, ".github")

    def test_workflow_lookalikes_inside_literal_script_are_data(self) -> None:
        data = governance()
        data["jobs"] = {"quality": {"runs-on": "ubuntu-24.04",
                                    "steps": [{"run": 'on: [push]\n"uses": "actions/checkout@main"\n  "quality":\n    "environment": "unprotected"\n---\n'}]}}
        self.add_reusable("governance.yml", data)
        workflows(self.root, ".github")

    def test_local_cli_setup_hook_accepts_only_the_scoped_quality_step(self) -> None:
        cases = ("valid", "different path", "missing profile", "different profile", "extra environment", "privileged job", "other unprivileged job", "duplicate step", "release")
        for case in cases:
            with self.subTest(case=case):
                data = governance()
                steps = data["jobs"]["quality"]["steps"]
                steps[:] = [step for step in steps if step.get("uses") != "./product/.github/actions/setup-ci"]
                hook: dict[str, Any] = {
                    "name": "Prepare ejm-cli remote test prerequisites",
                    "if": "${{ needs.admission.outputs.profile == 'ejm-cli' }}",
                    "uses": "./product/.github/actions/setup-ci",
                }
                steps.insert(-1, hook)
                if case == "different path":
                    hook["uses"] = "./product/.github/actions/other"
                elif case == "missing profile":
                    del hook["if"]
                elif case == "different profile":
                    hook["if"] = "${{ needs.admission.outputs.profile == 'ejm-harness' }}"
                elif case == "extra environment":
                    hook["env"] = {"EXTRA": "value"}
                elif case in ("privileged job", "other unprivileged job"):
                    steps.remove(hook)
                    data["jobs"]["prepare" if case == "privileged job" else "registry"]["steps"].append(hook)
                elif case == "duplicate step":
                    steps.append(hook.copy())
                elif case == "release":
                    data = release_workflow()
                    data["jobs"]["draft"]["steps"].append(hook)
                name = "draft-release.yml" if case == "release" else "governance.yml"
                self.add_reusable(name, data)
                if case == "valid":
                    workflows(self.root, ".github")
                else:
                    with self.assertRaises(ValueError):
                        workflows(self.root, ".github")
                (self.directory / name).unlink()

    def test_literal_hook_lookalike_cannot_authorize_another_step(self) -> None:
        for case in ("prepare hook", "unconditioned quality hook", "valid quality hook"):
            with self.subTest(case=case):
                data = governance()
                for job in data["jobs"].values():
                    job["steps"] = [step for step in job["steps"] if step.get("uses") != "./product/.github/actions/setup-ci"]
                hook: dict[str, Any] = {
                    "name": "Prepare ejm-cli remote test prerequisites",
                    "if": "${{ needs.admission.outputs.profile == 'ejm-cli' }}",
                    "uses": "./product/.github/actions/setup-ci",
                }
                data["jobs"]["quality"]["name"] = "-\n" + yaml(hook, 2) + "\n-\n"
                if case == "prepare hook":
                    data["jobs"]["prepare"]["steps"].append({"uses": hook["uses"]})
                elif case == "unconditioned quality hook":
                    data["jobs"]["quality"]["steps"].append({"uses": hook["uses"]})
                else:
                    data["jobs"]["quality"]["steps"].insert(-1, hook)
                self.add_reusable("governance.yml", data)
                if case == "valid quality hook":
                    workflows(self.root, ".github")
                else:
                    with self.assertRaises(ValueError):
                        workflows(self.root, ".github")

    def test_comment_dash_cannot_hide_extra_cli_setup_fields(self) -> None:
        hook = {
            "name": "Prepare ejm-cli remote test prerequisites",
            "if": "${{ needs.admission.outputs.profile == 'ejm-cli' }}",
            "uses": "./product/.github/actions/setup-ci",
        }
        name = '        "name": "Prepare ejm-cli remote test prerequisites"\n'
        for extra in ({"env": {"EXTRA": "value"}}, {"continue-on-error": True}, {}):
            with self.subTest(extra=extra):
                data = governance()
                for job in data["jobs"].values():
                    job["steps"] = [step for step in job["steps"] if step.get("uses") != hook["uses"]]
                data["jobs"]["quality"]["steps"].insert(-1, {**extra, **hook})
                text = self.add_reusable("governance.yml", data)
                if extra:
                    # This is still one real YAML step with an extra field. The
                    # comment must not become a second, canonical step boundary.
                    text = text.replace(name, "        #      -\n" + name)
                else:
                    # Comments before a real sequence boundary retain source
                    # line mapping and must not reject the permitted hook.
                    text = text.replace("      -\n" + name, "      # setup prerequisites\n      -\n" + name)
                (self.directory / "governance.yml").write_text(text)
                if extra:
                    with self.assertRaises(ValueError):
                        workflows(self.root, ".github")
                else:
                    workflows(self.root, ".github")

    def test_reusable_keys_that_are_not_json_are_rejected_with_the_file_name(self) -> None:
        original = self.reusable()
        for name, text in {"bad escape": original + '"x\\q": 1\n', "bad scalar": original.replace('"required": false', '"required": nope', 1)}.items():
            with self.subTest(name):
                (self.directory / "governance.yml").write_text(text)
                with self.assertRaisesRegex(ValueError, "governance.yml"):
                    workflows(self.root, ".github")


class ExtraWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.directory = self.root / ".github/workflows"
        self.directory.mkdir(parents=True)
        for name, text in consumer_workflows(REVISION).items():
            (self.directory / name).write_text(text)

    def lint(self, text: str, name: str = "ci.yml") -> list[str]:
        return lint_workflow(text, name)

    def test_a_realistic_workflow_is_accepted_in_every_profile(self) -> None:
        for suffix in ("yml", "yaml"):
            (self.directory / ("ci." + suffix)).write_text(CI_WORKFLOW)
            for profile in PROFILES:
                with self.subTest(profile=profile, suffix=suffix):
                    workflows(self.root, profile)
            (self.directory / ("ci." + suffix)).unlink()

    def test_the_review_found_false_positives_are_accepted(self) -> None:
        cases = {
            "uses and permissions in a comment": CI_WORKFLOW.replace("jobs:\n", "# uses permissions secrets environment\njobs:\n", 1),
            "uses and permissions in a step name": CI_WORKFLOW.replace("- name: Build\n", "- name: Set uses and permissions\n"),
            "uses and permissions in a script": CI_WORKFLOW.replace("run: cargo build --locked", "run: |\n          echo uses: x/y@v1\n          echo permissions: write-all\n          # secrets: inherit"),
            "a trailing comment mentioning them": CI_WORKFLOW.replace("fetch-depth: 0", "fetch-depth: 0 # uses permissions"),
            "quoted values": CI_WORKFLOW.replace("name: Build\n", 'name: "Build it"\n').replace("os: [ubuntu-24.04, macos-15]", 'os: ["ubuntu-24.04", \'macos-15\']'),
            "a quoted trigger list": CI_WORKFLOW.replace("branches: [main]", 'branches: ["main", "release/*"]'),
            "non-ascii text in a comment": CI_WORKFLOW.replace("jobs:\n", "# caf" + E_ACUTE + "\njobs:\n", 1),
            "non-ascii text in a script": CI_WORKFLOW.replace("run: cargo build --locked", "run: echo caf" + E_ACUTE),
            "an environment variable called ENVIRONMENT": CI_WORKFLOW.replace("env:\n  CARGO_TERM_COLOR: always", "env:\n  CARGO_TERM_COLOR: always\n  ENVIRONMENT: test"),
            "a word that merely contains a banned one": CI_WORKFLOW.replace("CARGO_TERM_COLOR: always", "SECRETS_FILE_NAME: none"),
            "the word pull_request in a script": CI_WORKFLOW.replace("run: cargo build --locked", "run: echo pull_request secrets"),
            "empty top-level permissions": CI_WORKFLOW.replace("permissions:\n  contents: read\n", "permissions: {}\n"),
            "a sequence at its key's indent": CI_WORKFLOW.replace("          - ubuntu-24.04\n          - macos-15\n", "        - ubuntu-24.04\n        - macos-15\n").replace("        os:\n", "        os:\n"),
            "a flow list of words": CI_WORKFLOW.replace("fail-fast: false", "fail-fast: false\n      max-parallel: 2").replace("os: [ubuntu-24.04, macos-15]", "os: [ubuntu-24.04, macos-15]\n        node: [20, 22.1, lts/*]"),
            "a scheduled trigger": CI_WORKFLOW.replace("  workflow_dispatch:\n", "  workflow_dispatch:\n  schedule:\n    - cron: '0 3 * * 1'\n"),
            "a merge group": CI_WORKFLOW.replace("  workflow_dispatch:\n", "  workflow_dispatch:\n  merge_group:\n"),
            "an inline trigger list": CI_WORKFLOW.replace("on:\n  push:\n    branches: [main]\n  pull_request:\n  workflow_dispatch:\n", "on: [push, pull_request]\n"),
            "no trailing newline": CI_WORKFLOW.rstrip("\n"),
            "a pinned reusable workflow": CI_WORKFLOW + "  call:\n    uses: owner/repo/.github/workflows/x.yml@" + SHA1 + "\n    with:\n      flag: yes\n",
            "a local action": CI_WORKFLOW + "      - uses: ./.github/actions/setup\n",
            "a pinned action with a subpath": CI_WORKFLOW + "      - uses: actions/cache/restore@" + SHA2 + "\n",
            "persist-credentials false": CI_WORKFLOW.replace("fetch-depth: 0", "persist-credentials: false"),
            "a folded scalar": CI_WORKFLOW.replace("run: cargo build --locked", "run: >-\n          cargo build\n          --locked"),
            "an indented block indicator": CI_WORKFLOW.replace("run: cargo build --locked", "run: |2\n            indented\n          done"),
            "a literal block with shell braces": CI_WORKFLOW.replace("run: cargo build --locked", 'run: |\n          for f in out/*; do echo "${f}"; done\n          [ -d out ] && true'),
            "a blank line and a comment between steps": CI_WORKFLOW.replace("      - name: Build\n", "\n      # build\n      - name: Build\n"),
            "an expression in a name": CI_WORKFLOW.replace("name: Build\n", "name: Build ${{ matrix.os }}\n"),
            "a github context that is not the token": CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ github.sha }} ${{ github.event.pull_request.number }} ${{ github['sha'] }}"),
            "a string literal that contains braces": CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ format('{0}}', github.sha) }}"),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertEqual(self.lint(text), [], name)

    def test_credential_and_privilege_rules(self) -> None:
        bad = {
            "write permissions": (CI_WORKFLOW.replace("contents: read", "contents: write"), "top-level permissions must be exactly"),
            "read-all permissions": (CI_WORKFLOW.replace("permissions:\n  contents: read\n", "permissions: read-all\n"), "top-level permissions"),
            "extra permission": (CI_WORKFLOW.replace("contents: read", "contents: read\n  actions: read"), "top-level permissions"),
            "id-token permission": (CI_WORKFLOW.replace("contents: read", "contents: read\n  id-token: write"), "top-level permissions"),
            "no permissions": (CI_WORKFLOW.replace("permissions:\n  contents: read\n", ""), "top-level permissions"),
            "job permissions": (CI_WORKFLOW.replace("    timeout-minutes: 10\n", "    timeout-minutes: 10\n    permissions:\n      contents: read\n"), "job test sets permissions"),
            "empty job permissions": (CI_WORKFLOW.replace("    timeout-minutes: 10\n", "    timeout-minutes: 10\n    permissions: {}\n"), "job test sets permissions"),
            "uppercase job permissions": (CI_WORKFLOW.replace("    timeout-minutes: 10\n", "    timeout-minutes: 10\n    PERMISSIONS: write-all\n"), "job test sets PERMISSIONS"),
            "job environment": (CI_WORKFLOW.replace("    timeout-minutes: 10\n", "    timeout-minutes: 10\n    environment: prod\n"), "job test sets environment"),
            "job secrets": (CI_WORKFLOW + "  call:\n    uses: owner/repo/.github/workflows/x.yml@" + SHA1 + "\n    secrets: inherit\n", "job call sets secrets"),
            "secret expression": (CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ secrets.TOKEN }}"), "references secrets"),
            "secret in env": (CI_WORKFLOW.replace("CARGO_TERM_COLOR: always", "K: ${{ secrets.K }}"), "references secrets"),
            "token expression": (CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ github.token }}"), "references github.token"),
            "bracketed token": (CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ github['token'] }}"), "references github.token"),
            "spaced token": (CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ github . token }}"), "references github.token"),
            "uppercase token": (CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ GITHUB.TOKEN }}"), "references github.token"),
            "whole github context": (CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ toJSON(github) }}"), "references tojson"),
            "dynamic github index": (CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ github[matrix.os] }}"), "references github\\["),
            "secrets context after a string with braces": (CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ format('{0}}', 1) && secrets.X }}"), "references secrets"),
            "GITHUB_TOKEN secret": (CI_WORKFLOW.replace("CARGO_TERM_COLOR: always", "T: ${{ secrets.GITHUB_TOKEN }}"), "references secrets"),
            "GITHUB_TOKEN variable": (CI_WORKFLOW.replace("CARGO_TERM_COLOR: always", "GITHUB_TOKEN: x"), "GITHUB_TOKEN must not be set"),
            "persist-credentials true": (CI_WORKFLOW.replace("fetch-depth: 0", "persist-credentials: true"), "persist-credentials must be false"),
            "persist-credentials quoted true": (CI_WORKFLOW.replace("fetch-depth: 0", "persist-credentials: 'true'"), "persist-credentials must be false"),
            "persist-credentials computed": (CI_WORKFLOW.replace("fetch-depth: 0", "persist-credentials: ${{ inputs.x }}"), "persist-credentials must be false"),
            "mutable action": (CI_WORKFLOW.replace("@" + SHA1, "@v4"), "uses 'actions/checkout@v4' must be owner/repo"),
            "short sha": (CI_WORKFLOW.replace("@" + SHA1, "@" + "1" * 39), "must be owner/repo"),
            "upper sha": (CI_WORKFLOW.replace("@" + SHA1, "@" + "A" * 40), "must be owner/repo"),
            "docker action": (CI_WORKFLOW + "      - uses: docker://alpine:3\n", "uses 'docker://alpine:3'"),
            "local reusable workflow": (CI_WORKFLOW + "  call:\n    uses: ./.github/workflows/x.yml\n", "uses './.github/workflows/x.yml'"),
            "local action escaping": (CI_WORKFLOW + "      - uses: ./.github/actions/../../x\n", "uses './.github/actions/../../x'"),
            "action path escaping": (CI_WORKFLOW + "      - uses: a/b/../c@" + SHA1 + "\n", "must be owner/repo"),
            "computed action": (CI_WORKFLOW + "      - uses: ${{ matrix.action }}\n", "must be owner/repo"),
            "empty action": (CI_WORKFLOW + "      - uses:\n", "uses '' must be owner/repo"),
            "quoted mutable action": (CI_WORKFLOW + "      - uses: 'a/b@main'\n", "uses 'a/b@main'"),
            "uppercase uses key": (CI_WORKFLOW + "      - Uses: a/b@main\n", "uses 'a/b@main'"),
        }
        for name, (text, pattern) in bad.items():
            with self.subTest(name):
                problems = self.lint(text)
                self.assertTrue(problems, name)
                self.assertRegex("\n".join(problems), pattern)

    def test_trigger_rules(self) -> None:
        for trigger in ("pull_request_target", "workflow_run", "issue_comment", "workflow_call", "release", "issues", "repository_dispatch", "create"):
            with self.subTest(trigger=trigger):
                problems = self.lint(CI_WORKFLOW.replace("  workflow_dispatch:\n", f"  workflow_dispatch:\n  {trigger}:\n"))
                self.assertRegex("\n".join(problems), f"trigger '{trigger}' is not allowed")
        for text in (CI_WORKFLOW.replace("on:\n  push:\n    branches: [main]\n  pull_request:\n  workflow_dispatch:\n", "on: pull_request_target\n"),
                     CI_WORKFLOW.replace("on:\n  push:\n    branches: [main]\n  pull_request:\n  workflow_dispatch:\n", "on: [push, workflow_run]\n"),
                     CI_WORKFLOW.replace("on:\n  push:\n    branches: [main]\n  pull_request:\n  workflow_dispatch:\n", "on:\n  - push\n  - issue_comment\n")):
            with self.subTest(text=text[:40]):
                self.assertRegex("\n".join(self.lint(text)), "is not allowed")
        for text in (CI_WORKFLOW.replace("on:\n  push:\n    branches: [main]\n  pull_request:\n  workflow_dispatch:\n", ""),
                     CI_WORKFLOW.replace("on:\n  push:\n    branches: [main]\n  pull_request:\n  workflow_dispatch:\n", "on:\n")):
            with self.subTest(text=text[:40]):
                self.assertRegex("\n".join(self.lint(text)), "declare the triggers under `on:`")

    def test_structure_rules(self) -> None:
        for name, text, pattern in (
            ("unknown top-level key", CI_WORKFLOW + "services: {}\n", "unknown top-level key 'services'"),
            ("uppercase on", CI_WORKFLOW.replace("on:\n", "ON:\n", 1), "unknown top-level key 'ON'"),
            ("no jobs", CI_WORKFLOW.split("jobs:")[0], "jobs must be a non-empty mapping"),
            ("a job that is not a mapping", CI_WORKFLOW.split("jobs:")[0] + "jobs:\n  a: x\n", "job a must be a mapping"),
        ):
            with self.subTest(name):
                self.assertRegex("\n".join(self.lint(text)), pattern)

    def test_the_restricted_yaml_subset_fails_closed(self) -> None:
        marker = "      - name: Build\n"
        bad = {
            "quoted key": CI_WORKFLOW.replace("    timeout-minutes: 10\n", '    "permissions": write-all\n'),
            "single-quoted key": CI_WORKFLOW.replace("    timeout-minutes: 10\n", "    'permissions': write-all\n"),
            "flow mapping": CI_WORKFLOW.replace("    timeout-minutes: 10\n", "    other: {permissions: write-all}\n"),
            "flow mapping step": CI_WORKFLOW.replace(marker, "      - {uses: someone/x@v1}\n" + marker),
            "nested flow list": CI_WORKFLOW.replace("os: [ubuntu-24.04, macos-15]", "os: [[a], b]"),
            "flow list with a mapping": CI_WORKFLOW.replace("os: [ubuntu-24.04, macos-15]", "os: [a, {b: c}]"),
            "flow list with an alias": CI_WORKFLOW.replace("os: [ubuntu-24.04, macos-15]", "os: [*a]"),
            "multiline flow list": CI_WORKFLOW.replace("os: [ubuntu-24.04, macos-15]", "os: [ubuntu-24.04,\n          macos-15]"),
            "anchor": CI_WORKFLOW.replace("runs-on: ${{ matrix.os }}", "runs-on: &os ubuntu-24.04"),
            "anchored list entry": CI_WORKFLOW.replace(marker, "      - &a x\n" + marker),
            "alias": CI_WORKFLOW.replace("runs-on: ${{ matrix.os }}", "runs-on: *os"),
            "merge key": CI_WORKFLOW.replace("    timeout-minutes: 10\n", "    <<: *base\n"),
            "tag": CI_WORKFLOW.replace("runs-on: ${{ matrix.os }}", "runs-on: !!str ubuntu"),
            "bang value": CI_WORKFLOW.replace("runs-on: ${{ matrix.os }}", "runs-on: !cancelled()"),
            "explicit key": CI_WORKFLOW.replace("    timeout-minutes: 10\n", '    ? "perm\\x69ssions"\n    : write-all\n'),
            "directive": "%YAML 1.1\n" + CI_WORKFLOW,
            "second document": CI_WORKFLOW + "---\nname: other\n",
            "document start": "---\n" + CI_WORKFLOW,
            "document end": CI_WORKFLOW + "...\n",
            "duplicate top-level key": CI_WORKFLOW + "jobs:\n  c:\n    runs-on: x\n",
            "duplicate on": CI_WORKFLOW + "on:\n  workflow_call:\n",
            "duplicate permissions": CI_WORKFLOW + "permissions: {}\n",
            "duplicate nested key": CI_WORKFLOW.replace("    timeout-minutes: 10\n", "    timeout-minutes: 10\n    timeout-minutes: 11\n"),
            "tab indent": CI_WORKFLOW.replace("      - name: Build", "\t- name: Build"),
            "tab separator": CI_WORKFLOW.replace("timeout-minutes: 10", "timeout-minutes:\t10"),
            "double quote with backslash": CI_WORKFLOW.replace("name: Build\n", 'name: "B\\x75ild"\n'),
            "escaped quoted value": CI_WORKFLOW.replace("run: cargo build --locked", 'run: "echo \\"x\\""'),
            "unterminated double quote": CI_WORKFLOW.replace("name: Build\n", 'name: "Build\n'),
            "unterminated single quote": CI_WORKFLOW.replace("name: Build\n", "name: 'Build\n"),
            "text after a quoted value": CI_WORKFLOW.replace("name: Build\n", 'name: "Build" x\n'),
            "multiline plain scalar": CI_WORKFLOW.replace("run: cargo build --locked", "run: cargo build\n          --locked"),
            "continuation that looks like a key": CI_WORKFLOW.replace("run: cargo build --locked", "run: cargo build\n          permissions: write-all"),
            "bare dash": CI_WORKFLOW.replace(marker, "      -\n        name: Build\n"),
            "nested dash": CI_WORKFLOW.replace(marker, "      - - x\n" + marker),
            "empty list entry": CI_WORKFLOW.replace(marker, "      - \n" + marker),
            "list entry holding a flow list": CI_WORKFLOW.replace(marker, "      - [a, b]\n" + marker),
            "list entry holding a block scalar": CI_WORKFLOW.replace(marker, "      - |\n        text\n" + marker),
            "space before the colon": CI_WORKFLOW.replace("timeout-minutes: 10", "timeout-minutes : 10"),
            "colon space inside a plain value": CI_WORKFLOW.replace("run: cargo build --locked", "run: echo a: b"),
            "plain value ending in a colon": CI_WORKFLOW.replace("run: cargo build --locked", "run: echo a:"),
            "unterminated expression": CI_WORKFLOW.replace("run: cargo build --locked", "run: echo ${{ github.sha"),
            "lone value line": CI_WORKFLOW + "stray\n",
            "indented first line": "  " + CI_WORKFLOW,
            "key after misplaced indentation": CI_WORKFLOW.replace("    timeout-minutes: 10\n", "    timeout-minutes: 10\n     extra: 1\n"),
            "bad block header": CI_WORKFLOW.replace("run: cargo build --locked", "run: |x"),
            "starts at a dash": "- a\n- b\n",
            "empty file": "",
            "only comments": "# nothing\n",
            "indicator value": CI_WORKFLOW.replace("run: cargo build --locked", "run: @x"),
            "percent value": CI_WORKFLOW.replace("run: cargo build --locked", "run: %x"),
            "backtick value": CI_WORKFLOW.replace("run: cargo build --locked", "run: `x`"),
            "question value": CI_WORKFLOW.replace("run: cargo build --locked", "run: ?x"),
            "dash value": CI_WORKFLOW.replace("run: cargo build --locked", "run: - x"),
        }
        for name, text in bad.items():
            with self.subTest(name):
                self.assertTrue(self.lint(text), name)

    def test_the_old_build_lint_bypass_attempts_stay_rejected(self) -> None:
        bad = {
            "explicit escaped key": NATIVE_BUILD.replace("    runs-on", '    ? "perm\\x69ssions"\n    : write-all\n    runs-on'),
            "two spaces then escaped key": NATIVE_BUILD.replace("      - run: cargo build --release --locked\n", '      -  "u\\x73es": someone/x@v1\n'),
            "key after a shallow block end": NATIVE_BUILD.replace("      - run: cargo build --release --locked\n", '      - name: |\n          hi\n        "u\\x73es": someone/x@v1\n'),
            "flow key after a run block": NATIVE_BUILD.replace("      - run: cargo build --release --locked\n", "      - run: |\n          make\n        env: {A: b}\n"),
            "carriage return in the name line": NATIVE_BUILD.replace("name: Build\n", 'name: Build\renv:\r  T: "${{ \\x73ecrets.K }}"\n', 1),
            "next-line break in the name line": NATIVE_BUILD.replace("name: Build\n", "name: Build" + NEL + "env:" + NEL + '  T: "${{ \\x73ecrets.K }}"\n', 1),
            "line separator in the body": NATIVE_BUILD.replace("      - run: cargo", "      - run: cargo" + LINE_SEP + "env: x\n      - run: cargo", 1),
            "no-break space before a comment mark": NATIVE_BUILD.replace("jobs:\n", "env:\n" + NBSP + ' #T: "${{ \\x73ecrets.K }}"\njobs:\n', 1),
            "en space before a comment mark": NATIVE_BUILD.replace("jobs:\n", "env:\n" + EN_SPACE + '#T: "${{ \\x73ecrets.K }}"\njobs:\n', 1),
            "control character": NATIVE_BUILD.replace("cargo build", "cargo\x07 build", 1),
            "bidirectional override in a comment": NATIVE_BUILD.replace("jobs:\n", "# " + chr(0x202E) + "x\njobs:\n", 1),
            "zero width space": NATIVE_BUILD.replace("cargo build", "cargo" + chr(0x200B) + " build", 1),
            "byte order mark": NATIVE_BUILD + chr(0xFEFF),
            "key after the permission block": NATIVE_BUILD.replace("  contents: read\n", "  contents: read\n\n  # more\n  actions: write\n", 1),
        }
        for name, text in bad.items():
            with self.subTest(name):
                self.assertTrue(lint_workflow(text, "build.yml", build=True), name)
                self.assertTrue(self.lint(text), name)

    def test_a_workflow_with_a_carriage_return_is_rejected_by_the_lint_but_normalized_when_read(self) -> None:
        self.assertRegex("\n".join(self.lint(CI_WORKFLOW.replace("\n", "\r\n"))), "use LF line endings")
        (self.directory / "ci.yml").write_bytes(CI_WORKFLOW.replace("\n", "\r\n").encode())
        workflows(self.root, ".github")

    def test_problems_name_the_file_and_the_line(self) -> None:
        problems = self.lint(CI_WORKFLOW.replace("timeout-minutes: 10", "timeout-minutes : 10"), ".github/workflows/ci.yml")
        self.assertEqual(len(problems), 1)
        self.assertRegex(problems[0], r"^\.github/workflows/ci\.yml:\d+: unsupported YAML")
        (self.directory / "ci.yml").write_text(CI_WORKFLOW.replace("contents: read", "contents: write"))
        with self.assertRaisesRegex(ValueError, r"\.github/workflows/ci\.yml: top-level permissions"):
            workflows(self.root, "ejm-cli")

    def test_every_rule_violation_is_reported_together(self) -> None:
        text = CI_WORKFLOW.replace("contents: read", "contents: write").replace("  workflow_dispatch:\n", "  workflow_dispatch:\n  issue_comment:\n").replace("@" + SHA1, "@v4").replace(
            "run: cargo build --locked", "run: echo ${{ secrets.X }}")
        problems = self.lint(text)
        self.assertGreaterEqual(len(problems), 4)
        self.assertEqual(len(problems), len(set(problems)))

    def test_nesting_is_bounded(self) -> None:
        deep = "name: x\njobs:\n" + "".join("  " * (index + 1) + f"k{index}:\n" for index in range(60)) + "  " * 61 + "v: 1\n"
        self.assertRegex("\n".join(self.lint(deep)), "nested more than 40 levels")

    def test_hostile_expressions_are_scanned_in_linear_time(self) -> None:
        started = time.monotonic()
        for text in ("name: x\nenv:\n  A: " + "${{ " * 40_000 + "\n",
                     "name: x\nenv:\n  A: " + "${{ }} " * 40_000 + "\n",
                     "name: x\njobs:\n  a:\n    steps:\n      - run: |\n" + "          ${{ x \n" * 40_000,
                     "name: x\nenv:\n  A: " + "${{ '" * 40_000 + "\n",
                     "name: x\nenv:\n  A: '" + "''" * 40_000 + "'\n",
                     "name: x\nenv:\n  A: " + "[" * 40_000 + "\n",
                     "name: x\nenv:\n  A: " + "a: " * 40_000 + "\n",
                     "name: x\nenv:\n  A: ${{ github" + "['x']" * 20_000 + " }}\n"):
            self.assertTrue(self.lint(text))
        self.assertLess(time.monotonic() - started, 10)

    def test_a_large_valid_workflow_is_checked_in_bounded_time(self) -> None:
        steps = "".join(f"      - name: Step {index}\n        run: echo {index}\n" for index in range(5_000))
        started = time.monotonic()
        self.assertEqual(self.lint(CI_WORKFLOW + steps), [])
        self.assertLess(time.monotonic() - started, 10)

    def test_non_workflow_canonical_names_are_ordinary_workflows_elsewhere(self) -> None:
        # pr.yml and release.yml are always the canonical callers; the optional names are canonical only for their profiles.
        (self.directory / "build.yml").write_text(NATIVE_BUILD.replace("workflow_dispatch:\n  push:\n    branches: [main]", "push:\n    branches: [main]\n  pull_request:"))
        workflows(self.root, "ejm-ui")
        with self.assertRaisesRegex(ValueError, "build.yml: a build workflow runs only on workflow_dispatch"):
            workflows(self.root, "ejm-cli")

    def test_everything_the_lint_accepts_is_structurally_read_only(self) -> None:
        """Backstop: PyYAML is not a dependency of the standards check, so this runs where it is installed."""
        try:
            parser = importlib.import_module("yaml")
        except ImportError:
            self.skipTest("PyYAML is not installed")
        rng = random.Random(7)  # noqa: S311 - a seeded generator for reproducible test input, not for security
        hostile = ["permissions: write-all", "  permissions: write-all", "    permissions:", "      contents: write", "      id-token: write", "    environment: prod",
                   "    secrets: inherit", "- uses: x/y@v1", "      - uses: x/y@v1", "uses: x/y@main", "on: [push]", "on:", "  workflow_run:", "  pull_request_target:",
                   "  issue_comment:", "ON: x", "Permissions: write-all", "env:", "  T: ${{ secrets.K }}", "  T: ${{ github.token }}", "name: x", "---", "&a b: c",
                   "  k: *a", "  k: !!str x", "  k: {a: b}", "      persist-credentials: true", "  GITHUB_TOKEN: x", '  "permissions": write-all', "  k: |", "  # c",
                   "  k: 'unterminated", '  k: "a\\x73b"', "\tk: v", "  k: a: b", "-", "  jobs:", "jobs:", "  x:"]
        alphabet = list("abcdefgxyz :-[]{}'\"|>#&*!%@`\\\n\t$0123456789._/=,?")
        accepted = 0
        for index in range(4_000):
            lines = (NATIVE_BUILD if index % 2 else CI_WORKFLOW).split("\n")
            for _ in range(rng.randint(1, 3)):
                position = rng.randrange(len(lines) + 1)
                kind = rng.randrange(4)
                if kind == 0:
                    lines.insert(position, " " * rng.choice([0, 0, 2, 4, 6, 8]) + rng.choice(hostile))
                elif kind == 1 and lines:
                    del lines[min(position, len(lines) - 1)]
                elif kind == 2 and lines:
                    at = min(position, len(lines) - 1)
                    cut = rng.randrange(len(lines[at]) + 1)
                    lines[at] = lines[at][:cut] + rng.choice(alphabet) + lines[at][cut:]
                else:
                    at = min(position, len(lines) - 1)
                    lines[at] = " " * rng.choice([0, 1, 2, 3]) + lines[at]
            text = "\n".join(lines)
            build = index % 2 == 1
            if lint_workflow(text, "x.yml", build=build):
                continue
            try:
                data = parser.safe_load(text)
            except parser.YAMLError:  # an unparsable file is not a workflow GitHub would run
                continue
            accepted += 1
            self.assertIsInstance(data, dict, text)
            self.assertLessEqual({"on" if key is True else key for key in data}, standards.TOP_LEVEL_KEYS, text)
            self.assertIn(data["permissions"], [{"contents": "read"}] if build else [{"contents": "read"}, {}], text)
            triggers = data.get(True, data.get("on"))
            names = list(triggers) if isinstance(triggers, dict) else triggers if isinstance(triggers, list) else [triggers]
            self.assertLessEqual(set(names), {"workflow_dispatch", "push"} if build else standards.EXTRA_TRIGGERS, text)
            for job in data["jobs"].values():
                self.assertFalse({str(key).lower() for key in job} & standards.JOB_KEYS_FORBIDDEN, text)
            self.assertNotRegex(text, r"(?i)\$\{\{[^}]*(secrets|github\.token)")
        self.assertGreaterEqual(accepted, 100)


class BuildWorkflowTests(unittest.TestCase):
    def test_native_build_shape_is_read_only_and_secretless(self) -> None:
        native_build(NATIVE_BUILD)
        bad = {
            "write permission": NATIVE_BUILD.replace("contents: read", "contents: write"),
            "empty permissions": NATIVE_BUILD.replace("permissions:\n  contents: read\n", "permissions: {}\n"),
            "job permissions": NATIVE_BUILD.replace("  build:\n", "  build:\n    permissions:\n      contents: read\n"),
            "secret": NATIVE_BUILD.replace("run: cargo", "env:\n          K: ${{ secrets.K }}\n        run: cargo"),
            "token": NATIVE_BUILD.replace("run: cargo", "env:\n          T: ${{ github.token }}\n        run: cargo"),
            "pull request": NATIVE_BUILD.replace("  workflow_dispatch:\n", "  workflow_dispatch:\n  pull_request:\n"),
            "no workflow_dispatch": NATIVE_BUILD.replace("  workflow_dispatch:\n", ""),
            "no push": NATIVE_BUILD.replace("  push:\n    branches: [main]\n", ""),
            "dispatch inputs": NATIVE_BUILD.replace("  workflow_dispatch:\n", "  workflow_dispatch:\n    inputs:\n      x:\n        type: string\n"),
            "schedule": NATIVE_BUILD.replace("  workflow_dispatch:\n", "  workflow_dispatch:\n  schedule:\n    - cron: '0 0 * * *'\n"),
            "mutable action": NATIVE_BUILD.replace("@" + "1" * 40, "@v4"),
            "local action": NATIVE_BUILD.replace("actions/checkout@" + "1" * 40, "./.github/actions/x"),
            "other branches": NATIVE_BUILD.replace("[main]", "[main, topic]"),
            "branch pattern": NATIVE_BUILD.replace("[main]", "['**']"),
            "tags": NATIVE_BUILD.replace("    branches: [main]\n", "    branches: [main]\n    tags: ['v*']\n"),
            "paths": NATIVE_BUILD.replace("    branches: [main]\n", "    branches: [main]\n    paths: [src]\n"),
            "no artifact": NATIVE_BUILD.replace("release-files", "files"),
            "second artifact": NATIVE_BUILD + "      - name: release-files\n",
            "second upload": NATIVE_BUILD + "      - uses: actions/upload-artifact@" + "2" * 40 + "\n        with:\n          name: release-files\n",
            "artifact from another action": NATIVE_BUILD.replace("actions/upload-artifact@", "actions/cache@"),
            "environment": NATIVE_BUILD.replace("    runs-on", "    environment: prod\n    runs-on"),
            "quoted job permissions": NATIVE_BUILD.replace("    runs-on", '    "permissions": write-all\n    runs-on'),
            "flow job permissions": NATIVE_BUILD.replace("    runs-on: ubuntu-24.04\n", "    other: {permissions: write-all, runs-on: x}\n    runs-on: ubuntu-24.04\n"),
            "quoted local action": NATIVE_BUILD.replace("      - run: cargo build --release --locked\n", '      - "uses": ./.github/actions/x\n'),
            "flow mutable action": NATIVE_BUILD.replace("      - run: cargo build --release --locked\n", "      - {uses: someone/x@v1}\n"),
            "anchor": NATIVE_BUILD.replace("    runs-on: ubuntu-24.04", "    runs-on: &os ubuntu-24.04"),
            "tab": NATIVE_BUILD.replace("      - run: cargo", "      -\trun: cargo"),
            "second document": NATIVE_BUILD + "---\nname: other\n",
            "repeated top-level key": NATIVE_BUILD + "jobs:\n  c:\n    runs-on: x\n",
            "repeated on": NATIVE_BUILD + "on:\n  workflow_call:\n",
            "uppercase on": NATIVE_BUILD + "ON:\n  workflow_call:\n",
            "permission after the header": NATIVE_BUILD.replace("  contents: read\n", "  contents: read\n\n  # more\n  actions: write\n", 1),
            "uppercase permissions": NATIVE_BUILD.replace("    runs-on", "    PERMISSIONS: write-all\n    runs-on"),
            "persist credentials": NATIVE_BUILD.replace("        with:\n          name: release-files", "        with:\n          persist-credentials: true\n          name: release-files"),
        }
        for name, text in bad.items():
            with self.subTest(name), self.assertRaises(ValueError):
                native_build(text)

    def test_native_build_accepts_what_the_old_lint_wrongly_rejected(self) -> None:
        good = {
            "quoted name": NATIVE_BUILD.replace("name: Build", 'name: "Build"', 1),
            "non-ascii comment": NATIVE_BUILD.replace("jobs:\n", "# caf" + E_ACUTE + "\njobs:\n", 1),
            "non-ascii script": NATIVE_BUILD.replace("cargo build", "cargo build " + E_ACUTE, 1),
            "matrix flow list": NATIVE_BUILD.replace("    runs-on: ubuntu-24.04\n", "    strategy:\n      matrix:\n        os: [a, b]\n    runs-on: ubuntu-24.04\n"),
            "no name": NATIVE_BUILD.replace("name: Build\n", ""),
            "comment about uses": NATIVE_BUILD.replace("jobs:\n", "# every uses line is pinned; permissions stay read-only\njobs:\n", 1),
            "step name about permissions": NATIVE_BUILD.replace("      - run: cargo build", "      - name: Check permissions and uses\n        run: cargo build", 1),
            "script about permissions": NATIVE_BUILD.replace("      - run: cargo build --release --locked\n", "      - run: |\n          echo permissions uses\n"),
            "branches as a block list": NATIVE_BUILD.replace("    branches: [main]\n", "    branches:\n      - main\n"),
            "dispatch with a null body": NATIVE_BUILD.replace("  workflow_dispatch:\n", "  workflow_dispatch: {}\n"),
            "no trailing newline": NATIVE_BUILD.rstrip("\n"),
            "defaults and env": NATIVE_BUILD.replace("jobs:\n", "env:\n  A: b\ndefaults:\n  run:\n    shell: bash\njobs:\n", 1),
        }
        for name, text in good.items():
            with self.subTest(name):
                native_build(text)

    def test_native_build_scripts_may_use_shell_braces(self) -> None:
        native_build(NATIVE_BUILD.replace("      - run: cargo build --release --locked\n", '      - run: |\n          for f in out/*; do echo "${f}"; done\n          [ -d out ] && true\n'))

    def test_native_build_accepts_block_lists_folded_and_indented_scalars(self) -> None:
        native_build(NATIVE_BUILD.replace("    runs-on: ubuntu-24.04\n", "    strategy:\n      matrix:\n        os:\n          - ubuntu-24.04\n          - macos-15\n    runs-on: ubuntu-24.04\n")
                     .replace("      - run: cargo build --release --locked\n", "\n      # build\n      - run: >-\n          cargo build\n          --locked\n      - run: |2\n            x\n"))

    def test_native_build_is_selected_by_structure_not_by_word_count(self) -> None:
        text = NATIVE_BUILD.replace("      - run: cargo build --release --locked\n", "      - name: uses uses uses\n        run: echo permissions permissions\n")
        native_build(text)
        with self.assertRaisesRegex(ValueError, "build.yml: top-level permissions must be exactly `contents: read`"):
            native_build(text.replace("contents: read", "contents: write"))


NATIVE_BUILD = """name: Build
on:
  workflow_dispatch:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@""" + SHA1 + """
      - run: cargo build --release --locked
      - uses: actions/upload-artifact@""" + SHA2 + """
        with:
          name: release-files
          path: out/
"""

CI_WORKFLOW = """name: CI
on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
env:
  CARGO_TERM_COLOR: always
jobs:
  test:
    runs-on: ${{ matrix.os }}
    timeout-minutes: 10
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, macos-15]
    steps:
      - uses: actions/checkout@""" + SHA1 + """
        with:
          fetch-depth: 0
      - name: Build
        run: cargo build --locked
"""


if __name__ == "__main__":
    unittest.main()
