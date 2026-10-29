#!/usr/bin/env python3
"""Dependency-free documentation, workflow pin, and release version checks."""
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote

HEADINGS = ("Overview", "Status", "Requirements", "Quick start", "Usage", "Development", "Documentation", "Contributing", "Security", "Support", "License")
DOCS = ("README.md", "CONTRIBUTING.md", "SECURITY.md", "SUPPORT.md", "CODE_OF_CONDUCT.md", "RELEASING.md", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "LICENSE")
COMMUNITY_GUIDES = {"ejm-cli": "docs/contributing.md", "ejm-harness": "docs/contributing.md", "ejm-ide": "docs/development.md", "ejmlabs": "site/README.md", ".github": "docs/operations.md", "ejm-ui": "README.md#development"}
UI_PACKAGES = tuple("packages/" + name for name in ("core", "demos", "ink", "shots", "site", "ssg", "tokens", "ui"))
VERSIONS = {
    "ejm-cli": (("Cargo.toml", "workspace.package.version"),),
    "ejm-harness": (("Cargo.toml", "workspace.package.version"), ("sdk/typescript/package.json", "version"), ("sdk/python/pyproject.toml", "project.version"), ("registry/Cargo.toml", "package.version")),
    "ejm-ide": (("package.json", "version"), ("package-lock.json", "version"), ("src-tauri/Cargo.toml", "package.version"), ("src-tauri/tauri.conf.json", "version")),
    "ejmlabs": (("site/package.json", "version"),),
    ".github": (),
    "ejm-ui": (("package.json", "version"), ("package-lock.json", "version"), ("crates/ejm-tui/Cargo.toml", "package.version"),
               *((path + "/package.json", "version") for path in UI_PACKAGES)),
}
UI_LICENSE_SCOPE = """The ejmlabs name, logos, supplied brand artwork, design assets, templates, and
visual identity retain their owners' rights. All rights in those materials are
reserved except where a file or its accompanying notice gives a separate
license. Public access does not grant a right to use the marks or redistribute
the brand materials."""
# The owner's public npm set. Every other UI package stays private.
UI_PUBLIC = tuple("packages/" + name for name in ("core", "ssg", "tokens", "ui"))
UI_PUBLISH_CONFIG = {"access": "public", "provenance": True}
# Every manifest field that decides what npm packs or what a package is called.
UI_PACKING_FIELDS = ("name", "files", "main", "types", "typings", "exports", "bin", "browser", "module", "directories", "man",
                     "bundleDependencies", "bundledDependencies", "workspaces")
# Lifecycle scripts that npm runs while packing, publishing or installing; they can change the packed files.
UI_LIFECYCLE_SCRIPTS = ("preprepare", "prepare", "postprepare", "prepack", "postpack", "prepublish", "prepublishOnly", "publish",
                        "postpublish", "preinstall", "install", "postinstall")
# SHA-256 of the reviewed values of those fields and of any lifecycle scripts, present ones only, in that order, as compact JSON. Brand logos and
# artwork stay out of the tokens tarball because its reviewed `files` list ships only assets/fonts, brand and icons.
# Any change to a public package's packing manifest needs a new shared revision.
UI_PACKING_SHA256 = {
    "packages/core": "8340bf6bd1ea23bd372acaccfa303b3fe6bc5f631ca95780b5c9b00f656dba29",
    "packages/ssg": "8f0b1dd2b3bfc85d1d15c5107d90ad0e400c0eaf5b0880877eb97468264545da",
    "packages/tokens": "6a42d63e7e4e6140855f25a6b1c016e75d01582a0005319089e7f836514ba575",  # gitleaks:allow (package manifest digest)
    "packages/ui": "e22c0b53fb8ab7ae638952245f8b94531acff1302853403e6b303ae64b8a3be7",
}
# The reviewed ejm-ui publish workflow; any change needs a new shared revision.
UI_PUBLISH_SHA256 = "b28800bd599a24b07f385202bad0e8ef53bc5f503bdd600b51fbd4f461f656e9"
UI_FONT_NOTICES = tuple("packages/" + path + "/" + name + "-OFL.txt"
                        for path in ("tokens/assets/fonts", "ui/src/fonts") for name in ("Manrope", "IBMPlexMono"))
UI_FONT_HASHES = {
    "Manrope": "58172e0c0fac2cda8a37b348164bb55e44b0e69051e557e92b1d3f6910141f7b",
    "IBMPlexMono": "7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da",
}
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")
MODEL_KEYS = ("XAI_API_KEY",)
# Repositories that may ship native builds. One adopts the native release by adding build.yml.
NATIVE_RELEASE = ("ejm-cli", "ejm-harness")
SHARED_WORKFLOWS = ("governance.yml", "draft-release.yml", "verify-build.yml", "attach-assets.yml", "warm-cache.yml")
# Repositories whose Rust gate builds may restore main's trusted cache. One adopts it by adding cache.yml.
WARM_CACHE = ("ejm-cli", "ejm-harness", "ejm-ide", "ejm-ui")
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


def semver(value: str) -> bool:
    match = SEMVER.fullmatch(value)
    if not match:
        return False
    return not match[4] or all(not item.isdigit() or item == "0" or not item.startswith("0") for item in match[4].split("."))


def read(root: Path, path: str, *, preserve_newlines: bool = False) -> str:
    file = root / path
    if file.is_symlink() or not file.resolve().is_relative_to(root.resolve()) or not file.is_file():
        raise ValueError(f"Missing or unsafe file: {path}")
    if file.stat().st_size > 8_000_000:
        raise ValueError(f"File exceeds validation limit: {path}")
    if preserve_newlines:
        return file.read_bytes().decode("utf-8")
    return file.read_text(encoding="utf-8")


def versions(root: Path, profile: str) -> str:
    if profile not in VERSIONS:
        raise ValueError("Unknown repository profile")
    canonical = read(root, "VERSION").strip()
    if not semver(canonical):
        raise ValueError("VERSION must be valid SemVer without a v prefix")
    licenses(root, profile)
    for path, key in VERSIONS[profile]:
        text = read(root, path)
        value = json.loads(text) if path.endswith(".json") else tomllib.loads(text)
        for part in key.split("."):
            value = value[part]
        if value != canonical:
            raise ValueError(f"{path}: {key} differs from VERSION")
    if profile == "ejm-ide":
        lock = json.loads(read(root, "package-lock.json"))
        if lock["packages"][""]["version"] != canonical:
            raise ValueError("package-lock.json root package differs from VERSION")
    if profile == "ejm-ui":
        lock = json.loads(read(root, "package-lock.json"))
        for path in ("", *UI_PACKAGES):
            if lock["packages"][path]["version"] != canonical:
                raise ValueError("Owned UI npm lock package differs from VERSION: " + path)
        lock = tomllib.loads(read(root, "crates/ejm-tui/Cargo.lock"))
        owned = [package for package in lock["package"] if package["name"] == "ejm-tui"]
        if len(owned) != 1 or owned[0]["version"] != canonical:
            raise ValueError("Owned UI Cargo lock package differs from VERSION")
    if profile == "ejm-harness":
        for path in ("sdk/typescript/LICENSE", "sdk/python/LICENSE"):
            if read(root, path) != read(root, "LICENSE"):
                raise ValueError("SDK license text differs from root: " + path)
        lock = json.loads(read(root, "package-lock.json"))
        if lock["packages"]["sdk/typescript"]["version"] != canonical:
            raise ValueError("SDK npm lock version differs from VERSION")
        python_lock = tomllib.loads(read(root, "sdk/python/uv.lock"))
        if not any(p["name"] == "ejm-harness" and p["version"] == canonical for p in python_lock["package"]):
            raise ValueError("SDK Python lock version differs from VERSION")
    lockfile = "src-tauri/Cargo.lock" if profile == "ejm-ide" else "Cargo.lock"
    if profile in ("ejm-cli", "ejm-harness", "ejm-ide"):
        lock = tomllib.loads(read(root, lockfile))
        owned = [p for p in lock["package"] if p["name"] == profile or (profile == "ejm-harness" and p["name"].startswith("ejm-harness"))]
        if not owned or any(p["version"] != canonical for p in owned):
            raise ValueError("Owned Cargo lock package versions differ from VERSION")
    notes = read(root, "CHANGELOG.md")
    if not re.search(r"^## \[" + re.escape(canonical) + r"\] - \d{4}-\d{2}-\d{2}$", notes, re.MULTILINE):
        raise ValueError("CHANGELOG.md needs a dated entry for VERSION")
    return canonical


def licenses(root: Path, profile: str) -> None:
    if profile == "ejmlabs":
        if json.loads(read(root, "site/package.json")).get("license") != "SEE LICENSE IN ../LICENSE":
            raise ValueError("Studio metadata must preserve its specific rights notice")
        return
    text = read(root, "LICENSE")
    if profile == "ejm-ui":
        ui_licenses(root, text)
        return
    if not text.startswith("MIT License") or not re.search(r"Copyright.*\d{4}.*\S", text) or " ".join(MIT_TERMS.split()) not in " ".join(text.split()):
        raise ValueError("Complete MIT license terms and copyright notice are required")
    manifests = []
    if profile in ("ejm-cli", "ejm-harness"):
        cargo = tomllib.loads(read(root, "Cargo.toml"))
        if cargo["workspace"]["package"].get("license") != "MIT":
            raise ValueError("Workspace license must remain MIT")
        members = cargo["workspace"]["members"]
        if len(members) > 50:
            raise ValueError("Too many owned manifests")
        for member in members:
            package = tomllib.loads(read(root, member + "/Cargo.toml"))["package"]
            if package.get("license") not in ("MIT", {"workspace": True}):
                raise ValueError("Owned crate license differs from MIT: " + member)
    if profile == "ejm-harness":
        manifests = [("sdk/typescript/package.json", "license"), ("sdk/python/pyproject.toml", "project.license"), ("registry/Cargo.toml", "package.license")]
    elif profile == "ejm-ide":
        manifests = [("package.json", "license"), ("src-tauri/Cargo.toml", "package.license")]
    for path, key in manifests:
        value = json.loads(read(root, path)) if path.endswith(".json") else tomllib.loads(read(root, path))
        for part in key.split("."):
            value = value[part]
        if value != "MIT":
            raise ValueError("Owned manifest license differs from MIT: " + path)


def ui_packing(package: dict[str, Any]) -> str:
    """Return the digest of a manifest's packing fields, which must match the reviewed values exactly."""
    values = {field: package[field] for field in UI_PACKING_FIELDS if field in package}
    scripts = package.get("scripts")
    if "scripts" in package and not isinstance(scripts, dict):
        values["scripts"] = scripts
    elif isinstance(scripts, dict) and any(name in scripts for name in UI_LIFECYCLE_SCRIPTS):
        values["scripts"] = {name: scripts[name] for name in UI_LIFECYCLE_SCRIPTS if name in scripts}
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode("utf-8")).hexdigest()


def ui_licenses(root: Path, text: str) -> None:
    """Keep the UI software grant, reserved assets, and packaged font notices."""
    def scoped_license(value: str) -> bool:
        return bool(value.startswith("ejm-ui license scope\n") and UI_LICENSE_SCOPE in value
                    and "MIT License" in value and re.search(r"Copyright.*\d{4}.*\S", value)
                    and " ".join(MIT_TERMS.split()) in " ".join(value.split()))

    if not scoped_license(text):
        raise ValueError("UI license must preserve complete MIT terms and reserved brand rights")
    manifests = {path.parent.relative_to(root).as_posix() for path in root.glob("packages/*/package.json")}
    if manifests != set(UI_PACKAGES):
        raise ValueError("UI owned package inventory changed; review its version and license policy")
    for path in ("", *UI_PACKAGES):
        prefix = path + "/" if path else ""
        package = json.loads(read(root, prefix + "package.json"))
        config = package.get("publishConfig")
        public = (path in UI_PUBLIC and "private" not in package and config == UI_PUBLISH_CONFIG
                  and config["provenance"] is True)
        if package.get("license") != "SEE LICENSE IN LICENSE" or not (public or package.get("private") is True):
            raise ValueError("UI npm packages must remain private and preserve their scoped license: " + prefix)
        if public and ui_packing(package) != UI_PACKING_SHA256[path]:
            raise ValueError("Public UI package name and packed files differ from the reviewed values: " + prefix)
        if not path:
            continue
        if package.get("repository") != {"type": "git", "url": "git+https://github.com/ejmlabs/ejm-ui.git", "directory": path}:
            raise ValueError("UI package repository metadata differs from its owner: " + path)
        if not scoped_license(read(root, prefix + "LICENSE")) or not read(root, prefix + "THIRD_PARTY_NOTICES.md").strip():
            raise ValueError("UI package needs complete scoped license and third-party notices: " + path)
    crate = tomllib.loads(read(root, "crates/ejm-tui/Cargo.toml"))["package"]
    if crate.get("license") != "MIT" or crate.get("publish") is not False:
        raise ValueError("UI terminal crate must retain MIT terms and remain unpublished")
    for name in ("Manrope", "IBMPlexMono"):
        source = read(root, "packages/tokens/assets/fonts/" + name + "-OFL.txt", preserve_newlines=True)
        if hashlib.sha256(source.encode("utf-8")).hexdigest() != UI_FONT_HASHES[name]:
            raise ValueError("UI fonts need their original OFL and copyright notices")
        copy = read(root, "packages/ui/src/fonts/" + name + "-OFL.txt")
        if [line.rstrip() for line in copy.splitlines()] != [line.rstrip() for line in source.splitlines()]:
            raise ValueError("UI package font notice differs from the token owner: " + name)


def consumer_workflows(revision: str, *, model_key: str = "XAI_API_KEY", native: bool = False) -> dict[str, str]:
    """Return the normal consumer workflows for one reviewed revision."""
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Standards revision must be a full lowercase commit SHA")
    if model_key not in MODEL_KEYS:
        raise ValueError("Unsupported model key name")
    documents = {
        "pr.yml": """name: Human-admitted PR checks
on:
  issue_comment:
    types: [created, edited, deleted]
  pull_request_target:
    types: [unlabeled]
permissions: {}
jobs:
  governance:
    if: ${{ github.event.issue.pull_request || github.event_name == 'pull_request_target' }}
    permissions:
      contents: read
      pull-requests: write
      statuses: write
      actions: write
    uses: ejmlabs/.github/.github/workflows/governance.yml@STANDARDS_REVISION
    secrets:
      XAI_API_KEY: ${{ secrets.XAI_API_KEY }}
      EJM_HARNESS_TOKEN: ${{ secrets.EJM_HARNESS_TOKEN }}
""",
        "release.yml": """name: Draft source release
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
""",
    }
    if native:
        documents["release.yml"] = NATIVE_RELEASE_CALLER
    return {name: text.replace("STANDARDS_REVISION", revision).replace("XAI_API_KEY", model_key) for name, text in documents.items()}


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


def native_build(text: str) -> None:
    """Lint a product build workflow: read-only token, no secrets, pinned actions, one release-files artifact.

    This is a line-based check of the shape, not a YAML parser: it accepts only plain block-style YAML. Review still covers what the build runs.
    """
    trigger = "on:\n  workflow_dispatch:\n  push:\n    branches: [main]\npermissions:\n  contents: read\n"
    head, _, rest = text.partition("\n")
    if re.search(r"[^\n\x20-\x7e]", text) or not re.fullmatch(r"name: [^\s\"'{}\[\]&*!|>#?%@`][^{}\[\]\t]*", head) or not rest.startswith(trigger):
        raise ValueError("Build workflow must run only on workflow_dispatch and pushes to main with contents: read")
    # Reject every spelling the canonical block style does not use, so a quoted key, a flow mapping,
    # an anchor or a tag cannot hide a permission or an action from the checks below.
    # The contents of literal block scalars (`run: |`) are script text, not YAML structure.
    block = content = None
    top = {"run-name", "env", "defaults", "concurrency", "jobs"}
    current = None
    for line in rest.removeprefix(trigger).splitlines():
        indent = len(line) - len(line.lstrip(" "))
        if block is not None and not line.strip(" "):
            continue
        if block is not None and content is None and indent > block:
            content = indent
        if content is not None and indent >= content:
            continue
        block = content = None
        key = re.sub(r"\$\{\{.*?\}\}", "", line)
        if not line.strip(" ") or line.lstrip(" ").startswith("#"):
            continue
        if not re.fullmatch(r" *(?:- )?[A-Za-z][A-Za-z0-9_-]*:(?: +[^\s\"'{}\[\]&*!|>#?][^{}\[\]\t]*| +[|>][1-9]?[+-]?| *)?| *- [^\s\"'{}\[\]&*!|>#?:-][^{}\[\]\t]*", key):
            raise ValueError("Build workflow must use plain block-style YAML without quoted keys, flow collections or anchors")
        if indent == 0 and not line.startswith("-"):
            current = line.split(":")[0]
            if current not in top:
                raise ValueError("Build workflow repeats a top-level key or uses an unknown one")
            top.remove(current)
        elif current is None:
            raise ValueError("Build workflow must set only the top-level read permission")
        if re.search(r": *[|>][1-9]?[+-]?$", line):
            block = len(line) - len(line.lstrip(" -"))
    if text.lower().count("permissions") != 1 or text.lower().count("uses") != len(re.findall(r"(?m)^\s*(?:- )?uses: ", text)):
        raise ValueError("Build workflow must use plain block-style YAML without quoted keys, flow collections or anchors")
    if len(re.findall(r"(?m)^\s*permissions:", text)) != 1:
        raise ValueError("Build workflow must set only the top-level read permission")
    if re.search(r"(?i)secrets|github\.token|GITHUB_TOKEN|id-token|environment:|pull_request|workflow_run|persist-credentials: *true", text):
        raise ValueError("Build workflow must use no secret, token, environment or untrusted trigger")
    uses = re.findall(r"(?m)^\s*(?:- )?uses: *(\S+)", text)
    if not uses or any(not re.fullmatch(r"[^@\s./][^@\s]*@[0-9a-f]{40}", item) for item in uses):
        raise ValueError("Build workflow actions must be pinned to full commit SHAs")
    if len(re.findall(r"(?m)^\s+(?:- )?name: release-files$", text)) != 1:
        raise ValueError("Build workflow must upload exactly one artifact named release-files")


def missing_model_key_workflows(revision: str, *, model_key: str = "XAI_API_KEY") -> dict[str, str]:
    """Return the exact shared-only caller for staged missing-key acceptance."""
    documents = consumer_workflows(revision, model_key=model_key)
    header, job = documents["pr.yml"].split("  governance:\n", 1)
    original = "    if: ${{ github.event.issue.pull_request || github.event_name == 'pull_request_target' }}\n"
    scope = "(github.event.issue.pull_request || github.event_name == 'pull_request_target') && github.repository == 'ejmlabs/.github'"
    label = "contains(github.event.issue.labels.*.name, 'acceptance:missing-model-key')"
    normal = job.replace(original, "    if: ${{ " + scope + " && !" + label + " }}\n")
    missing = job.split("    secrets:\n", 1)[0].replace(original, "    if: ${{ " + scope + " && " + label + " }}\n")
    documents["pr.yml"] = header + "  governance:\n" + normal + "  missing_model_key:\n" + missing
    return documents


def _reusable_workflow(text: str, name: str, *, model_key: str = "XAI_API_KEY") -> None:
    """Accept only the trigger scaffold and YAML subset emitted by our generator."""
    header = "# Generated by scripts/build_workflows.py. Edit scripts and regenerate.\n"
    if name == "governance.yml":
        header += """"name": "Human-admitted PR checks"
"on":
  "workflow_call":
    "secrets":
      "XAI_API_KEY":
        "required": false
      "EJM_HARNESS_TOKEN":
        "required": false
"permissions": {}
""".replace("XAI_API_KEY", model_key)
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
            key, value = json.loads(field[1]), field[2]
            if json.dumps(key) != field[1]:
                raise ValueError("Reusable workflow has a noncanonical key: " + name)
        if key == "environment" and len(parents) == 2 and parents[0][1] == "jobs":
            environments.append(line)
        if value is None:
            parents.append((indent, key))
            continue
        if value == "|":
            block = indent
            continue
        scalar = json.loads(value)
        if isinstance(scalar, (dict, list)) and scalar:
            raise ValueError("Reusable workflow has an unexpected flow mapping or list: " + name)
        if key == "uses":
            if scalar == "./product/.github/actions/setup-ci":
                local_uses.append(number)
            elif not isinstance(scalar, str) or not re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", scalar):
                raise ValueError("Reusable workflow action must use an immutable SHA or the scoped CLI setup hook: " + name)

    visible = "\n".join(structural) + "\n"
    if name == "governance.yml":
        review = re.findall(r'(?ms)^  "ai":\n(.*?)(?=^  "[^\"]+":|\Z)', visible)
        legacy = '    "environment": "legacy-review"'
        if len(review) != 1 or environments != [legacy] or legacy not in review[0].splitlines():
            raise ValueError("Only the review job must declare the legacy-review environment: " + name)
    elif environments:
        raise ValueError("Only the governance review job may declare an environment: " + name)

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


def workflows(root: Path, profile: str) -> None:
    directory = root / ".github/workflows"
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Missing or unsafe workflows directory")
    allowed = {"pr.yml", "release.yml"}
    native = profile in NATIVE_RELEASE and (directory / "build.yml").exists()
    if native:
        allowed.add("build.yml")
    publish = directory / "publish.yml"
    if profile == "ejm-ui" and publish.is_file() and not publish.is_symlink():
        if hashlib.sha256(publish.read_bytes()).hexdigest() != UI_PUBLISH_SHA256:
            raise ValueError("UI publish workflow differs from the reviewed revision")
        allowed.add("publish.yml")
    warm = directory / "cache.yml"
    if profile in WARM_CACHE and warm.is_file() and not warm.is_symlink():
        allowed.add("cache.yml")
    if profile == ".github":
        allowed.update(SHARED_WORKFLOWS)
    if any(file.name not in allowed for file in directory.iterdir()):
        raise ValueError("Unexpected workflow; use only the canonical consumers and shared reusables")
    pr = read(root, ".github/workflows/pr.yml")
    # Extract the candidate pin only. Exact document comparison below is the
    # validation, so comments, quoted keys, duplicate triggers and extra jobs fail.
    pin = re.search(r"^    uses: ejmlabs/\.github/\.github/workflows/governance\.yml@([0-9a-f]{40})$", pr, re.MULTILINE)
    if not pin:
        raise ValueError("PR workflow must pin governance.yml to a full commit SHA")
    model_key = re.search(r"^      (" + "|".join(MODEL_KEYS) + r"): \$\{\{ secrets\.\1 \}\}$", pr, re.MULTILINE)
    if not model_key:
        raise ValueError("PR workflow must forward exactly one supported model key")
    consumers = consumer_workflows(pin[1], model_key=model_key[1], native=native)
    if "cache.yml" in allowed:
        consumers["cache.yml"] = WARM_CACHE_CALLER.replace("STANDARDS_REVISION", pin[1])
    if native:
        native_build(read(root, ".github/workflows/build.yml"))
    if profile == ".github":
        fixture = missing_model_key_workflows(pin[1], model_key=model_key[1])
        if pr == fixture["pr.yml"]:
            consumers = fixture
    for name, expected in consumers.items():
        if read(root, ".github/workflows/" + name) != expected:
            raise ValueError("Workflow differs from the canonical consumer: " + name)
    if profile == ".github":
        for name in SHARED_WORKFLOWS:
            if (directory / name).exists() or (directory / name).is_symlink():
                _reusable_workflow(read(root, ".github/workflows/" + name), name, model_key=model_key[1])


def uniform_guidance(root: Path, profile: str, templates: dict[str, str]) -> None:
    for name, template in templates.items():
        expected = template.replace("{{repository}}", "ejmlabs/" + profile).replace("{{development_guide}}", COMMUNITY_GUIDES[profile])
        if read(root, name) != expected:
            raise ValueError("Community guidance differs from the pinned standard: " + name)


def standards(root: Path, profile: str, templates: dict[str, str] | None = None) -> None:
    version = versions(root, profile)
    if templates is None:
        directory = Path(__file__).resolve().parents[1] / "templates/community"
        templates = {file.name: file.read_text() for file in directory.glob("*.md")}
    if not templates:
        raise ValueError("Pinned community templates are required")
    uniform_guidance(root, profile, templates)
    for path in DOCS:
        text = read(root, path)
        if not text.strip() or "\u2014" in text:
            raise ValueError(f"Empty document or em dash: {path}")
        if not path.endswith(".md"):
            continue
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            target = link.strip("<>").split("#", 1)[0]
            if not target or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            resolved = (root / Path(path).parent / unquote(target)).resolve()
            if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                raise ValueError(f"Broken or outside-repository link in {path}: {target}")
    if profile != "ejmlabs" and "MIT License" not in read(root, "LICENSE"):
        raise ValueError("Product and standards source must retain the MIT license")
    readme = read(root, "README.md")
    for heading in HEADINGS:
        if not re.search(r"^## " + re.escape(heading) + r"$", readme, re.MULTILINE):
            raise ValueError(f"README.md lacks heading: {heading}")
    for path in (".github/CODEOWNERS", ".github/dependabot.yml", ".github/pull_request_template.md", ".github/ISSUE_TEMPLATE/config.yml"):
        read(root, path)
    workflows(root, profile)
    if profile in ("ejm-cli", "ejm-ide") and not re.fullmatch(r"[0-9a-f]{40}\n?", read(root, ".github/harness-revision")):
        raise ValueError("harness revision must be a full immutable commit")
    print(f"Repository standards and version {version} passed for {profile}")


if __name__ == "__main__":
    try:
        standards(Path(sys.argv[1]), sys.argv[2])
    except (ValueError, KeyError, OSError, tomllib.TOMLDecodeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
