"""Throwaway SSH signing keys for the approval tests; nothing here is a real key."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import batch
from batch import NAMESPACE, canonical

TOOL = os.environ.get("SSH_KEYGEN") or shutil.which("ssh-keygen")
if TOOL:
    batch.SSH_KEYGEN = TOOL  # the checker uses a fixed absolute path; the tests may point it at a scratch copy
needs_ssh_keygen = unittest.skipUnless(TOOL, "ssh-keygen is not installed")


class Signer:
    """A fresh ed25519 key, its allowed_signers file and a way to sign a batch the way the owner does."""

    def __init__(self, identity="owner"):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.identity = identity
        self.key = self.root / "key"
        subprocess.run([TOOL, "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(self.key)], check=True)
        self.signers = self.root / "allowed_signers"
        self.signers.write_text(f"{identity} {(self.key.with_suffix('.pub')).read_text()}")

    def sign(self, batch, path):
        """Write PATH.sig: a signature over the canonical bytes of `batch`, as the owner signs `batch-to-sign.json`."""
        data = self.root / "batch-to-sign.json"
        data.write_bytes(canonical(batch))
        Path(str(path) + ".sig").unlink(missing_ok=True)
        subprocess.run([TOOL, "-Y", "sign", "-f", str(self.key), "-n", NAMESPACE, str(data)], check=True, capture_output=True)
        shutil.move(str(data) + ".sig", str(path) + ".sig")

    def cleanup(self):
        self.directory.cleanup()
