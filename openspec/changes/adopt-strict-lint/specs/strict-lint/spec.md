## ADDED Requirements

### Requirement: Python is strictly typed and linted
Python under `scripts/` and `tests/` SHALL pass `mypy --strict` (2.4.0) and ruff (0.17.0) with the shared `ruff.strict.toml`, run from a locked development group.

#### Scenario: An unannotated function
- **WHEN** a change adds a Python function without annotations
- **THEN** the check fails

### Requirement: CI enforces the strict settings
The existing unit-test command SHALL run both tools and SHALL fail on any finding or when `uv` is unavailable, without a change to the shared gate's commands.

#### Scenario: A violation reaches a pull request
- **WHEN** a pull request introduces any finding from these tools
- **THEN** the repository's required check fails

### Requirement: Escape hatches are line-scoped and reasoned
The repository SHALL contain no explicit `any`, no `@ts-ignore`, `@ts-expect-error` or `@ts-nocheck`, no unlimited or file-wide lint disable, and no strict compiler flag or lint rule turned off. Every remaining suppression SHALL name one rule and carry a reason.

#### Scenario: Undescribed suppression
- **WHEN** a change adds `// eslint-disable-next-line` without a rule name and a ` -- reason`, or a Rust `#[allow]` without a reason
- **THEN** the repository's check fails
