#!/usr/bin/env python3
"""Dependency-free repository standards: documents, version and license metadata, and workflow callers.

This is a consistency lint, not a security boundary. A `pull_request` run uses the caller in the PR, so
a PR chooses its own pin and with it the standards that judge it; human review of the pin line is the
control. What the check keeps: callers equal the canonical text except the pin, product workflows stay
credential-free, and version and license metadata stay consistent. It reports every problem it finds.
"""
import difflib
import fnmatch
import hashlib
import json
import os
import posixpath
import re
import sys
import tomllib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from itertools import islice
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple, cast
from urllib.parse import unquote

if "semver" not in globals():  # a workflow embeds versioning.py before this file, and has no module to import
    sys.path.append(str(Path(__file__).resolve().parent))  # python -I keeps this trusted directory off the path
    from versioning import semver

DOCS = ("README.md", "CONTRIBUTING.md", "SECURITY.md", "SUPPORT.md", "CODE_OF_CONDUCT.md", "RELEASING.md", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "LICENSE")
GITHUB_FILES = (".github/CODEOWNERS", ".github/dependabot.yml", ".github/pull_request_template.md", ".github/ISSUE_TEMPLATE/config.yml")
MAX_READ_BYTES = 8_000_000
MAX_WORKFLOW_BYTES = 1_000_000
MAX_MEMBERS = 50
MAX_LISTING = 1_000  # directory entries examined in one listing
MAX_LINKS = 10_000
MAX_REPORTED = 50
MAX_DIFF_LINES = 40
MAX_DIFF_BYTES = 20_000


class Profile(NamedTuple):
    """What the check requires of one repository."""

    guide: str  # where the synced CONTRIBUTING.md sends contributors
    versions: tuple[tuple[str, str], ...] = ()  # (file, dotted key) that must equal VERSION
    locks: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (file, key path) in a lock that must equal VERSION
    licenses: tuple[tuple[str, str], ...] = ()  # (file, dotted key) that must be MIT
    workspace: bool = False  # a Cargo workspace whose members are all MIT
    cargo_lock: str = ""  # a Cargo.lock whose owned packages must equal VERSION
    native: bool = False  # may ship native builds by adding build.yml
    cache: bool = False  # may warm gate caches by adding cache.yml
    deploy: bool = False  # may deploy a site by adding deploy.yml
    harness_pin: bool = False  # pins ejm-harness in .github/harness-revision
    publish: bool = False  # may publish with the reviewed publish.yml


PROFILES = {
    "ejm-cli": Profile(
        guide="docs/contributing.md", versions=(("Cargo.toml", "workspace.package.version"),),
        workspace=True, cargo_lock="Cargo.lock", native=True, cache=True, deploy=True, harness_pin=True),
    "ejm-harness": Profile(
        guide="docs/contributing.md",
        versions=(("Cargo.toml", "workspace.package.version"), ("sdk/typescript/package.json", "version"),
                  ("sdk/python/pyproject.toml", "project.version"), ("registry/Cargo.toml", "package.version")),
        locks=(("package-lock.json", ("packages", "sdk/typescript", "version")),),
        licenses=(("sdk/typescript/package.json", "license"), ("sdk/python/pyproject.toml", "project.license"),
                  ("registry/Cargo.toml", "package.license")),
        workspace=True, cargo_lock="Cargo.lock", native=True, cache=True, deploy=True),
    "ejm-ide": Profile(
        guide="docs/development.md",
        versions=(("package.json", "version"), ("package-lock.json", "version"), ("src-tauri/Cargo.toml", "package.version"),
                  ("src-tauri/tauri.conf.json", "version")),
        locks=(("package-lock.json", ("packages", "", "version")),),
        licenses=(("package.json", "license"), ("src-tauri/Cargo.toml", "package.license")),
        cargo_lock="src-tauri/Cargo.lock", cache=True, deploy=True, harness_pin=True),
    "ejmlabs": Profile(guide="site/README.md", versions=(("site/package.json", "version"),), deploy=True),
    ".github": Profile(guide="docs/operations.md"),
    "ejm-ui": Profile(
        guide="README.md#development",
        versions=(("package.json", "version"), ("package-lock.json", "version"), ("crates/ejm-tui/Cargo.toml", "package.version")),
        cache=True, deploy=True, publish=True),
}
# Repositories that may ship native builds. One adopts the native release by adding build.yml.
NATIVE_RELEASE = tuple(name for name, profile in PROFILES.items() if profile.native)
# Repositories whose Rust gate builds may restore main's trusted cache. One adopts it by adding cache.yml.
WARM_CACHE = tuple(name for name, profile in PROFILES.items() if profile.cache)
# Repositories that serve a Cloudflare site. One adopts staging and approved production deploys by adding deploy.yml.
SITE_DEPLOY = tuple(name for name, profile in PROFILES.items() if profile.deploy)
SHARED_WORKFLOWS = ("governance.yml", "draft-release.yml", "verify-build.yml", "attach-assets.yml", "warm-cache.yml", "deploy-site.yml")

UI_LICENSE_SCOPE = """The ejmlabs name, logos, supplied brand artwork, design assets, templates, and
visual identity retain their owners' rights. All rights in those materials are
reserved except where a file or its accompanying notice gives a separate
license. Public access does not grant a right to use the marks or redistribute
the brand materials."""
# The owner's public npm set. Every other UI package stays private.
UI_PUBLIC = tuple("packages/" + name for name in ("core", "ssg", "tokens", "ui"))
UI_PUBLISH_CONFIG = {"access": "public", "provenance": True}
# Lifecycle scripts that npm runs while packing, publishing or installing; they can change the packed files.
UI_LIFECYCLE_SCRIPTS = ("preprepare", "prepare", "postprepare", "prepack", "postpack", "prepublish", "prepublishOnly", "publish",
                        "postpublish", "preinstall", "install", "postinstall")
# Where a public package's `files`, `main`, `bin` and similar entries may point, from the reviewed manifests.
# Brand logos and artwork stay out of the tokens tarball because only assets/fonts, brand and icons are allowed.
UI_PACKING_PREFIXES = {
    "packages/core": ("src", "contract.json", "LICENSE", "THIRD_PARTY_NOTICES.md"),
    "packages/ssg": ("bin", "src", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"),
    "packages/tokens": ("src", "generated", "rust", "theme.json", "README.md", "assets/fonts", "assets/brand", "assets/icons",
                        "LICENSE", "THIRD_PARTY_NOTICES.md"),
    "packages/ui": ("src", "public/theme-boot.js", "public/static.css", "THEME.md", "COMPONENTS.md", "LICENSE", "THIRD_PARTY_NOTICES.md"),
}
# The reviewed ejm-ui publish workflow, the privileged publishing path; the error prints the actual digest so a reviewed update is one copy.
UI_PUBLISH_SHA256 = "b28800bd599a24b07f385202bad0e8ef53bc5f503bdd600b51fbd4f461f656e9"
UI_FONT_NOTICES = tuple("packages/" + path + "/" + name + "-OFL.txt"
                        for path in ("tokens/assets/fonts", "ui/src/fonts") for name in ("Manrope", "IBMPlexMono"))
UI_FONT_HASHES = {
    "Manrope": "58172e0c0fac2cda8a37b348164bb55e44b0e69051e557e92b1d3f6910141f7b",
    "IBMPlexMono": "7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da",
}
INHERIT = "    secrets: inherit\n"
# Each push to main deploys to staging; production waits for a required reviewer on the production environment.
# The called workflow reads the environment's CLOUDFLARE_API_TOKEN only when the caller passes secrets on.
SITE_DEPLOY_CALLER = """name: Deploy site
on:
  push:
    branches: [main]
permissions: {}
jobs:
  deploy:
    permissions:
      contents: read
      actions: read
    uses: ejmlabs/.github/.github/workflows/deploy-site.yml@STANDARDS_REVISION
    secrets: inherit
"""
# The form before `secrets: inherit` stays accepted until every consumer has moved.
SITE_DEPLOY_CALLER_WITHOUT_SECRETS = SITE_DEPLOY_CALLER.removesuffix(INHERIT)
# The only writer of gate caches: a push to main builds the reviewed commit and saves it.
WARM_CACHE_CALLER = """name: Warm trusted gate build caches
on:
  push:
    branches: [main]
permissions: {}
jobs:
  warm:
    permissions:
      contents: read
    uses: ejmlabs/.github/.github/workflows/warm-cache.yml@STANDARDS_REVISION
"""
MIT_TERMS = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""
RELEASE_CALLER = """name: Draft source release
on:
  workflow_dispatch:
    inputs:
      commit:
        description: Full protected main commit SHA
        required: true
        type: string
      version:
        description: SemVer version matching VERSION
        required: true
        type: string
permissions: {}
jobs:
  release:
    permissions:
      contents: write
      pull-requests: read
      statuses: read
    uses: ejmlabs/.github/.github/workflows/draft-release.yml@STANDARDS_REVISION
    with:
      commit: ${{ inputs.commit }}
      version: ${{ inputs.version }}
      standards-ref: "STANDARDS_REVISION"
"""
# Ready-for-review lifecycle caller. Control plane is PR actions and labels, not comments.
PR_CALLER = """name: Human-admitted PR checks
on:
  pull_request:
    types: [opened, reopened, synchronize, ready_for_review, converted_to_draft, labeled]
permissions: {}
jobs:
  governance:
    if: ${{ github.event_name == 'pull_request' }}
    permissions:
      contents: read
      pull-requests: write
      statuses: write
      actions: write
    uses: ejmlabs/.github/.github/workflows/governance.yml@STANDARDS_REVISION
    secrets:
      EJM_HARNESS_TOKEN: ${{ secrets.EJM_HARNESS_TOKEN }}
"""
# Build output is verified before the tag exists and attached after the draft, from the same main commit.
NATIVE_RELEASE_CALLER = """name: Draft native release
on:
  workflow_dispatch:
    inputs:
      commit:
        description: Full protected main commit SHA
        required: true
        type: string
      version:
        description: SemVer version matching VERSION
        required: true
        type: string
      build-run-id:
        description: Run id of the successful Build workflow for that commit
        required: true
        type: string
      attest:
        description: Attest build provenance
        required: false
        default: false
        type: boolean
permissions: {}
jobs:
  verify:
    permissions:
      actions: read
    uses: ejmlabs/.github/.github/workflows/verify-build.yml@STANDARDS_REVISION
    with:
      commit: ${{ inputs.commit }}
      build-workflow: build.yml
      build-run-id: ${{ inputs.build-run-id }}
  release:
    needs: verify
    permissions:
      contents: write
      pull-requests: read
      statuses: read
    uses: ejmlabs/.github/.github/workflows/draft-release.yml@STANDARDS_REVISION
    with:
      commit: ${{ inputs.commit }}
      version: ${{ inputs.version }}
      standards-ref: "STANDARDS_REVISION"
  attach:
    needs: release
    permissions:
      contents: write
      actions: read
      id-token: write
      attestations: write
    uses: ejmlabs/.github/.github/workflows/attach-assets.yml@STANDARDS_REVISION
    with:
      commit: ${{ inputs.commit }}
      version: ${{ inputs.version }}
      build-workflow: build.yml
      build-run-id: ${{ inputs.build-run-id }}
      attest: ${{ inputs.attest }}
"""
PR_PIN = re.compile(r"^    uses: ejmlabs/\.github/\.github/workflows/governance\.yml@([0-9a-f]{40})$", re.MULTILINE)


class StandardsError(ValueError):
    """Every problem one check run found, one message each."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = list(problems)


def raise_problems(problems: Sequence[str]) -> None:
    if problems:
        raise StandardsError(problems)


@contextmanager
def collecting(problems: list[str], where: str) -> Iterator[None]:
    """Record a failed check and carry on, so one run reports every problem."""
    try:
        yield
    except ValueError as error:
        problems.append(str(error))
    except (KeyError, TypeError, AttributeError, OSError) as error:  # a manifest shaped in a way the check did not expect
        problems.append(f"{where}: unexpected {type(error).__name__}: {error}")


def read_bytes(root: Path, path: str, *, limit: int = MAX_READ_BYTES) -> bytes:
    """Read one regular file inside root, following no symlink at any component, and never more than `limit` bytes."""
    pure = PurePosixPath(path)
    if not pure.parts or pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"Missing or unsafe file: {path}")
    file = root
    for part in pure.parts:
        file /= part
        if file.is_symlink():
            raise ValueError(f"Missing or unsafe file: {path} (symlink at {file.relative_to(root).as_posix()})")
    if not file.is_file():
        raise ValueError(f"Missing or unsafe file: {path} (not a regular file)")
    try:
        with file.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as error:
        raise ValueError(f"Missing or unsafe file: {path} ({error.strerror})") from error
    if len(data) > limit:
        raise ValueError(f"File exceeds validation limit of {limit} bytes: {path}")
    return data


def read(root: Path, path: str, *, preserve_newlines: bool = False, limit: int = MAX_READ_BYTES) -> str:
    try:
        text = read_bytes(root, path, limit=limit).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"File is not valid UTF-8: {path}") from error
    return text if preserve_newlines else text.replace("\r\n", "\n").replace("\r", "\n")


def manifest(root: Path, path: str) -> dict[str, Any]:
    """Parse a JSON or TOML manifest, naming the file in any error."""
    text = read(root, path)
    try:
        data = json.loads(text) if path.endswith(".json") else tomllib.loads(text)
    except (ValueError, RecursionError) as error:
        raise ValueError(f"{path}: invalid {'JSON' if path.endswith('.json') else 'TOML'}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected an object or table")  # noqa: TRY004 - a data error, reported with the others
    return data


def lookup(data: object, path: str, *keys: str) -> Any:  # noqa: ANN401 - a decoded manifest value has no fixed shape
    """Follow keys through nested tables, naming the file and key when one is missing."""
    value = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"{path}: missing key {'.'.join(item or '<root>' for item in keys)}")
        value = value[key]
    return value


def table(data: object, path: str, *keys: str) -> dict[str, Any]:
    value = lookup(data, path, *keys)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: {'.'.join(keys)} must be a table")  # noqa: TRY004 - a data error, reported with the others
    return value


def workspace_members(root: Path, cargo: dict[str, Any]) -> list[str]:
    """Return the workspace member directories, expanding `*` globs inside the root without following symlinks."""
    patterns = lookup(cargo, "Cargo.toml", "workspace", "members")
    excluded = cargo["workspace"].get("exclude", [])
    if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns) or not isinstance(excluded, list):
        raise ValueError("Cargo.toml: workspace.members must be a list of paths")
    found: list[str] = []
    for pattern in patterns:
        pure = PurePosixPath(pattern)
        if not pure.parts or pure.is_absolute() or any(part in ("..", "**") for part in pure.parts):
            raise ValueError("Cargo.toml: unsupported workspace member " + pattern)
        candidates = [""]
        for part in pure.parts:
            following = []
            for base in candidates:
                if not any(mark in part for mark in "*?["):
                    following.append(posixpath.join(base, part))
                    continue
                with os.scandir(root / base) as entries:
                    following += [posixpath.join(base, entry.name) for entry in sorted(islice(entries, MAX_LISTING), key=lambda entry: entry.name)
                                  if entry.is_dir(follow_symlinks=False) and fnmatch.fnmatchcase(entry.name, part)]
            if len(following) > MAX_MEMBERS * 100:
                raise ValueError("Too many owned manifests")
            candidates = following
        literal = not any(mark in pattern for mark in "*?[")
        found += [path for path in candidates if literal or (root / path / "Cargo.toml").is_file()]
        if len(found) > MAX_MEMBERS:
            raise ValueError("Too many owned manifests")
    return [member for member in dict.fromkeys(found) if member not in excluded]


def ui_packages(root: Path) -> list[str]:
    """Return packages/<name> for every directory holding a package.json, listing without following symlinks."""
    base = root / "packages"
    if base.is_symlink():
        raise ValueError("packages must not be a symlink")
    if not base.is_dir():
        return []
    names = []
    with os.scandir(base) as entries:
        for entry in sorted(islice(entries, MAX_LISTING), key=lambda item: item.name):
            if entry.is_symlink():
                raise ValueError(f"packages/{entry.name} must not be a symlink")
            if entry.is_dir(follow_symlinks=False) and ((base / entry.name / "package.json").is_symlink() or (base / entry.name / "package.json").exists()):
                names.append("packages/" + entry.name)
    if len(names) > MAX_MEMBERS:
        raise ValueError("Too many owned UI packages")
    return names


def mit_problems(text: str) -> list[str]:
    if not text.startswith("MIT License") or not re.search(r"Copyright.*\d{4}.*\S", text) or " ".join(MIT_TERMS.split()) not in " ".join(text.split()):
        return ["LICENSE: complete MIT license terms and copyright notice are required"]
    return []


def license_problems(root: Path, profile: str) -> list[str]:
    problems: list[str] = []
    if profile == "ejmlabs":
        with collecting(problems, "site/package.json"):
            if manifest(root, "site/package.json").get("license") != "SEE LICENSE IN ../LICENSE":
                raise ValueError("site/package.json: Studio metadata must preserve its specific rights notice")
        return problems
    with collecting(problems, "LICENSE"):
        text = read(root, "LICENSE")
        problems += ui_license_problems(root, text) if profile == "ejm-ui" else mit_problems(text)
    if profile == "ejm-ui":
        return problems
    if PROFILES[profile].workspace:
        with collecting(problems, "Cargo.toml"):
            cargo = manifest(root, "Cargo.toml")
            if table(cargo, "Cargo.toml", "workspace", "package").get("license") != "MIT":
                raise ValueError("Cargo.toml: workspace license must remain MIT")
            for member in workspace_members(root, cargo):
                with collecting(problems, member + "/Cargo.toml"):
                    package = table(manifest(root, member + "/Cargo.toml"), member + "/Cargo.toml", "package")
                    if package.get("license") not in ("MIT", {"workspace": True}):
                        raise ValueError("Owned crate license differs from MIT: " + member)
    for path, key in PROFILES[profile].licenses:
        with collecting(problems, path):
            if lookup(manifest(root, path), path, *key.split(".")) != "MIT":
                raise ValueError("Owned manifest license differs from MIT: " + path)
    return problems


def licenses(root: Path, profile: str) -> None:
    if profile not in PROFILES:
        raise ValueError("Unknown repository profile")
    raise_problems(license_problems(root, profile))


def scoped_license(value: str) -> bool:
    return bool(value.startswith("ejm-ui license scope\n") and UI_LICENSE_SCOPE in value
                and "MIT License" in value and re.search(r"Copyright.*\d{4}.*\S", value)
                and " ".join(MIT_TERMS.split()) in " ".join(value.split()))


def inside(entry: str, prefixes: Sequence[str]) -> bool:
    """Whether a packed path stays inside the reviewed prefixes. A `!` entry only removes files, so it is always safe."""
    if entry.startswith("!"):
        return not entry.startswith("!!")
    normalized = entry.removeprefix("./")
    if not normalized or normalized.startswith("/") or "\\" in normalized or {"", "..", "."} & set(normalized.split("/")):
        return False
    return any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in prefixes)


def strings(value: object) -> Iterator[str]:
    """Yield the string leaves of a manifest field (a path, a list of paths or a mapping to paths), keys excluded."""
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            yield current
        elif isinstance(current, list):
            pending += current
        elif isinstance(current, dict):
            pending += list(current.values())


def ui_packing_problems(path: str, package: dict[str, Any]) -> list[str]:
    """Structural rules for a public UI package, so routine export and file changes need no shared PR."""
    where = path + "/package.json"
    problems = []
    if package.get("name") != "@ejm/" + path.split("/")[1]:
        problems.append(f"{where}: name must be @ejm/{path.split('/')[1]}")
    scripts = package.get("scripts")
    if "scripts" in package and not isinstance(scripts, dict):
        problems.append(f"{where}: scripts must be an object")
    problems += [f"{where}: lifecycle script {hook} could change the packed files" for hook in UI_LIFECYCLE_SCRIPTS if isinstance(scripts, dict) and hook in scripts]
    problems += [f"{where}: {field} could change the packed files" for field in ("bundleDependencies", "bundledDependencies", "workspaces") if field in package]
    prefixes = UI_PACKING_PREFIXES[path]
    files = package.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(entry, str) for entry in files):
        problems.append(f"{where}: files must list exactly what is packed")
    else:
        problems += [f"{where}: files entry {entry!r} is outside the reviewed set: {', '.join(prefixes)}" for entry in files if not inside(entry, prefixes)]
    # npm always packs the files named by these fields, whatever `files` says.
    for field in ("main", "browser", "bin", "man", "directories"):
        problems += [f"{where}: {field} {target!r} is outside the reviewed set: {', '.join(prefixes)}"
                     for target in strings(package.get(field)) if not inside(target, prefixes)]
    return problems


def ui_package_problems(root: Path, path: str) -> list[str]:
    prefix = path + "/" if path else ""
    package = manifest(root, prefix + "package.json")
    config = package.get("publishConfig")
    public = path in UI_PUBLIC and "private" not in package and config == UI_PUBLISH_CONFIG and config["provenance"] is True
    problems = []
    if package.get("license") != "SEE LICENSE IN LICENSE" or not (public or package.get("private") is True):
        problems.append("UI npm packages must remain private and preserve their scoped license: " + (prefix or "<root>"))
    if public:
        problems += ui_packing_problems(path, package)
    if not path:
        return problems
    if package.get("repository") != {"type": "git", "url": "git+https://github.com/ejmlabs/ejm-ui.git", "directory": path}:
        problems.append("UI package repository metadata differs from its owner: " + path)
    if not scoped_license(read(root, prefix + "LICENSE")) or not read(root, prefix + "THIRD_PARTY_NOTICES.md").strip():
        problems.append("UI package needs complete scoped license and third-party notices: " + path)
    return problems


def ui_license_problems(root: Path, text: str) -> list[str]:
    """Keep the UI software grant, reserved assets, and packaged font notices."""
    problems = []
    if not scoped_license(text):
        problems.append("LICENSE: UI license must preserve complete MIT terms and reserved brand rights")
    packages: list[str] | None = None
    with collecting(problems, "packages"):
        packages = ui_packages(root)
    problems += [path + ": the reviewed public UI package is missing" for path in UI_PUBLIC if packages is not None and path not in packages]
    for path in ("", *(packages or [])):
        with collecting(problems, path + "/package.json"):
            problems += ui_package_problems(root, path)
    with collecting(problems, "crates/ejm-tui/Cargo.toml"):
        crate = table(manifest(root, "crates/ejm-tui/Cargo.toml"), "crates/ejm-tui/Cargo.toml", "package")
        if crate.get("license") != "MIT" or crate.get("publish") is not False:
            raise ValueError("crates/ejm-tui/Cargo.toml: UI terminal crate must retain MIT terms and remain unpublished")
    for name in ("Manrope", "IBMPlexMono"):
        with collecting(problems, name):
            source = read(root, "packages/tokens/assets/fonts/" + name + "-OFL.txt", preserve_newlines=True)
            if hashlib.sha256(source.encode("utf-8")).hexdigest() != UI_FONT_HASHES[name]:
                raise ValueError("UI fonts need their original OFL and copyright notices: " + name)
            copy = read(root, "packages/ui/src/fonts/" + name + "-OFL.txt")
            if [line.rstrip() for line in copy.splitlines()] != [line.rstrip() for line in source.splitlines()]:
                raise ValueError("UI package font notice differs from the token owner: " + name)
    return problems


def version_problems(root: Path, profile: str) -> tuple[str, list[str]]:
    """Return VERSION (empty if invalid) and every version or license problem."""
    if profile not in PROFILES:
        raise ValueError("Unknown repository profile")
    settings = PROFILES[profile]
    problems: list[str] = []
    canonical = ""
    with collecting(problems, "VERSION"):
        value = read(root, "VERSION").strip()
        if not semver(value):
            raise ValueError("VERSION must be valid SemVer without a v prefix")
        canonical = value
    problems += license_problems(root, profile)
    if not canonical:
        return canonical, problems
    for path, key in settings.versions:
        with collecting(problems, path):
            found = lookup(manifest(root, path), path, *key.split("."))
            if found != canonical:
                raise ValueError(f"{path}: {key} differs from VERSION ({found!r} != {canonical})")
    for path, keys in settings.locks:
        with collecting(problems, path):
            found = lookup(manifest(root, path), path, *keys)
            if found != canonical:
                raise ValueError(f"{path}: {'.'.join(keys)} differs from VERSION ({found!r} != {canonical})")
    if profile == "ejm-ui":
        problems += ui_version_problems(root, canonical)
    if profile == "ejm-harness":
        problems += harness_sdk_problems(root, canonical)
    if settings.cargo_lock:
        with collecting(problems, settings.cargo_lock):
            lock = manifest(root, settings.cargo_lock)
            owned = [p for p in lookup(lock, settings.cargo_lock, "package") if p["name"] == profile or (profile == "ejm-harness" and p["name"].startswith("ejm-harness"))]
            if not owned or any(p["version"] != canonical for p in owned):
                raise ValueError(f"{settings.cargo_lock}: owned Cargo lock package versions differ from VERSION")
    with collecting(problems, "CHANGELOG.md"):
        if not re.search(r"^## \[" + re.escape(canonical) + r"\] - \d{4}-\d{2}-\d{2}$", read(root, "CHANGELOG.md"), re.MULTILINE):
            raise ValueError("CHANGELOG.md needs a dated entry for VERSION")
    return canonical, problems


def ui_version_problems(root: Path, canonical: str) -> list[str]:
    problems: list[str] = []
    packages: list[str] = []
    with collecting(problems, "packages"):
        packages = ui_packages(root)
    lock: dict[str, Any] = {}
    with collecting(problems, "package-lock.json"):
        lock = manifest(root, "package-lock.json")
    for path in ("", *packages):
        if path:
            with collecting(problems, path + "/package.json"):
                found = lookup(manifest(root, path + "/package.json"), path + "/package.json", "version")
                if found != canonical:
                    raise ValueError(f"{path}/package.json: version differs from VERSION ({found!r} != {canonical})")
        if lock:
            with collecting(problems, "package-lock.json"):
                if lookup(lock, "package-lock.json", "packages", path, "version") != canonical:
                    raise ValueError("Owned UI npm lock package differs from VERSION: " + (path or "<root>"))
    with collecting(problems, "crates/ejm-tui/Cargo.lock"):
        crate_lock = manifest(root, "crates/ejm-tui/Cargo.lock")
        owned = [package for package in lookup(crate_lock, "crates/ejm-tui/Cargo.lock", "package") if package["name"] == "ejm-tui"]
        if len(owned) != 1 or owned[0]["version"] != canonical:
            raise ValueError("Owned UI Cargo lock package differs from VERSION")
    return problems


def harness_sdk_problems(root: Path, canonical: str) -> list[str]:
    problems: list[str] = []
    for path in ("sdk/typescript/LICENSE", "sdk/python/LICENSE"):
        with collecting(problems, path):
            if read(root, path) != read(root, "LICENSE"):
                raise ValueError("SDK license text differs from root: " + path)
    with collecting(problems, "sdk/python/uv.lock"):
        python_lock = manifest(root, "sdk/python/uv.lock")
        if not any(p["name"] == "ejm-harness" and p["version"] == canonical for p in lookup(python_lock, "sdk/python/uv.lock", "package")):
            raise ValueError("SDK Python lock version differs from VERSION")
    return problems


def versions(root: Path, profile: str) -> str:
    """Return the canonical VERSION after checking every manifest, lock and license that must match it."""
    canonical, problems = version_problems(root, profile)
    raise_problems(problems)
    return canonical


# Markdown: fenced blocks and inline code are not links, so they are removed before looking for `](destination)`.
FENCE = re.compile(r"\s*(`{3,}|~{3,})(.*)")
SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")
TITLE = re.compile(r"\"[^\"]*\"|'[^']*'|\([^)]*\)")
EM_DASH = chr(0x2014)
BAD_TEXT = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")


def without_code_spans(line: str) -> str:
    """Remove `inline code` in one pass, pairing each backtick run with the next run of the same length."""
    runs = [(match.start(), match.end()) for match in re.finditer(r"`+", line)]
    closer: dict[int, int] = {}
    latest: dict[int, int] = {}
    for index in range(len(runs) - 1, -1, -1):
        length = runs[index][1] - runs[index][0]
        if length in latest:
            closer[index] = latest[length]
        latest[length] = index
    pieces = []
    cursor = index = 0
    while index < len(runs):
        if index in closer:
            pieces.append(line[cursor:runs[index][0]])
            cursor = runs[closer[index]][1]
            index = closer[index]
        index += 1
    pieces.append(line[cursor:])
    return " ".join(pieces)


def link_destination(text: str) -> str | None:
    """Parse `destination "optional title")` after `](`, allowing balanced parentheses; None if it is not a link."""
    text = text.lstrip(" \t")
    if text.startswith("<"):
        end = text.find(">")
        if end == -1:
            return None
        destination, rest = text[1:end], text[end + 1:]
    else:
        depth = end = 0
        while end < len(text) and text[end] not in " \t":
            if text[end] == "(":
                depth += 1
            elif text[end] == ")":
                if depth == 0:
                    break
                depth -= 1
            end += 1
        destination, rest = text[:end], text[end:]
    rest = rest.lstrip(" \t")
    title = TITLE.match(rest)
    if title:
        rest = rest[title.end():].lstrip(" \t")
    return destination if rest.startswith(")") else None


def markdown_links(text: str) -> Iterator[tuple[int, str]]:
    """Yield (line number, destination) for every inline link outside code, examining a bounded number of candidates."""
    fence = ""
    candidates = 0
    for number, line in enumerate(text.split("\n"), 1):
        marker = FENCE.fullmatch(line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = ""
            continue
        if marker and not (marker[1][0] == "`" and "`" in marker[2]):
            fence = marker[1]
            continue
        plain = without_code_spans(line)
        start = plain.find("](")
        while start != -1:
            candidates += 1
            if candidates > MAX_LINKS:
                raise ValueError(f"more than {MAX_LINKS} links; not all were checked")
            destination = link_destination(plain[start + 2:start + 2 + 1024])
            if destination is not None:
                yield number, destination
            start = plain.find("](", start + 2)


def link_problem(root: Path, directory: str, target: str) -> str | None:
    """Return why a relative link is broken. Targets starting with `/` are relative to the repository root."""
    path = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not path or SCHEME.match(path) or path.startswith("//"):
        return None
    resolved = posixpath.normpath(posixpath.join("" if path.startswith("/") else directory, path.lstrip("/")))
    if resolved == ".." or resolved.startswith("../"):
        return "outside the repository"
    return None if (root / resolved).exists() else "missing"


def document_problems(root: Path, path: str) -> list[str]:
    text = read(root, path)
    if not text.strip():
        return [f"{path}: document is empty"]
    problems = []
    if EM_DASH in text:
        problems.append(f"{path}:{text[:text.index(EM_DASH)].count(chr(10)) + 1}: em dash; write a plain sentence")
    if path.endswith(".md"):
        broken = []
        try:
            for number, target in markdown_links(text):
                reason = link_problem(root, posixpath.dirname(path), target.strip("<>"))
                if reason:
                    broken.append(f"{path}:{number}: link target is {reason}: {target}")
        except ValueError as error:
            broken.append(f"{path}: {error}")
        problems += broken[:20]
        if len(broken) > 20:
            problems.append(f"{path}: and {len(broken) - 20} more broken links")
    return problems


def consumer_workflows(revision: str, *, native: bool = False, cache: bool = False, deploy: bool = False) -> dict[str, str]:
    """Return the canonical consumer workflows for one reviewed revision, as the sync tooling emits them."""
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Standards revision must be a full lowercase commit SHA")
    files = {"pr.yml": PR_CALLER, "release.yml": NATIVE_RELEASE_CALLER if native else RELEASE_CALLER}
    if cache:
        files["cache.yml"] = WARM_CACHE_CALLER
    if deploy:
        files["deploy.yml"] = SITE_DEPLOY_CALLER
    return {name: text.replace("STANDARDS_REVISION", revision) for name, text in files.items()}


def caller_mismatch(name: str, expected: str, actual: str) -> str:
    """Name the file and show a bounded diff against the canonical text."""
    head = "Workflow differs from the canonical consumer: " + name
    if len(actual) > MAX_DIFF_BYTES:
        return head + " (too large to diff)"
    diff = islice(difflib.unified_diff(expected.splitlines(), actual.splitlines(), "canonical/" + name, "actual/" + name, lineterm="", n=2), MAX_DIFF_LINES + 1)
    shown = list(diff)
    return head + "\n" + "\n".join(shown[:MAX_DIFF_LINES]) + ("\n..." if len(shown) > MAX_DIFF_LINES else "")


# A deliberately small YAML subset for product-owned workflows: plain block mappings and lists, plain, quoted or literal
# scalars and flow lists of plain words. Everything else is rejected, so no anchor, alias, tag, flow mapping, quoted key,
# document marker or duplicate key can hide a permission, a secret or an action from the rules below.
EXTRA_TRIGGERS = frozenset({"push", "pull_request", "workflow_dispatch", "schedule", "merge_group"})
TOP_LEVEL_KEYS = frozenset({"name", "run-name", "on", "permissions", "env", "defaults", "concurrency", "jobs"})
JOB_KEYS_FORBIDDEN = frozenset({"permissions", "environment", "secrets"})
CREDENTIAL_WORDS = ("secrets", "github.token", "github_token", "tojson(github)", "github[")
MAX_DEPTH = 40
KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):(?: |$)")
DOUBLE_QUOTED = re.compile(r'"([^"\\]*)"(?: +#.*)?')
SINGLE_QUOTED = re.compile(r"'((?:[^']|'')*)'(?: +#.*)?")
BLOCK_HEADER = re.compile(r"[|>](?:([1-9])[+-]?|[+-]([1-9])?)?(?: +#.*)?")
EMPTY_MAPPING = re.compile(r"\{\}(?: +#.*)?")
FLOW_WORD = r"""[A-Za-z0-9_][A-Za-z0-9_./*+@=-]*|"[^"\\,]*"|'[^',]*'"""
FLOW_LIST = re.compile(r"\[ *(?:(?:" + FLOW_WORD + r")(?: *, *(?:" + FLOW_WORD + r"))*)? *\](?: +#.*)?")
FLOW_ITEM = re.compile(FLOW_WORD)
PINNED_ACTION = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}")
LOCAL_ACTION = re.compile(r"\./\.github/actions/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
BRACKET_NAME = re.compile(r"\[(?:'([^']*)'|\"([^\"]*)\")\]")


class Header(NamedTuple):
    """A literal or folded block scalar header; its lines follow."""

    indicator: int | None


class Line(NamedTuple):
    number: int
    indent: int
    kind: str  # "key", "item" (a list entry that starts a mapping) or "scalar" (a list entry that is a value)
    key: str = ""
    value: str | list[str] | dict[str, Any] | None = None


def expression_spans(text: str) -> Iterator[tuple[int, int, bool]]:
    """Yield (start, end, closed) for each `${{ }}` in one linear pass, honoring single-quoted strings."""
    position = 0
    while (start := text.find("${{", position)) != -1:
        index, quoted = start + 3, False
        while index < len(text):
            if text[index] == "'":
                quoted = not quoted
            elif not quoted and text.startswith("}}", index):
                break
            index += 1
        else:
            yield start, len(text), False
            return
        yield start, index + 2, True
        position = index + 2


def plain_value(text: str, where: str) -> str:
    text = text.split(" #", 1)[0].rstrip(" ")
    pieces = []
    cursor = 0
    for start, end, closed in expression_spans(text):
        if not closed:
            raise ValueError(f"{where}: unterminated expression")
        pieces += [text[cursor:start], "_"]
        cursor = end
    masked = "".join([*pieces, text[cursor:]])
    if ": " in masked or masked.endswith(":"):
        raise ValueError(f"{where}: a plain value cannot contain ': ' (quote it or use a literal block)")
    return text


def scalar_value(text: str, where: str) -> str | list[str] | dict[str, Any] | Header | None:
    """Parse the text after `key:` or `- `. None means the value is empty and children may follow."""
    text = text.strip(" ")
    if not text or text.startswith("#"):
        return None
    first = text[0]
    if first == '"':
        match = DOUBLE_QUOTED.fullmatch(text)
        if not match:
            raise ValueError(f"{where}: a double-quoted value must close on its line and use no backslash (use single quotes or a literal block)")
        return match[1]
    if first == "'":
        match = SINGLE_QUOTED.fullmatch(text)
        if not match:
            raise ValueError(f"{where}: a single-quoted value must close on its line")
        return match[1].replace("''", "'")
    if first in "|>":
        match = BLOCK_HEADER.fullmatch(text)
        if not match:
            raise ValueError(f"{where}: unsupported block scalar header")
        return Header(int(match[1] or match[2]) if match[1] or match[2] else None)
    if first == "{":
        if not EMPTY_MAPPING.fullmatch(text):
            raise ValueError(f"{where}: flow mappings are not supported (write a block mapping)")
        return {}
    if first == "[":
        if not FLOW_LIST.fullmatch(text):
            raise ValueError(f"{where}: a flow list may hold only plain or quoted words")
        return [item[1:-1] if item[0] in "\"'" else item for item in FLOW_ITEM.findall(text.split("]", 1)[0])]
    if first in "&*!%@`,]}#?:" or text == "-" or text.startswith("- "):
        raise ValueError(f"{where}: anchors, aliases, tags and other YAML indicators are not supported")
    return plain_value(text, where)


def tokenize(text: str, name: str) -> list[Line]:
    """Split a workflow into key, list-entry and scalar lines, folding literal block scalars into their key's value."""
    lines: list[Line] = []
    owner = -1
    parent, indicator, content_indent = 0, None, None
    content: list[str] = []
    for number, raw in enumerate(text.split("\n"), 1):
        stripped = raw.lstrip(" ")
        indent = len(raw) - len(stripped)
        if owner >= 0:
            if not stripped:
                content.append("")
                continue
            if content_indent is None and indent > parent:
                content_indent = indent if indicator is None else parent + indicator
            if content_indent is not None and indent >= content_indent:
                content.append(raw[content_indent:])
                continue
            lines[owner] = lines[owner]._replace(value="\n".join(content))
            owner = -1
        if not stripped or stripped.startswith("#"):
            continue
        where = f"{name}:{number}"
        if "\t" in raw:
            raise ValueError(f"{where}: tabs are not allowed outside literal blocks")
        entry = stripped.startswith("- ")
        inner = stripped[1:].lstrip(" ") if entry else stripped
        column = indent + len(stripped) - len(inner) if entry else indent
        match = KEY.match(inner)
        if inner == "-" or inner.startswith("- "):
            raise ValueError(f"{where}: nested or bare list entries are not supported")
        if match:
            if entry:
                lines.append(Line(number, indent, "item"))
            value = scalar_value(inner[match.end():], where)
            if isinstance(value, Header):
                lines.append(Line(number, column, "key", match[1], ""))
                owner, parent, indicator, content_indent, content = len(lines) - 1, column, value.indicator, None, []
            else:
                lines.append(Line(number, column, "key", match[1], value))
        elif entry:
            value = scalar_value(inner, where)
            if not isinstance(value, str):
                raise ValueError(f"{where}: a list entry must be a plain or quoted scalar or start a mapping")
            lines.append(Line(number, indent, "scalar", "", value))
        else:
            raise ValueError(f"{where}: unsupported YAML ({stripped[:40]!r}); use plain block mappings and lists, no anchors, tags, flow mappings, quoted keys or document markers")
    if owner >= 0:
        lines[owner] = lines[owner]._replace(value="\n".join(content))
    return lines


def build_tree(lines: list[Line], position: int, depth: int, name: str) -> tuple[dict[str, Any] | list[Any], int]:
    """Build nested dicts and lists from tokenized lines, rejecting duplicate keys at any level."""
    if depth > MAX_DEPTH:
        raise ValueError(f"{name}:{lines[position].number}: nested more than {MAX_DEPTH} levels")
    indent = lines[position].indent
    if lines[position].kind != "key":
        items: list[Any] = []
        while position < len(lines) and lines[position].indent == indent and lines[position].kind != "key":
            line = lines[position]
            position += 1
            if line.kind == "scalar":
                items.append(line.value)
            elif position < len(lines) and lines[position].kind == "key" and lines[position].indent > indent:
                item, position = build_tree(lines, position, depth + 1, name)
                items.append(item)
            else:
                raise ValueError(f"{name}:{line.number}: a list entry needs a value or a mapping")
        return items, position
    mapping: dict[str, Any] = {}
    while position < len(lines) and lines[position].indent == indent and lines[position].kind == "key":
        line = lines[position]
        position += 1
        if line.key in mapping:
            raise ValueError(f"{name}:{line.number}: duplicate key {line.key}")
        value: Any = line.value
        if value is None:
            following = lines[position] if position < len(lines) else None
            if following and (following.indent > indent or (following.indent == indent and following.kind != "key")):
                value, position = build_tree(lines, position, depth + 1, name)
            else:
                value = ""
        mapping[line.key] = value
    return mapping, position


def parse_workflow(text: str, name: str) -> dict[str, Any]:
    if "\r" in text:
        raise ValueError(f"{name}: use LF line endings")
    if match := BAD_TEXT.search(text):
        raise ValueError(f"{name}: control, line-separator or invisible character U+{ord(match[0]):04X} is not allowed")
    lines = tokenize(text, name)
    if not lines:
        raise ValueError(f"{name}: workflow is empty")
    if lines[0].indent != 0 or lines[0].kind != "key":
        raise ValueError(f"{name}:{lines[0].number}: a workflow starts with an unindented top-level key")
    tree, position = build_tree(lines, 0, 0, name)
    if position != len(lines):
        raise ValueError(f"{name}:{lines[position].number}: unexpected indentation or list entry (a second document or a misplaced key?)")
    return cast("dict[str, Any]", tree)


def walk(node: object, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str, object]]:
    """Yield (path, key, value) for every mapping entry; a list entry adds "-" to the path."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, key, value
            yield from walk(value, (*path, key))
    elif isinstance(node, list):
        for item in node:
            yield from walk(item, (*path, "-"))


def scalars(node: object) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from scalars(value)
    elif isinstance(node, list):
        for value in node:
            yield from scalars(value)


def expression_problems(text: str, name: str) -> list[str]:
    """Reject an expression that reads a secret or the token, whatever spelling it uses."""
    found = []
    for start, end, _closed in expression_spans(text):
        body = BRACKET_NAME.sub(lambda match: "." + (match[1] or match[2] or ""), re.sub(r"\s+", "", text[start + 3:end]).lower())
        found += [f"{name}: an expression references {word}; product workflows use no secret or token" for word in CREDENTIAL_WORDS if word in body]
    return found


def trigger_problems(on: object, name: str, *, build: bool) -> list[str]:
    if isinstance(on, dict):
        names = list(on)
    elif isinstance(on, list):
        names = [str(item) for item in on]
    elif isinstance(on, str) and on:
        names = [on]
    else:
        return [f"{name}: declare the triggers under `on:`"]
    if build:
        mapping = on if isinstance(on, dict) else {}
        exact = set(mapping) == {"workflow_dispatch", "push"} and mapping["workflow_dispatch"] in ("", {}) and mapping["push"] == {"branches": ["main"]}
        return [] if exact else [f"{name}: a build workflow runs only on workflow_dispatch and pushes to main (push with branches [main], no other keys)"]
    return [f"{name}: trigger {item!r} is not allowed; use push, pull_request, workflow_dispatch, schedule or merge_group" for item in names if item not in EXTRA_TRIGGERS]


def uses_problems(value: object, name: str, *, build: bool) -> list[str]:
    if isinstance(value, str) and ".." not in value.split("/") and (PINNED_ACTION.fullmatch(value) or (not build and LOCAL_ACTION.fullmatch(value))):
        return []
    return [f"{name}: uses {value!r} must be owner/repo[/path]@<40-hex commit>" + ("" if build else " or a local ./.github/actions path")]


def release_uploads(tree: dict[str, Any]) -> int:
    """Count upload-artifact steps that publish the release-files artifact."""
    jobs = tree.get("jobs")
    steps = [step for job in (jobs.values() if isinstance(jobs, dict) else []) if isinstance(job, dict) and isinstance(job.get("steps"), list) for step in job["steps"]]
    return sum(1 for step in steps if isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/upload-artifact@")
               and isinstance(step.get("with"), dict) and step["with"].get("name") == "release-files")


def lint_workflow(text: str, name: str, *, build: bool = False) -> list[str]:
    """Return every reason a product workflow is not provably credential-free.

    Product workflows run PR code, so they get a read-only token (`contents: read` or none), no secrets or
    environments, only safe triggers and pinned actions. `build=True` adds the native build rules: it runs
    only on workflow_dispatch and pushes to main, uploads exactly one release-files artifact and uses no
    local action. This reads the shape of the file; review still covers what the steps run.
    """
    try:
        tree = parse_workflow(text, name)
    except ValueError as error:
        return [str(error)]
    problems = [f"{name}: unknown top-level key {key!r}" for key in tree if key not in TOP_LEVEL_KEYS]
    problems += trigger_problems(tree.get("on"), name, build=build)
    allowed = [{"contents": "read"}] if build else [{"contents": "read"}, {}]
    if tree.get("permissions") not in allowed:
        problems.append(f"{name}: top-level permissions must be exactly `contents: read`" + ("" if build else " or `{}`"))
    jobs = tree.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        problems.append(f"{name}: jobs must be a non-empty mapping")
    else:
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                problems.append(f"{name}: job {job_id} must be a mapping")
                continue
            problems += [f"{name}: job {job_id} sets {key}; jobs keep the read-only top-level permissions and use no secret or environment"
                         for key in job if key.lower() in JOB_KEYS_FORBIDDEN]
    for _path, key, value in walk(tree):
        if key.lower() == "uses":
            problems += uses_problems(value, name, build=build)
        elif key.lower() == "persist-credentials" and (not isinstance(value, str) or value.strip().lower() == "true" or "${{" in value):
            problems.append(f"{name}: persist-credentials must be false")
        elif key.lower() == "github_token":
            problems.append(f"{name}: GITHUB_TOKEN must not be set")
    for text_value in scalars(tree):
        problems += expression_problems(text_value, name)
    if build:
        named = sum(1 for _path, key, value in walk(tree) if key == "name" and value == "release-files")
        if named != 1 or release_uploads(tree) != 1:
            problems.append(f"{name}: a build workflow must upload exactly one artifact named release-files")
    return list(dict.fromkeys(problems))


def native_build(text: str) -> None:
    """Lint a product build workflow: read-only token, no secrets, pinned actions, one release-files artifact."""
    raise_problems(lint_workflow(text, "build.yml", build=True))


def _reusable_workflow(text: str, name: str) -> None:
    """Accept only the trigger scaffold and YAML subset emitted by our generator."""
    header = "# Generated by scripts/build_workflows.py. Edit scripts and regenerate.\n"
    if name == "governance.yml":
        # The only secret is the optional harness token. The retired model key is not declared.
        header += """"name": "Human-admitted PR checks"
"on":
  "workflow_call":
    "secrets":
      "EJM_HARNESS_TOKEN":
        "required": false
"permissions": {}
"""
        roots = ['"jobs":']
    elif name == "verify-build.yml":
        header += """"name": "Verified build run"
"on":
  "workflow_call":
    "inputs":
      "commit":
        "required": true
        "type": "string"
      "build-workflow":
        "required": true
        "type": "string"
      "build-run-id":
        "required": true
        "type": "string"
"permissions": {}
"""
        roots = ['"jobs":']
    elif name == "attach-assets.yml":
        header += """"name": "Attach verified build files"
"on":
  "workflow_call":
    "inputs":
      "commit":
        "required": true
        "type": "string"
      "build-workflow":
        "required": true
        "type": "string"
      "build-run-id":
        "required": true
        "type": "string"
      "version":
        "required": true
        "type": "string"
      "attest":
        "required": false
        "default": false
        "type": "boolean"
"permissions": {}
"""
        roots = ['"concurrency":', '"jobs":']
    elif name == "deploy-site.yml":
        header += """"name": "Deploy site"
"on":
  "workflow_call": {}
"permissions": {}
"""
        roots = ['"jobs":']
    elif name == "warm-cache.yml":
        header += """"name": "Warm trusted gate build caches"
"on":
  "workflow_call": {}
"permissions": {}
"""
        roots = ['"concurrency":', '"jobs":']
    else:
        header += """"name": "Checked draft source release"
"on":
  "workflow_call":
    "inputs":
      "commit":
        "required": true
        "type": "string"
      "version":
        "required": true
        "type": "string"
      "standards-ref":
        "required": true
        "type": "string"
"permissions": {}
"""
        roots = ['"concurrency":', '"jobs":']
    if not text.startswith(header):
        raise ValueError("Reusable workflow must retain its workflow_call scaffold: " + name)
    top = [line for line in text.splitlines() if line and not line[0].isspace()]
    expected = [line for line in header.splitlines() if line and not line[0].isspace()] + roots
    if top != expected:
        raise ValueError("Unexpected or duplicate reusable workflow key: " + name)

    # This is deliberately not a general YAML parser. The generator quotes keys
    # and scalar values as JSON and emits block strings for embedded scripts.
    # Reject other YAML syntax instead of guessing its meaning. Block contents
    # are data here; fake uses/on text inside a script is not workflow structure.
    # The admitted CLI owns one setup action in its credential-free quality job.
    # Match its complete canonical step and job, not a general local-action path.
    # The cache warm job builds reviewed main with the same hook, selected by repository name instead of admission.
    profile = "github.event.repository.name" if name == "warm-cache.yml" else "needs.admission.outputs.profile"
    cli_setup = """      -
        "name": "Prepare ejm-cli remote test prerequisites"
        "if": "${{ PROFILE == 'ejm-cli' }}"
        "uses": "./product/.github/actions/setup-ci"
""".replace("PROFILE", profile)
    structural = []
    local_uses = []
    parents: list[tuple[int, str | None]] = []
    environments = []
    block = None
    for number, line in enumerate(text.splitlines()):
        structural.append("")
        stripped = line.lstrip(" ")
        if not line.strip() or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if block is not None and indent > block:
            continue
        block = None
        while parents and indent <= parents[-1][0]:
            parents.pop()
        structural[-1] = line
        if stripped == "-":
            continue
        value: str | None
        if stripped.startswith("- "):
            key, value = None, stripped[2:]
        else:
            field = re.fullmatch(r'("(?:[^"\\]|\\.)*"):(?: (.*))?', stripped)
            if not field:
                raise ValueError("Reusable workflow must use canonical generated YAML: " + name)
            try:
                key = json.loads(field[1])
            except ValueError as error:
                raise ValueError("Reusable workflow has an unreadable key: " + name) from error
            if json.dumps(key) != field[1]:
                raise ValueError("Reusable workflow has a noncanonical key: " + name)
            value = field[2]
        if key == "environment" and len(parents) == 2 and parents[0][1] == "jobs":
            environments.append(line)
        if value is None:
            parents.append((indent, key))
            continue
        if value == "|":
            block = indent
            continue
        try:
            scalar = json.loads(value)
        except ValueError as error:
            raise ValueError("Reusable workflow must use canonical generated YAML: " + name) from error
        if isinstance(scalar, (dict, list)) and scalar:
            raise ValueError("Reusable workflow has an unexpected flow mapping or list: " + name)
        if key == "uses":
            if scalar == "./product/.github/actions/setup-ci":
                local_uses.append(number)
            elif not isinstance(scalar, str) or not re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", scalar):
                raise ValueError("Reusable workflow action must use an immutable SHA or the scoped CLI setup hook: " + name)

    visible = "\n".join(structural) + "\n"
    if name == "deploy-site.yml":
        deploys = {job: re.findall(r'(?ms)^  "' + job + r'":\n(.*?)(?=^  "[^\"]+":|\Z)', visible) for job in ("staging", "production")}
        expected = ['    "environment": "staging"', '    "environment": "production"']
        if environments != expected or any(len(found) != 1 or line not in found[0].splitlines() for (_, found), line in zip(deploys.items(), expected, strict=True)):
            raise ValueError("Only the staging and production deploy jobs may declare their environments: " + name)
    elif environments:
        raise ValueError("Reusable workflows must not declare an environment: " + name)

    if local_uses:
        # Comments and literal block contents are data. Bind the exception to
        # the actual quality.steps entry and its uses line, never a lookalike.
        quality = re.search(r'(?ms)^  "quality":\n(.*?)(?=^  "[^\"]+":|\Z)', visible)
        steps = re.search(r'(?ms)^    "steps":\n(.*?)(?=^    "[^\"]+":|\Z)', quality[1]) if quality else None
        hook = re.search(r"(?m)^" + re.escape(cli_setup) + r"(?=^      -\n|\Z)", steps[1]) if steps else None
        allowed = None
        if name in ("governance.yml", "warm-cache.yml") and hook:
            start = cast("re.Match[str]", quality).start(1) + cast("re.Match[str]", steps).start(1) + hook.start()
            allowed = visible[:start].count("\n") + len(cli_setup.splitlines()) - 1
        if local_uses != [allowed]:
            raise ValueError("Reusable workflow action must use an immutable SHA or the scoped CLI setup hook: " + name)


def workflow_problems(root: Path, profile: str) -> list[str]:
    """Check the caller workflows of one repository and return every problem."""
    settings = PROFILES[profile]
    github, directory = root / ".github", root / ".github/workflows"
    if github.is_symlink() or directory.is_symlink() or not directory.is_dir():
        return ["Missing or unsafe .github/workflows directory (neither .github nor workflows may be a symlink)"]
    with os.scandir(directory) as entries:
        listing = sorted(islice(entries, 201), key=lambda entry: entry.name)
    if len(listing) > 200:
        return ["Too many entries in .github/workflows"]
    names = {entry.name for entry in listing}
    native = settings.native and "build.yml" in names
    cache = settings.cache and "cache.yml" in names
    deploy = settings.deploy and "deploy.yml" in names
    publish = settings.publish and "publish.yml" in names
    shared = SHARED_WORKFLOWS if profile == ".github" else ()
    canonical = {"pr.yml", "release.yml", *shared, *(["build.yml"] if native else []), *(["cache.yml"] if cache else []),
                 *(["deploy.yml"] if deploy else []), *(["publish.yml"] if publish else [])}
    problems: list[str] = []
    prefix = ".github/workflows/"
    # Canonical names are read below, and read() rejects a symlink. Every other workflow must pass the credential-free lint.
    for entry in (entry for entry in listing if entry.name not in canonical):
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            problems.append(f"{prefix}{entry.name}: workflow entries must be regular files, not symlinks or directories")
        elif entry.name.lower().endswith((".yml", ".yaml")):
            with collecting(problems, prefix + entry.name):
                problems += lint_workflow(read(root, prefix + entry.name, limit=MAX_WORKFLOW_BYTES), prefix + entry.name)
        else:
            problems.append(f"{prefix}{entry.name}: only .yml and .yaml files belong in the workflows directory")
    pin = ""
    with collecting(problems, "pr.yml"):
        found = PR_PIN.search(read(root, prefix + "pr.yml"))
        if not found:
            raise ValueError("pr.yml: PR workflow must pin governance.yml to a full commit SHA")
        pin = found[1]
    if pin:
        for name, expected in consumer_workflows(pin, native=native, cache=cache, deploy=deploy).items():
            with collecting(problems, name):
                actual = read(root, prefix + name)
                if name == "deploy.yml" and not actual.endswith(INHERIT):
                    expected = SITE_DEPLOY_CALLER_WITHOUT_SECRETS.replace("STANDARDS_REVISION", pin)  # noqa: PLW2901 - the older accepted form
                if actual != expected:
                    problems.append(caller_mismatch(name, expected, actual))
    if native:
        with collecting(problems, "build.yml"):
            problems += lint_workflow(read(root, prefix + "build.yml", limit=MAX_WORKFLOW_BYTES), prefix + "build.yml", build=True)
    if publish:
        with collecting(problems, "publish.yml"):
            digest = hashlib.sha256(read_bytes(root, prefix + "publish.yml")).hexdigest()
            if digest != UI_PUBLISH_SHA256:
                problems.append(f"{prefix}publish.yml differs from the reviewed revision: its SHA-256 is {digest}, the reviewed one is {UI_PUBLISH_SHA256}. "
                                "After review, set UI_PUBLISH_SHA256 in scripts/standards.py to the new digest.")
    for name in shared:
        if name in names:
            with collecting(problems, name):
                _reusable_workflow(read(root, prefix + name), name)
    return problems


def workflows(root: Path, profile: str) -> None:
    if profile not in PROFILES:
        raise ValueError("Unknown repository profile")
    raise_problems(workflow_problems(root, profile))


def standards_problems(root: Path, profile: str) -> tuple[str, list[str]]:
    """Return VERSION and every problem found in one repository."""
    version, problems = version_problems(root, profile)
    for path in DOCS:
        with collecting(problems, path):
            problems += document_problems(root, path)
    for path in GITHUB_FILES:
        with collecting(problems, path):
            read(root, path)
    problems += workflow_problems(root, profile)
    if PROFILES[profile].harness_pin:
        with collecting(problems, ".github/harness-revision"):
            if not re.fullmatch(r"[0-9a-f]{40}\n?", read(root, ".github/harness-revision")):
                raise ValueError(".github/harness-revision: harness revision must be a full immutable commit")
    return version, problems


def standards(root: Path, profile: str) -> str:
    """Check one repository, raising every problem together; return its VERSION."""
    version, problems = standards_problems(root, profile)
    raise_problems(problems)
    return version


def standards_main(arguments: Sequence[str]) -> int:
    """Print each problem and return 1, or print the success line and return 0; never a traceback for a failed check."""
    if len(arguments) != 2:
        print("usage: standards.py ROOT PROFILE", file=sys.stderr)
        return 2
    try:
        version = standards(Path(arguments[0]), arguments[1])
    except StandardsError as error:
        shown = error.problems[:MAX_REPORTED]
        print("\n".join(shown) + (f"\nand {len(error.problems) - MAX_REPORTED} more problems" if len(error.problems) > MAX_REPORTED else ""), file=sys.stderr)
        print(f"Repository standards failed for {arguments[1]}: {len(error.problems)} problem(s)", file=sys.stderr)
        return 1
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Repository standards and version {version} passed for {arguments[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(standards_main(sys.argv[1:]))
