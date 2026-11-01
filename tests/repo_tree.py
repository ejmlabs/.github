"""Synthetic repositories that pass the standards check for one profile, so a test can break one rule at a time."""
import json
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import standards
from standards import (
    MIT_TERMS,
    PROFILES,
    UI_LICENSE_SCOPE,
    UI_PACKING_PREFIXES,
    UI_PUBLIC,
    consumer_workflows,
)

REVISION = "0123456789abcdef0123456789abcdef01234567"
MIT = "MIT License\nCopyright (c) 2026 Example\n" + MIT_TERMS
UI_LICENSE = "ejm-ui license scope\n\n" + UI_LICENSE_SCOPE + "\n\nMIT License\nCopyright (c) 2026 Example\n" + MIT_TERMS
FONTS = Path(__file__).parent / "fixtures" / "font-notices"
UI_DIRS = ("core", "demos", "ink", "shots", "site", "ssg", "tokens", "ui")
CRATE = '[package]\nname = "{name}"\nversion = "0.1.0"\nlicense = "MIT"\n'


class RepoTree:
    """Write a minimal repository for `profile` under `root`, then edit it with `write`, `replace` and `change_json`."""

    def __init__(self, profile: str, root: Path, *, cache: bool = False, deploy: bool = False, native: bool = False) -> None:
        self.profile, self.root = profile, root
        self.write("VERSION", "0.1.0\n")
        self.write("CHANGELOG.md", "## [Unreleased]\n\n## [0.1.0] - 2026-10-18\nNotes\n")
        self.write("LICENSE", UI_LICENSE if profile == "ejm-ui" else "Studio rights are reserved.\n" if profile == "ejmlabs" else MIT)
        self.write("README.md", "# Project\n\nSee [the guide](docs/guide.md).\n")
        self.write("docs/guide.md", "# Guide\n")
        for name in ("CONTRIBUTING", "SECURITY", "SUPPORT", "CODE_OF_CONDUCT", "RELEASING", "THIRD_PARTY_NOTICES"):
            self.write(name + ".md", f"# {name}\nText.\n")
        for path in standards.GITHUB_FILES:
            self.write(path, "placeholder\n")
        for name, text in consumer_workflows(REVISION, native=native, cache=cache, deploy=deploy).items():
            self.write(".github/workflows/" + name, text)
        {"ejm-cli": self.build_cli, "ejm-rightkit-fs": self.build_rightkit, "ejm-harness": self.build_harness, "ejm-ide": self.build_ide, "ejmlabs": self.build_studio,
         ".github": self.build_shared, "ejm-ui": self.build_ui, "ejm-calm": self.build_calm}[profile]()

    def write(self, path: str, text: str | bytes) -> Path:
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(text.encode() if isinstance(text, str) else text)
        return file

    def read(self, path: str) -> str:
        return (self.root / path).read_text()

    def replace(self, path: str, old: str, new: str) -> None:
        text = self.read(path)
        if old not in text:
            raise AssertionError(f"{old!r} is not in {path}")
        self.write(path, text.replace(old, new))

    def change_json(self, path: str, change: Callable[[dict[str, Any]], None]) -> None:
        data = json.loads(self.read(path))
        change(data)
        self.write(path, json.dumps(data))

    def check(self) -> str:
        return standards.standards(self.root, self.profile)

    def set_members(self, members: list[str]) -> None:
        """Replace the Cargo workspace members of a workspace profile."""
        self.write("Cargo.toml", f'[workspace]\nmembers = {json.dumps(members)}\n[workspace.package]\nversion = "0.1.0"\nlicense = "MIT"\n')

    def build_cli(self) -> None:
        self.write("Cargo.toml", '[workspace]\nmembers = ["crates/core", "crates/cli"]\n[workspace.package]\nversion = "0.1.0"\nlicense = "MIT"\n')
        self.write("crates/core/Cargo.toml", CRATE.format(name="core"))
        self.write("crates/cli/Cargo.toml", '[package]\nname = "cli"\nlicense.workspace = true\n')
        self.write("Cargo.lock", '[[package]]\nname = "ejm-cli"\nversion = "0.1.0"\n\n[[package]]\nname = "serde"\nversion = "1.0.0"\n')
        self.write(".github/harness-revision", "a" * 40 + "\n")

    def build_rightkit(self) -> None:
        self.write("Cargo.toml", '[package]\nname = "ejm-rightkit-fs"\nversion = "0.1.0"\nlicense = "MIT OR Apache-2.0"\n')
        self.write("Cargo.lock", '[[package]]\nname = "ejm-rightkit-fs"\nversion = "0.1.0"\n')

    def build_harness(self) -> None:
        self.write("Cargo.toml", '[workspace]\nmembers = ["crates/*"]\n[workspace.package]\nversion = "0.1.0"\nlicense = "MIT"\n')
        for name in ("a", "b"):
            self.write(f"crates/{name}/Cargo.toml", CRATE.format(name=name))
        self.write("sdk/typescript/package.json", json.dumps({"version": "0.1.0", "license": "MIT"}))
        self.write("sdk/python/pyproject.toml", '[project]\nname = "ejm-harness"\nversion = "0.1.0"\nlicense = "MIT"\n')
        self.write("registry/Cargo.toml", CRATE.format(name="registry"))
        for path in ("sdk/typescript/LICENSE", "sdk/python/LICENSE"):
            self.write(path, MIT)
        self.write("package-lock.json", json.dumps({"packages": {"sdk/typescript": {"version": "0.1.0"}}}))
        self.write("sdk/python/uv.lock", '[[package]]\nname = "ejm-harness"\nversion = "0.1.0"\n')
        self.write("Cargo.lock", '[[package]]\nname = "ejm-harness"\nversion = "0.1.0"\n\n[[package]]\nname = "ejm-harness-core"\nversion = "0.1.0"\n\n[[package]]\nname = "serde"\nversion = "1.0.0"\n')

    def build_ide(self) -> None:
        self.write("package.json", json.dumps({"version": "0.1.0", "license": "MIT"}))
        self.write("package-lock.json", json.dumps({"version": "0.1.0", "packages": {"": {"version": "0.1.0"}}}))
        self.write("src-tauri/Cargo.toml", CRATE.format(name="ide"))
        self.write("src-tauri/tauri.conf.json", json.dumps({"version": "0.1.0"}))
        self.write("src-tauri/Cargo.lock", '[[package]]\nname = "ejm-ide"\nversion = "0.1.0"\n')
        self.write(".github/harness-revision", "b" * 40 + "\n")

    def build_studio(self) -> None:
        self.write("site/package.json", json.dumps({"version": "0.1.0", "license": "SEE LICENSE IN ../LICENSE"}))

    def build_calm(self) -> None:
        self.write("package.json", json.dumps({"version": "0.1.0", "license": "MIT"}))
        self.write("package-lock.json", json.dumps({"version": "0.1.0", "packages": {"": {"version": "0.1.0"}}}))

    def build_shared(self) -> None:
        """The shared standards repository has no manifest besides VERSION."""

    def build_ui(self) -> None:
        manifest: dict[str, Any] = {"version": "0.1.0", "private": True, "license": "SEE LICENSE IN LICENSE"}
        lock: dict[str, Any] = {"version": "0.1.0", "packages": {"": {"version": "0.1.0"}}}
        self.write("package.json", json.dumps(manifest))
        for name in UI_DIRS:
            self.add_ui_package(name)
            lock["packages"]["packages/" + name] = {"version": "0.1.0"}
        self.write("package-lock.json", json.dumps(lock))
        self.write("crates/ejm-tui/Cargo.toml", CRATE.format(name="ejm-tui") + "publish = false\n")
        self.write("crates/ejm-tui/Cargo.lock", '[[package]]\nname = "ejm-tui"\nversion = "0.1.0"\n')
        for font in ("Manrope", "IBMPlexMono"):
            notice = (FONTS / (font + "-OFL.txt")).read_bytes()
            self.write(f"packages/tokens/assets/fonts/{font}-OFL.txt", notice)
            self.write(f"packages/ui/src/fonts/{font}-OFL.txt", notice)

    def add_ui_package(self, name: str, **changes: Any) -> None:  # noqa: ANN401 - manifest values have no fixed shape
        """Write packages/<name> in the reviewed public shape if it is in the public set, else as a private package."""
        path = "packages/" + name
        package: dict[str, Any] = {"name": "@ejm/" + name, "version": "0.1.0", "license": "SEE LICENSE IN LICENSE", "main": "./src/index.ts",
                                   "repository": {"type": "git", "url": "git+https://github.com/ejmlabs/ejm-ui.git", "directory": path}}
        if path in UI_PUBLIC:
            package["files"] = ["!src/**/*.test.*", *UI_PACKING_PREFIXES[path]]
            package["publishConfig"] = {"access": "public", "provenance": True}
            if name == "ssg":
                package["bin"] = {"ejm-ssg": "./bin/ejm-ssg.mjs"}
        else:
            package["private"] = True
        package.update(changes)
        self.write(path + "/package.json", json.dumps({key: value for key, value in package.items() if value is not None}))
        self.write(path + "/LICENSE", UI_LICENSE)
        self.write(path + "/THIRD_PARTY_NOTICES.md", "# Third-party notices\nSee LICENSE.\n")


class TreeCase(unittest.TestCase):
    def tree(self, profile: str, **options: bool) -> RepoTree:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return RepoTree(profile, Path(directory.name), **options)

    def fails(self, tree: RepoTree, pattern: str) -> list[str]:
        """Assert the check fails with a message matching pattern; return every problem it reported."""
        with self.assertRaises(standards.StandardsError) as caught:
            tree.check()
        problems: list[str] = caught.exception.problems
        self.assertRegex("\n".join(problems), pattern)
        return problems


if set(PROFILES) != {".github", "ejm-calm", "ejm-cli", "ejm-harness", "ejm-ide", "ejm-rightkit-fs", "ejm-ui", "ejmlabs"}:
    raise AssertionError("RepoTree must build every profile in the table")
