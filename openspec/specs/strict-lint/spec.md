# strict-lint Specification

## Purpose

The strict type-checking and lint settings this repository holds, how CI enforces them, and how suppressions are allowed.

## Requirements

### Requirement: Python is strictly typed and linted

Python under `scripts/` and `tests/` SHALL pass `mypy --strict` and ruff with the shared `ruff.strict.toml`, run from the locked development group in `pyproject.toml`.

#### Scenario: An unannotated function

- **WHEN** a change adds a Python function without annotations
- **THEN** the check fails

### Requirement: CI enforces the strict settings

The existing unit-test command SHALL run both tools and SHALL fail on any finding or when `uv` is unavailable, without a change to the shared gate's commands.

#### Scenario: A violation reaches a pull request

- **WHEN** a pull request introduces any finding from these tools
- **THEN** the repository's required check fails

### Requirement: Escape hatches are line-scoped and reasoned

Every suppression SHALL name one rule and carry a reason. The repository SHALL contain no file-wide or unlimited disable and no strict flag or lint rule turned off.

#### Scenario: Undescribed suppression

- **WHEN** a change adds a suppression without a rule name and a reason
- **THEN** the repository's check fails
