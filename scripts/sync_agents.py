#!/usr/bin/env python3
"""Copy the shared agent skills and house rules into a repository checkout, or report drift from them."""
import argparse
import re
import shutil
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "templates/agents"
SKILLS = TEMPLATES / "skills"
CORE = ("ejmlabs-engineering", "ejmlabs-security", "ejmlabs-testing", "ejmlabs-workflow", "ejmlabs-writing")
BLOCK = re.compile(r"<!-- ejmlabs:house-rules:start -->\n.*?<!-- ejmlabs:house-rules:end -->\n", re.DOTALL)


def refuse_symlink(path: Path) -> None:
    if path.is_symlink():
        raise SystemExit("Refusing to use a symlink: " + str(path))


def contents(directory: Path) -> dict[str, bytes] | None:
    """Map each file under a directory to its bytes, or None when it holds a symlink."""
    paths = sorted(directory.rglob("*"))
    if any(path.is_symlink() for path in paths):
        return None
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in paths if path.is_file()}


def sync_skills(root: Path, names: list[str], *, check: bool) -> list[str]:
    """Copy or compare the core skills, the named ones and every shared skill already installed."""
    skills = root / ".agents/skills"
    refuse_symlink(skills.parent)
    refuse_symlink(skills)
    known = {path.name for path in SKILLS.iterdir() if path.is_dir()}
    installed = {path.name for path in skills.glob("ejmlabs-*")} if skills.is_dir() else set()
    errors = []
    for name in sorted({*CORE, *names, *installed}):
        target = skills / name
        refuse_symlink(target)
        if name not in known:
            errors.append(f"{target}: not a shared skill; remove it or add it to ejmlabs/.github")
        elif check:
            if not target.is_dir() or contents(target) != contents(SKILLS / name):
                errors.append(f"{target}: differs from the shared skill")
        else:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(SKILLS / name, target)
    return errors


def sync_house_rules(agents: Path, *, check: bool) -> list[str]:
    """Replace the marked house rules block in AGENTS.md, or compare it."""
    refuse_symlink(agents)
    text = agents.read_text() if agents.is_file() else ""
    block = (TEMPLATES / "house-rules.md").read_text()
    found = BLOCK.findall(text)
    if len(found) != 1:
        return [f"{agents}: add one block between the ejmlabs:house-rules start and end markers"]
    if found[0] == block:
        return []
    if check:
        return [f"{agents}: house rules differ from the shared block"]
    agents.write_text(BLOCK.sub(lambda _: block, text))  # a function keeps backslashes in the block literal
    return []


def sync_links(root: Path, *, check: bool) -> list[str]:
    """Give every skill a Claude Code discovery link and AGENTS.md routing; drop dangling links."""
    claude = root / ".claude/skills"
    refuse_symlink(claude.parent)
    refuse_symlink(claude)
    routing = (root / "AGENTS.md").read_text() if (root / "AGENTS.md").is_file() else ""
    errors = []
    for skill in sorted((root / ".agents/skills").glob("*/SKILL.md")):
        name = skill.parent.name
        if f".agents/skills/{name}/SKILL.md" not in routing:
            errors.append(f"{root / 'AGENTS.md'}: route .agents/skills/{name}/SKILL.md")
        link, expected = claude / name, Path("../../.agents/skills") / name
        if link.is_symlink() and link.readlink() == expected:
            continue
        if check or link.exists() or link.is_symlink():
            errors.append(f"{link}: must be a symlink to {expected}")
            continue
        claude.mkdir(parents=True, exist_ok=True)
        link.symlink_to(expected, target_is_directory=True)
    for link in sorted(claude.iterdir()) if claude.is_dir() else []:
        if link.is_symlink() and not link.exists():
            if check:
                errors.append(f"{link}: dangling skill link")
            else:
                link.unlink()
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("names", nargs="*", help="stack skills to add, such as ejmlabs-rust; core and installed skills always sync")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    refuse_symlink(args.root)
    if args.check and args.names:
        raise SystemExit("--check takes no skill names; it checks the installed set")
    errors = sync_skills(args.root, args.names, check=args.check)
    errors += sync_house_rules(args.root / "AGENTS.md", check=args.check)
    errors += sync_links(args.root, check=args.check)
    if errors:
        raise SystemExit("\n".join(errors))


if __name__ == "__main__":
    main()
