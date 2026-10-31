import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import extract

Member = tuple[str, bytes, dict[str, object]]


def entry(name: str, content: bytes = b"", /, **attributes: object) -> Member:
    return name, content, attributes


def archive(*members: Member) -> bytes:
    """Build a tar with the given members, setting each TarInfo attribute exactly as given."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, content, attributes in members:
            info = tarfile.TarInfo(name)
            info.mtime = 0
            info.mode = 0o644
            info.size = len(content)
            for key, value in attributes.items():
                setattr(info, key, value)
            if info.type != tarfile.REGTYPE:
                info.size = 0
            tar.addfile(info, io.BytesIO(content) if info.size else None)
    return buffer.getvalue()


def directory(name: str, **attributes: object) -> Member:
    return entry(name, type=tarfile.DIRTYPE, mode=0o755, **attributes)


def symlink(name: str, target: str) -> Member:
    return entry(name, type=tarfile.SYMTYPE, linkname=target, mode=0o777)


class Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.prepared = self.root / "prepared"
        self.prepared.mkdir()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()

    def write(self, name: str, *members: Member) -> None:
        (self.prepared / name).write_bytes(archive(*members))

    def extract(self) -> None:
        extract.extract(self.prepared, self.workspace)


class ExtractionTests(Workspace):
    def test_extracts_files_directories_and_inside_symlinks_from_every_archive(self) -> None:
        self.write("product.tar",
                   directory("product/"), directory("product/.agents/"), directory("product/.agents/skills/"), directory("product/.claude/"), directory("product/.claude/skills/"),
                   entry("product/run.sh", b"#!/bin/sh\n", mode=0o755), entry("product/.agents/skills/one", b"skill"),
                   symlink("product/.claude/skills/one", "../../.agents/skills/one"), symlink("product/alias", "run.sh"))
        self.write("harness.tar", directory("ejm-harness/"), entry("ejm-harness/source.txt", b"harness"))
        self.write("ui.tar", entry("ejm-ui/source.txt", b"ui"))
        self.extract()
        self.assertEqual((self.workspace / "product/run.sh").read_bytes(), b"#!/bin/sh\n")
        self.assertTrue(os.access(self.workspace / "product/run.sh", os.X_OK))
        self.assertEqual((self.workspace / "product/.claude/skills/one").read_bytes(), b"skill")
        self.assertEqual((self.workspace / "product/.claude/skills/one").resolve(), (self.workspace / "product/.agents/skills/one").resolve())
        self.assertEqual((self.workspace / "product/alias").readlink(), Path("run.sh"))
        self.assertEqual((self.workspace / "ejm-harness/source.txt").read_bytes(), b"harness")
        self.assertEqual((self.workspace / "ejm-ui/source.txt").read_bytes(), b"ui")

    def test_every_extracted_file_and_directory_is_newer_than_a_restored_build(self) -> None:
        # Git exports carry the commit time. A cached build is older than extraction and newer than that, so Cargo would skip it.
        self.write("product.tar", directory("product/", mtime=0), directory("product/src/", mtime=0), entry("product/src/lib.rs", b"fn main() {}", mtime=0))
        before = time.time() - 1
        self.extract()
        for path in ("product", "product/src", "product/src/lib.rs"):
            with self.subTest(path=path):
                self.assertGreaterEqual((self.workspace / path).stat().st_mtime, before)
                self.assertLessEqual((self.workspace / path).stat().st_mtime, time.time() + 1)

    def test_the_data_filter_still_strips_special_mode_bits(self) -> None:
        self.write("product.tar", entry("product/setuid", b"x", mode=0o6777), entry("product/open", b"x", mode=0o666))
        self.extract()
        for name in ("setuid", "open"):
            mode = (self.workspace / "product" / name).stat().st_mode
            self.assertFalse(mode & (stat.S_ISUID | stat.S_ISGID | stat.S_IWGRP | stat.S_IWOTH), name)

    def test_fresh_filter_applies_the_data_filter_then_the_given_time(self) -> None:
        info = tarfile.TarInfo("product/file")
        info.mode, info.mtime, info.uid, info.gid = 0o4755, 5, 1000, 1000
        result = extract.fresh(123.0)(info, str(self.workspace))
        self.assertEqual((result.mtime, result.mode & stat.S_ISUID, result.uid, result.gid), (123.0, 0, None, None))
        outside = tarfile.TarInfo("product/../../escape")
        with self.assertRaises(tarfile.FilterError):
            extract.fresh(123.0)(outside, str(self.workspace))

    def test_symlink_targets_that_stay_inside_the_prefix_are_accepted(self) -> None:
        for target in ("../a", "..", ".", "a", "./a", "a/../b", "../dir/a"):
            with self.subTest(target=target):
                shutil.rmtree(self.workspace)
                self.workspace.mkdir()
                self.write("product.tar", directory("product/"), directory("product/dir/"), entry("product/a", b"a"), symlink("product/dir/link", target))
                self.extract()
                self.assertTrue((self.workspace / "product/dir/link").is_symlink())

    def test_prepared_directory_must_hold_a_product_archive_and_only_known_archives(self) -> None:
        with self.assertRaises(ValueError):
            self.extract()
        self.write("product.tar", entry("product/a", b"a"))
        self.write("other.tar", entry("other/a", b"a"))
        with self.assertRaises(ValueError):
            self.extract()
        (self.prepared / "other.tar").unlink()
        (self.prepared / "note.txt").write_text("not an archive")
        with self.assertRaises(ValueError):
            self.extract()
        self.assertEqual(list(self.workspace.iterdir()), [])
        (self.prepared / "note.txt").unlink()
        (self.prepared / "product.tar").rename(self.root / "elsewhere.tar")
        (self.prepared / "product.tar").symlink_to(self.root / "elsewhere.tar")
        with self.assertRaises(ValueError):
            self.extract()
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_compressed_archives_are_not_accepted(self) -> None:
        with tarfile.open(self.prepared / "product.tar", "w:gz") as tar:
            info = tarfile.TarInfo("product/a")
            tar.addfile(info)
        with self.assertRaises(tarfile.TarError):
            self.extract()
        self.assertEqual(list(self.workspace.iterdir()), [])


class RejectionTests(Workspace):
    def rejected(self, *members: Member, name: str = "product.tar") -> None:
        shutil.rmtree(self.workspace)  # a case that wrongly succeeded must not fail the cases after it
        self.workspace.mkdir()
        self.write(name, *members)
        with self.assertRaises(ValueError):
            self.extract()
        # Validation finishes before anything is written, so a rejected archive leaves no file behind.
        self.assertEqual(list(self.workspace.iterdir()), [])
        self.assertFalse((self.root / "escape").exists())

    def test_names_outside_the_archive_prefix_are_rejected(self) -> None:
        for name in ("/etc/passwd", "/product/a", "../escape", "product/../../escape", "product/../escape", "other/a", "productx/a", "ejm-harness/a",
                     "product//a", "product/./a", "product\\a", "product/..\\..\\escape", "", "/"):
            with self.subTest(name=name):
                self.rejected(entry("product/ok", b"ok"), entry(name, b"x"))

    def test_the_prefix_must_match_the_archive_it_arrives_in(self) -> None:
        self.rejected(entry("ejm-ui/a", b"a"), name="product.tar")
        self.rejected(entry("product/a", b"a"), name="harness.tar")
        self.rejected(entry("ejm-harness/a", b"a"), name="ui.tar")

    def test_links_devices_and_other_special_members_are_rejected(self) -> None:
        for kind in (tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE, tarfile.CONTTYPE):
            with self.subTest(kind=kind):
                self.rejected(entry("product/a", b"a"), entry("product/special", type=kind, linkname="product/a"))

    def test_duplicates_and_a_non_directory_prefix_are_rejected(self) -> None:
        self.rejected(entry("product/a", b"a"), entry("product/a", b"b"))
        self.rejected(entry("product/a", b"a"), symlink("product/a", "b"))
        self.rejected(entry("product", b"file"), entry("product/a", b"a"))
        self.rejected(symlink("product", "elsewhere"))

    def test_symlinks_must_stay_inside_the_prefix(self) -> None:
        # The link is product/dir/link, so one `..` reaches product itself and two reach its parent.
        for target in ("/etc/passwd", "", "../../escape", "../..", "../../product/a", "a/../../../escape", "C:\\escape", "dir\\..\\..\\escape", "/product/a"):
            with self.subTest(target=target):
                self.rejected(directory("product/"), directory("product/dir/"), entry("product/a", b"a"), symlink("product/dir/link", target))

    def test_a_symlink_chain_cannot_walk_out_through_an_earlier_link(self) -> None:
        # Each link looks inside the prefix on its own: `dir/up` is `product`, and `escape` is `product/dir`.
        # Resolved through `up`, `escape` reaches the parent of `product`, so a link on the path is never allowed.
        self.rejected(directory("product/"), directory("product/dir/"), symlink("product/dir/up", ".."), symlink("product/escape", "dir/up/.."))
        self.rejected(symlink("product/escape", "dir/up/.."), symlink("product/dir/up", ".."), directory("product/dir/"))
        self.rejected(directory("product/dir/"), symlink("product/dir/up", ".."), symlink("product/escape", "dir/up/../"))

    def test_nothing_may_be_extracted_below_a_symlink(self) -> None:
        self.rejected(symlink("product/link", "."), entry("product/link/file", b"x"))
        self.rejected(entry("product/link/file", b"x"), directory("product/other/"), symlink("product/link", "other"))
        self.rejected(directory("product/a/"), symlink("product/a/link", ".."), entry("product/a/link/x/y", b"x"))

    def test_error_messages_cannot_carry_control_characters(self) -> None:
        for hostile in ("product/\n::error::forged/..", "product/\x1b[31m/..", "product/\n::error::forged\\x"):
            with self.subTest(name=hostile):
                self.write("product.tar", entry("product/ok", b"ok"), entry(hostile, b"x"))
                with self.assertRaises(ValueError) as caught:
                    self.extract()
                self.assertTrue(str(caught.exception).isprintable())
                self.assertLess(len(str(caught.exception)), 300)

    def test_a_second_bad_archive_does_not_leave_a_half_validated_tree_for_that_archive(self) -> None:
        self.write("product.tar", entry("product/a", b"a"))
        self.write("harness.tar", entry("ejm-harness/ok", b"ok"), entry("ejm-harness/../escape", b"x"))
        with self.assertRaises(ValueError):
            self.extract()
        self.assertFalse((self.workspace / "ejm-harness").exists())
        self.assertFalse((self.root / "escape").exists())


class ScriptTests(Workspace):
    def test_the_script_extracts_prepared_sources_into_the_working_directory_in_isolated_mode(self) -> None:
        self.write("product.tar", directory("product/"), entry("product/file.txt", b"data", mtime=0))
        # A module in the working directory must not be importable by the trusted script.
        (self.root / "tarfile.py").write_text("raise SystemExit('planted module ran')\n")
        result = subprocess.run([sys.executable, "-I", extract.__file__], cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "product/file.txt").read_bytes(), b"data")
        self.assertGreater((self.root / "product/file.txt").stat().st_mtime, time.time() - 60)

    def test_the_script_fails_without_extracting_a_hostile_archive(self) -> None:
        self.write("product.tar", entry("product/ok", b"ok"), entry("product/../../escape", b"x"))
        result = subprocess.run([sys.executable, "-I", extract.__file__], cwd=self.root, capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsafe archive member", result.stderr)
        self.assertFalse((self.root / "product").exists())
        self.assertFalse((self.root.parent / "escape").exists())


if __name__ == "__main__":
    unittest.main()
