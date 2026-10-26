"""Governance path lists, one per kind of backstop repository.

The CODEOWNERS test reads these lists, and the standards ownership check for
each backstop repository is to read the list for that repository's kind.
Directory prefixes end with "/"; "*" means every path; everything else is an
exact root file.
"""

# The .github repository (this one).
GOVERNANCE = (
    ".github/", "scripts/", "review/", "templates/community/",
    "tests/", "openspec/", "docs/operations.md", "VERSION", "RELEASING.md", "CONTRIBUTING.md",
    "SECURITY.md", "SUPPORT.md", "CODE_OF_CONDUCT.md", "THIRD_PARTY_NOTICES.md",
    ".gitignore", ".gitattributes",
)

# Intentionally left to maintainers in .github through the "*" fallback: they
# carry no governance rule, and a change to them cannot alter how anything merges.
MAINTAINER_OWNED = ("LICENSE", "README.md", "CHANGELOG.md")

# Both runner repositories and the service repository carry runner or service
# source outside the .github prefixes. There every path is governance: "*" is
# owned by the security team alone and maintainers own nothing, so a
# maintainer-only code-owner approval can never satisfy the two-person deploy.
WHOLE_REPOSITORY = ("*",)

PROFILES = {
    "dot-github": (GOVERNANCE, MAINTAINER_OWNED),
    "runner": (WHOLE_REPOSITORY, ()),
    "service": (WHOLE_REPOSITORY, ()),
}


def is_governance(path, kind="dot-github"):
    entries, _ = PROFILES[kind]
    return any(
        entry == "*" or (path.startswith(entry) if entry.endswith("/") else path == entry)
        for entry in entries
    )
