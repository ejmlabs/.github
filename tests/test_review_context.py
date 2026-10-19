import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import export_review_context as exporter


class ReviewContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.repository = self.root / "shared"
        self.repository.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.sources = {}
        for path in exporter.SOURCE_PATHS:
            source = self.repository / path
            source.parent.mkdir(parents=True, exist_ok=True)
            data = (path + "\r\n$Format:%H$\n").encode() + b"\x00\xff\n"
            source.write_bytes(data)
            self.sources[path] = data
        (self.repository / "scripts/prepare.py").chmod(0o755)
        # Archive attributes must not omit directories or substitute source bytes.
        (self.repository / ".gitattributes").write_text(".github export-ignore\nreview export-ignore\nscripts/*.py export-subst\n")
        (self.repository / "unrelated.txt").write_text("Do not export this file\n")
        self.old = self.commit("old source")
        self.changed = "scripts/governance.py"
        (self.repository / self.changed).write_bytes(b"new committed source\n")
        self.new = self.commit("new source")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repository), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
            check=True, capture_output=True,
        ).stdout

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "--quiet", "--message", message)
        return self.git("rev-parse", "HEAD").decode().strip()

    def test_cli_exports_only_exact_static_blobs_and_manifest(self):
        destination = self.root / "review-data"
        subprocess.run([
            sys.executable, exporter.__file__, "--repository", str(self.repository),
            "--old", self.old, "--new", self.new, "--destination", str(destination),
        ], check=True, capture_output=True)
        manifest = json.loads((destination / "manifest.json").read_text())
        self.assertEqual(manifest["repository"], "ejmlabs/.github")
        expected_paths = {"manifest.json"}
        for role, sha in (("old", self.old), ("new", self.new)):
            revision = manifest["revisions"][role]
            self.assertEqual(revision["commit"], sha)
            self.assertEqual(revision["tree"], self.git("rev-parse", sha + "^{tree}").decode().strip())
            self.assertEqual({item["path"] for item in revision["files"]}, set(exporter.SOURCE_PATHS))
            for item in revision["files"]:
                relative = sha + "/" + item["path"]
                expected_paths.add(relative)
                expected = b"new committed source\n" if role == "new" and item["path"] == self.changed else self.sources[item["path"]]
                self.assertEqual((destination / relative).read_bytes(), expected)
                self.assertEqual(item["size"], len(expected))
                self.assertEqual(item["sha256"], hashlib.sha256(expected).hexdigest())
                self.assertEqual(item["blob"], self.git("rev-parse", sha + ":" + item["path"]).decode().strip())
                self.assertEqual(item["mode"], "100755" if item["path"] == "scripts/prepare.py" else "100644")
                self.assertEqual((destination / relative).stat().st_mode & 0o111, 0)
        self.assertEqual({str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()}, expected_paths)
        self.assertLessEqual(sum(path.stat().st_size for path in destination.rglob("*") if path.is_file()), exporter.MAX_EXPORT_BYTES)

    def test_invalid_names_and_noncommit_object_ids_leave_no_output(self):
        self.git("tag", "--annotate", "--message", "fixture tag", "fixture")
        invalid = ["HEAD", self.old[:12], self.old.upper(), "0" * 40,
                   self.git("rev-parse", "fixture").decode().strip(),
                   self.git("rev-parse", self.old + "^{tree}").decode().strip()]
        for index, sha in enumerate(invalid):
            with self.subTest(sha=sha):
                destination = self.root / ("invalid-" + str(index))
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    exporter.export_context(self.repository, self.old, sha, destination)
                self.assertFalse(destination.exists())

    def test_missing_or_unsafe_entries_leave_no_output(self):
        for kind in ("missing", "symlink", "directory", "submodule"):
            with self.subTest(kind=kind):
                self.git("reset", "--hard", self.old)
                source = self.repository / self.changed
                source.unlink()
                if kind == "symlink":
                    source.symlink_to("prepare.py")
                elif kind == "directory":
                    source.mkdir()
                    (source / "nested").write_text("wrong type\n")
                if kind == "submodule":
                    self.git("update-index", "--add", "--cacheinfo", "160000," + self.old + "," + self.changed)
                    self.git("commit", "--quiet", "--message", "unsafe submodule")
                    sha = self.git("rev-parse", "HEAD").decode().strip()
                else:
                    sha = self.commit("unsafe " + kind)
                destination = self.root / ("unsafe-" + kind)
                with self.assertRaises(ValueError):
                    exporter.export_context(self.repository, self.old, sha, destination)
                self.assertFalse(destination.exists())

    def test_combined_limit_includes_manifest_before_destination_creation(self):
        valid = self.root / "valid"
        exporter.export_context(self.repository, self.old, self.new, valid)
        total = sum(path.stat().st_size for path in valid.rglob("*") if path.is_file())
        for limit in (1, total - 1):
            with self.subTest(limit=limit), patch.object(exporter, "MAX_EXPORT_BYTES", limit):
                destination = self.root / ("oversize-" + str(limit))
                with self.assertRaises(ValueError):
                    exporter.export_context(self.repository, self.old, self.new, destination)
                self.assertFalse(destination.exists())

    def test_existing_destinations_are_never_modified(self):
        file = self.root / "existing-file"
        file.write_bytes(b"keep file\n")
        directory = self.root / "existing-directory"
        directory.mkdir()
        (directory / "manifest.json").write_bytes(b"keep directory\n")
        link = self.root / "existing-link"
        link.symlink_to(directory, target_is_directory=True)
        for destination in (file, directory, link):
            with self.subTest(destination=destination):
                with self.assertRaises(FileExistsError):
                    exporter.export_context(self.repository, self.old, self.new, destination)
        self.assertEqual(file.read_bytes(), b"keep file\n")
        self.assertEqual((directory / "manifest.json").read_bytes(), b"keep directory\n")
        self.assertEqual(list(directory.iterdir()), [directory / "manifest.json"])
        self.assertTrue(link.is_symlink())

    def test_destination_ancestors_must_not_be_symlinks(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep").write_bytes(b"keep\n")
        ancestor = self.root / "linked-parent"
        ancestor.symlink_to(outside, target_is_directory=True)
        for destination in (ancestor / "export", ancestor / ".." / "export"):
            with self.subTest(destination=destination):
                with self.assertRaises((OSError, ValueError)):
                    exporter.export_context(self.repository, self.old, self.new, destination)
        self.assertEqual(list(outside.iterdir()), [outside / "keep"])
        self.assertEqual((outside / "keep").read_bytes(), b"keep\n")


if __name__ == "__main__":
    unittest.main()
