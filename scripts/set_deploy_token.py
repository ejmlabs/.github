#!/usr/bin/env python3
"""Store one Cloudflare API token as CLOUDFLARE_API_TOKEN in every site repository's deploy environments.

Run it from a clone of ejmlabs/.github with gh signed in as an admin of the ejmlabs repositories:

    python3 scripts/set_deploy_token.py

It asks for the token once without echo, or reads one line from standard input when piped. It checks
the token with Cloudflare before it writes anything. For each repository that may deploy a site, it
creates or repairs the staging and production environments with the main-only branch policy that
configure_repositories.py applies, then hands the token to `gh secret set` on standard input. The
token never appears in arguments, the environment, or output. It warns when production has no
required reviewer, because production deploys then fail until a maintainer is added.
"""
import argparse
import getpass
import json
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

import configure_repositories as settings
import standards

from deploy import ACCOUNT_ID

SECRET = "CLOUDFLARE_API_TOKEN"  # noqa: S105 - the secret's name, not its value
CLOUDFLARE = "https://api.cloudflare.com/client/v4"
# Cloudflare verifies user tokens and account tokens at different paths; either one active is enough.
VERIFY_PATHS = ("/user/tokens/verify", f"/accounts/{ACCOUNT_ID}/tokens/verify")
MAX_TOKEN = 1000


def read_token(prompt: Callable[[str], str] = getpass.getpass) -> str:
    """One token: from a hidden prompt on a terminal, or the first line of piped standard input."""
    raw = prompt("Cloudflare API token: ") if sys.stdin.isatty() else sys.stdin.readline()
    token = raw.strip()
    if not token or len(token) > MAX_TOKEN or not token.isascii() or not token.isprintable() or any(c.isspace() for c in token):
        raise ValueError("the token must be one line of printable ASCII without spaces")
    return token


def cloudflare_accepts(token: str) -> bool:
    """True when Cloudflare reports the token as active at either verify endpoint."""
    for path in VERIFY_PATHS:
        request = urllib.request.Request(CLOUDFLARE + path, headers={"Authorization": f"Bearer {token}"})  # noqa: S310 - fixed https Cloudflare URL
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https Cloudflare URL
                body: Any = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError):
            continue
        if isinstance(body, dict) and body.get("success") is True and settings.dig(body, "result", "status") == "active":
            return True
    return False


def set_secret(name: str, environment: str, token: str) -> None:
    """Write the secret with gh, which encrypts it for the environment. The token goes only to gh's standard input."""
    args = ["gh", "secret", "set", SECRET, "--env", environment, "--repo", f"{settings.OWNER}/{name}"]
    try:
        result = subprocess.run(args, input=token, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"{name} {environment}: cannot run gh: {type(error).__name__}") from error
    if result.returncode:
        raise RuntimeError(f"{name} {environment}: gh secret set failed: {result.stderr.strip()}")


def store(name: str, environment: str, token: str) -> str:
    """Configure one environment, write the secret, and read back its update time (GitHub never returns the value)."""
    root = f"repos/{settings.OWNER}/{name}"
    state = settings.configure_environment(root, environment)
    if environment == "production" and state["required_reviewers"] < 1:
        print(f"warning: {name}: {settings.NO_RELEASER}", file=sys.stderr, flush=True)
    set_secret(name, environment, token)
    stored = settings.find(f"{root}/environments/{environment}/secrets/{SECRET}")
    if not isinstance(stored, dict) or stored.get("name") != SECRET:
        raise RuntimeError(f"{name} {environment}: the secret is not listed after it was set")
    return str(stored.get("updated_at", ""))


def apply(names: Sequence[str], token: str) -> list[str]:
    """Store the secret in every environment. Returns one failure line per environment that did not take it."""
    failures: list[str] = []
    for name in names:
        for environment in settings.ENVIRONMENTS:
            try:
                updated = store(name, environment, token)
            except (settings.ApiError, ValueError, RuntimeError) as error:
                failures.append(str(error))
                print(f"FAIL {name} {environment}: {error}", file=sys.stderr, flush=True)
                continue
            print(f"ok   {name} {environment}: {SECRET} updated {updated}", flush=True)
    return failures


def checked_token(names: Sequence[str], *, verify: bool) -> str:
    """Fail before the prompt if a repository is not visible, and before any write if Cloudflare rejects the token."""
    missing = [name for name in names if settings.find(f"repos/{settings.OWNER}/{name}") is None]
    if missing:
        raise ValueError("not found or not visible to gh: " + ", ".join(missing))
    token = read_token()
    if verify and not cloudflare_accepts(token):
        raise ValueError("Cloudflare did not accept the token as active; nothing was written")
    return token


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository", choices=standards.SITE_DEPLOY, action="append", help="Limit to these repositories (default: every site repository)")
    parser.add_argument("--dry-run", action="store_true", help="Print the repositories and environments, then stop without asking for the token")
    parser.add_argument("--skip-verify", action="store_true", help="Do not check the token with Cloudflare first")
    args = parser.parse_args(argv)
    names = list(dict.fromkeys(args.repository or standards.SITE_DEPLOY))
    for name in names:
        print(f"target {settings.OWNER}/{name}: {', '.join(settings.ENVIRONMENTS)}", flush=True)
    if args.dry_run:
        return
    try:
        failures = apply(names, checked_token(names, verify=not args.skip_verify))
    except (settings.ApiError, ValueError, RuntimeError) as error:
        raise SystemExit("error: " + str(error)) from error
    if failures:
        raise SystemExit(f"error: {len(failures)} environment(s) did not take the token; rerun after fixing them")
    print(f"done: {SECRET} is set in {len(names) * len(settings.ENVIRONMENTS)} environments", flush=True)


if __name__ == "__main__":
    main()
