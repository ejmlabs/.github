import hashlib
import io
import os
import sys
import tarfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tools


def archive(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class ToolTests(unittest.TestCase):
    def test_every_tool_pins_a_digest_for_every_runner(self) -> None:
        for tool, (url, digests) in tools.TOOLS.items():
            with self.subTest(tool=tool):
                self.assertTrue(url.startswith("https://github.com/") and "{target}" in url)
                self.assertEqual(set(digests), set(tools.TARGETS.values()))
                self.assertTrue(all(len(value) == 64 and value == value.lower() for value in digests.values()))

    def test_binary_returns_only_the_pinned_member(self) -> None:
        for triple in tools.TARGETS.values():
            suffix = ".exe" if "windows" in triple else ""
            folder = tools.TOOLS["cargo-deny"][0].format(target=triple).rsplit("/", 1)[1].removesuffix(".tar.gz")
            data = archive({folder + "/README.md": b"docs", folder + "/cargo-deny" + suffix: b"binary"})
            pins = {"cargo-deny": (tools.TOOLS["cargo-deny"][0], {**tools.TOOLS["cargo-deny"][1], triple: hashlib.sha256(data).hexdigest()})}
            with self.subTest(triple=triple), mock.patch.dict(tools.TOOLS, pins):
                self.assertEqual(tools.binary("cargo-deny", data, triple), b"binary")

    def test_binary_rejects_a_changed_archive_or_a_missing_binary(self) -> None:
        triple = "x86_64-unknown-linux-musl"
        folder = "cargo-deny-0.20.2-" + triple
        with self.assertRaisesRegex(ValueError, "digest"):
            tools.binary("cargo-deny", archive({folder + "/cargo-deny": b"tampered"}), triple)
        empty = archive({folder + "/README.md": b"docs"})
        with mock.patch.dict(tools.TOOLS, {"cargo-deny": (tools.TOOLS["cargo-deny"][0], {triple: hashlib.sha256(empty).hexdigest()})}), self.assertRaises(KeyError):
            tools.binary("cargo-deny", empty, triple)
        with self.assertRaisesRegex(ValueError, "Unknown tool"):
            tools.binary("cargo-other", empty, triple)

    def test_target_refuses_an_unpinned_runner(self) -> None:
        with mock.patch.dict(os.environ, {"RUNNER_OS": "Linux", "RUNNER_ARCH": "ARM64"}), self.assertRaisesRegex(ValueError, "No pinned tool build"):
            tools.target()
        with mock.patch.dict(os.environ, {"RUNNER_OS": "macOS", "RUNNER_ARCH": "ARM64"}):
            self.assertEqual(tools.target(), "aarch64-apple-darwin")


if __name__ == "__main__":
    unittest.main()
