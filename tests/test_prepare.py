import io
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import zipfile
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare


class GitRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name)
        self.root = self.workspace / "product"
        self.root.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args], check=True, capture_output=True).stdout

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "--message", "source fixture")
        return self.git("rev-parse", "HEAD").decode().strip()


class SourceArchiveTests(GitRepositoryTests):
    def setUp(self):
        super().setUp()
        (self.root / "hidden").mkdir()
        (self.root / "hidden/nested.txt").write_bytes(b"ignored directory source\n")
        (self.root / "LICENSE").write_bytes(b"ignored license\n")
        (self.root / "substituted.txt").write_bytes(b"$Format:%H$\n")
        (self.root / "script.sh").write_bytes(b"#!/bin/sh\nexit 99\n")
        (self.root / "script.sh").chmod(0o755)
        (self.root / "link").symlink_to("LICENSE")
        (self.root / ".github/workflows").mkdir(parents=True)
        self.workflow = b"name: exact workflow\n# $Format:%H$\n"
        (self.root / ".github/workflows/pr.yml").write_bytes(self.workflow)
        (self.root / ".gitattributes").write_text("hidden export-ignore\nLICENSE export-ignore\nsubstituted.txt export-subst\n.github export-ignore\n.github/workflows/*.yml export-subst\n")
        self.sha = self.commit()

    def test_real_git_exports_ignored_and_substituted_blobs_exactly(self):
        ordinary = self.git("archive", "--format=tar", "--prefix=product/", self.sha)
        with tarfile.open(fileobj=io.BytesIO(ordinary)) as archive:
            self.assertNotIn("product/LICENSE", archive.getnames())
            self.assertNotIn("product/hidden/nested.txt", archive.getnames())
            self.assertNotIn("product/.github/workflows/pr.yml", archive.getnames())
            self.assertEqual(archive.extractfile("product/substituted.txt").read(), (self.sha + "\n").encode())
        for format_ in ("tar", "tar.gz", "zip"):
            with self.subTest(format=format_):
                data = prepare.source_archive(self.root, self.sha, "product/", format_)
                if format_ == "zip":
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        self.assertEqual(archive.read("product/LICENSE"), b"ignored license\n")
                        self.assertEqual(archive.read("product/hidden/nested.txt"), b"ignored directory source\n")
                        self.assertEqual(archive.read("product/substituted.txt"), b"$Format:%H$\n")
                        self.assertEqual(archive.read("product/.github/workflows/pr.yml"), self.workflow)
                        self.assertEqual(archive.read("product/link"), b"LICENSE")
                else:
                    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                        self.assertEqual(archive.extractfile("product/LICENSE").read(), b"ignored license\n")
                        self.assertEqual(archive.extractfile("product/hidden/nested.txt").read(), b"ignored directory source\n")
                        self.assertEqual(archive.extractfile("product/substituted.txt").read(), b"$Format:%H$\n")
                        self.assertEqual(archive.extractfile("product/.github/workflows/pr.yml").read(), self.workflow)
                        self.assertTrue(archive.getmember("product/script.sh").mode & 0o111)
                        self.assertTrue(archive.getmember("product/link").issym())
                        self.assertEqual(archive.getmember("product/link").linkname, "LICENSE")
        self.assertFalse((self.root / ".git/info/attributes").exists())

    def test_external_attributes_cannot_omit_or_substitute_checked_source(self):
        external = self.root / ".git/external-attributes"
        external.write_text("* export-ignore export-subst\n")
        self.git("config", "core.attributesFile", str(external))
        data = prepare.source_archive(self.root, self.sha, "product", "tar")
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            self.assertEqual(archive.extractfile("product/substituted.txt").read(), b"$Format:%H$\n")
            self.assertEqual(archive.extractfile("product/.github/workflows/pr.yml").read(), self.workflow)

    def test_existing_git_attributes_are_restored_even_when_archive_fails(self):
        attributes = self.root / ".git/info/attributes"
        original = b"*.txt export-ignore\n"
        attributes.write_bytes(original)
        prepare.source_archive(self.root, self.sha, "product", "tar")
        self.assertEqual(attributes.read_bytes(), original)
        original_run = prepare.run

        def fail_archive(*args):
            if "archive" in args:
                raise subprocess.CalledProcessError(1, args)
            return original_run(*args)

        with patch.object(prepare, "run", side_effect=fail_archive):
            with self.assertRaises(subprocess.CalledProcessError):
                prepare.source_archive(self.root, self.sha, "product", "tar")
        self.assertEqual(attributes.read_bytes(), original)

    def test_source_limits_and_invalid_revisions_fail_closed(self):
        for limit in ("MAX_SOURCE_FILES", "MAX_SOURCE_BYTES", "MAX_TREE_BYTES"):
            with self.subTest(limit=limit), patch.object(prepare, limit, 1):
                with self.assertRaises(ValueError):
                    prepare.source_archive(self.root, self.sha, "product", "tar")
        for sha, prefix, format_ in (("HEAD", "product", "tar"), (self.sha, "../product", "tar"), (self.sha, "product", "custom")):
            with self.assertRaises(ValueError):
                prepare.source_archive(self.root, sha, prefix, format_)


class HarnessPinTests(GitRepositoryTests):
    PIN = "b" * 40

    def setUp(self):
        super().setUp()
        (self.root / ".github").mkdir()
        self.pin = self.root / ".github/harness-revision"
        self.pin.write_text(self.PIN + "\n")
        self.base = self.commit()

    def test_pin_comes_from_the_admitted_git_blob_not_the_worktree(self):
        candidate = "c" * 40
        self.pin.write_text(candidate)
        head = self.commit()
        self.pin.unlink()
        self.pin.symlink_to("/nonexistent/worktree-pin")
        self.assertEqual(prepare.harness_pin(self.root, self.base), self.PIN)
        self.assertEqual(prepare.harness_pin(self.root, head), candidate)
        with self.assertRaises(ValueError):
            prepare.harness_pin(self.root, "HEAD")

    def test_missing_nonregular_or_malformed_committed_pin_fails_closed(self):
        for content in (b"", b"a" * 39, b"A" * 40, b"a" * 40 + b"\r\n", b" " + b"a" * 40, b"a" * 40 + b"\n\n", b"\xff" * 40, b"a" * 4097):
            with self.subTest(content=content[:42]):
                self.pin.write_bytes(content)
                revision = self.commit()
                with self.assertRaises((ValueError, UnicodeDecodeError)):
                    prepare.harness_pin(self.root, revision)
        self.pin.unlink()
        revision = self.commit()
        with self.assertRaises(ValueError):
            prepare.harness_pin(self.root, revision)
        self.pin.symlink_to("../outside-pin")
        (self.root / "outside-pin").write_text(self.PIN)
        revision = self.commit()
        with self.assertRaises(ValueError):
            prepare.harness_pin(self.root, revision)

    def test_symlinked_parent_does_not_supply_a_pin(self):
        self.pin.unlink()
        self.pin.parent.rmdir()
        (self.root / "outside").mkdir()
        (self.root / "outside/harness-revision").write_text(self.PIN)
        (self.root / ".github").symlink_to("outside", target_is_directory=True)
        revision = self.commit()
        with self.assertRaises(ValueError):
            prepare.harness_pin(self.root, revision)


class HarnessSelectionTests(unittest.TestCase):
    HEAD, BASE, PIN, MAIN, TREE = (character * 40 for character in "abcde")

    def proof(self):
        branch = {"name": "main", "protected": True, "commit": {"sha": self.MAIN}}
        comparison = {"status": "ahead", "behind_by": 0, "ahead_by": 1,
                      "base_commit": {"sha": self.PIN, "commit": {"tree": {"sha": self.TREE}}},
                      "merge_base_commit": {"sha": self.PIN}}
        return branch, comparison

    def test_cli_pin_uses_fixed_repository_and_exact_protected_main_comparison(self):
        branch, comparison = self.proof()
        for identical in (False, True):
            if identical:
                branch["commit"]["sha"] = self.PIN
                comparison["status"] = "identical"
                comparison["ahead_by"] = 0
            with self.subTest(identical=identical), patch.object(prepare, "harness_pin", return_value=self.PIN) as pin, patch.object(prepare, "harness_json", side_effect=[branch, comparison]) as api:
                self.assertEqual(prepare.select_harness("ejm-cli", self.HEAD, self.BASE, "harness-read"), {
                    "repository": "ejmlabs/ejm-harness", "revision": self.PIN, "tree": self.TREE,
                    "protected_main": branch["commit"]["sha"], "pin_source": "head", "pin_revision": self.HEAD,
                })
                pin.assert_called_once_with("product", self.HEAD)
                self.assertEqual(api.call_args_list, [
                    unittest.mock.call("branches/main", "harness-read"),
                    unittest.mock.call("compare/" + self.PIN + "..." + branch["commit"]["sha"] + "?per_page=1", "harness-read"),
                ])

    def test_missing_malformed_or_unprotected_main_fails_before_comparison(self):
        for name, branch in (
            ("missing", {}),
            ("other branch", {"name": "other", "protected": True, "commit": {"sha": self.MAIN}}),
            ("unprotected", {"name": "main", "protected": False, "commit": {"sha": self.MAIN}}),
            ("truthy protection", {"name": "main", "protected": "true", "commit": {"sha": self.MAIN}}),
            ("malformed commit", {"name": "main", "protected": True, "commit": {"sha": "main"}}),
            ("missing commit", {"name": "main", "protected": True}),
        ):
            with self.subTest(case=name), patch.object(prepare, "harness_pin", return_value=self.PIN), patch.object(prepare, "harness_json", return_value=branch) as api:
                with self.assertRaises(ValueError):
                    prepare.select_harness("ejm-cli", self.HEAD, self.BASE, "harness-read")
                api.assert_called_once_with("branches/main", "harness-read")

    def test_diverged_nonancestor_or_malformed_comparisons_fail_closed(self):
        for name, changes in (
            ("missing", lambda value: value.clear()),
            ("diverged", lambda value: value.update(status="diverged")),
            ("descendant", lambda value: value.update(status="behind", behind_by=1)),
            ("wrong base", lambda value: value["base_commit"].update(sha=self.BASE)),
            ("not ancestor", lambda value: value["merge_base_commit"].update(sha=self.BASE)),
            ("behind", lambda value: value.update(behind_by=1)),
            ("malformed distance", lambda value: value.update(behind_by="0")),
            ("boolean distance", lambda value: value.update(behind_by=False)),
            ("incoherent distance", lambda value: value.update(ahead_by=0)),
            ("missing tree", lambda value: value["base_commit"]["commit"].clear()),
            ("malformed tree", lambda value: value["base_commit"]["commit"]["tree"].update(sha="HEAD")),
        ):
            branch, comparison = self.proof()
            changes(comparison)
            with self.subTest(case=name), patch.object(prepare, "harness_pin", return_value=self.PIN), patch.object(prepare, "harness_json", side_effect=[branch, comparison]):
                with self.assertRaises(ValueError):
                    prepare.select_harness("ejm-cli", self.HEAD, self.BASE, "harness-read")

    def test_inaccessible_official_api_does_not_fall_back_to_a_base_pin(self):
        branch, _ = self.proof()
        for responses in ([urllib.error.URLError("unavailable")], [branch, urllib.error.URLError("unavailable")]):
            with self.subTest(after_branch=len(responses) == 2), patch.object(prepare, "harness_pin", return_value=self.PIN) as pin, patch.object(prepare, "harness_json", side_effect=responses):
                with self.assertRaises(urllib.error.URLError):
                    prepare.select_harness("ejm-cli", self.HEAD, self.BASE, "harness-read")
                pin.assert_called_once_with("product", self.HEAD)

    def test_ide_keeps_the_base_pin_and_other_profiles_do_not_select_a_harness(self):
        with tempfile.TemporaryDirectory() as directory, chdir(directory), patch.object(prepare, "harness_json") as api:
            Path("base/.github").mkdir(parents=True)
            Path("product/.github").mkdir(parents=True)
            base_pin = Path("base/.github/harness-revision")
            base_pin.write_text(self.PIN + "\n")
            Path("product/.github/harness-revision").write_text(self.MAIN + "\n")
            self.assertEqual(prepare.select_harness("ejm-ide", self.HEAD, self.BASE, "unused"), {
                "repository": "ejmlabs/ejm-harness", "revision": self.PIN,
                "pin_source": "base", "pin_revision": self.BASE,
            })
            base_pin.unlink()
            base_pin.symlink_to("../../product/.github/harness-revision")
            with self.assertRaises(ValueError):
                prepare.select_harness("ejm-ide", self.HEAD, self.BASE, "unused")
            for profile in ("ejm-harness", "ejmlabs", "ejm-ui"):
                self.assertIsNone(prepare.select_harness(profile, self.HEAD, self.BASE, "unused"))
            api.assert_not_called()


class HarnessMetadataTests(unittest.TestCase):
    URL = "https://api.github.com/repos/ejmlabs/ejm-harness/branches/main"

    def test_metadata_request_is_bounded_get_only_and_cannot_redirect_credentials(self):
        with patch.object(prepare.urllib.request, "build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.geturl.return_value = self.URL
            response.read.return_value = b'{"protected":true}'
            self.assertEqual(prepare.harness_json("branches/main", "fixture"), {"protected": True})
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, self.URL)
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("Authorization"), "Bearer fixture")
            self.assertEqual(opener.return_value.open.call_args.kwargs, {"timeout": 30})
            response.read.assert_called_once_with(prepare.MAX_HARNESS_METADATA_BYTES + 1)
            handler = opener.call_args.args[0]
            self.assertIsInstance(handler, prepare.urllib.request.HTTPRedirectHandler)
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "redirect", {}, "https://other.invalid/")
        for path in ("https://other.invalid/", "../other/repository", "branches/other", "compare/main...HEAD?per_page=1"):
            with self.subTest(path=path), patch.object(prepare.urllib.request, "build_opener") as opener:
                with self.assertRaises(ValueError):
                    prepare.harness_json(path, "fixture")
                opener.assert_not_called()

    def test_inaccessible_redirected_or_malformed_metadata_fails_closed(self):
        cases = ((200, self.URL, b""), (200, self.URL, b"x" * 65),
                 (200, self.URL, b"[]"), (200, self.URL, b"null"),
                 (200, self.URL, b"{"), (200, self.URL, b"\xff"),
                 (302, self.URL, b"{}"), (200, "https://other.invalid/", b"{}"))
        for status, url, body in cases:
            with self.subTest(status=status, url=url, body=body[:10]), patch.object(prepare, "MAX_HARNESS_METADATA_BYTES", 64), patch.object(prepare.urllib.request, "build_opener") as opener:
                response = opener.return_value.open.return_value.__enter__.return_value
                response.status, response.geturl.return_value, response.read.return_value = status, url, body
                with self.assertRaises(ValueError):
                    prepare.harness_json("branches/main", "fixture")
        with patch.object(prepare.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.URLError("unavailable")
            with self.assertRaises(ValueError):
                prepare.harness_json("branches/main", "fixture")


class HarnessArchiveTests(GitRepositoryTests):
    def setUp(self):
        super().setUp()
        (self.root / "source.txt").write_text("reviewed harness source\n")
        self.revision = self.commit()
        self.tree = self.git("rev-parse", "HEAD^{tree}").decode().strip()
        subprocess.run(["git", "clone", "--quiet", str(self.root), str(self.workspace / "harness")], check=True, capture_output=True)
        (self.root / ".github").mkdir()
        (self.root / ".github/harness-revision").write_text(self.revision + "\n")
        self.head = self.commit()
        self.selection = {"repository": "ejmlabs/ejm-harness", "revision": self.revision,
                          "tree": self.tree, "protected_main": self.revision,
                          "pin_source": "head", "pin_revision": self.head}
        self.file = self.workspace / "harness-selection.json"
        self.file.write_text(json.dumps(self.selection))

    def test_preparation_binds_pin_checkout_archive_and_context_to_one_source(self):
        env = {"PR_HEAD": self.head, "PR_BASE": self.revision, "GITHUB_REPOSITORY": "ejmlabs/ejm-cli", "PR_NUMBER": "7", "GH_TOKEN": "product-read"}
        diff = b"diff --git a/pin b/pin\n"
        with chdir(self.workspace), patch.dict(os.environ, env), patch.object(prepare.sys, "argv", ["prepare.py"]), patch.object(prepare, "review_diff", return_value=diff):
            self.assertEqual(prepare.load_harness_selection("ejm-cli", self.head, self.revision), self.selection)
            prepare.main()
        context = json.loads((self.workspace / "prepared/context.json").read_text())
        archive_bytes = (self.workspace / "prepared/harness.tar").read_bytes()
        self.assertEqual(context, {"repository": "ejmlabs/ejm-cli", "pr": 7, "head": self.head, "base": self.revision,
                                   "harness": {**self.selection, "archive_sha256": hashlib.sha256(archive_bytes).hexdigest()}})
        self.assertEqual((self.workspace / "prepared/change.patch").read_bytes(), diff)
        with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
            self.assertEqual(archive.extractfile("ejm-harness/source.txt").read(), b"reviewed harness source\n")
            self.assertNotIn("ejm-harness/.github/harness-revision", archive.getnames())
        with tarfile.open(self.workspace / "prepared/product.tar") as archive:
            self.assertEqual(archive.extractfile("product/.github/harness-revision").read(), (self.revision + "\n").encode())

    def test_changed_checkout_head_or_tree_is_rejected_before_export(self):
        for head, tree in ((self.head, self.tree), (self.revision, "e" * 40)):
            selection = {**self.selection, "tree": tree}
            subprocess.run(["git", "-C", str(self.workspace / "harness"), "fetch", "--quiet", str(self.root), head], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(self.workspace / "harness"), "checkout", "--quiet", "--detach", head], check=True, capture_output=True)
            with self.subTest(head=head, tree=tree), chdir(self.workspace), patch.object(prepare, "source_archive") as archive:
                with self.assertRaises(ValueError):
                    prepare.archive_harness(selection)
                archive.assert_not_called()

    def test_selection_cannot_change_admitted_pin_identity_or_exceed_its_bound(self):
        for field, value in (("repository", "other/harness"), ("revision", "f" * 40), ("pin_source", "base"),
                             ("pin_revision", self.revision), ("tree", "main"), ("protected_main", "main")):
            self.file.write_text(json.dumps({**self.selection, field: value}))
            with self.subTest(field=field), chdir(self.workspace):
                with self.assertRaises(ValueError):
                    prepare.load_harness_selection("ejm-cli", self.head, self.revision)
        for body in (b"x" * (prepare.MAX_HARNESS_SELECTION_BYTES + 1), b"null", b"{}"):
            self.file.write_bytes(body)
            with self.subTest(body=body[:10]), chdir(self.workspace):
                with self.assertRaises(ValueError):
                    prepare.load_harness_selection("ejm-cli", self.head, self.revision)
        self.file.unlink()
        self.file.symlink_to("product/.github/harness-revision")
        with chdir(self.workspace), self.assertRaises(ValueError):
            prepare.load_harness_selection("ejm-cli", self.head, self.revision)

    def test_selector_emits_checkout_revision_and_rejects_repository_profile_mismatch(self):
        self.file.unlink()
        output = self.workspace / "outputs"
        env = {"PR_HEAD": self.head, "PR_BASE": self.revision, "GITHUB_REPOSITORY": "ejmlabs/ejm-cli",
               "PROFILE": "ejm-cli", "HARNESS_READ_TOKEN": "harness-read", "GITHUB_OUTPUT": str(output)}
        with chdir(self.workspace), patch.dict(os.environ, env), patch.object(prepare.sys, "argv", ["prepare.py", "select-harness"]), patch.object(prepare, "select_harness", return_value=self.selection) as select:
            prepare.main()
            select.assert_called_once_with("ejm-cli", self.head, self.revision, "harness-read")
            self.assertEqual(json.loads(self.file.read_text()), self.selection)
            self.assertEqual(output.read_text(), "revision=" + self.revision + "\n")
            with patch.dict(os.environ, {"PROFILE": "ejm-ide"}):
                with self.assertRaises(ValueError):
                    prepare.main()
            self.assertEqual(select.call_count, 1)


class ReviewDiffTests(unittest.TestCase):
    BASE, HEAD = "a" * 40, "b" * 40

    def test_comparison_is_bound_to_both_immutable_revisions(self):
        expected = "https://api.github.com/repos/ejmlabs/ejm-cli/compare/" + self.BASE + "..." + self.HEAD
        self.assertEqual(prepare.compare_url("ejmlabs/ejm-cli", self.BASE, self.HEAD), expected)
        for base, head in (("main", self.HEAD), (self.BASE, "HEAD"), (self.BASE, "B" * 40)):
            with self.assertRaises(ValueError): prepare.compare_url("ejmlabs/ejm-cli", base, head)

    def test_diff_bytes_and_file_count_are_bounded(self):
        valid = b"diff --git a/file b/file\n--- a/file\n+++ b/file\n"
        for content, ok in ((valid, True), (b"", False), (b"x" * (prepare.MAX_DIFF_BYTES + 1), False), (valid * (prepare.MAX_DIFF_FILES + 1), False)):
            with self.subTest(length=len(content)), patch.object(prepare.urllib.request, "urlopen") as request:
                request.return_value.__enter__.return_value.read.return_value = content
                if ok:
                    self.assertEqual(prepare.review_diff("ejmlabs/ejm-cli", self.BASE, self.HEAD, "fixture"), valid)
                    self.assertEqual(request.call_args.args[0].full_url, prepare.compare_url("ejmlabs/ejm-cli", self.BASE, self.HEAD))
                else:
                    with self.assertRaises(ValueError): prepare.review_diff("ejmlabs/ejm-cli", self.BASE, self.HEAD, "fixture")
                request.return_value.__enter__.return_value.read.assert_called_once_with(prepare.MAX_DIFF_BYTES + 1)


if __name__ == "__main__": unittest.main()
