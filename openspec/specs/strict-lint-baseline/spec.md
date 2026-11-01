# strict-lint-baseline Specification

## Purpose

The shared strict lint layer, and how repositories copy it and check for drift.

## Requirements

### Requirement: The standards repository holds the shared strict layer

The standards repository SHALL hold the shared strict lint layer in `templates/lint/`: ESLint, ruff, ShellCheck and Rust lint configuration. Changing these files SHALL NOT change any generated shared workflow.

#### Scenario: Workflows unchanged by the templates

- **WHEN** only files under `templates/lint/` change
- **THEN** `python3 scripts/build_workflows.py --check` passes without regeneration

### Requirement: Repositories copy the layer and detect drift

`scripts/sync_lint.py` SHALL copy named templates into a repository checkout and, with `--check`, SHALL fail when a copied file differs, when a target is a symlink, or when a Cargo manifest's lint tables are looser than the template or miss one of its entries.

#### Scenario: Drifted copy

- **WHEN** a repository's copy differs from the template
- **THEN** `sync_lint.py --check` fails and names the file

#### Scenario: Stricter Rust level

- **WHEN** a manifest sets a stricter level than the template for a lint
- **THEN** the check passes
