import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
import urllib.error
import zipfile
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
namespace: dict[str, Any] = {"__name__": "release_test_library"}
for name in ("governance.py", "versioning.py", "standards.py", "prepare.py", "release.py"):
    text = (ROOT / "scripts" / name).read_text().split('\nif __name__ == "__main__":')[0]
    exec(compile(text, name, "exec"), namespace)  # noqa: S102 - scripts run in one shared namespace, as embedded in the workflow
release = namespace["release"]
SHA, HEAD, LATER, PIN = "a" * 40, "b" * 40, "d" * 40, "c" * 40
RELEASE_CALLER = "jobs:\n  release:\n    uses: ejmlabs/.github/.github/workflows/draft-release.yml@" + PIN + '\n    with:\n      standards-ref: "' + PIN + '"\n'


def review(login: str | None, state: str, commit: str, at: str = "2026-10-19T10:00:00Z") -> dict[str, Any]:
    return {"state": state, "commit_id": commit, "submitted_at": at, "user": None if login is None else {"login": login}}


def pull(number: int, merge_commit: str, **changes: Any) -> dict[str, Any]:
    return {"number": number, "merged_at": "2026-10-19", "merge_commit_sha": merge_commit, "base": {"ref": "main"}, "head": {"sha": HEAD}, **changes}


class API:
    repo = "ejmlabs/ejmlabs"

    def __init__(self) -> None:
        self.main, self.tree = SHA, "same-tree"
        self.relation, self.merge_base = "ahead", SHA
        self.existing: str | None = None
        self.releases: list[dict[str, Any]] = []
        self.role, self.checks = "maintain", True
        self.reviews: list[dict[str, Any]] = [review("maintainer", "APPROVED", HEAD)]
        self.pulls: list[dict[str, Any]] = [pull(4, SHA)]
        self.calls: list[str] = []

    def permission(self, _login: str) -> str:
        return self.role

    def request(self, path: str) -> dict[str, Any]:
        self.calls.append(path)
        if path.startswith("https://api.github.com/users/"):
            return {"login": "maintainer", "type": "User"}
        if path == "/branches/main":
            return {"commit": {"sha": self.main}}
        if path == f"/compare/{SHA}...{self.main}?per_page=1":
            return {"status": self.relation, "merge_base_commit": {"sha": self.merge_base}}
        if path.startswith(("/git/ref/tags/", "/releases/tags/")):
            if self.existing and self.existing in path:
                return {}
            raise urllib.error.HTTPError(path, 404, "Not Found", Message(), None)
        if path == f"/git/commits/{SHA}":
            return {"tree": {"sha": self.tree}}
        if path == f"/git/commits/{HEAD}":
            return {"tree": {"sha": "same-tree"}}
        raise AssertionError(path)

    def pages(self, path: str) -> list[dict[str, Any]]:
        self.calls.append(path)
        if path == "/releases":
            return self.releases
        return self.reviews if "reviews" in path else self.pulls

    def statuses(self, _sha: str) -> dict[str, dict[str, str]]:
        statuses = {key: {"state": "success", "description": "passed"} for key in ("Quality", "Repository standards")}
        if not self.checks:
            statuses["Quality"]["state"] = "failure"
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
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/release.yml").write_text(RELEASE_CALLER)
        # No GITHUB_OUTPUT: a release writes no step outputs.
        os.environ.update(GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1", GITHUB_ACTOR="maintainer")
        os.environ.pop("GITHUB_OUTPUT", None)

    def restore_environment(self) -> None:
        os.environ.clear()
        os.environ.update(self.old_env)

    def refused(self, api: API, pattern: str, ref: str = PIN) -> None:
        with self.assertRaisesRegex(ValueError, pattern):
            release(api, self.root, SHA, "0.1.0", ref)
        self.assertFalse(Path("release-assets").exists())

    def draft(self, api: API) -> "MagicMock":
        """Run a release that passes every check, with git and the archive export faked, and return the faked git call."""
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
            release(api, self.root, SHA, "0.1.0", PIN)
        return process

    def test_existing_tag_or_release_refuses_all_asset_creation(self) -> None:
        for existing in ("/git/ref/tags/", "/releases/tags/"):
            api = API()
            api.existing = existing
            self.refused(api, "already exists")

    def test_a_draft_or_published_release_for_the_tag_refuses_the_release(self) -> None:
        # The lookup by tag never returns a draft, so drafts are found by listing every release.
        for name, releases in {
            "a draft without a tag": [{"tag_name": "v0.1.0", "draft": True}],
            "a published release": [{"tag_name": "v0.1.0", "draft": False}],
            "a draft among others": [{"tag_name": "v0.0.9", "draft": False}, {"tag_name": "v0.1.0", "draft": True}, {"tag_name": "v0.2.0", "draft": True}],
        }.items():
            with self.subTest(name):
                api = API()
                api.releases = releases
                self.refused(api, "already exists")
        api = API()
        api.releases = [{"tag_name": "v0.0.9", "draft": False}, {"tag_name": "v0.2.0", "draft": True}]
        self.draft(api)

    def test_an_existing_draft_stops_the_release_before_the_pull_request_lookup(self) -> None:
        api = API()
        api.releases = [{"tag_name": "v0.1.0", "draft": True}]
        self.refused(api, "already exists")
        self.assertIn("/releases", api.calls)
        self.assertNotIn(f"/commits/{SHA}/pulls", api.calls)

    def test_failed_checks_different_tree_and_ordinary_writer_block(self) -> None:
        for field, value, pattern in (("checks", False, "required check"), ("tree", "different", "differs from the checked PR"), ("role", "write", "human maintainer")):
            with self.subTest(field=field):
                api = API()
                setattr(api, field, value)
                self.refused(api, pattern)

    def test_the_main_head_or_an_earlier_main_commit_is_accepted(self) -> None:
        for main, relation in ((SHA, "identical"), (LATER, "ahead")):
            with self.subTest(main=main):
                api = API()
                api.main, api.relation = main, relation
                self.draft(api)
                self.assertEqual(json.loads(Path("release-assets/provenance.json").read_text())["commit"], SHA)
                self.assertEqual(("/compare/" + SHA + "..." + main + "?per_page=1" in api.calls), main != SHA)
                shutil.rmtree("release-assets")

    def test_a_commit_that_is_not_an_ancestor_of_main_is_refused(self) -> None:
        for relation, merge_base in (("diverged", HEAD), ("behind", SHA), ("ahead", HEAD), ("identical", SHA), ("", SHA)):
            with self.subTest(relation=relation, merge_base=merge_base):
                api = API()
                api.main, api.relation, api.merge_base = LATER, relation, merge_base
                self.refused(api, "on protected main")

    def test_standards_ref_must_equal_the_pin_in_the_release_commit(self) -> None:
        caller = self.root / ".github/workflows/release.yml"
        other = "e" * 40
        for ref in (other, "main", "", PIN.upper()):
            with self.subTest(ref=ref):
                self.refused(API(), "standards-ref", ref)
        for text in (RELEASE_CALLER.replace(PIN, other), RELEASE_CALLER + RELEASE_CALLER.replace(PIN, other), "jobs: {}\n"):
            with self.subTest(text=text):
                caller.write_text(text)
                self.refused(API(), "standards-ref")
        caller.unlink()
        self.refused(API(), "Missing or unsafe file")
        # A native release caller pins verify, release and attach alike.
        caller.write_text("".join(RELEASE_CALLER.replace("draft-release", name) for name in ("verify-build", "draft-release", "attach-assets")))
        self.draft(API())

    def test_only_one_checked_merged_pr_may_own_the_commit(self) -> None:
        cases = {
            "two merged PRs": [pull(4, SHA), pull(5, SHA)],
            "no PR": [],
            "other merge commit": [pull(4, HEAD)],
            "not merged": [pull(4, SHA, merged_at=None)],
            "other base": [pull(4, SHA, base={"ref": "topic"})],
        }
        for name, pulls in cases.items():
            with self.subTest(name):
                api = API()
                api.pulls = pulls
                self.refused(api, "exactly one checked merged PR")
        api = API()
        api.pulls = [pull(4, SHA), pull(5, HEAD), pull(6, SHA, merged_at=None)]
        self.draft(api)
        self.assertEqual(json.loads(Path("release-assets/provenance.json").read_text())["checked_pr"], 4)

    def test_only_an_approval_that_stands_on_the_merged_head_counts(self) -> None:
        approve = review("maintainer", "APPROVED", HEAD, "2026-10-19T10:00:00Z")
        cases = {
            "no review": [],
            "approval of an older commit": [review("maintainer", "APPROVED", SHA)],
            "comment only": [review("maintainer", "COMMENTED", HEAD)],
            "dismissed": [review("maintainer", "DISMISSED", HEAD)],
            "changes requested after the approval": [approve, review("maintainer", "CHANGES_REQUESTED", HEAD, "2026-10-19T11:00:00Z")],
            "pending review": [{"state": "PENDING", "commit_id": HEAD, "user": {"login": "maintainer"}}],
            "reviewer without an account": [review(None, "APPROVED", HEAD)],
        }
        for name, reviews in cases.items():
            with self.subTest(name):
                api = API()
                api.reviews = reviews
                self.refused(api, "approving review")
        for name, reviews in {
            "approval then a comment": [approve, review("maintainer", "COMMENTED", HEAD, "2026-10-19T11:00:00Z")],
            "changes requested then approval": [review("maintainer", "CHANGES_REQUESTED", HEAD, "2026-10-19T09:00:00Z"), approve],
            "one reviewer's approval beside another's older rejection": [review("other", "CHANGES_REQUESTED", HEAD, "2026-10-19T09:00:00Z"), approve],
            "out of order listing": [review("maintainer", "CHANGES_REQUESTED", HEAD, "2026-10-19T09:00:00Z"), approve][::-1],
        }.items():
            with self.subTest(name):
                api = API()
                api.reviews = reviews
                self.draft(api)
                shutil.rmtree("release-assets")

    def test_rerun_and_mismatched_requested_version_block(self) -> None:
        with self.assertRaises(ValueError):
            release(API(), self.root, SHA, "0.2.0", PIN)
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        with self.assertRaisesRegex(ValueError, "reruns"):
            release(API(), self.root, SHA, "0.1.0", PIN)

    def test_validated_sources_produce_checksums_provenance_and_no_publication(self) -> None:
        api = API()
        process = self.draft(api)
        self.assertEqual(process.call_count, 1)
        for call in process.call_args_list:
            self.assertEqual(call.args[0][:3], ["git", "-C", "product"])
            self.assertEqual(call.args[0][-1], SHA)
        manifest = json.loads(Path("release-assets/provenance.json").read_text())
        self.assertEqual(manifest["commit"], SHA)
        self.assertEqual(manifest["standards_revision"], PIN)
        self.assertFalse(manifest["signed"])
        for line in Path("release-assets/SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ")
            self.assertEqual(digest, hashlib.sha256((Path("release-assets") / name).read_bytes()).hexdigest())
        self.assertFalse(any("POST" in path for path in api.calls))
        self.assertFalse(Path("output").exists())

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
        # Packages come from the commit tree, so one added after the last review is still required.
        paths.update(path + "/" + name for path in ("packages/core", "packages/tokens", "packages/added-later") for name in ("package.json", "LICENSE", "THIRD_PARTY_NOTICES.md"))
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
