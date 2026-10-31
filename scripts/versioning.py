#!/usr/bin/env python3
"""SemVer 2.0.0 validation, shared by the standards check, the release draft and the build attach."""
import re

SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")


def semver(value: str) -> bool:
    """True for a valid SemVer string with no `v` prefix. Numeric prerelease identifiers carry no leading zero."""
    match = SEMVER.fullmatch(value)
    if not match:
        return False
    return not match[4] or all(not item.isdigit() or item == "0" or not item.startswith("0") for item in match[4].split("."))
