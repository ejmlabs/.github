import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch import Refused, load
from deploy_record import decide, decide_approved, merged_tree, record_deploy
from signing import Signer, needs_ssh_keygen
from test_carry_over import git

REPO = "ejmlabs/ejmlabs"
SIBLING = "c" * 40


def batch(deploy=True, **change):
    document = {"items": []}
    if deploy:
        document["deploy"] = {"repo": REPO, "tree": TREE, "pass": {"id": "r1", "tree": TREE}, "siblings": {"ejm-ui": SIBLING}, **change}
    return load(json.dumps(document))


TREE = None


class DeployTests(unittest.TestCase):
    def setUp(self):
        global TREE
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("reviewed\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "reviewed")
        self.commit = git(self.repo, "rev-parse", "main")
        TREE = git(self.repo, "rev-parse", "main^{tree}")

    def decide(self, group=None, commit=None, siblings=None):
        return decide(group or batch(), REPO, self.repo, commit or self.commit, {"ejm-ui": SIBLING} if siblings is None else siblings, "main")

    def test_the_reviewed_tree_at_the_tip_of_main_with_sibling_pins_deploys(self):
        self.assertEqual(self.decide()["repo"], REPO)

    def test_a_commit_whose_tree_is_not_the_reviewed_one_does_not_deploy(self):
        (self.repo / "a.txt").write_text("changed\n")
        git(self.repo, "commit", "-qam", "other")
        with self.assertRaisesRegex(Refused, "not the reviewed tree"):
            self.decide(commit=git(self.repo, "rev-parse", "main"))

    def test_a_commit_that_is_not_the_tip_of_main_does_not_deploy(self):
        (self.repo / "a.txt").write_text("changed\n")
        git(self.repo, "commit", "-qam", "other")
        with self.assertRaisesRegex(Refused, "is not the current main"):
            self.decide(commit=self.commit)

    def test_a_deploy_without_a_pass_for_the_reviewed_tree_does_not_deploy(self):
        for group in (batch(**{"pass": None}), batch(**{"pass": {"id": "r1", "tree": "d" * 40}})):
            with self.assertRaisesRegex(Refused, "No review"):
                self.decide(group)

    def test_a_sibling_off_its_pin_or_missing_does_not_deploy(self):
        for siblings in ({"ejm-ui": "d" * 40}, {}, {"ejm-ui": SIBLING, "other": SIBLING}):
            with self.assertRaisesRegex(Refused, "protected pins"):
                self.decide(siblings=siblings)

    def test_a_deploy_the_batch_does_not_name_is_refused(self):
        with self.assertRaisesRegex(Refused, "does not name a deploy"):
            self.decide(batch(deploy=False))
        with self.assertRaisesRegex(Refused, "does not name a deploy"):
            decide(batch(), "ejmlabs/ejm-cli", self.repo, self.commit, {"ejm-ui": SIBLING}, "main")

    def approved_file(self, group, sign=True):
        signer = Signer()
        self.addCleanup(signer.cleanup)
        file = signer.root / "batch.json"
        file.write_text(json.dumps({"items": [], "deploy": dict(group["deploy"])}))
        if sign:
            signer.sign(load(file.read_text()), file)
        return signer, file

    def decide_file(self, signer, file, **change):
        return decide_approved(file, signer.signers, "owner", REPO, self.repo, self.commit, {"ejm-ui": SIBLING}, "main")

    @needs_ssh_keygen
    def test_a_deploy_needs_the_signed_approval_as_well_as_the_pass_and_tree(self):
        signer, file = self.approved_file(batch())
        self.assertEqual(self.decide_file(signer, file)["repo"], REPO)
        unsigned = self.approved_file(batch(), sign=False)
        invented = self.approved_file(batch(**{"pass": {"id": "invented", "tree": TREE}}), sign=False)
        for other_signer, other_file in (unsigned, invented):
            with self.assertRaisesRegex(Refused, "needs"):
                self.decide_file(other_signer, other_file)
        edited = json.loads(file.read_text())
        edited["deploy"]["pass"] = {"id": "invented", "tree": TREE}
        file.write_text(json.dumps(edited))
        with self.assertRaisesRegex(Refused, "not signed by the owner"):
            self.decide_file(signer, file)

    @needs_ssh_keygen
    def test_a_signed_deploy_without_a_pass_record_is_refused(self):
        signer, file = self.approved_file(batch(**{"pass": None}))
        with self.assertRaisesRegex(Refused, "No review"):
            self.decide_file(signer, file)

    def test_a_malformed_deploy_is_rejected(self):
        for change in ({"repo": "someone/else"}, {"tree": "abc"}, {"siblings": {"ejm-ui": "main"}}):
            with self.assertRaises(ValueError):
                batch(**change)

    def test_each_deploy_records_the_previous_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deploys.jsonl"
            record_deploy(path, REPO, self.commit, TREE, "d" * 40, "2026-10-25T10:00:00Z")
            record_deploy(path, REPO, self.commit, TREE, None, "2026-10-25T11:00:00-07:00")
            first, second = map(json.loads, path.read_text().splitlines())
        self.assertEqual((first["commit"], first["tree"], first["previous"]), (self.commit, TREE, "d" * 40))
        self.assertEqual(second["at"], "2026-10-25T18:00:00+00:00")
        self.assertIsNone(second["previous"])
        with self.assertRaises(ValueError):
            record_deploy(path, REPO, self.commit, TREE, "main", "2026-10-25T10:00:00Z")

    def test_the_reviewed_tree_is_what_main_holds_after_the_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            git(repo, "init", "-q", "-b", "main")
            (repo / "a.txt").write_text("a\n")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "base")
            git(repo, "checkout", "-qb", "feature")
            (repo / "b.txt").write_text("b\n")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "feature")
            git(repo, "checkout", "-q", "main")
            predicted = merged_tree(repo, "main", "feature")
            git(repo, "merge", "-q", "--ff-only", "feature")
            self.assertEqual(git(repo, "rev-parse", "main^{tree}"), predicted)


if __name__ == "__main__":
    unittest.main()
