#!/usr/bin/env python3
"""Install pinned prebuilt cargo tools after checking each archive against a reviewed digest."""
import hashlib
import io
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

MAX_ARCHIVE_BYTES = 64_000_000
MAX_BINARY_BYTES = 256_000_000
# Hosted runner (RUNNER_OS, RUNNER_ARCH) to the release target each tool publishes.
TARGETS = {("Linux", "X64"): "x86_64-unknown-linux-musl", ("macOS", "ARM64"): "aarch64-apple-darwin", ("Windows", "X64"): "x86_64-pc-windows-msvc"}
# Each digest matches the .sha256 file published with its release; a new version needs new reviewed digests.
TOOLS = {
    "cargo-deny": ("https://github.com/EmbarkStudios/cargo-deny/releases/download/0.20.2/cargo-deny-0.20.2-{target}.tar.gz", {
        "x86_64-unknown-linux-musl": "9f12ed4c49936e09b48bf862b595cde2fe64fcbd9d74dfacac6131ca824c8d5f",
        "aarch64-apple-darwin": "fe67d82a10d8597a3549364cb733a3f9cc1bfff9031b7ae46384a9f2a72090c3",
        "x86_64-pc-windows-msvc": "975a22143262fd27476d19ee00c7af67978426e40e1dee94eed6bbade1cf87dc",
    }),
    "cargo-machete": ("https://github.com/bnjbvr/cargo-machete/releases/download/v0.9.2/cargo-machete-v0.9.2-{target}.tar.gz", {
        "x86_64-unknown-linux-musl": "48200087f54c55aabcd4db4af1e25742b49846c02a1b1bfa134711945b35b2e9",
        "aarch64-apple-darwin": "63e28fee386d82d33f2d12406c857f98e2d4697f3f7df7f71f34dff07fca0fde",
        "x86_64-pc-windows-msvc": "996120ac70afe405c58fce508a476f25bb71032c6fb8013aa0123bba36429c76",
    }),
}


def target() -> str:
    runner = (os.environ.get("RUNNER_OS", ""), os.environ.get("RUNNER_ARCH", ""))
    if runner not in TARGETS:
        raise ValueError("No pinned tool build for this runner: " + "/".join(runner))
    return TARGETS[runner]


def binary(tool: str, archive: bytes, triple: str) -> bytes:
    """Return the tool binary from a verified archive, refusing anything but the expected member."""
    if tool not in TOOLS:
        raise ValueError("Unknown tool: " + tool)
    url, digests = TOOLS[tool]
    if hashlib.sha256(archive).hexdigest() != digests[triple]:
        raise ValueError("Tool archive digest does not match its reviewed pin: " + tool)
    name = url.format(target=triple).rsplit("/", 1)[1].removesuffix(".tar.gz") + "/" + tool + (".exe" if "windows" in triple else "")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        member = bundle.getmember(name)
        data = bundle.extractfile(member) if member.isfile() else None
        if data is None:
            raise ValueError("Tool archive has no regular binary: " + name)
        if member.size > MAX_BINARY_BYTES:
            raise ValueError("Tool binary exceeds its byte limit: " + name)
        return data.read()


def install(tools: list[str], directory: Path) -> None:
    triple = target()
    unknown = [tool for tool in tools if tool not in TOOLS]
    if unknown:
        raise ValueError("Unknown tool: " + ", ".join(unknown))
    directory.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        url = TOOLS[tool][0].format(target=triple)
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https release URL; the digest check is the trust boundary
            archive = response.read(MAX_ARCHIVE_BYTES + 1)
        if len(archive) > MAX_ARCHIVE_BYTES:
            raise ValueError("Tool archive exceeds its byte limit: " + tool)
        path = directory / (tool + (".exe" if "windows" in triple else ""))
        path.write_bytes(binary(tool, archive, triple))
        path.chmod(0o755)
        print(tool, "installed from", url)


if __name__ == "__main__":
    install(sys.argv[1:], Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")) / "bin")
