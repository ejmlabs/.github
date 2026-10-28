import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
import urllib.error
import zipfile
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
namespace: dict[str, Any] = {"__name__": "release_test_library"}
for name in ("governance.py", "standards.py", "prepare.py", "release.py"):
    text = (ROOT / "scripts" / name).read_text().split('\nif __name__ == "__main__":')[0]
    exec(compile(text, name, "exec"), namespace)  # noqa: S102 - scripts run in one shared namespace, as embedded in the workflow
release = namespace["release"]
SHA, HEAD = "a" * 40, "b" * 40


class API:
    repo = "ejmlabs/ejmlabs"

    def __init__(self) -> None:
        self.main, self.tree = SHA, "same-tree"
        self.existing: str | None = None
        self.role, self.body, self.checks = "maintain", True, True
        self.calls: list[str] = []

    def permission(self, _login: str) -> str:
        return self.role

    def request(self, path: str) -> dict[str, Any]:
        self.calls.append(path)
        if path.startswith("https://api.github.com/users/"):
            return {"login": "maintainer", "type": "User"}
        if path == "/branches/main":
            return {"commit": {"sha": self.main}}
        if path.startswith(("/git/ref/tags/", "/releases/tags/")):
            if self.existing and self.existing in path:
                return {}
            raise urllib.error.HTTPError(path, 404, "Not Found", Message(), None)
        if path == f"/git/commits/{SHA}":
            return {"tree": {"sha": self.tree}}
        if path == f"/git/commits/{HEAD}":
            return {"tree": {"sha": "same-tree"}}
        if path.startswith("/issues/comments/"):
            kind = "ready" if path.endswith("1") else "approve"
            return {"issue_url": "https://api.github.com/repos/ejmlabs/ejmlabs/issues/4", "body": "/" + kind + " " + (HEAD if self.body else SHA), "created_at": "2026-10-19", "updated_at": "2026-10-19", "user": {"login": "maintainer", "type": "User"}}
        raise AssertionError(path)

    def pages(self, _path: str) -> list[dict[str, Any]]:
        return [{"number": 4, "merged_at": "2026-10-19", "merge_commit_sha": SHA, "base": {"ref": "main"}, "head": {"sha": HEAD}}]

    def statuses(self, _sha: str) -> dict[str, dict[str, str]]:
        statuses = {key: {"state": "success", "description": "passed"} for key in namespace["CONTEXTS"]}
        statuses["Human readiness"]["description"] = "[ready:1]"
        statuses["Maintainer approval"]["description"] = "[approve:2]"
        if not self.checks:
            statuses["AI review"]["state"] = "failure"
        return statuses


class ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.old_cwd, self.old_env = Path.cwd(), dict(os.environ)
        self.addCleanup(lambda: os.chdir(self.old_cwd))
        self.addCleanup(self.restore_environment)
        os.chdir(self.directory.name)
        self.root = Path("product")
        (self.root / "site").mkdir(parents=True)
        (self.root / "VERSION").write_text("0.1.0\n")
        (self.root / "site/package.json").write_text('{"version":"0.1.0","license":"SEE LICENSE IN ../LICENSE"}')
        (self.root / "CHANGELOG.md").write_text("## [0.1.0] - 2026-10-18\n- Initial source.\n")
        for name in namespace["DOCS"]:
            if not (self.root / name).exists():
                (self.root / name).write_text("Release notice: " + name)
        os.environ.update(GITHUB_OUTPUT=str(Path.cwd() / "output"), GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1", GITHUB_ACTOR="maintainer", STANDARDS_REF="c" * 40)

    def restore_environment(self) -> None:
        os.environ.clear()
        os.environ.update(self.old_env)

    def test_existing_tag_or_release_refuses_all_asset_creation(self) -> None:
        for existing in ("/git/ref/tags/", "/releases/tags/"):
            api = API()
            api.existing = existing
            with self.assertRaises(ValueError):
                release(api, self.root, SHA, "0.1.0")
            self.assertFalse(Path("release-assets").exists())

    def test_changed_main_failed_checks_edited_approval_and_different_tree_block(self) -> None:
        for field, value in (("main", HEAD), ("checks", False), ("body", False), ("tree", "different"), ("role", "write")):
            api = API()
            setattr(api, field, value)
            with self.assertRaises(ValueError):
                release(api, self.root, SHA, "0.1.0")
            self.assertFalse(Path("release-assets").exists())

    def test_rerun_and_mismatched_requested_version_block(self) -> None:
        with self.assertRaises(ValueError):
            release(API(), self.root, SHA, "0.2.0")
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        with self.assertRaises(ValueError):
            release(API(), self.root, SHA, "0.1.0")

    def test_validated_sources_produce_checksums_provenance_and_no_publication(self) -> None:
        with patch("subprocess.run") as process, patch.dict(namespace, {"source_archive": lambda _root, _sha, _prefix, format_: self.archive(format_)}):
            def source_result(args: list[str], **_kwargs: Any) -> SimpleNamespace:
                result = SimpleNamespace()
                if args[3] == "ls-tree":
                    result.stdout = b"LICENSE\nVERSION\n"
                else:
                    format_ = args[4].split("=", 1)[1]
                    result.stdout = self.archive(format_)
                return result
            process.side_effect = source_result
            api = API()
            release(api, self.root, SHA, "0.1.0")
            self.assertEqual(process.call_count, 1)
            for call in process.call_args_list:
                self.assertEqual(call.args[0][:3], ["git", "-C", "product"])
                self.assertEqual(call.args[0][-1], SHA)
        manifest = json.loads(Path("release-assets/provenance.json").read_text())
        self.assertEqual(manifest["commit"], SHA)
        self.assertFalse(manifest["signed"])
        for line in Path("release-assets/SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ")
            self.assertEqual(digest, hashlib.sha256((Path("release-assets") / name).read_bytes()).hexdigest())
        self.assertFalse(any("POST" in path for path in api.calls))

    def archive(self, format_: str, omit: str | None = None) -> bytes:
        buffer = io.BytesIO()
        files = {name: (self.root / name).read_bytes() for name in (*namespace["DOCS"], "VERSION") if name != omit}
        if format_ == "zip":
            with zipfile.ZipFile(buffer, "w") as archive:
                for name, content in files.items():
                    archive.writestr("ejmlabs-0.1.0/" + name, content)
        else:
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                for name, content in files.items():
                    info = tarfile.TarInfo("ejmlabs-0.1.0/" + name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
        return buffer.getvalue()

    def test_export_ignore_cannot_remove_root_license_from_assets(self) -> None:
        for format_ in ("zip", "tar.gz"):
            with self.assertRaises((KeyError, ValueError)):
                namespace["validate_archive"](self.archive(format_, omit="LICENSE"), format_, "ejmlabs-0.1.0", {"LICENSE": (self.root / "LICENSE").read_bytes()})

    def test_ui_release_requires_package_metadata_and_exact_font_notice_bytes(self) -> None:
        paths = set(namespace["DOCS"]) | {"VERSION", "package.json", "package-lock.json", "crates/ejm-tui/Cargo.toml", "crates/ejm-tui/Cargo.lock", *namespace["UI_FONT_NOTICES"]}
        paths.update(path + "/" + name for path in namespace["UI_PACKAGES"] for name in ("package.json", "LICENSE", "THIRD_PARTY_NOTICES.md"))
        for name in paths:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"Copyright fixture\r\nPreserve the exact notice bytes.\r\n")
        tree = type("Tree", (), {"stdout": "\n".join(sorted(paths)).encode()})()
        with patch.object(namespace["subprocess"], "run", return_value=tree):
            required = namespace["archive_requirements"](self.root, SHA, "ejm-ui")
        self.assertEqual(set(required), paths)
        self.assertTrue(all(value == b"Copyright fixture\r\nPreserve the exact notice bytes.\r\n" for value in required.values()))
        for format_ in ("zip", "tar.gz"):
            with self.subTest(format=format_), self.assertRaises((KeyError, ValueError)):
                namespace["validate_archive"](self.archive(format_), format_, "ejmlabs-0.1.0", required)


if __name__ == "__main__":
    unittest.main()
