## ADDED Requirements

### Requirement: The standards repository holds the shared strict layer
The standards repository SHALL hold the shared strict lint layer in `templates/lint/`: an ESLint flat config built from typescript-eslint `strictTypeChecked` and `stylisticTypeChecked`, a ruff configuration selecting all rules except a documented list, a ShellCheck configuration enabling all optional checks except SC2250, and the Rust lint tables. Adding or changing these files SHALL NOT change any generated shared workflow.

#### Scenario: Workflows unchanged by the templates
- **WHEN** only files under `templates/lint/` change
- **THEN** `python3 scripts/build_workflows.py --check` passes without regeneration

### Requirement: Repositories copy the layer and detect drift
`scripts/sync_lint.py` SHALL copy named templates into a repository checkout and, with `--check`, SHALL fail when a copied file differs, when a target is a symlink, or when a Cargo manifest's lint tables are looser than the template or miss one of its entries.

#### Scenario: Drifted copy
- **WHEN** a repository's `eslint.strict.mjs` differs from the template
- **THEN** `sync_lint.py --check` fails and names the file

#### Scenario: Stricter Rust level
- **WHEN** a manifest sets `unsafe_code = "forbid"` where the template sets `deny`
- **THEN** the check passes
