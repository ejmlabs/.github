import hashlib
import io
import json
import os
import tempfile
import tarfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
namespace = {"__name__": "release_test_library"}
for name in ("governance.py", "standards.py", "prepare.py", "release.py"):
    text = (ROOT / "scripts" / name).read_text().split('\nif __name__ == "__main__":')[0]
    exec(compile(text, name, "exec"), namespace)
release = namespace["release"]
SHA, HEAD = "a" * 40, "b" * 40


class API:
    repo = "ejmlabs/ejmlabs"

    def __init__(self):
        self.main, self.tree, self.existing = SHA, "same-tree", None
        self.role, self.body, self.checks = "maintain", True, True
        self.calls = []

    def permission(self, login): return self.role

    def request(self, path):
        self.calls.append(path)
        if path.startswith("https://api.github.com/users/"): return {"login": "maintainer", "type": "User"}
        if path == "/branches/main": return {"commit": {"sha": self.main}}
        if path.startswith(("/git/ref/tags/", "/releases/tags/")):
            if self.existing and self.existing in path: return {}
            raise urllib.error.HTTPError(path, 404, "Not Found", None, None)
        if path == f"/git/commits/{SHA}": return {"tree": {"sha": self.tree}}
        if path == f"/git/commits/{HEAD}": return {"tree": {"sha": "same-tree"}}
        if path.startswith("/issues/comments/"):
            kind = "ready" if path.endswith("1") else "approve"
            return {"issue_url": "https://api.github.com/repos/ejmlabs/ejmlabs/issues/4", "body": "/" + kind + " " + (HEAD if self.body else SHA), "created_at": "2026-10-19", "updated_at": "2026-10-19", "user": {"login": "maintainer", "type": "User"}}
        raise AssertionError(path)

    def pages(self, path):
        return [{"number": 4, "merged_at": "2026-10-19", "merge_commit_sha": SHA, "base": {"ref": "main"}, "head": {"sha": HEAD}}]

    def statuses(self, sha):
        statuses = {key: {"state": "success", "description": "passed"} for key in namespace["CONTEXTS"]}
        statuses["Human readiness"]["description"] = "[ready:1]"
        statuses["Maintainer approval"]["description"] = "[approve:2]"
        if not self.checks: statuses["AI review"]["state"] = "failure"
        return statuses


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.old_cwd, self.old_env = Path.cwd(), dict(os.environ)
        self.addCleanup(lambda: os.chdir(self.old_cwd))
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.old_env)))
        os.chdir(self.directory.name)
        self.root = Path("product")
        (self.root / "site").mkdir(parents=True)
        (self.root / "VERSION").write_text("0.1.0\n")
        (self.root / "site/package.json").write_text('{"version":"0.1.0","license":"SEE LICENSE IN ../LICENSE"}')
        (self.root / "CHANGELOG.md").write_text("## [0.1.0] - 2026-10-18\n- Initial source.\n")
        for name in namespace["DOCS"]:
            if not (self.root / name).exists(): (self.root / name).write_text("Release notice: " + name)
        os.environ.update(GITHUB_OUTPUT=str(Path.cwd() / "output"), GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1", GITHUB_ACTOR="maintainer", STANDARDS_REF="c" * 40)

    def test_existing_tag_or_release_refuses_all_asset_creation(self):
        for existing in ("/git/ref/tags/", "/releases/tags/"):
            api = API()
            api.existing = existing
            with self.assertRaises(ValueError): release(api, self.root, SHA, "0.1.0")
            self.assertFalse(Path("release-assets").exists())

    def test_changed_main_failed_checks_edited_approval_and_different_tree_block(self):
        for field, value in (("main", HEAD), ("checks", False), ("body", False), ("tree", "different"), ("role", "write")):
            api = API()
            setattr(api, field, value)
            with self.assertRaises(ValueError): release(api, self.root, SHA, "0.1.0")
            self.assertFalse(Path("release-assets").exists())

    def test_rerun_and_mismatched_requested_version_block(self):
        with self.assertRaises(ValueError): release(API(), self.root, SHA, "0.2.0")
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        with self.assertRaises(ValueError): release(API(), self.root, SHA, "0.1.0")

    def test_validated_sources_produce_checksums_provenance_and_no_publication(self):
        with patch("subprocess.run") as process, patch.dict(namespace, {"source_archive": lambda root, sha, prefix, format_: self.archive(format_)}):
            def source_result(args, **kwargs):
                class Result: pass
                result = Result()
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

    def archive(self, format_, omit=None):
        buffer = io.BytesIO()
        files = {name: (self.root / name).read_bytes() for name in (*namespace["DOCS"], "VERSION") if name != omit}
        if format_ == "zip":
            with zipfile.ZipFile(buffer, "w") as archive:
                for name, content in files.items(): archive.writestr("ejmlabs-0.1.0/" + name, content)
        else:
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                for name, content in files.items():
                    info = tarfile.TarInfo("ejmlabs-0.1.0/" + name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
        return buffer.getvalue()

    def test_export_ignore_cannot_remove_root_license_from_assets(self):
        for format_ in ("zip", "tar.gz"):
            with self.assertRaises((KeyError, ValueError)):
                namespace["validate_archive"](self.archive(format_, omit="LICENSE"), format_, "ejmlabs-0.1.0", {"LICENSE": (self.root / "LICENSE").read_bytes()})


if __name__ == "__main__": unittest.main()
