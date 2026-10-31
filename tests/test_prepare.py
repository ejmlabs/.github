import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import zipfile
from collections.abc import Callable
from contextlib import chdir
from email.message import Message
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare


def member(archive: tarfile.TarFile, name: str) -> bytes:
    extracted = archive.extractfile(name)
    assert extracted is not None
    return extracted.read()


class GitRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name)
        self.root = self.workspace / "product"
        self.root.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")

    def git(self, *args: str, stdin: bytes | None = None) -> bytes:
        return subprocess.run(["git", "-C", str(self.root), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, input=stdin).stdout

    def commit(self) -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "--message", "source fixture")
        return self.git("rev-parse", "HEAD").decode().strip()


class SourceArchiveTests(GitRepositoryTests):
    def setUp(self) -> None:
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

    def test_real_git_exports_ignored_and_substituted_blobs_exactly(self) -> None:
        ordinary = self.git("archive", "--format=tar", "--prefix=product/", self.sha)
        with tarfile.open(fileobj=io.BytesIO(ordinary)) as archive:
            self.assertNotIn("product/LICENSE", archive.getnames())
            self.assertNotIn("product/hidden/nested.txt", archive.getnames())
            self.assertNotIn("product/.github/workflows/pr.yml", archive.getnames())
            self.assertEqual(member(archive, "product/substituted.txt"), (self.sha + "\n").encode())
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
                        self.assertEqual(member(archive, "product/LICENSE"), b"ignored license\n")
                        self.assertEqual(member(archive, "product/hidden/nested.txt"), b"ignored directory source\n")
                        self.assertEqual(member(archive, "product/substituted.txt"), b"$Format:%H$\n")
                        self.assertEqual(member(archive, "product/.github/workflows/pr.yml"), self.workflow)
                        self.assertTrue(archive.getmember("product/script.sh").mode & 0o111)
                        self.assertTrue(archive.getmember("product/link").issym())
                        self.assertEqual(archive.getmember("product/link").linkname, "LICENSE")
        self.assertFalse((self.root / ".git/info/attributes").exists())

    def test_external_attributes_cannot_omit_or_substitute_checked_source(self) -> None:
        external = self.root / ".git/external-attributes"
        external.write_text("* export-ignore export-subst\n")
        self.git("config", "core.attributesFile", str(external))
        data = prepare.source_archive(self.root, self.sha, "product", "tar")
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            self.assertEqual(member(archive, "product/substituted.txt"), b"$Format:%H$\n")
            self.assertEqual(member(archive, "product/.github/workflows/pr.yml"), self.workflow)

    def test_existing_git_attributes_are_restored_even_when_archive_fails(self) -> None:
        attributes = self.root / ".git/info/attributes"
        original = b"*.txt export-ignore\n"
        attributes.write_bytes(original)
        prepare.source_archive(self.root, self.sha, "product", "tar")
        self.assertEqual(attributes.read_bytes(), original)
        original_run = prepare.run

        def fail_archive(*args: str) -> Any:
            if "archive" in args:
                raise subprocess.CalledProcessError(1, args)
            return original_run(*args)

        with patch.object(prepare, "run", side_effect=fail_archive), self.assertRaises(subprocess.CalledProcessError):
            prepare.source_archive(self.root, self.sha, "product", "tar")
        self.assertEqual(attributes.read_bytes(), original)

    def test_failed_commands_report_a_bounded_single_line_stderr(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            prepare.source_archive(self.root, "0" * 40, "product", "tar")
        # Git words its message differently by version and locale; any text after the status is its stderr.
        self.assertRegex(str(caught.exception), r"^git failed with status 128: \S")
        self.assertIsInstance(caught.exception.__cause__, subprocess.CalledProcessError)
        script = "import sys; sys.stderr.write('first\\n::error::forged\\x1b[31m' + 'x' * 100); sys.exit(3)"
        with patch.object(prepare, "MAX_COMMAND_ERROR_BYTES", 40), self.assertRaises(RuntimeError) as caught:
            prepare.run(sys.executable, "-c", script)
        message = str(caught.exception)
        self.assertTrue(message.endswith(": first ::error::forged [31m" + "x" * 14), message)
        self.assertNotIn("\n", message)
        self.assertNotIn("\x1b", message)

    def test_gitlinks_and_unsafe_paths_are_rejected_before_archiving(self) -> None:
        blob = bytes.fromhex(self.git("hash-object", "-w", "--stdin", stdin=b"x").decode().strip())

        def crafted(entries: bytes) -> str:
            tree = self.git("hash-object", "-w", "-t", "tree", "--literally", "--stdin", stdin=entries).decode().strip()
            return self.git("commit-tree", tree, "-m", "crafted").decode().strip()

        inner = self.git("hash-object", "-w", "-t", "tree", "--literally", "--stdin", stdin=b"100644 ..\0" + blob).decode().strip()
        cases = {
            "gitlink": (b"160000 sub\0" + b"\x01" * 20, "ordinary blobs"),
            "parent entry": (b"100644 ..\0" + blob, "Unsafe source archive path"),
            "nested parent entry": (b"40000 dir\0" + bytes.fromhex(inner), "Unsafe source archive path"),
        }
        for name, (entries, reason) in cases.items():
            sha = crafted(entries)
            with self.subTest(case=name), patch.object(prepare, "run", wraps=prepare.run) as run, self.assertRaisesRegex(ValueError, reason):
                prepare.source_archive(self.root, sha, "product", "tar")
            self.assertFalse(any("archive" in call.args for call in run.call_args_list), name)

    def test_source_limits_and_invalid_revisions_fail_closed(self) -> None:
        for limit in ("MAX_SOURCE_FILES", "MAX_SOURCE_BYTES", "MAX_TREE_BYTES"):
            with self.subTest(limit=limit), patch.object(prepare, limit, 1), self.assertRaises(ValueError):
                prepare.source_archive(self.root, self.sha, "product", "tar")
        for sha, prefix, format_ in (("HEAD", "product", "tar"), (self.sha, "../product", "tar"), (self.sha, "product", "custom")):
            with self.assertRaises(ValueError):
                prepare.source_archive(self.root, sha, prefix, format_)

    def test_ui_handoff_uses_only_the_trusted_pin_and_preserves_exact_source(self) -> None:
        work = self.root / "handoff"
        work.mkdir()
        for name in ("product", "ejm-ui"):
            subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(self.root), str(work / name)], check=True, capture_output=True)
        for name, revision in (("base", self.sha), ("product", "b" * 40)):
            directory = work / name / ".github"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "ui-source.json").write_text(json.dumps({"repository": "ejmlabs/ejm-ui", "revision": revision}))
        product = work / "product"
        subprocess.run(["git", "-C", str(product), "add", ".github/ui-source.json"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(product), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "proposed future pin"], check=True, capture_output=True)
        head = subprocess.run(["git", "-C", str(product), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        env = {"PR_HEAD": head, "GITHUB_REPOSITORY": "ejmlabs/ejmlabs"}
        with chdir(work), patch.dict(os.environ, env), patch.object(sys, "argv", ["prepare.py"]):
            prepare.main()
        with tarfile.open(work / "prepared/ui.tar") as archive:
            self.assertEqual(member(archive, "ejm-ui/substituted.txt"), b"$Format:%H$\n")
            self.assertEqual(member(archive, "ejm-ui/.github/workflows/pr.yml"), self.workflow)
            self.assertTrue(archive.getmember("ejm-ui/script.sh").mode & 0o111)
        with tarfile.open(work / "prepared/product.tar") as archive:
            self.assertEqual(json.loads(member(archive, "product/.github/ui-source.json"))["revision"], "b" * 40)
        self.assertEqual(sorted(path.name for path in (work / "prepared").iterdir()), ["product.tar", "ui.tar"])


class RawArchiveTests(GitRepositoryTests):
    FILES: ClassVar[dict[str, bytes]] = {
        "lines.txt": b"one\ntwo\n",                       # text eol=crlf
        "id.ident": b"$Id$\nbody\n",                      # ident
        "lower.filtered": b"lower",                       # smudge filter
        "wide.utf16": "wide".encode("utf-16-le"),         # working-tree-encoding, stored as UTF-8 "wide"
    }

    def test_committed_conversion_attributes_cannot_rewrite_archived_bytes(self) -> None:
        self.git("config", "filter.fixture.smudge", "tr a-z A-Z")
        # `!text` would fall back to this setting; the archive must still hold the blob bytes.
        self.git("config", "core.autocrlf", "true")
        (self.root / ".gitattributes").write_text("* text eol=crlf\n*.ident ident\n*.filtered filter=fixture\n*.utf16 working-tree-encoding=UTF-16LE\n")
        for name, content in self.FILES.items():
            (self.root / name).write_bytes(content)
        sha = self.commit()
        blobs = {name: self.git("cat-file", "blob", sha + ":" + name) for name in (*self.FILES, ".gitattributes")}
        self.assertEqual(blobs["lines.txt"], b"one\ntwo\n")
        self.assertEqual(blobs["wide.utf16"], b"wide")
        ordinary = self.git("archive", "--format=tar", "--prefix=product/", sha)
        with tarfile.open(fileobj=io.BytesIO(ordinary)) as archive:
            for name in self.FILES:
                # Control: plain git archive rewrites each of these files, so equality below is not vacuous.
                self.assertNotEqual(member(archive, "product/" + name), blobs[name], name)
        for format_ in ("tar", "tar.gz"):
            with self.subTest(format=format_), tarfile.open(fileobj=io.BytesIO(prepare.source_archive(self.root, sha, "product", format_))) as archive:
                for name, blob in blobs.items():
                    self.assertEqual(member(archive, "product/" + name), blob, name)
        data = prepare.source_archive(self.root, sha, "product", "zip")
        with zipfile.ZipFile(io.BytesIO(data)) as zipped:
            for name, blob in blobs.items():
                self.assertEqual(zipped.read("product/" + name), blob, name)


class UIOwnerPinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / ".github").mkdir()
        self.file = self.root / ".github/ui-source.json"

    def test_absent_owner_is_optional_and_only_an_exact_owner_commit_is_accepted(self) -> None:
        self.assertEqual(prepare.ui_revision(self.root), "")
        self.file.write_text(json.dumps({"repository": "ejmlabs/ejm-ui", "revision": "a" * 40}))
        self.assertEqual(prepare.ui_revision(self.root), "a" * 40)
        candidates: tuple[object, ...] = (
            {"repository": "other/repo", "revision": "a" * 40},
            {"repository": "https://github.com/ejmlabs/ejm-ui", "revision": "a" * 40},
            {"repository": "ejmlabs/ejm-ui", "revision": "main"},
            {"repository": "ejmlabs/ejm-ui", "revision": True},
            {"repository": "ejmlabs/ejm-ui", "revision": "A" * 40},
            {"repository": "ejmlabs/ejm-ui", "revision": "a" * 40, "token": "forbidden"},
            [],
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self.file.write_text(json.dumps(candidate))
                with self.assertRaises(ValueError):
                    prepare.ui_revision(self.root)

    def test_unsafe_or_oversized_metadata_fails_before_source_checkout(self) -> None:
        self.file.write_text(" " * 1025)
        with self.assertRaises(ValueError):
            prepare.ui_revision(self.root)
        self.file.unlink()
        self.file.symlink_to(self.root / "missing")
        with self.assertRaises(ValueError):
            prepare.ui_revision(self.root)
        self.file.unlink()
        (self.root / ".github").rmdir()
        (self.root / "elsewhere").mkdir()
        (self.root / ".github").symlink_to(self.root / "elsewhere", target_is_directory=True)
        with self.assertRaises(ValueError):
            prepare.ui_revision(self.root)

    def test_checkout_output_ignores_a_different_pr_pin(self) -> None:
        for name, revision in (("base", "a" * 40), ("product", "b" * 40)):
            directory = self.root / name / ".github"
            directory.mkdir(parents=True)
            (directory / "ui-source.json").write_text(json.dumps({"repository": "ejmlabs/ejm-ui", "revision": revision}))
        output = self.root / "outputs"
        env = {**os.environ, "GITHUB_OUTPUT": str(output)}
        subprocess.run([sys.executable, prepare.__file__, "ui-pin"], cwd=self.root, env=env, check=True, capture_output=True)
        self.assertEqual(output.read_text(), "revision=" + "a" * 40 + "\n")


class HarnessPinTests(GitRepositoryTests):
    PIN = "b" * 40

    def setUp(self) -> None:
        super().setUp()
        (self.root / ".github").mkdir()
        self.pin = self.root / ".github/harness-revision"
        self.pin.write_text(self.PIN + "\n")
        self.base = self.commit()

    def test_pin_comes_from_the_admitted_git_blob_not_the_worktree(self) -> None:
        candidate = "c" * 40
        self.pin.write_text(candidate)
        head = self.commit()
        self.pin.unlink()
        self.pin.symlink_to("/nonexistent/worktree-pin")
        self.assertEqual(prepare.harness_pin(self.root, self.base), self.PIN)
        self.assertEqual(prepare.harness_pin(self.root, head), candidate)
        with self.assertRaises(ValueError):
            prepare.harness_pin(self.root, "HEAD")

    def test_missing_nonregular_or_malformed_committed_pin_fails_closed(self) -> None:
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

    def test_symlinked_parent_does_not_supply_a_pin(self) -> None:
        self.pin.unlink()
        self.pin.parent.rmdir()
        (self.root / "outside").mkdir()
        (self.root / "outside/harness-revision").write_text(self.PIN)
        (self.root / ".github").symlink_to("outside", target_is_directory=True)
        revision = self.commit()
        with self.assertRaises(ValueError):
            prepare.harness_pin(self.root, revision)


class HarnessSelectionTests(unittest.TestCase):
    HEAD, OTHER, PIN, MAIN, TREE = (character * 40 for character in "abcde")

    def proof(self) -> tuple[dict[str, Any], dict[str, Any]]:
        branch = {"name": "main", "protected": True, "commit": {"sha": self.MAIN}}
        comparison = {"status": "ahead", "behind_by": 0, "ahead_by": 1,
                      "base_commit": {"sha": self.PIN, "commit": {"tree": {"sha": self.TREE}}},
                      "merge_base_commit": {"sha": self.PIN}}
        return branch, comparison

    def test_cli_and_ide_pins_come_from_the_admitted_head_through_one_protected_main_comparison(self) -> None:
        for profile in prepare.HARNESS_PROFILES:
            branch, comparison = self.proof()
            for identical in (False, True):
                if identical:
                    branch["commit"]["sha"] = self.PIN
                    comparison["status"] = "identical"
                    comparison["ahead_by"] = 0
                with self.subTest(profile=profile, identical=identical), patch.object(prepare, "harness_pin", return_value=self.PIN) as pin, patch.object(prepare, "harness_json", side_effect=[branch, comparison]) as api:
                    self.assertEqual(prepare.select_harness(profile, self.HEAD, "harness-read"), {"revision": self.PIN, "tree": self.TREE})
                    pin.assert_called_once_with("product", self.HEAD)
                    self.assertEqual(api.call_args_list, [
                        unittest.mock.call("branches/main", "harness-read"),
                        unittest.mock.call("compare/" + self.PIN + "..." + branch["commit"]["sha"] + "?per_page=1", "harness-read"),
                    ])
        self.assertEqual(prepare.HARNESS_PROFILES, ("ejm-cli", "ejm-ide"))

    def test_missing_malformed_or_unprotected_main_fails_before_comparison(self) -> None:
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
                    prepare.select_harness("ejm-ide", self.HEAD, "harness-read")
                api.assert_called_once_with("branches/main", "harness-read")

    def test_diverged_nonancestor_or_malformed_comparisons_fail_closed(self) -> None:
        cases: list[tuple[str, Callable[[dict[str, Any]], object]]] = [
            ("missing", lambda value: value.clear()),
            ("diverged", lambda value: value.update(status="diverged")),
            ("descendant", lambda value: value.update(status="behind", behind_by=1)),
            ("wrong base", lambda value: value["base_commit"].update(sha=self.OTHER)),
            ("not ancestor", lambda value: value["merge_base_commit"].update(sha=self.OTHER)),
            ("behind", lambda value: value.update(behind_by=1)),
            ("malformed distance", lambda value: value.update(behind_by="0")),
            ("boolean distance", lambda value: value.update(behind_by=False)),
            ("incoherent distance", lambda value: value.update(ahead_by=0)),
            ("missing tree", lambda value: value["base_commit"]["commit"].clear()),
            ("malformed tree", lambda value: value["base_commit"]["commit"]["tree"].update(sha="HEAD")),
        ]
        for name, changes in cases:
            branch, comparison = self.proof()
            changes(comparison)
            with self.subTest(case=name), patch.object(prepare, "harness_pin", return_value=self.PIN), patch.object(prepare, "harness_json", side_effect=[branch, comparison]), self.assertRaises(ValueError):
                prepare.select_harness("ejm-cli", self.HEAD, "harness-read")

    def test_inaccessible_official_api_does_not_fall_back_to_another_pin(self) -> None:
        branch, _ = self.proof()
        for responses in ([urllib.error.URLError("unavailable")], [branch, urllib.error.URLError("unavailable")]):
            with self.subTest(after_branch=len(responses) == 2), patch.object(prepare, "harness_pin", return_value=self.PIN) as pin, patch.object(prepare, "harness_json", side_effect=responses):
                with self.assertRaises(urllib.error.URLError):
                    prepare.select_harness("ejm-ide", self.HEAD, "harness-read")
                pin.assert_called_once_with("product", self.HEAD)

    def test_other_profiles_select_no_harness_and_read_nothing(self) -> None:
        with patch.object(prepare, "harness_json") as api, patch.object(prepare, "harness_pin") as pin:
            for profile in ("ejm-harness", "ejmlabs", "ejm-ui", ".github"):
                self.assertIsNone(prepare.select_harness(profile, self.HEAD, "unused"))
            api.assert_not_called()
            pin.assert_not_called()


class HarnessMetadataTests(unittest.TestCase):
    URL = "https://api.github.com/repos/ejmlabs/ejm-harness/branches/main"

    def test_metadata_request_is_bounded_get_only_and_cannot_redirect_credentials(self) -> None:
        with patch.object(urllib.request, "build_opener") as opener:
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
            self.assertIsInstance(handler, urllib.request.HTTPRedirectHandler)
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "redirect", {}, "https://other.invalid/")
        for path in ("https://other.invalid/", "../other/repository", "branches/other", "compare/main...HEAD?per_page=1"):
            with self.subTest(path=path), patch.object(urllib.request, "build_opener") as opener:
                with self.assertRaises(ValueError):
                    prepare.harness_json(path, "fixture")
                opener.assert_not_called()

    def test_inaccessible_redirected_or_malformed_metadata_fails_closed(self) -> None:
        cases = ((200, self.URL, b""), (200, self.URL, b"x" * 65),
                 (200, self.URL, b"[]"), (200, self.URL, b"null"),
                 (200, self.URL, b"{"), (200, self.URL, b"\xff"),
                 (302, self.URL, b"{}"), (200, "https://other.invalid/", b"{}"))
        for status, url, body in cases:
            with self.subTest(status=status, url=url, body=body[:10]), patch.object(prepare, "MAX_HARNESS_METADATA_BYTES", 64), patch.object(urllib.request, "build_opener") as opener:
                response = opener.return_value.open.return_value.__enter__.return_value
                response.status, response.geturl.return_value, response.read.return_value = status, url, body
                with self.assertRaises(ValueError):
                    prepare.harness_json("branches/main", "fixture")
        with patch.object(urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.URLError("unavailable")
            with self.assertRaises(ValueError):
                prepare.harness_json("branches/main", "fixture")

    def test_failures_name_the_status_or_reason_without_response_content(self) -> None:
        for status in (403, 404, 502):
            with self.subTest(status=status), patch.object(urllib.request, "build_opener") as opener:
                opener.return_value.open.side_effect = urllib.error.HTTPError(self.URL, status, "secret body text", Message(), None)
                with self.assertRaisesRegex(ValueError, f"verify protected harness source metadata: HTTP {status}$"):
                    prepare.harness_json("branches/main", "fixture")
        with patch.object(urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError("handshake detail")
            with self.assertRaisesRegex(ValueError, r"metadata: TimeoutError$"):
                prepare.harness_json("branches/main", "fixture")
        with patch.object(urllib.request, "build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.status, response.geturl.return_value = 200, "https://other.invalid/"
            with self.assertRaisesRegex(ValueError, r"metadata: Unexpected harness metadata response$"):
                prepare.harness_json("branches/main", "fixture")


class HarnessArchiveTests(GitRepositoryTests):
    def setUp(self) -> None:
        super().setUp()
        (self.root / "source.txt").write_text("reviewed harness source\n")
        self.revision = self.commit()
        self.tree = self.git("rev-parse", "HEAD^{tree}").decode().strip()
        subprocess.run(["git", "clone", "--quiet", str(self.root), str(self.workspace / "harness")], check=True, capture_output=True)
        (self.root / ".github").mkdir()
        (self.root / ".github/harness-revision").write_text(self.revision + "\n")
        self.head = self.commit()
        self.selection = {"revision": self.revision, "tree": self.tree}
        self.file = self.workspace / "harness-selection.json"
        self.file.write_text(json.dumps(self.selection))

    def environment(self, repository: str) -> dict[str, str]:
        return {"PR_HEAD": self.head, "GITHUB_REPOSITORY": "ejmlabs/" + repository}

    def test_preparation_binds_pin_checkout_and_archive_to_one_source(self) -> None:
        # A stale pin in the trusted base checkout must not matter for either profile: the admitted head chooses.
        stale = self.workspace / "base/.github"
        stale.mkdir(parents=True)
        (stale / "harness-revision").write_text("f" * 40 + "\n")
        for repository in ("ejm-cli", "ejm-ide"):
            with self.subTest(repository=repository), chdir(self.workspace), patch.dict(os.environ, self.environment(repository)), patch.object(sys, "argv", ["prepare.py"]):
                self.assertEqual(prepare.load_harness_selection(self.head), self.selection)
                prepare.main()
                self.assertEqual(sorted(path.name for path in Path("prepared").iterdir()), ["harness.tar", "product.tar"])
                with tarfile.open("prepared/harness.tar") as archive:
                    self.assertEqual(member(archive, "ejm-harness/source.txt"), b"reviewed harness source\n")
                    self.assertNotIn("ejm-harness/.github/harness-revision", archive.getnames())
                with tarfile.open("prepared/product.tar") as archive:
                    self.assertEqual(member(archive, "product/.github/harness-revision"), (self.revision + "\n").encode())
                shutil.rmtree("prepared")

    def test_ui_base_pin_and_admitted_harness_selection_share_one_handoff(self) -> None:
        subprocess.run(["git", "clone", "--quiet", str(self.root), str(self.workspace / "ejm-ui")], check=True, capture_output=True)
        (self.root / ".github/ui-source.json").write_text(json.dumps({"repository": "ejmlabs/ejm-ui", "revision": "b" * 40}))
        self.head = self.commit()
        base = self.workspace / "base/.github"
        base.mkdir(parents=True)
        (base / "ui-source.json").write_text(json.dumps({"repository": "ejmlabs/ejm-ui", "revision": self.revision}))
        with chdir(self.workspace), patch.dict(os.environ, self.environment("ejm-ide")), patch.object(sys, "argv", ["prepare.py"]):
            prepare.main()
        self.assertEqual(sorted(path.name for path in (self.workspace / "prepared").iterdir()), ["harness.tar", "product.tar", "ui.tar"])
        for name, prefix in (("harness", "ejm-harness"), ("ui", "ejm-ui")):
            with tarfile.open(self.workspace / ("prepared/" + name + ".tar")) as archive:
                self.assertEqual(member(archive, prefix + "/source.txt"), b"reviewed harness source\n")
        with tarfile.open(self.workspace / "prepared/product.tar") as archive:
            self.assertEqual(json.loads(member(archive, "product/.github/ui-source.json"))["revision"], "b" * 40)

    def test_changed_checkout_head_or_tree_is_rejected_before_export(self) -> None:
        for head, tree in ((self.head, self.tree), (self.revision, "e" * 40)):
            selection = {**self.selection, "tree": tree}
            subprocess.run(["git", "-C", str(self.workspace / "harness"), "fetch", "--quiet", str(self.root), head], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(self.workspace / "harness"), "checkout", "--quiet", "--detach", head], check=True, capture_output=True)
            with self.subTest(head=head, tree=tree), chdir(self.workspace), patch.object(prepare, "source_archive") as archive:
                with self.assertRaises(ValueError):
                    prepare.archive_harness(selection)
                archive.assert_not_called()

    def test_selection_must_match_the_admitted_pin_exactly_and_stay_bounded(self) -> None:
        mutations: tuple[dict[str, str], ...] = (
            {"revision": "f" * 40}, {"tree": "main"}, {"revision": "HEAD"},
            {"repository": "ejmlabs/ejm-harness"}, {"protected_main": self.revision}, {"pin_source": "head"},
        )
        for change in mutations:
            self.file.write_text(json.dumps({**self.selection, **change}))
            with self.subTest(change=change), chdir(self.workspace), self.assertRaises(ValueError):
                prepare.load_harness_selection(self.head)
        self.file.write_text(json.dumps({"revision": self.revision}))
        with self.subTest(missing="tree"), chdir(self.workspace), self.assertRaises(ValueError):
            prepare.load_harness_selection(self.head)
        for body in (b"x" * (prepare.MAX_HARNESS_SELECTION_BYTES + 1), b"null", b"{}"):
            self.file.write_bytes(body)
            with self.subTest(body=body[:10]), chdir(self.workspace), self.assertRaises(ValueError):
                prepare.load_harness_selection(self.head)
        self.file.unlink()
        self.file.symlink_to("product/.github/harness-revision")
        with chdir(self.workspace), self.assertRaises(ValueError):
            prepare.load_harness_selection(self.head)

    def test_selector_emits_checkout_revision_and_rejects_repository_profile_mismatch(self) -> None:
        output = self.workspace / "outputs"
        for profile in ("ejm-cli", "ejm-ide"):
            self.file.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
            env = {**self.environment(profile), "PROFILE": profile, "HARNESS_READ_TOKEN": "harness-read", "GITHUB_OUTPUT": str(output)}
            with self.subTest(profile=profile), chdir(self.workspace), patch.dict(os.environ, env), patch.object(sys, "argv", ["prepare.py", "select-harness"]), patch.object(prepare, "select_harness", return_value=self.selection) as select:
                prepare.main()
                select.assert_called_once_with(profile, self.head, "harness-read")
                self.assertEqual(json.loads(self.file.read_text()), self.selection)
                self.assertEqual(output.read_text(), "revision=" + self.revision + "\n")
                with patch.dict(os.environ, {"PROFILE": "ejm-harness"}), self.assertRaises(ValueError):
                    prepare.main()
                self.assertEqual(select.call_count, 1)


if __name__ == "__main__":
    unittest.main()
