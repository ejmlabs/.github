import hashlib
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
namespace = {"__name__": "attach_test_library"}
for name in ("governance.py", "attach.py"):
    text = (ROOT / "scripts" / name).read_text().split('\nif __name__ == "__main__":')[0]
    exec(compile(text, name, "exec"), namespace)
SHA, OTHER = "a" * 40, "b" * 40
digest = lambda data: hashlib.sha256(data).hexdigest()


class API:
    repo = "ejmlabs/ejm-cli"

    def __init__(self, **changes):
        self.run = {"path": ".github/workflows/build.yml@refs/heads/main", "event": "push", "head_branch": "main", "head_sha": SHA,
                    "head_repository": {"full_name": self.repo}, "status": "completed", "conclusion": "success"}
        self.tag = {"object": {"type": "commit", "sha": SHA}}
        self.release = {"tag_name": "v0.1.0", "draft": True, "assets": []}
        self.__dict__.update(changes)

    def request(self, path):
        if path == "/actions/runs/7": return self.run
        if path == "/git/ref/tags/v0.1.0":
            if self.tag is None: raise urllib.error.HTTPError(path, 404, "Not Found", None, None)
            return self.tag
        raise AssertionError(path)

    def pages(self, path):
        assert path == "/releases"
        return [self.release]


class RunTests(unittest.TestCase):
    def check(self, **run):
        api = API()
        api.run.update(run)
        namespace["verify_run"](api, "build.yml", "7", SHA)

    def test_matching_runs_are_accepted(self):
        self.check()
        self.check(event="workflow_dispatch", path=".github/workflows/build.yml")

    def test_wrong_sha_workflow_trigger_branch_repository_or_result_is_refused(self):
        for name, change in {
            "wrong sha": {"head_sha": OTHER},
            "other workflow": {"path": ".github/workflows/other.yml@refs/heads/main"},
            "pull request trigger": {"event": "pull_request"},
            "other branch": {"head_branch": "topic"},
            "fork": {"head_repository": {"full_name": "someone/ejm-cli"}},
            "failed": {"conclusion": "failure"},
            "unfinished": {"status": "in_progress", "conclusion": None},
        }.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.check(**change)

    def test_unsafe_inputs_are_refused(self):
        for workflow, run_id, sha in (("../build.yml", "7", SHA), ("build.yml", "7/x", SHA), ("build.yml", "7", "main")):
            with self.subTest(workflow=workflow, run_id=run_id), self.assertRaises(ValueError):
                namespace["verify_run"](API(), workflow, run_id, sha)

    def test_draft_needs_a_lightweight_tag_on_the_commit(self):
        verify = namespace["verify_draft"]
        self.assertTrue(verify(API(), "v0.1.0", SHA)["draft"])
        for name, change in {
            "other commit": {"tag": {"object": {"type": "commit", "sha": OTHER}}},
            "annotated tag": {"tag": {"object": {"type": "tag", "sha": SHA}}},
            "published": {"release": {"tag_name": "v0.1.0", "draft": False, "assets": []}},
            "no release": {"release": {"tag_name": "v0.2.0", "draft": True, "assets": []}},
        }.items():
            with self.subTest(name), self.assertRaises(ValueError):
                verify(API(**change), "v0.1.0", SHA)


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.built = self.work / "built"
        self.built.mkdir()
        self.data = {"ejm-cli-0.1.0-linux-x86_64.tar.gz": b"linux", "ejm-cli-0.1.0-macos-arm64.tar.gz": b"macos"}
        for name, data in self.data.items(): (self.built / name).write_bytes(data)
        self.write_manifest()
        self.calls = []

    def write_manifest(self, **overrides):
        lines = "".join(f"{overrides.get(name, digest(data))}  {name}\n" for name, data in self.data.items())
        (self.built / "build-sha256.txt").write_text(lines)

    def attach(self, release=None):
        namespace["attach"](API(), self.built, "v0.1.0", release or {"assets": [{"name": "source.zip"}]}, run_gh=lambda *args: self.calls.append(args))

    def test_matching_digests_upload_files_then_the_checksum_list(self):
        self.attach()
        self.assertEqual([call[1] for call in self.calls], ["upload", "upload"])
        self.assertIn("--clobber", self.calls[1])
        sums = (self.work / "SHA256SUMS").read_text()
        for name, data in self.data.items(): self.assertIn(f"{digest(data)}  {name}\n", sums)
        self.assertNotIn("build-sha256.txt", sums)

    def test_changed_file_refuses_every_upload(self):
        (self.built / "ejm-cli-0.1.0-linux-x86_64.tar.gz").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Digest changed"):
            self.attach()
        self.assertEqual(self.calls, [])

    def test_wrong_manifest_digest_refuses_every_upload(self):
        self.write_manifest(**{"ejm-cli-0.1.0-macos-arm64.tar.gz": "0" * 64})
        with self.assertRaisesRegex(ValueError, "Digest changed"):
            self.attach()
        self.assertEqual(self.calls, [])

    def test_extra_missing_unlisted_or_linked_files_are_refused(self):
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

    def test_missing_or_unsafe_manifest_is_refused(self):
        for text in ("", "short  name\n", f"{digest(b'x')}  ../escape\n", f"{digest(b'x')}  SHA256SUMS\n"):
            (self.built / "build-sha256.txt").write_text(text)
            with self.subTest(text), self.assertRaises(ValueError):
                self.attach()
        (self.built / "build-sha256.txt").unlink()
        with self.assertRaisesRegex(ValueError, "no digest manifest"):
            self.attach()

    def test_existing_assets_are_never_replaced_and_existing_sums_are_extended(self):
        with self.assertRaisesRegex(ValueError, "replace an existing"):
            self.attach({"assets": [{"name": "ejm-cli-0.1.0-linux-x86_64.tar.gz"}]})
        self.assertEqual(self.calls, [])

        def fetch(*args):
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


if __name__ == "__main__":
    unittest.main()
