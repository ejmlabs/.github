## Why

The owner asked for strict type checking and strict linting in every ejmlabs repository where they apply, with one shared configuration where it fits and CI enforcing it. Today each repository chose its own settings: two repositories already run typed ESLint and clippy pedantic, others run plain `strict` TypeScript or no linter at all, and this repository's own Python has no linter or type checker. This change makes `.github` the home of the shared layer. The repository's own Python adopts it in the companion change `adopt-strict-lint` on the same branch.

## What Changes

- Add `templates/lint/` with the shared strict layer: `eslint.strict.mjs` (typescript-eslint `strictTypeChecked` and `stylisticTypeChecked`, unused or undescribed disable directives refused), `ruff.strict.toml` (all rules except a short reasoned list), `.shellcheckrc` (all optional checks except variable braces), and `cargo-lints.toml` (clippy `all` and `pedantic` denied plus the restriction lints the Rust repositories already use).
- Add `scripts/sync_lint.py` to copy those files into a repository checkout and, with `--check`, to report drift, including the Rust lint tables in a `Cargo.toml`.
- TypeScript needs no template: repositories extend the published `@tsconfig/strictest` package.

## Capabilities

### New Capabilities

- `strict-lint-baseline`: the shared strict layer and how repositories copy it and check for drift.

## Impact

New `templates/lint/`, `scripts/sync_lint.py`, `tests/test_sync_lint.py`, a section in `docs/operations.md` and a CHANGELOG line. No script embedded in the shared workflows changes, so `build_workflows.py --check` passes without regeneration and no pin moves. Consumers adopt the layer in their own `adopt-strict-lint` changes.
