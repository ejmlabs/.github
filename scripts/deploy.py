#!/usr/bin/env python3
"""Deploy a built site with the pinned Wrangler. Config and Worker source come from the reviewed commit, never from the build."""
import http.client
import json
import os
import posixpath
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

ACCOUNT_ID = "478a0db3a110d8503c16abbc1db27af4"
# Profile: (build commands run from the product root in the credential-free build job when the product has no
# executable .github/site-build, Wrangler config, paths the deploy needs). The path that contains the config is
# source: it is committed, so the deploy takes it from the reviewed commit and requires the build's copy to match
# byte for byte (the config file alone for most sites; ejm-ide's whole distribution directory, which holds its
# Worker). Every other path is build output. Sites that link ../ejm-ui get it at main's pinned revision and install
# its own dependencies first (npm --prefix ../ejm-ui ci), because the file: links resolve into its packages.
SITES = {
    "ejmlabs": ("npm --prefix ../ejm-ui ci --ignore-scripts\nnpm --prefix site ci --ignore-scripts\nnpm --prefix site run build\n",
                "site/wrangler.jsonc", ("site/wrangler.jsonc", "site/dist")),
    "ejm-cli": ("npm --prefix ../ejm-ui ci --ignore-scripts\nnpm --prefix site ci --ignore-scripts\nnpm --prefix site run build\n",
                "site/wrangler.jsonc", ("site/wrangler.jsonc", "site/dist")),
    "ejm-harness": ("npm --prefix ../ejm-ui ci --ignore-scripts\nnpm --prefix site ci --ignore-scripts\nnpm --prefix site run build\n",
                    "site/wrangler.jsonc", ("site/wrangler.jsonc", "site/dist")),
    "ejm-ide": ("npm --prefix ../ejm-ui ci --ignore-scripts\nnpm ci --ignore-scripts\nnpm run site:build\n",
                "distribution/wrangler.jsonc", ("distribution", "website/dist")),
    "ejm-ui": ("npm ci --ignore-scripts\nnpm run build -w @ejm/gallery\n", "apps/gallery/wrangler.jsonc", ("apps/gallery/wrangler.jsonc", "apps/gallery/dist")),
    "ejm-calm": ("npm ci --ignore-scripts\nnpm run build\n", "wrangler.jsonc", ("wrangler.jsonc", "dist")),
}
ENVIRONMENTS = ("staging", "production")
MAX_API_BYTES = 1_000_000
MAX_MEMBERS = 100_000
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_SOURCE_FILES = 1_000
MAX_SOURCE_BYTES = 16_000_000


def source_path(profile: str) -> str:
    """The declared path that holds this site's Wrangler config, the part the reviewed commit must supply."""
    _, config, paths = SITES[profile]
    return next(path for path in paths if config == path or config.startswith(path + "/"))


def scan(text: str) -> list[tuple[bool, str]]:
    """Split JSONC into string literals (True) and single other characters (False), dropping comments."""
    parts: list[tuple[bool, str]] = []
    size, index = len(text), 0
    while index < size:
        if text[index] == '"':
            end = index + 1
            while end < size and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            if end >= size:
                raise ValueError("Wrangler config has an unterminated string")
            parts.append((True, text[index:end + 1]))
            index = end + 1
        elif text.startswith("//", index):
            newline = text.find("\n", index)
            index = size if newline < 0 else newline
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise ValueError("Wrangler config has an unterminated comment")
            parts.append((False, " "))
            index = end + 2
        else:
            parts.append((False, text[index]))
            index += 1
    return parts


def site_config(text: str) -> dict[str, Any]:
    """Read the JSONC the sites use: // and /* */ comments and trailing commas, never inside strings."""
    parts = scan(text.removeprefix("﻿"))
    kept: list[str] = []
    for index, (is_string, chunk) in enumerate(parts):
        if chunk == "," and not is_string:
            ahead = index + 1
            while ahead < len(parts) and not parts[ahead][0] and parts[ahead][1].isspace():
                ahead += 1
            if ahead < len(parts) and not parts[ahead][0] and parts[ahead][1] in "}]":
                continue
        kept.append(chunk)
    value = json.loads("".join(kept))
    if not isinstance(value, dict):
        raise ValueError("Wrangler config must be an object")  # noqa: TRY004 - callers expect ValueError for every invalid config
    return value


def environments(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [env for env in (config.get("env") or {}).values() if isinstance(env, dict)]


def check(config: dict[str, Any], environment: str) -> list[str]:
    """Return the Wrangler arguments for this environment, refusing configs that could reach production by mistake."""
    if environment not in ENVIRONMENTS:
        raise ValueError("Unknown deploy environment: " + environment)
    # A build command would run product code beside the deploy token.
    if "build" in config or any("build" in env for env in environments(config)):
        raise ValueError("Site configs must not declare a Wrangler build command")
    if environment == "production":
        return []
    staging = (config.get("env") or {}).get("staging")
    # Without its own routes, `--env staging` inherits the production custom domain.
    if not isinstance(staging, dict) or not staging.get("routes") or staging.get("routes") == config.get("routes"):
        raise ValueError("Staging needs env.staging with its own routes")
    if staging.get("name") in (None, config.get("name")):
        raise ValueError("Staging needs its own Worker name")
    return ["--env", "staging"]


def inside(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent + "/")


def resolve(config_path: str, value: Any) -> str:  # noqa: ANN401 - a config value is untyped until checked here
    """Resolve a path from the config the way Wrangler does, relative to the config file; reject anything that leaves the tree."""
    if not isinstance(value, str) or not value or posixpath.isabs(value) or "\\" in value:
        raise ValueError("Wrangler config paths must be relative: " + str(value))
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(config_path), value))
    if resolved == ".." or resolved.startswith("../"):
        raise ValueError("Wrangler config path leaves the site tree: " + value)
    return resolved


def check_paths(config: dict[str, Any], config_path: str, source: str, paths: "Sequence[str]") -> None:
    """Keep every file Wrangler reads inside the declared paths: Worker code from source, assets from declared output."""
    if config.get("account_id") not in (None, ACCOUNT_ID):
        raise ValueError("Wrangler config names a different Cloudflare account")
    for scope in (config, *environments(config)):
        if "main" in scope:
            main = resolve(config_path, scope["main"])
            if not inside(main, source) or main == source:
                raise ValueError(f"Worker main {main} must be committed source inside {source}, the path the deploy takes from the reviewed commit; list its directory in SITES")
        assets = scope.get("assets")
        if isinstance(assets, dict) and "directory" in assets:
            directory = resolve(config_path, assets["directory"])
            if not any(inside(directory, path) for path in paths):
                raise ValueError(f"Asset directory {directory} must be one of this site's declared paths")


def checked_members(archive: tarfile.TarFile, paths: "Sequence[str]") -> list[tarfile.TarInfo]:
    """Return the members to extract: regular files and directories under the declared paths, within size limits."""
    members: list[tarfile.TarInfo] = []
    total = 0
    for member in archive:
        parts = PurePosixPath(member.name).parts
        if not (member.isfile() or member.isdir()) or not parts or parts[0] == "/" or ".." in parts:
            raise ValueError("Site archive may hold only regular files and directories with relative paths: " + member.name)
        if not any(inside("/".join(parts), path) for path in paths):
            raise ValueError("Site archive member is outside this site's declared paths: " + member.name)
        total += member.size if member.isfile() else 0
        if len(members) >= MAX_MEMBERS or total > MAX_ARCHIVE_BYTES:
            raise ValueError("Site archive exceeds its member or byte limit")
        members.append(member)
    return members


def read_source(root: Path, relative: str) -> dict[str, bytes]:
    """Read a source path (a file, or a directory of regular files) as bytes, refusing links and special files."""
    base = root / relative
    if base.is_symlink() or not base.exists():
        raise ValueError(f"Missing or unsafe source path {relative} under {root}")
    found: dict[str, bytes] = {}
    paths = [base] if base.is_file() else []
    for directory, folders, files in os.walk(base):
        for name in (*folders, *files):
            if (Path(directory) / name).is_symlink():
                raise ValueError("Source path must not contain links: " + relative)
        paths.extend(Path(directory) / name for name in files)
    if len(paths) > MAX_SOURCE_FILES:
        raise ValueError("Source path exceeds its file limit: " + relative)
    total = 0
    for path in paths:
        if not path.is_file():
            raise ValueError("Source path may hold only regular files: " + relative)
        total += path.stat().st_size
        if total > MAX_SOURCE_BYTES:
            raise ValueError("Source path exceeds its byte limit: " + relative)
        found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def require_reviewed(source: str, built: Path, reviewed: Path) -> None:
    """The build's copy of the source path must equal the committed one, so no build step can change what is deployed."""
    ours, theirs = read_source(built, source), read_source(reviewed, source)
    if ours != theirs:
        differing = sorted(name for name in ours.keys() | theirs.keys() if ours.get(name) != theirs.get(name))
        raise ValueError("The built site differs from the reviewed commit in: " + ", ".join(differing[:5]))


def github(path: str) -> Any:  # noqa: ANN401 - GitHub's JSON is untyped until checked by the caller
    url = "https://api.github.com/repos/" + os.environ["GITHUB_REPOSITORY"] + path
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json",
                                                   "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https API URL
        body = response.read(MAX_API_BYTES + 1)
    if len(body) > MAX_API_BYTES:
        raise ValueError("GitHub response exceeds its byte limit")
    return json.loads(body)


def required_reviewers(environment: dict[str, Any]) -> int:
    rules = environment.get("protection_rules") or []
    return sum(len(rule.get("reviewers") or []) for rule in rules if isinstance(rule, dict) and rule.get("type") == "required_reviewers")


def require_main_head() -> None:
    """A maintainer can approve an older run after main moved on. Deploying it would roll production back, and the newer commit has its own run."""
    ref = github("/git/ref/heads/main")
    target = ref.get("object") if isinstance(ref, dict) else None
    head = target.get("sha") if isinstance(target, dict) else None
    if not isinstance(head, str) or head != os.environ["GITHUB_SHA"]:
        raise ValueError("Main has moved past this commit, so this run would roll production back. Approve the newest production run instead")


def check_environment(environment: str) -> None:
    """GitHub creates a missing environment without rules, so require the rules this deploy relies on: only main may deploy, and a maintainer releases production."""
    if environment not in ENVIRONMENTS:
        raise ValueError("Unknown deploy environment: " + environment)
    found = github("/environments/" + environment)
    policy = found.get("deployment_branch_policy") if isinstance(found, dict) else None
    if not isinstance(policy, dict) or policy.get("protected_branches") is not False or policy.get("custom_branch_policies") is not True:
        raise ValueError(f"The {environment} environment must use a custom deployment branch policy")
    listing = github("/environments/" + environment + "/deployment-branch-policies?per_page=100")
    entries = listing.get("branch_policies") if isinstance(listing, dict) else None
    if (not isinstance(entries, list) or len(entries) != 1 or listing.get("total_count") != 1
            or not isinstance(entries[0], dict) or entries[0].get("name") != "main" or entries[0].get("type") != "branch"):
        raise ValueError(f"The {environment} environment must allow deployments from the main branch only")
    if environment == "production":
        if required_reviewers(found) < 1:
            raise ValueError("The production environment must require a maintainer's approval before any deploy")
        require_main_head()


def wrangler_environment() -> dict[str, str]:
    """Only what Wrangler needs. The repository token and every other runner variable stay out of its reach."""
    if not os.environ.get("CLOUDFLARE_API_TOKEN"):
        raise ValueError("CLOUDFLARE_API_TOKEN is empty: set it on the environment and pass secrets: inherit in deploy.yml")
    kept = {name: os.environ[name] for name in ("PATH", "HOME", "RUNNER_TEMP", "CLOUDFLARE_API_TOKEN", "CI") if name in os.environ}
    return {**kept, "CLOUDFLARE_ACCOUNT_ID": ACCOUNT_ID, "WRANGLER_SEND_METRICS": "false"}


def deploy(environment: str, profile: str) -> None:
    env = wrangler_environment()
    _, config_path, paths = SITES[profile]
    source = source_path(profile)
    built = Path("built")
    with tarfile.open("artifact/site.tar", "r:") as archive:
        members = checked_members(archive, paths)
        built.mkdir()
        archive.extractall(built, members=members, filter="data")
    require_reviewed(source, built, Path("reviewed"))
    reviewed_config = Path("reviewed", config_path)
    if reviewed_config.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Wrangler config exceeds its byte limit")
    config = site_config(reviewed_config.read_text(encoding="utf-8"))
    arguments = check(config, environment)
    check_paths(config, config_path, source, paths)
    wrangler = Path(os.environ["RUNNER_TEMP"], "deployer/node_modules/.bin/wrangler")
    subprocess.run([str(wrangler), "deploy", "--config", str(built / config_path), *arguments], check=True, env=env)


def main(argv: "Sequence[str]") -> None:
    if len(argv) != 2 or argv[0] not in ("protection", "deploy") or argv[1] not in ENVIRONMENTS:
        raise ValueError("Usage: deploy.py (protection|deploy) (staging|production)")
    profile = os.environ["PROFILE"]
    if profile not in SITES:
        raise ValueError("No site deploy for this repository")
    if argv[0] == "protection":
        check_environment(argv[1])
    else:
        deploy(argv[1], profile)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (ValueError, KeyError, OSError, tarfile.TarError, http.client.HTTPException, subprocess.CalledProcessError, urllib.error.URLError) as error:
        print(f"Deploy stopped: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
