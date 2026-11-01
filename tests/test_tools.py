import contextlib
import hashlib
import io
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Any
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

    def test_binary_refuses_an_oversized_member(self) -> None:
        triple = "x86_64-unknown-linux-musl"
        data = archive({"cargo-deny-0.20.2-" + triple + "/cargo-deny": b"binary"})
        pins = {"cargo-deny": (tools.TOOLS["cargo-deny"][0], {**tools.TOOLS["cargo-deny"][1], triple: hashlib.sha256(data).hexdigest()})}
        with mock.patch.dict(tools.TOOLS, pins), mock.patch.object(tools, "MAX_BINARY_BYTES", 5), self.assertRaisesRegex(ValueError, "byte limit"):
            tools.binary("cargo-deny", data, triple)

    def test_target_refuses_an_unpinned_runner(self) -> None:
        with mock.patch.dict(os.environ, {"RUNNER_OS": "Linux", "RUNNER_ARCH": "ARM64"}), self.assertRaisesRegex(ValueError, "No pinned tool build"):
            tools.target()
        with mock.patch.dict(os.environ, {"RUNNER_OS": "macOS", "RUNNER_ARCH": "ARM64"}):
            self.assertEqual(tools.target(), "aarch64-apple-darwin")


class InstallTests(unittest.TestCase):
    """tools.install with a fake release server: archives built here, digests pinned here, nothing downloaded."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bin = Path(self.directory.name) / "cargo/bin"
        self.requested: list[tuple[str, int]] = []
        self.served: dict[str, bytes] = {}
        self.printed = ""

    def serve(self, triple: str, **overrides: bytes) -> dict[str, tuple[str, dict[str, str]]]:
        """Build one archive per tool, serve it at the pinned URL, and return pins whose digests match what is served."""
        pins = {}
        for tool, (url, digests) in tools.TOOLS.items():
            address = url.format(target=triple)
            folder = address.rsplit("/", 1)[1].removesuffix(".tar.gz")
            data = archive({folder + "/README.md": b"docs", folder + "/" + tool + (".exe" if "windows" in triple else ""): b"binary of " + tool.encode()})
            pins[tool] = (url, {**digests, triple: hashlib.sha256(data).hexdigest()})
            self.served[address] = overrides.get(tool, data)
        return pins

    def fake_open(self, url: str, timeout: int) -> Any:
        self.requested.append((url, timeout))
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(self.served[url])
        return response

    def run_install(self, pins: dict[str, tuple[str, dict[str, str]]], names: list[str], runner: dict[str, str] | None = None) -> None:
        environment = runner or {"RUNNER_OS": "Linux", "RUNNER_ARCH": "X64"}
        with (mock.patch.dict(os.environ, environment), mock.patch.dict(tools.TOOLS, pins), mock.patch("urllib.request.urlopen", self.fake_open),
              contextlib.redirect_stdout(io.StringIO()) as output):
            tools.install(names, self.bin)
        self.printed = output.getvalue()

    def test_each_verified_binary_is_written_executable(self) -> None:
        triple = "x86_64-unknown-linux-musl"
        self.run_install(self.serve(triple), ["cargo-deny", "cargo-machete"])
        for tool in ("cargo-deny", "cargo-machete"):
            self.assertEqual((self.bin / tool).read_bytes(), b"binary of " + tool.encode())
            self.assertEqual((self.bin / tool).stat().st_mode & 0o777, 0o755)
        self.assertEqual(sorted(path.name for path in self.bin.iterdir()), ["cargo-deny", "cargo-machete"])
        self.assertEqual(self.requested, [(tools.TOOLS[tool][0].format(target=triple), 60) for tool in ("cargo-deny", "cargo-machete")])
        self.assertEqual(self.printed.count("installed from"), 2)

    def test_a_windows_runner_gets_exe_files(self) -> None:
        triple = "x86_64-pc-windows-msvc"
        self.run_install(self.serve(triple), ["cargo-deny"], {"RUNNER_OS": "Windows", "RUNNER_ARCH": "X64"})
        self.assertEqual((self.bin / "cargo-deny.exe").read_bytes(), b"binary of cargo-deny")

    def test_a_changed_archive_is_refused_and_nothing_is_written(self) -> None:
        triple = "x86_64-unknown-linux-musl"
        pins = self.serve(triple)
        self.served[tools.TOOLS["cargo-deny"][0].format(target=triple)] = archive({"cargo-deny-0.20.2-" + triple + "/cargo-deny": b"tampered"})
        with self.assertRaisesRegex(ValueError, "digest"):
            self.run_install(pins, ["cargo-deny"])
        self.assertFalse((self.bin / "cargo-deny").exists())

    def test_an_oversized_download_is_refused_after_reading_one_byte_past_the_limit(self) -> None:
        triple = "x86_64-unknown-linux-musl"
        pins = self.serve(triple, **{"cargo-deny": b"x" * 11})
        with mock.patch.object(tools, "MAX_ARCHIVE_BYTES", 10), self.assertRaisesRegex(ValueError, "byte limit"):
            self.run_install(pins, ["cargo-deny"])
        self.assertFalse((self.bin / "cargo-deny").exists())

    def test_an_unknown_tool_is_refused_before_any_download(self) -> None:
        pins = self.serve("x86_64-unknown-linux-musl")
        with self.assertRaisesRegex(ValueError, "Unknown tool: cargo-other"):
            self.run_install(pins, ["cargo-deny", "cargo-other"])
        self.assertEqual(self.requested, [])
        self.assertFalse(self.bin.exists())

    def test_an_unpinned_runner_is_refused_before_any_download(self) -> None:
        with self.assertRaisesRegex(ValueError, "No pinned tool build"):
            self.run_install(self.serve("x86_64-unknown-linux-musl"), ["cargo-deny"], {"RUNNER_OS": "Linux", "RUNNER_ARCH": "ARM64"})
        self.assertEqual(self.requested, [])


if __name__ == "__main__":
    unittest.main()
