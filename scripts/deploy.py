#!/usr/bin/env python3
"""Deploy a built site with the pinned Wrangler; nothing from the product runs here."""
import json
import os
import re
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

ACCOUNT_ID = "478a0db3a110d8503c16abbc1db27af4"
# Profile: (build commands run from the product root in the credential-free build job,
# Wrangler config, paths the deploy needs). Sites that link ../ejm-ui get it at main's pinned revision.
SITES = {
    "ejmlabs": ("npm --prefix ../ejm-ui ci --ignore-scripts\nnpm --prefix site ci --ignore-scripts\nnpm --prefix site run build\n",
                "site/wrangler.jsonc", ("site/wrangler.jsonc", "site/dist")),
    "ejm-cli": ("npm --prefix ../ejm-ui ci --ignore-scripts\nnpm --prefix site ci --ignore-scripts\nnpm --prefix site run build\n",
                "site/wrangler.jsonc", ("site/wrangler.jsonc", "site/dist")),
    "ejm-harness": ("", "site/wrangler.jsonc", ("site/wrangler.jsonc", "site/public")),
    "ejm-ide": ("npm ci --ignore-scripts\nnpm run site:build\n", "distribution/wrangler.jsonc", ("distribution", "website/dist")),
    "ejm-ui": ("npm ci --ignore-scripts\nnpm run build -w @ejm/gallery\n", "apps/gallery/wrangler.jsonc", ("apps/gallery/wrangler.jsonc", "apps/gallery/dist")),
    "ejm-calm": ("npm ci --ignore-scripts\nnpm run build\n", "wrangler.jsonc", ("wrangler.jsonc", "dist")),
}
ENVIRONMENTS = ("staging", "production")


def site_config(text: str) -> dict[str, Any]:
    """Read the JSONC the sites use: whole-line comments and trailing commas."""
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("//")]
    value = json.loads(re.sub(r",(\s*[}\]])", r"\1", "\n".join(lines)))
    if not isinstance(value, dict):
        raise ValueError("Wrangler config must be an object")  # noqa: TRY004 - callers expect ValueError for every invalid config
    return value


def check(config: dict[str, Any], environment: str) -> list[str]:
    """Return the Wrangler arguments for this environment, refusing configs that could reach production by mistake."""
    if environment not in ENVIRONMENTS:
        raise ValueError("Unknown deploy environment: " + environment)
    # A build command would run product code beside the deploy token.
    if "build" in config or any("build" in env for env in config.get("env", {}).values() if isinstance(env, dict)):
        raise ValueError("Site configs must not declare a Wrangler build command")
    if environment == "production":
        return []
    staging = config.get("env", {}).get("staging")
    # Without its own routes, `--env staging` inherits the production custom domain.
    if not isinstance(staging, dict) or not staging.get("routes") or staging.get("routes") == config.get("routes"):
        raise ValueError("Staging needs env.staging with its own routes")
    if staging.get("name") in (None, config.get("name")):
        raise ValueError("Staging needs its own Worker name")
    return ["--env", "staging"]


def required_reviewers(environment: dict[str, Any]) -> int:
    rules = environment.get("protection_rules") or []
    return sum(len(rule.get("reviewers") or []) for rule in rules if isinstance(rule, dict) and rule.get("type") == "required_reviewers")


def require_approval() -> None:
    """GitHub creates a missing environment without rules, so production must prove a human reviewer gates it."""
    url = "https://api.github.com/repos/" + os.environ["GITHUB_REPOSITORY"] + "/environments/production"
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json",
                                                   "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https API URL
        environment = json.loads(response.read(1_000_000))
    if not isinstance(environment, dict) or required_reviewers(environment) < 1:
        raise ValueError("The production environment must require a human reviewer before any deploy")


def main() -> None:
    environment, profile = sys.argv[1], os.environ["PROFILE"]
    if profile not in SITES:
        raise ValueError("No site deploy for this repository")
    if environment == "production":
        require_approval()
    with tarfile.open("artifact/site.tar") as archive:
        archive.extractall("site", filter="data")
    path = Path("site", SITES[profile][1])
    arguments = check(site_config(path.read_text()), environment)
    wrangler = Path(os.environ["RUNNER_TEMP"], "deployer/node_modules/.bin/wrangler")
    subprocess.run([str(wrangler), "deploy", "--config", str(path), *arguments], check=True,
                   env={**os.environ, "CLOUDFLARE_ACCOUNT_ID": ACCOUNT_ID, "WRANGLER_SEND_METRICS": "false"})


if __name__ == "__main__":
    main()
