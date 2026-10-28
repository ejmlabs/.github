import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import batch as batch_module
from batch import Refused, canonical, digest, load, load_approved, push, reconcile
from signing import Signer, TOOL, needs_ssh_keygen

A, B, C = "a" * 40, "b" * 40, "c" * 40
ONE = "https://github.com/ejmlabs/ejm-cli/pull/7"
TWO = "https://github.com/ejmlabs/ejm-ide/pull/9"


def batch(**items):
    return load(json.dumps({"items": [
        {"pr": ONE, "branch": "one", "head": A, "pass": {"id": "r1", "head": A}},
        {"pr": TWO, "branch": "two", "head": B, **items}]}))


class BatchTests(unittest.TestCase):
    def test_a_moved_head_drops_the_item_and_says_why(self):
        kept, dropped = reconcile(batch(), {ONE: A, TWO: C})
        self.assertEqual([item["pr"] for item in kept["items"]], [ONE])
        self.assertEqual(len(dropped), 1)
        self.assertIn(TWO, dropped[0])
        self.assertIn(C, dropped[0])
        self.assertEqual(reconcile(batch(), {ONE: A})[0]["items"][0]["pr"], ONE)

    def test_only_the_listed_commit_of_the_listed_branch_and_repository_may_be_pushed(self):
        self.assertEqual(push(batch(), "ejmlabs/ejm-cli", "one", A)["pr"], ONE)
        for repo, branch, commit, reason in (("ejmlabs/ejm-cli", "one", C, "not " + C), ("ejmlabs/ejm-cli", "other", A, "lists no push"),
                                             ("ejmlabs/ejm-ide", "one", A, "lists no push"), ("elsewhere/ejm-cli", "one", A, "lists no push"),
                                             ("ejmlabs/ejm-cli", "one", "0" * 40, "deleting"), ("ejmlabs/ejm-cli", "one", "main", "full commit SHA"),
                                             ("ejmlabs/ejm-ide", "two", B, "No review")):
            with self.subTest(repo=repo, branch=branch, commit=commit):
                with self.assertRaisesRegex(Refused, reason):
                    push(batch(), repo, branch, commit)

    def test_a_force_push_is_refused_whatever_the_file_says(self):
        with self.assertRaisesRegex(Refused, "Force-push"):
            push(batch(), "ejmlabs/ejm-cli", "one", A, force=True)

    def test_a_push_needs_the_pass_for_the_exact_commit(self):
        with self.assertRaisesRegex(Refused, "covers " + A):
            push(batch(**{"pass": {"id": "r2", "head": A}}), "ejmlabs/ejm-ide", "two", B)

    @needs_ssh_keygen
    def test_the_command_exits_nonzero_on_a_refusal_and_logs_it(self):
        signer, file = self.signed()
        log = signer.root / "writes.jsonl"
        self.assertEqual(self.command(file, "push", signer.signers, "owner", "ejmlabs/ejm-cli", "one", A, BATCH_WRITE_LOG=str(log)).returncode, 0)
        self.assertFalse(log.exists())
        refused = self.command(file, "push", signer.signers, "owner", "ejmlabs/ejm-cli", "one", C, "--force", BATCH_WRITE_LOG=str(log))
        self.assertEqual(refused.returncode, 1)
        self.assertIn("Force-push", refused.stderr)
        self.assertEqual(json.loads(log.read_text())["outcome"], "refused")

    def test_the_refusal_log_is_written_when_python_runs_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            file, log = Path(directory) / "batch.json", Path(directory) / "writes.jsonl"
            file.write_text(json.dumps({"items": [{"pr": ONE, "branch": "one", "head": A, "pass": {"id": "r1", "head": A}}]}))
            script = str(Path(__file__).resolve().parents[1] / "scripts/batch.py")
            done = subprocess.run([sys.executable, "-I", script, str(file), "push", "signers", "owner", "ejmlabs/ejm-cli", "one", C], capture_output=True, text=True, env={"BATCH_WRITE_LOG": str(log)})
            self.assertEqual(done.returncode, 1)
            self.assertEqual(json.loads(log.read_text())["outcome"], "refused")

    @needs_ssh_keygen
    def test_push_and_reconcile_treat_an_unsigned_or_badly_signed_batch_as_empty(self):
        signer, file = self.signed()
        other = Signer()
        self.addCleanup(other.cleanup)
        operations = (("push", "ejmlabs/ejm-cli", "one", A), ("reconcile", ONE + "=" + A))
        for op, *rest in operations:
            self.assertEqual(self.command(file, op, signer.signers, "owner", *rest).returncode, 0)
        for op, *rest in operations:
            with self.subTest(op=op, case="wrong key"):
                done = self.command(file, op, other.signers, "owner", *rest)
                self.assertEqual(done.returncode, 1)
                self.assertIn("not signed by the owner", done.stderr)
            with self.subTest(op=op, case="wrong identity"):
                self.assertEqual(self.command(file, op, signer.signers, "operator", *rest).returncode, 1)
        edited = json.loads(file.read_text())
        edited["items"][0]["head"] = C
        edited["items"][0]["pass"]["head"] = C
        file.write_text(json.dumps(edited))
        for op, *rest in operations:
            with self.subTest(op=op, case="edited"):
                done = self.command(file, op, signer.signers, "owner", *rest)
                self.assertEqual(done.returncode, 1)
        self.assertEqual(self.command(file, "push", signer.signers, "owner", "ejmlabs/ejm-cli", "one", C).returncode, 1)
        Path(str(file) + ".sig").unlink()
        for op, *rest in operations:
            with self.subTest(op=op, case="unsigned"):
                done = self.command(file, op, signer.signers, "owner", *rest)
                self.assertEqual(done.returncode, 1)
                self.assertIn("needs", done.stderr)

    def test_a_default_branch_is_never_listed_or_pushed(self):
        item = {"pr": ONE, "branch": "main", "head": A, "pass": {"id": "r1", "head": A}}
        with self.assertRaisesRegex(ValueError, "never a default branch"):
            load(json.dumps({"items": [item]}))
        with self.assertRaisesRegex(Refused, "default branch"):
            push(batch(), "ejmlabs/ejm-cli", "main", A)

    def signed(self, text=None):
        signer = Signer()
        self.addCleanup(signer.cleanup)
        file = signer.root / "batch.json"
        file.write_text(text or json.dumps({"items": [{"pr": ONE, "branch": "one", "head": A, "patch_id": B, "pass": {"id": "r1", "head": A}}]}))
        signer.sign(load(file.read_text()), file)
        return signer, file

    def command(self, *args, **env):
        """Run batch.py's main in this process, so the tests' ssh-keygen path applies; returns the exit code and both streams."""
        out, err, code = io.TextIOWrapper(io.BytesIO(), encoding="utf-8"), io.StringIO(), 0
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err), mock.patch.dict(os.environ, env):
            try:
                batch_module.main([str(arg) for arg in args])
            except SystemExit as stop:
                code = stop.code if isinstance(stop.code, int) else 1
        out.flush()
        return SimpleNamespace(returncode=code, stdout=out.buffer.getvalue().decode(), stderr=err.getvalue())

    @needs_ssh_keygen
    def test_the_approval_is_the_owners_ssh_signature_over_the_canonical_batch(self):
        signer, file = self.signed()
        self.assertEqual(load_approved(file, signer.signers, "owner")["items"][0]["pr"], ONE)
        other = Signer()
        self.addCleanup(other.cleanup)
        for reason, signers, identity in (("not signed by the owner", other.signers, "owner"), ("not signed by the owner", signer.signers, "operator"),
                                          ("plain name", signer.signers, "a b")):
            with self.assertRaisesRegex(Refused, reason):
                load_approved(file, signers, identity)

    @needs_ssh_keygen
    def test_an_edited_unsigned_or_wrongly_scoped_batch_is_refused(self):
        signer, file = self.signed()
        edited = json.loads(file.read_text())
        edited["items"][0]["head"] = C
        edited["items"][0]["pass"]["head"] = C
        file.write_text(json.dumps(edited))
        with self.assertRaisesRegex(Refused, "not signed by the owner"):
            load_approved(file, signer.signers, "owner")
        Path(str(file) + ".sig").unlink()
        with self.assertRaisesRegex(Refused, "needs"):
            load_approved(file, signer.signers, "owner")
        wrong = Signer()
        self.addCleanup(wrong.cleanup)
        wrong.sign(load(file.read_text()), file)
        with self.assertRaisesRegex(Refused, "not signed by the owner"):
            load_approved(file, signer.signers, "owner")

    @needs_ssh_keygen
    def test_a_comment_is_not_an_approval(self):
        signer, file = self.signed()
        file.write_text(json.dumps({**json.loads(file.read_text()), "approval": "https://github.com/ejmlabs/ejm-cli/pull/7#issuecomment-55 " + digest(load(file.read_text()))}))
        Path(str(file) + ".sig").unlink()
        with self.assertRaisesRegex(Refused, "needs"):
            load_approved(file, signer.signers, "owner")

    @needs_ssh_keygen
    def test_a_signature_for_another_namespace_or_over_a_digest_line_is_refused(self):
        signer, file = self.signed()
        for namespace, content in (("other", canonical(load(file.read_text()))), ("ejmlabs-batch", (digest(load(file.read_text())) + "\n").encode())):
            data = signer.root / "to-sign"
            data.write_bytes(content)
            Path(str(file) + ".sig").unlink()
            subprocess.run([TOOL, "-Y", "sign", "-f", str(signer.key), "-n", namespace, str(data)], check=True, capture_output=True)
            shutil.move(str(data) + ".sig", str(file) + ".sig")
            with self.assertRaisesRegex(Refused, "not signed by the owner"):
                load_approved(file, signer.signers, "owner")

    @needs_ssh_keygen
    def test_the_owner_signs_the_file_the_canonical_command_writes(self):
        signer, file = self.signed()
        shown = self.command(file, "canonical")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        sent = signer.root / "batch-to-sign.json"
        sent.write_text(shown.stdout)
        self.assertEqual(sent.read_bytes(), canonical(load(file.read_text())))
        Path(str(file) + ".sig").unlink()
        subprocess.run([TOOL, "-Y", "sign", "-f", str(signer.key), "-n", "ejmlabs-batch", str(sent)], check=True, capture_output=True)
        shutil.move(str(sent) + ".sig", str(file) + ".sig")
        done = self.command(file, "verify", signer.signers, "owner")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_fake_ssh_keygen_first_on_path_approves_nothing(self):
        self.assertTrue(batch_module.SSH_KEYGEN.startswith("/") or TOOL)
        with tempfile.TemporaryDirectory() as directory:
            fake, called = Path(directory) / "ssh-keygen", Path(directory) / "called"
            fake.write_text(f"#!/bin/sh\ntouch {called}\nexit 0\n")
            fake.chmod(0o755)
            file = Path(directory) / "batch.json"
            file.write_text(json.dumps({"items": [{"pr": ONE, "branch": "one", "head": A, "pass": {"id": "r1", "head": A}}]}))
            Path(str(file) + ".sig").write_text("junk")
            (Path(directory) / "allowed_signers").write_text("owner ssh-ed25519 AAAA\n")
            done = self.command(file, "verify", Path(directory) / "allowed_signers", "owner", PATH=directory + os.pathsep + os.environ["PATH"])
            self.assertEqual(done.returncode, 1)
            self.assertFalse(called.exists())

    @needs_ssh_keygen
    def test_a_hand_written_carry_over_record_approves_nothing(self):
        signer, file = self.signed()
        record = [{"pr": ONE, "head": C, "patch_id": B, "pass": {"id": "r2", "head": C, "tree": C}}]
        Path(str(file) + ".carried.json").write_text(json.dumps(record))
        self.assertFalse(hasattr(batch_module, "load_effective"))
        self.assertEqual(self.command(file, "verify", signer.signers, "owner").returncode, 0)
        for head in (C, A):
            done = self.command(file, "push", signer.signers, "owner", "ejmlabs/ejm-cli", "one", head)
            self.assertEqual(done.returncode, 0 if head == A else 1, done.stderr)
        self.assertIn("not " + C, self.command(file, "push", signer.signers, "owner", "ejmlabs/ejm-cli", "one", C).stderr)

    def test_the_digest_covers_the_items_and_the_deploy_but_not_later_records(self):
        group = batch()
        self.assertEqual(digest(group), digest({**group, "carried": [1]}))
        self.assertNotEqual(digest(group), digest({**group, "items": group["items"][:1]}))
        self.assertNotEqual(digest(group), digest({**group, "deploy": {"repo": "ejmlabs/x", "tree": A}}))

    @needs_ssh_keygen
    def test_the_approved_file_stays_as_signed(self):
        signer, file = self.signed()
        before = file.read_bytes()
        file.chmod(0o444)
        for args in (("push", signer.signers, "owner", "ejmlabs/ejm-cli", "one", A), ("reconcile", signer.signers, "owner", ONE + "=" + C), ("canonical",)):
            self.assertEqual(self.command(file, *args).returncode, 0)
        self.assertEqual(file.read_bytes(), before)

    @needs_ssh_keygen
    def test_stray_arguments_and_malformed_shapes_are_refusals_not_tracebacks(self):
        for text in ('{"items": [{"pr": "%s", "branch": "one", "head": "%s", "pass": 3}]}' % (ONE, A), '{"items": 5}', "[]"):
            signer = Signer()
            self.addCleanup(signer.cleanup)
            file = signer.root / "batch.json"
            file.write_text(text)
            Path(str(file) + ".sig").write_text("junk")
            done = self.command(file, "push", signer.signers, "owner", "ejmlabs/ejm-cli", "one", A)
            self.assertEqual((done.returncode, "Traceback" in done.stderr), (1, False))
        signer, file = self.signed(json.dumps({"approval": "m"}))
        done = self.command(file, "push", signer.signers, "owner", "ejmlabs/ejm-cli", "one", A)
        self.assertEqual((done.returncode, "lists no push" in done.stderr), (1, True))
        signer, file = self.signed()
        self.assertEqual(self.command(file, "push", signer.signers, "owner", "ejmlabs/ejm-cli", "one", A, "--fast").returncode, 1)
        self.assertEqual(self.command(file, "push", signer.signers, "owner", "ejmlabs/ejm-cli", "one").returncode, 1)

    def test_malformed_files_are_rejected(self):
        good = {"items": [{"pr": ONE, "branch": "x", "head": A}]}
        for change in ({"items": 3}, {"items": [{"pr": "https://example.com/x/pull/1", "branch": "x", "head": A}]},
                       {"items": [{"pr": ONE, "branch": "x", "head": "abc"}]}, {"items": [good["items"][0], good["items"][0]]},
                       {"items": [{"pr": ONE, "branch": "x", "head": A, "pass": {"id": "", "head": A}}]}):
            with self.assertRaises(ValueError):
                load(json.dumps({**good, **change}))


if __name__ == "__main__":
    unittest.main()
