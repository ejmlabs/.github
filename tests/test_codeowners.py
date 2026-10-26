import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from governance_paths import GOVERNANCE, MAINTAINER_OWNED, PROFILES, is_governance

SECURITY = "@ejmlabs/security"
MAINTAINERS = "@ejmlabs/maintainers"
SKIP_DIRS = {".git", "__pycache__"}


def parse(text):
    parsed = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pattern, *owners = line.split()
            parsed.append((pattern, owners))
    return parsed


def matches(pattern, path):
    # Only the forms this file uses: "*", "/dir/" and "/exact-file".
    if pattern == "*":
        return True
    if not pattern.startswith("/") or any(c in pattern for c in "*?["):
        raise ValueError(f"unsupported CODEOWNERS pattern: {pattern}")
    pattern = pattern[1:]
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return path == pattern


def owners_of(rules, path):
    found = None
    for pattern, owners in rules:
        if matches(pattern, path):
            found = owners
    return found


def repository_files():
    # Tracked plus untracked-but-not-ignored files, so stray ignored files
    # (bytecode, editor files) do not trip the test; new files still count.
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, check=True,
        ).stdout.decode()
    except (OSError, subprocess.CalledProcessError):
        out = None
    if out is not None:
        for path in sorted(set(filter(None, out.split("\0")))):
            if (ROOT / path).is_file():
                yield path
        return
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name in SKIP_DIRS:
                continue
            yield Path(directory, name).relative_to(ROOT).as_posix()


def violations(rules, paths, kind="dot-github"):
    return [path for path in paths if is_governance(path, kind) and owners_of(rules, path) != [SECURITY]]


class CodeOwnersTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github" / "CODEOWNERS").read_text()
        self.rules = parse(self.text)
        self.files = sorted(repository_files())

    def test_every_governance_file_is_owned_by_security_only(self):
        self.assertTrue(any(is_governance(path) for path in self.files))
        self.assertEqual(violations(self.rules, self.files), [])

    def test_each_governance_entry_has_a_security_only_rule(self):
        for entry in GOVERNANCE:
            with self.subTest(entry=entry):
                self.assertIn(("/" + entry, [SECURITY]), self.rules)

    def test_an_overriding_rule_on_any_governance_file_is_detected(self):
        rules = parse(self.text + "\n/scripts/configure_repositories.py @ejmlabs/maintainers\n")
        self.assertEqual(violations(rules, self.files), ["scripts/configure_repositories.py"])

    def test_other_paths_fall_back_to_maintainers(self):
        self.assertEqual(self.rules[0], ("*", [MAINTAINERS]))
        outside = sorted(path for path in self.files if not is_governance(path))
        self.assertEqual(outside, sorted(MAINTAINER_OWNED))
        for path in outside:
            with self.subTest(path=path):
                self.assertEqual(owners_of(self.rules, path), [MAINTAINERS])

    def test_runner_and_service_repositories_leave_nothing_to_maintainers(self):
        for kind in ("runner", "service"):
            with self.subTest(kind=kind):
                entries, maintainer_owned = PROFILES[kind]
                self.assertEqual(maintainer_owned, ())
                self.assertTrue(all(is_governance(path, kind) for path in self.files))
                # This repository's CODEOWNERS would leave LICENSE, README.md and
                # CHANGELOG.md to maintainers, so it is not valid there.
                self.assertEqual(violations(self.rules, self.files, kind), sorted(MAINTAINER_OWNED))
                # The intended form for those repositories passes.
                self.assertEqual(violations(parse("* @ejmlabs/security\n"), self.files, kind), [])

    def test_only_supported_patterns_and_team_owners(self):
        for pattern, owners in self.rules:
            matches(pattern, "x")
            for owner in owners:
                self.assertIn(owner, (SECURITY, MAINTAINERS))


if __name__ == "__main__":
    unittest.main()
