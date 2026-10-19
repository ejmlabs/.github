import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare


class SourceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
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
        self.git("add", "--all")
        self.git("commit", "--quiet", "--message", "source fixture")
        self.sha = self.git("rev-parse", "HEAD").decode().strip()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args], check=True, capture_output=True).stdout

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
