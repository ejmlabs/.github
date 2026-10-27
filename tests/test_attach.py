import hashlib
import os
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
namespace: dict[str, Any] = {"__name__": "attach_test_library"}
for name in ("governance.py", "standards.py", "attach.py"):
    text = (ROOT / "scripts" / name).read_text().split('\nif __name__ == "__main__":')[0]
    exec(compile(text, name, "exec"), namespace)  # noqa: S102 - scripts run in one shared namespace, as embedded in the workflow
SHA, OTHER = "a" * 40, "b" * 40


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class API:
    repo = "ejmlabs/ejm-cli"

    def __init__(self, **changes: Any) -> None:
        self.run = {"path": ".github/workflows/build.yml@refs/heads/main", "event": "push", "head_branch": "main", "head_sha": SHA,
                    "head_repository": {"full_name": self.repo}, "status": "completed", "conclusion": "success"}
        self.tag: dict[str, Any] | None = {"object": {"type": "commit", "sha": SHA}}
        self.main_tag, self.artifacts = False, [{"name": "release-files", "expired": False}]
        self.release = {"tag_name": "v0.1.0", "draft": True, "assets": []}
        self.__dict__.update(changes)

    def request(self, path: str) -> dict[str, Any]:
        if path == "/actions/runs/7":
            return self.run
        if path == "/actions/runs/7/artifacts?name=release-files":
            return {"artifacts": self.artifacts}
        if path == "/git/ref/tags/main" and not self.main_tag:
            raise urllib.error.HTTPError(path, 404, "Not Found", Message(), None)
        if path == "/git/ref/tags/main":
            return {}
        if path == "/git/ref/tags/v0.1.0":
            if self.tag is None:
                raise urllib.error.HTTPError(path, 404, "Not Found", Message(), None)
            return self.tag
        raise AssertionError(path)

    def pages(self, path: str) -> list[dict[str, Any]]:
        assert path == "/releases"
        return [self.release]


class RunTests(unittest.TestCase):
    def check(self, **run: Any) -> None:
        api = API(**run.pop("api", {}))
        api.run.update(run)
        namespace["verify_run"](api, "build.yml", "7", SHA)

    def test_matching_runs_are_accepted(self) -> None:
        self.check()
        self.check(event="workflow_dispatch", path=".github/workflows/build.yml")

    def test_wrong_sha_workflow_trigger_branch_repository_or_result_is_refused(self) -> None:
        cases: dict[str, dict[str, Any]] = {
            "wrong sha": {"head_sha": OTHER},
            "other workflow": {"path": ".github/workflows/other.yml@refs/heads/main"},
            "pull request trigger": {"event": "pull_request"},
            "other branch": {"head_branch": "topic"},
            "fork": {"head_repository": {"full_name": "someone/ejm-cli"}},
            "failed": {"conclusion": "failure"},
            "unfinished": {"status": "in_progress", "conclusion": None},
            "branch is a tag named main": {"api": {"main_tag": True}},
            "no release-files artifact": {"api": {"artifacts": []}},
            "expired artifact": {"api": {"artifacts": [{"name": "release-files", "expired": True}]}},
            "two release-files artifacts": {"api": {"artifacts": [{"name": "release-files", "expired": False}] * 2}},
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.check(**change)

    def test_unsafe_inputs_are_refused(self) -> None:
        for workflow, run_id, sha in (("../build.yml", "7", SHA), ("build.yml", "7/x", SHA), ("build.yml", "7", "main")):
            with self.subTest(workflow=workflow, run_id=run_id), self.assertRaises(ValueError):
                namespace["verify_run"](API(), workflow, run_id, sha)

    def test_draft_needs_a_lightweight_tag_on_the_commit(self) -> None:
        verify = namespace["verify_draft"]
        self.assertTrue(verify(API(), "v0.1.0", SHA)["draft"])
        cases: dict[str, dict[str, Any]] = {
            "other commit": {"tag": {"object": {"type": "commit", "sha": OTHER}}},
            "annotated tag": {"tag": {"object": {"type": "tag", "sha": SHA}}},
            "published": {"release": {"tag_name": "v0.1.0", "draft": False, "assets": []}},
            "no release": {"release": {"tag_name": "v0.2.0", "draft": True, "assets": []}},
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                verify(API(**change), "v0.1.0", SHA)


class DigestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.built = self.work / "built"
        self.built.mkdir()
        self.data = {"ejm-cli-0.1.0-linux-x86_64.tar.gz": b"linux", "ejm-cli-0.1.0-macos-arm64.tar.gz": b"macos"}
        for name, data in self.data.items():
            (self.built / name).write_bytes(data)
        self.write_manifest()
        self.calls: list[tuple[str, ...]] = []

    def write_manifest(self, **overrides: str) -> None:
        lines = "".join(f"{overrides.get(name, digest(data))}  {name}\n" for name, data in self.data.items())
        (self.built / "build-sha256.txt").write_text(lines)

    def attach(self, release: dict[str, Any] | None = None) -> None:
        namespace["attach"](API(), self.built, "v0.1.0", release or {"assets": [{"name": "source.zip"}]}, run_gh=lambda *args: self.calls.append(args))

    def test_matching_digests_upload_files_then_the_checksum_list(self) -> None:
        self.attach()
        self.assertEqual([call[1] for call in self.calls], ["upload", "upload"])
        self.assertIn("--clobber", self.calls[1])
        sums = (self.work / "SHA256SUMS").read_text()
        for name, data in self.data.items():
            self.assertIn(f"{digest(data)}  {name}\n", sums)
        self.assertNotIn("build-sha256.txt", sums)

    def test_changed_file_refuses_every_upload(self) -> None:
        (self.built / "ejm-cli-0.1.0-linux-x86_64.tar.gz").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Digest changed"):
            self.attach()
        self.assertEqual(self.calls, [])

    def test_wrong_manifest_digest_refuses_every_upload(self) -> None:
        self.write_manifest(**{"ejm-cli-0.1.0-macos-arm64.tar.gz": "0" * 64})
        with self.assertRaisesRegex(ValueError, "Digest changed"):
            self.attach()
        self.assertEqual(self.calls, [])

    def test_extra_missing_unlisted_or_linked_files_are_refused(self) -> None:
        (self.built / "extra.bin").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "differ from the manifest"):
            self.attach()
        (self.built / "extra.bin").unlink()
        (self.built / "ejm-cli-0.1.0-macos-arm64.tar.gz").unlink()
        with self.assertRaisesRegex(ValueError, "differ from the manifest"):
            self.attach()
        (self.built / "ejm-cli-0.1.0-macos-arm64.tar.gz").symlink_to(self.built / "ejm-cli-0.1.0-linux-x86_64.tar.gz")
        self.write_manifest(**{"ejm-cli-0.1.0-macos-arm64.tar.gz": digest(b"linux")})
        with self.assertRaisesRegex(ValueError, "regular files"):
            self.attach()
        self.assertEqual(self.calls, [])

    def test_missing_or_unsafe_manifest_is_refused(self) -> None:
        for text in ("", "short  name\n", f"{digest(b'x')}  ../escape\n", f"{digest(b'x')}  SHA256SUMS\n", f"{digest(b'x')}  a+b\n"):
            (self.built / "build-sha256.txt").write_text(text)
            with self.subTest(text), self.assertRaises(ValueError):
                self.attach()
        (self.built / "build-sha256.txt").unlink()
        with self.assertRaisesRegex(ValueError, "no digest manifest"):
            self.attach()

    def test_subdirectory_in_the_artifact_is_refused(self) -> None:
        (self.built / "nested").mkdir()
        with self.assertRaisesRegex(ValueError, "differ from the manifest"):
            self.attach()
        (self.built / "nested").rmdir()
        self.data["nested"] = b""
        (self.built / "nested").mkdir()
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "regular files"):
            self.attach()
        self.assertEqual(self.calls, [])

    def test_existing_assets_are_never_replaced_and_existing_sums_are_extended(self) -> None:
        with self.assertRaisesRegex(ValueError, "replace an existing"):
            self.attach({"assets": [{"name": "ejm-cli-0.1.0-linux-x86_64.tar.gz"}]})
        self.assertEqual(self.calls, [])

        def fetch(*args: str) -> None:
            self.calls.append(args)
            if args[1] == "download":
                (self.work / "sums").mkdir()
                (self.work / "sums/SHA256SUMS").write_text(f"{'1' * 64}  source.zip\n")
        namespace["attach"](API(), self.built, "v0.1.0", {"assets": [{"name": "SHA256SUMS"}]}, run_gh=fetch)
        sums = (self.work / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(sums[0], f"{'1' * 64}  source.zip")
        self.assertEqual(len(sums), 3)
        with self.assertRaisesRegex(ValueError, "replace an existing"):
            namespace["merge_sums"](f"{digest(b'x')}  ejm-cli-0.1.0-linux-x86_64.tar.gz\n", {"ejm-cli-0.1.0-linux-x86_64.tar.gz": digest(b"y")})


class DispatchTests(unittest.TestCase):
    """main() runs the right checks for each workflow step."""
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.old_cwd, self.old_env, self.old_argv = Path.cwd(), dict(os.environ), list(sys.argv)
        self.addCleanup(self.restore)
        os.chdir(self.directory.name)
        os.environ.update(RELEASE_COMMIT=SHA, BUILD_WORKFLOW="build.yml", BUILD_RUN_ID="7", RELEASE_VERSION="0.1.0")
        self.api = API()
        self.calls: list[tuple[str, ...]] = []
        self.patches = [patch.dict(namespace, GitHub=lambda: self.api, gh=lambda *args: self.calls.append(args))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def restore(self) -> None:
        os.chdir(self.old_cwd)
        os.environ.clear()
        os.environ.update(self.old_env)
        sys.argv[:] = self.old_argv

    def run_main(self, mode: str) -> None:
        sys.argv[1:] = [mode]
        namespace["main"]()

    def test_verify_needs_neither_tag_nor_draft(self) -> None:
        self.api.tag, self.api.release = None, {"tag_name": "v0.1.0", "draft": False, "assets": []}
        self.run_main("verify")

    def test_check_verifies_run_and_draft_without_touching_files(self) -> None:
        self.run_main("check")
        self.api.run["head_sha"] = OTHER
        with self.assertRaisesRegex(ValueError, "different commit"):
            self.run_main("check")
        self.api.run["head_sha"], self.api.release["draft"] = SHA, False
        with self.assertRaisesRegex(ValueError, "draft"):
            self.run_main("check")
        self.assertEqual(self.calls, [])

    def test_attach_reverifies_before_any_digest_or_upload(self) -> None:
        self.api.run["head_sha"] = OTHER
        with self.assertRaisesRegex(ValueError, "different commit"):
            self.run_main("attach")
        self.api.run["head_sha"], self.api.tag = SHA, {"object": {"type": "commit", "sha": OTHER}}
        with self.assertRaisesRegex(ValueError, "Tag"):
            self.run_main("attach")
        self.assertEqual(self.calls, [])

    def test_attach_uploads_verified_files_and_bad_modes_or_versions_are_refused(self) -> None:
        built = Path("built")
        built.mkdir()
        (built / "tool.tar.gz").write_bytes(b"x")
        (built / "build-sha256.txt").write_text(f"{digest(b'x')}  tool.tar.gz\n")
        self.run_main("attach")
        self.assertEqual(len(self.calls), 2)
        with self.assertRaises(ValueError):
            self.run_main("other")
        os.environ["RELEASE_VERSION"] = "1.0"
        with self.assertRaisesRegex(ValueError, "SemVer"):
            self.run_main("check")


if __name__ == "__main__":
    unittest.main()
