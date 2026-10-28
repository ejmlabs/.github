import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from batch import load
from carry_over import carry, changed_files, overlapping, patch_id, review_request

PR = "https://github.com/ejmlabs/ejm-cli/pull/7"
OLD = "a" * 40
NEW = "b" * 40
PATCH = "c" * 40


def git(repo, *args):
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", "PATH": "/usr/bin:/bin"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env).stdout.strip()


def batch(**item):
    return load(json.dumps({"items": [{"pr": PR, "branch": "one", "head": OLD, "patch_id": PATCH, "pass": {"id": "r1", "head": OLD, "tree": OLD}, **item}]}))


class CarryOverTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("a\n")
        (self.repo / "b.txt").write_text("b\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")
        git(self.repo, "checkout", "-qb", "feature")
        (self.repo / "a.txt").write_text("a changed\n")
        git(self.repo, "commit", "-qam", "feature")
        self.reviewed = git(self.repo, "rev-parse", "HEAD")
        self.before = patch_id(self.repo, "main", "feature")

    def move_main(self):
        git(self.repo, "checkout", "-q", "main")
        (self.repo / "b.txt").write_text("b moved\n")
        git(self.repo, "commit", "-qam", "other merge")
        git(self.repo, "checkout", "-q", "feature")
        git(self.repo, "merge", "-q", "--no-edit", "main")

    def test_a_merge_of_main_keeps_the_patch_id_and_changes_the_head(self):
        self.move_main()
        self.assertNotEqual(git(self.repo, "rev-parse", "HEAD"), self.reviewed)
        self.assertEqual(patch_id(self.repo, "main", "feature"), self.before)
        request = review_request(self.repo, PR, "feature")
        self.assertEqual(request["tree"], git(self.repo, "rev-parse", "feature^{tree}"))

    def test_a_changed_patch_has_a_different_id(self):
        self.move_main()
        (self.repo / "a.txt").write_text("a changed again\n")
        git(self.repo, "commit", "-qam", "edit")
        self.assertNotEqual(patch_id(self.repo, "main", "feature"), self.before)
        self.assertEqual(changed_files(self.repo, "main", "feature"), {"a.txt"})

    def approved(self, **item):
        return batch(**{"head": self.reviewed, "patch_id": self.before, "pass": {"id": "r1", "head": self.reviewed, "tree": OLD}, **item})

    def fresh(self, **change):
        head = git(self.repo, "rev-parse", "feature")
        return head, {"id": "r2", "head": head, "tree": git(self.repo, "rev-parse", "feature^{tree}"), **change}

    def test_an_identical_patch_with_a_fresh_pass_keeps_the_ok(self):
        self.move_main()
        head, fresh = self.fresh()
        record, reason = carry(self.approved(), self.repo, PR, head, fresh, "main")
        self.assertIsNone(reason)
        self.assertEqual(record, {"pr": PR, "head": head, "patch_id": self.before, "pass": fresh})

    def test_a_changed_patch_needs_a_new_approval(self):
        self.move_main()
        (self.repo / "a.txt").write_text("a changed again\n")
        git(self.repo, "commit", "-qam", "edit")
        head, fresh = self.fresh()
        self.assertIn("the patch changed", carry(self.approved(), self.repo, PR, head, fresh, "main")[1])

    def test_a_patch_that_only_moves_indentation_is_a_different_patch(self):
        git(self.repo, "checkout", "-q", "main")
        (self.repo / "w.yml").write_text("jobs:\n  one:\n    steps: []\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "workflow")
        for name, text in (("inner", "jobs:\n  one:\n    steps: []\n    permissions: write\n"), ("outer", "jobs:\n  one:\n    steps: []\npermissions: write\n")):
            git(self.repo, "checkout", "-q", "-b", name, "main")
            (self.repo / "w.yml").write_text(text)
            git(self.repo, "commit", "-qam", name)
        inner, outer = patch_id(self.repo, "main", "inner"), patch_id(self.repo, "main", "outer")
        self.assertNotEqual(inner, outer)
        head = git(self.repo, "rev-parse", "outer")
        fresh = {"id": "r2", "head": head, "tree": git(self.repo, "rev-parse", "outer^{tree}")}
        self.assertIn("the patch changed", carry(batch(patch_id=inner), self.repo, PR, head, fresh, "main")[1])

    def test_the_new_pass_must_name_the_new_head_and_the_tree_git_computes(self):
        self.move_main()
        head, good = self.fresh()
        for fresh in (None, {**good, "head": OLD}, {**good, "tree": OLD}, {**good, "tree": None}, {**good, "id": ""}):
            with self.subTest(fresh=fresh):
                self.assertIn("no fresh review", carry(self.approved(), self.repo, PR, head, fresh, "main")[1])

    def test_an_item_without_a_recorded_patch_id_never_carries_over(self):
        head, fresh = self.fresh()
        self.assertIn("no patch id", carry(self.approved(patch_id=None), self.repo, PR, head, fresh, "main")[1])

    def carry_cli(self, head, fresh, *extra):
        file = self.repo.parent / (self.repo.name + ".batch.json")
        self.out = self.repo.parent / (self.repo.name + ".next.json")
        for name in (file, self.out):
            self.addCleanup(name.unlink, missing_ok=True)
        file.write_text(json.dumps({"items": [{"pr": PR, "branch": "one", "head": self.reviewed, "patch_id": self.before, "pass": {"id": "r1", "head": self.reviewed, "tree": OLD}}]}))
        self.original = file.read_bytes()
        self.file = file
        script = str(Path(__file__).resolve().parents[1] / "scripts/carry_over.py")
        return subprocess.run([sys.executable, script, "carry", str(file), str(self.repo), PR, head, json.dumps(fresh), *(extra or [str(self.out)])], capture_output=True, text=True)

    def test_carry_computes_its_base_from_origin_main_and_takes_none_from_the_caller(self):
        self.move_main()
        git(self.repo, "update-ref", "refs/remotes/origin/main", "main")
        head, fresh = self.fresh()
        done = self.carry_cli(head, fresh)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.carry_cli(head, fresh, "main", str(self.out)).returncode, 1)

    def test_a_carried_head_is_written_as_a_new_batch_to_sign_again(self):
        self.move_main()
        git(self.repo, "update-ref", "refs/remotes/origin/main", "main")
        head, fresh = self.fresh()
        self.assertEqual(self.carry_cli(head, fresh).returncode, 0)
        item = json.loads(self.out.read_text())["items"][0]
        self.assertEqual((item["head"], item["pass"], item["patch_id"]), (head, fresh, self.before))
        self.assertEqual(self.file.read_bytes(), self.original)
        self.assertFalse(Path(str(self.file) + ".carried.json").exists())
        written = self.out.read_bytes()
        again = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/carry_over.py"), "carry", str(self.file), str(self.repo), PR, head, json.dumps(fresh), str(self.out)],
                               capture_output=True, text=True)
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual(self.out.read_bytes(), written)

    def test_an_unapproved_commit_under_the_approved_patch_is_not_carried(self):
        git(self.repo, "update-ref", "refs/remotes/origin/main", "main")
        git(self.repo, "checkout", "-q", "-b", "rebuilt", "main")
        (self.repo / "evil.py").write_text("print('x')\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "unapproved")
        unapproved = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "a.txt").write_text("a changed\n")
        git(self.repo, "commit", "-qam", "feature")
        head, fresh = git(self.repo, "rev-parse", "HEAD"), None
        fresh = {"id": "r2", "head": head, "tree": git(self.repo, "rev-parse", "HEAD^{tree}")}
        self.assertEqual(patch_id(self.repo, unapproved, head), self.before)
        done = self.carry_cli(head, fresh)
        self.assertEqual(done.returncode, 1)
        self.assertIn("the patch changed", done.stderr)

    def test_overlapping_files_are_reported(self):
        self.assertEqual(overlapping({"one": {"a", "b"}, "two": {"c"}}), {})
        self.assertEqual(overlapping({"one": {"a", "b"}, "two": {"b"}, "three": {"b", "a"}}), {"a": ["one", "three"], "b": ["one", "two", "three"]})


if __name__ == "__main__":
    unittest.main()
