import hashlib
import json
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
for name in ("governance.py", "versioning.py", "attach.py"):
    text = (ROOT / "scripts" / name).read_text().split('\nif __name__ == "__main__":')[0]
    exec(compile(text, name, "exec"), namespace)  # noqa: S102 - scripts run in one shared namespace, as embedded in the workflow
SHA, OTHER = "a" * 40, "b" * 40


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_draft(**changes: Any) -> dict[str, Any]:
    return {"id": 1, "tag_name": "v0.1.0", "draft": True, "target_commitish": SHA, "assets": [], **changes}


class API:
    repo = "ejmlabs/ejm-cli"
    releases: list[dict[str, Any]] | None = None
    # The listing from the second call on, to change the draft between the first check and the upload.
    later: list[dict[str, Any]] | None = None

    def __init__(self, **changes: Any) -> None:
        self.run = {"path": ".github/workflows/build.yml@refs/heads/main", "event": "push", "head_branch": "main", "head_sha": SHA,
                    "head_repository": {"full_name": self.repo}, "status": "completed", "conclusion": "success"}
        # GitHub creates the tag when a human publishes the draft, so none exists while it is a draft.
        self.tag: dict[str, Any] | None = None
        self.main_tag, self.artifacts = False, [{"name": "release-files", "expired": False}]
        self.release = new_draft()
        self.listed = 0
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
        self.listed += 1
        if self.later is not None and self.listed > 1:
            return self.later
        return self.releases if self.releases is not None else [self.release]


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

    def test_draft_binds_to_the_tag_name_and_the_commit_and_no_tag_exists_yet(self) -> None:
        verify = namespace["verify_draft"]
        self.assertTrue(verify(API(), "v0.1.0", SHA)["draft"])
        cases: dict[str, dict[str, Any]] = {
            "targets another commit": {"release": new_draft(target_commitish=OTHER)},
            "targets a branch": {"release": new_draft(target_commitish="main")},
            "targets nothing": {"release": {key: value for key, value in new_draft().items() if key != "target_commitish"}},
            "published": {"release": new_draft(draft=False)},
            "no release": {"release": new_draft(tag_name="v0.2.0")},
            "tag created before the publication, on the commit": {"tag": {"object": {"type": "commit", "sha": SHA}}},
            "tag created before the publication, elsewhere": {"tag": {"object": {"type": "commit", "sha": OTHER}}},
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                verify(API(**change), "v0.1.0", SHA)

    def test_a_tag_lookup_that_fails_for_another_reason_is_not_read_as_no_tag(self) -> None:
        class Failing(API):
            def request(self, path: str) -> dict[str, Any]:
                if path == "/git/ref/tags/v0.1.0":
                    raise urllib.error.HTTPError(path, 403, "Forbidden", Message(), None)
                return super().request(path)

        with self.assertRaises(urllib.error.HTTPError):
            namespace["verify_draft"](Failing(), "v0.1.0", SHA)

    def test_two_releases_for_one_tag_are_refused_even_when_both_are_drafts(self) -> None:
        verify = namespace["verify_draft"]
        draft = new_draft()
        other = new_draft(tag_name="v0.2.0")
        for name, releases in {
            "two drafts": [draft, {**draft, "assets": [{"name": "source.zip"}]}],
            "a draft and a published release": [draft, {**draft, "draft": False}],
            "a published release first": [{**draft, "draft": False}, draft],
        }.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, "exactly one draft"):
                verify(API(releases=releases), "v0.1.0", SHA)
        # Drafts for other tags do not matter.
        self.assertEqual(verify(API(releases=[other, draft]), "v0.1.0", SHA), draft)


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

    def attach(self, release: dict[str, Any] | None = None, api: API | None = None) -> dict[str, str]:
        release = release or new_draft(assets=[{"name": "source.zip"}])
        result: dict[str, str] = namespace["attach"](api or API(releases=[release]), self.built, "v0.1.0", SHA, release, run_gh=lambda *args: self.calls.append(args))
        return result

    def test_matching_digests_upload_files_then_the_checksum_list(self) -> None:
        self.attach()
        self.assertEqual([call[1] for call in self.calls], ["upload", "upload"])
        self.assertIn("--clobber", self.calls[1])
        sums = (self.work / "SHA256SUMS").read_text()
        for name, data in self.data.items():
            self.assertIn(f"{digest(data)}  {name}\n", sums)
        self.assertNotIn("build-sha256.txt", sums)

    def test_attach_returns_the_digest_of_every_file_in_the_build_output_including_the_manifest(self) -> None:
        attested = self.attach()
        expected = {name: digest(data) for name, data in self.data.items()}
        expected["build-sha256.txt"] = digest((self.built / "build-sha256.txt").read_bytes())
        self.assertEqual(attested, expected)
        self.assertEqual(namespace["digests"](self.built), expected)

    def test_the_draft_is_read_again_right_before_the_first_upload(self) -> None:
        release = new_draft(assets=[{"name": "source.zip"}])
        # The listing at the second read: published, replaced by another draft, or changed assets since the first check. Nothing is uploaded.
        for name, later in {
            "published meanwhile": [new_draft(draft=False, assets=release["assets"])],
            "another draft took its place": [new_draft(id=2, assets=release["assets"])],
            "an asset appeared": [new_draft(assets=[{"name": "source.zip"}, {"name": "extra.bin"}])],
            "the target moved": [new_draft(target_commitish=OTHER, assets=release["assets"])],
            "two drafts now": [new_draft(assets=release["assets"]), new_draft(id=2, assets=release["assets"])],
        }.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.attach(release, API(releases=later))
            self.assertEqual(self.calls, [])
        with self.assertRaisesRegex(ValueError, "tag exists"):
            self.attach(release, API(releases=[release], tag={"object": {"type": "commit", "sha": SHA}}))
        self.assertEqual(self.calls, [])
        self.attach(release, API(releases=[release]))
        self.assertEqual(len(self.calls), 2)

    def test_confirm_requires_every_digest_to_equal_the_attached_digests(self) -> None:
        confirm = namespace["confirm"]
        attached = json.dumps(self.attach())
        self.calls.clear()
        confirm(self.built, attached)
        confirm(self.built, json.dumps(json.loads(attached), sort_keys=True, indent=2))
        digests = json.loads(attached)
        name = "ejm-cli-0.1.0-linux-x86_64.tar.gz"
        wrong: dict[str, str] = {
            "a different digest": json.dumps({**digests, name: "0" * 64}),
            "a different manifest digest": json.dumps({**digests, "build-sha256.txt": "0" * 64}),
            "a missing file": json.dumps({key: value for key, value in digests.items() if key != name}),
            "an extra file": json.dumps({**digests, "extra.bin": "1" * 64}),
            "not a mapping": json.dumps(list(digests.values())),
            "empty": "{}",
            "null": "null",
        }
        for case, text in wrong.items():
            with self.subTest(case), self.assertRaisesRegex(ValueError, "differ from the files the attach job attached"):
                confirm(self.built, text)
        with self.assertRaises(ValueError):
            confirm(self.built, "not json")
        # A swapped file or manifest is caught by the recomputation before the comparison.
        (self.built / name).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Digest changed"):
            confirm(self.built, attached)
        (self.built / name).write_bytes(self.data[name])
        self.data[name] = b"other"
        (self.built / name).write_bytes(b"other")
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "differ from the files the attach job attached"):
            confirm(self.built, attached)

    def test_output_is_one_json_line_that_cannot_add_another_output(self) -> None:
        output = self.work / "output"
        old = os.environ.get("GITHUB_OUTPUT")
        os.environ["GITHUB_OUTPUT"] = str(output)
        self.addCleanup(lambda: os.environ.pop("GITHUB_OUTPUT") if old is None else os.environ.update(GITHUB_OUTPUT=old))
        namespace["write_output"]("digests", {"a\nevil=1": "0" * 64, "b": "1" * 64})
        lines = output.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("digests="))
        self.assertEqual(json.loads(lines[0].removeprefix("digests=")), {"a\nevil=1": "0" * 64, "b": "1" * 64})

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
            self.attach(new_draft(assets=[{"name": "ejm-cli-0.1.0-linux-x86_64.tar.gz"}]))
        self.assertEqual(self.calls, [])

        def fetch(*args: str) -> None:
            self.calls.append(args)
            if args[1] == "download":
                (self.work / "sums").mkdir()
                (self.work / "sums/SHA256SUMS").write_text(f"{'1' * 64}  source.zip\n")
        release = new_draft(assets=[{"name": "SHA256SUMS"}])
        namespace["attach"](API(releases=[release]), self.built, "v0.1.0", SHA, release, run_gh=fetch)
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

    def build_output(self) -> None:
        built = Path("built")
        built.mkdir()
        (built / "tool.tar.gz").write_bytes(b"x")
        (built / "build-sha256.txt").write_text(f"{digest(b'x')}  tool.tar.gz\n")

    def test_verify_needs_neither_tag_nor_draft(self) -> None:
        self.api.tag, self.api.release = None, new_draft(draft=False)
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
        self.api.run["head_sha"], self.api.release["target_commitish"] = SHA, OTHER
        with self.assertRaisesRegex(ValueError, "target the release commit"):
            self.run_main("attach")
        self.api.release["target_commitish"], self.api.tag = SHA, {"object": {"type": "commit", "sha": SHA}}
        with self.assertRaisesRegex(ValueError, "tag exists"):
            self.run_main("attach")
        self.assertEqual(self.calls, [])

    def test_two_drafts_for_the_tag_stop_check_and_attach_before_any_upload(self) -> None:
        self.build_output()
        draft = new_draft()
        self.api.releases = [draft, dict(draft)]
        for mode in ("check", "attach"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "exactly one draft"):
                self.run_main(mode)
        self.assertEqual(self.calls, [])

    def test_a_draft_published_between_the_check_and_the_upload_stops_attach(self) -> None:
        self.build_output()
        self.api.later = [new_draft(draft=False)]
        with self.assertRaisesRegex(ValueError, "exactly one draft"):
            self.run_main("attach")
        self.assertEqual(self.calls, [])

    def test_attach_uploads_verified_files_and_bad_modes_or_versions_are_refused(self) -> None:
        self.build_output()
        output = Path("github-output")
        os.environ["GITHUB_OUTPUT"] = str(output)
        self.run_main("attach")
        self.assertEqual(len(self.calls), 2)
        # The job passes the verified digests, the manifest's included, to the attestation job.
        (line,) = output.read_text().splitlines()
        self.assertEqual(json.loads(line.removeprefix("digests=")), {"tool.tar.gz": digest(b"x"), "build-sha256.txt": digest(Path("built/build-sha256.txt").read_bytes())})
        with self.assertRaises(ValueError):
            self.run_main("other")
        os.environ["RELEASE_VERSION"] = "1.0"
        with self.assertRaisesRegex(ValueError, "SemVer"):
            self.run_main("check")

    def test_confirm_needs_only_the_run_and_the_attached_digests_and_never_touches_the_release(self) -> None:
        self.build_output()
        del os.environ["RELEASE_VERSION"]
        attached = json.dumps({"tool.tar.gz": digest(b"x"), "build-sha256.txt": digest(Path("built/build-sha256.txt").read_bytes())})
        with self.assertRaises(KeyError):
            self.run_main("confirm")
        os.environ["ATTACHED_DIGESTS"] = attached
        # A draft that does not exist, or a tag that does, is none of the attestation job's business.
        self.api.releases, self.api.tag = [], {"object": {"type": "commit", "sha": OTHER}}
        self.run_main("confirm")
        os.environ["ATTACHED_DIGESTS"] = attached.replace(digest(b"x"), "0" * 64)
        with self.assertRaisesRegex(ValueError, "differ from the files the attach job attached"):
            self.run_main("confirm")
        os.environ["ATTACHED_DIGESTS"] = attached
        self.api.run["head_sha"] = OTHER
        with self.assertRaisesRegex(ValueError, "different commit"):
            self.run_main("confirm")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
