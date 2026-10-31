#!/usr/bin/env python3
"""Copy the shared agent skills and house rules into a repository checkout, or report drift from them."""
import argparse
import re
import shutil
import tempfile
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "templates/agents"
SKILLS = TEMPLATES / "skills"
FIRST = "ejmlabs-workflow"
CORE = ("ejmlabs-engineering", "ejmlabs-security", "ejmlabs-testing", "ejmlabs-workflow", "ejmlabs-writing")
RULES = re.compile(r"<!-- ejmlabs:house-rules:start -->\n.*?<!-- ejmlabs:house-rules:end -->(?:\n|\Z)", re.DOTALL)
ROUTING = re.compile(r"<!-- ejmlabs:skills:start -->\n.*?<!-- ejmlabs:skills:end -->(?:\n|\Z)", re.DOTALL)
SKILLS_HEADING = "## Skills\n\nLoad the skill whose trigger matches the work before you start it. Load more than one only\nwhen the work crosses them.\n\n"


def symlinks(*paths: Path) -> list[str]:
    """Name each path that is a symlink; this tool never reads or writes through one."""
    return [f"Refusing to use a symlink: {path}" for path in paths if path.is_symlink()]


def contents(directory: Path) -> dict[str, bytes] | None:
    """Map each file under a directory to its bytes, or None when it holds a symlink."""
    paths = sorted(directory.rglob("*"))
    if any(path.is_symlink() for path in paths):
        return None
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in paths if path.is_file()}


def remove(path: Path) -> None:
    """Delete a directory or file; a symlink inside is removed, never followed."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def replace_directory(source: Path, target: Path) -> None:
    """Swap a copy of source in for target. The old copy stays until the new one is complete."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{target.name}.new-", dir=target.parent))
    old = staged.with_name(staged.name.replace(".new-", ".old-"))
    try:
        shutil.copytree(source, staged, dirs_exist_ok=True)
        if target.exists():
            target.rename(old)
        staged.rename(target)
    except BaseException:
        remove(staged)
        if old.exists() and not target.exists():
            old.rename(target)
        raise
    remove(old)


def selection(root: Path, names: list[str]) -> list[str]:
    """The shared skills a run manages: the core ones, the named ones and every one already installed."""
    skills = root / ".agents/skills"
    installed = {path.name for path in skills.glob("ejmlabs-*")} if skills.is_dir() else set()
    return sorted({*CORE, *names, *installed})


def installed_skills(root: Path, selected: list[str]) -> list[str]:
    """Every skill directory the checkout will hold: those on disk, shared or its own, and the selected ones."""
    return sorted({*(path.parent.name for path in (root / ".agents/skills").glob("*/SKILL.md")), *selected})


def trigger(name: str) -> str:
    """The first sentence of a shared skill's description, which says when to load it."""
    header = (SKILLS / name / "SKILL.md").read_text().removeprefix("---\n").partition("\n---\n")[0]
    for line in header.splitlines():
        if line.startswith("description: "):
            return re.split(r"(?<=\.)\s", line.removeprefix("description: "), maxsplit=1)[0]
    raise SystemExit(f"{name}: the shared SKILL.md has no description")


def routing(selected: list[str]) -> str:
    """The routing block: one line per shared skill, built from the frontmatter of the shared copies."""
    known = {path.name for path in SKILLS.iterdir() if path.is_dir()}
    shared = sorted((name for name in selected if name in known), key=lambda name: (name != FIRST, name))
    lines = "".join(f"- [{name}](.agents/skills/{name}/SKILL.md): {trigger(name)}\n" for name in shared)
    return f"<!-- ejmlabs:skills:start -->\n\n{lines}\n<!-- ejmlabs:skills:end -->\n"


def put(text: str, found: re.Match[str], block: str) -> str:
    """Put a block where a match was, keeping a file that ends at the end marker without a final newline."""
    new = block if found.group().endswith("\n") else block.rstrip("\n")
    return text[: found.start()] + new + text[found.end() :]


def update_agents(text: str, selected: list[str]) -> tuple[str, list[str], list[str]]:
    """Return AGENTS.md text with both marked blocks current, what stops a sync, and what changed."""
    rules = list(RULES.finditer(text))
    if len(rules) != 1:
        return text, ["add one block between the ejmlabs:house-rules start and end markers"], []
    starts, ends = text.count("<!-- ejmlabs:skills:start -->"), text.count("<!-- ejmlabs:skills:end -->")
    if starts != ends or starts > 1 or len(ROUTING.findall(text)) != starts:
        return text, ["keep at most one block between the ejmlabs:skills start and end markers, start first"], []
    changes = []
    block = (TEMPLATES / "house-rules.md").read_text()
    if rules[0].group().rstrip("\n") != block.rstrip("\n"):
        changes.append("house rules differ from the shared block")
        text = put(text, rules[0], block)
    block = routing(selected)
    found = ROUTING.search(text)
    if found is None:
        changes.append("skills routing block is missing")
        after = RULES.search(text)
        end = after.end() if after else len(text)
        head = text[:end] if text[:end].endswith("\n") else text[:end] + "\n"
        return head + "\n" + SKILLS_HEADING + block + text[end:], [], changes
    if found.group().rstrip("\n") != block.rstrip("\n"):
        changes.append("skills routing differs from the shared skills")
        text = put(text, found, block)
    return text, [], changes


def link_problems(root: Path, skills: list[str]) -> list[str]:
    """List symlink refusals and links that exist but point elsewhere; a sync does not repair these."""
    claude = root / ".claude/skills"
    problems = symlinks(claude.parent, claude)
    for name in skills:
        link, expected = claude / name, Path("../../.agents/skills") / name
        if (link.exists() or link.is_symlink()) and not (link.is_symlink() and link.readlink() == expected):
            problems.append(f"{link}: must be a symlink to {expected}")
    return problems


def link_drift(root: Path, skills: list[str]) -> list[str]:
    """List missing links and links whose skill is gone; a sync creates and removes these."""
    claude = root / ".claude/skills"
    drift = [f"{claude / name}: must be a symlink to {Path('../../.agents/skills') / name}" for name in skills if not (claude / name).exists() and not (claude / name).is_symlink()]
    drift += [f"{link}: dangling skill link" for link in sorted(claude.iterdir()) if link.is_symlink() and not link.exists()] if claude.is_dir() else []
    return drift


def run(root: Path, names: list[str], *, check: bool) -> list[str]:
    """Sync or check a checkout. Nothing is written when anything that a sync cannot fix is wrong."""
    selected = selection(root, names)
    skills = root / ".agents/skills"
    agents = root / "AGENTS.md"
    known = {path.name for path in SKILLS.iterdir() if path.is_dir()}
    problems = symlinks(skills.parent, skills, agents, *(skills / name for name in selected))
    problems += [f"{skills / name}: not a shared skill; remove it or add it to ejmlabs/.github" for name in selected if name not in known]
    text = agents.read_text() if agents.is_file() and not agents.is_symlink() else ""
    planned, blocked, changes = update_agents(text, selected)
    problems += [f"{agents}: {message}" for message in blocked]
    present = installed_skills(root, selected)
    problems += link_problems(root, present)
    stale = [name for name in selected if name in known and (not (skills / name).is_dir() or contents(skills / name) != contents(SKILLS / name))]
    drift = [f"{skills / name}: differs from the shared skill" for name in stale]
    drift += [f"{agents}: {message}" for message in changes] + link_drift(root, present)
    unrouted = [f"{agents}: route .agents/skills/{name}/SKILL.md" for name in present if f".agents/skills/{name}/SKILL.md" not in planned]
    if check:
        return problems + drift + unrouted
    if problems:
        return problems
    for name in stale:
        replace_directory(SKILLS / name, skills / name)
    if planned != text:
        agents.write_text(planned)
    claude = root / ".claude/skills"
    for name in present:
        link = claude / name
        if not link.exists() and not link.is_symlink():
            claude.mkdir(parents=True, exist_ok=True)
            link.symlink_to(Path("../../.agents/skills") / name, target_is_directory=True)
    for link in sorted(claude.iterdir()) if claude.is_dir() else []:
        if link.is_symlink() and not link.exists():
            link.unlink()
    return unrouted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("names", nargs="*", help="stack skills to add, such as ejmlabs-rust; core and installed skills always sync")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.root.is_symlink():
        raise SystemExit("Refusing to use a symlink: " + str(args.root))
    if args.check and args.names:
        raise SystemExit("--check takes no skill names; it checks the installed set")
    errors = run(args.root, args.names, check=args.check)
    if errors:
        raise SystemExit("\n".join(errors))


if __name__ == "__main__":
    main()
