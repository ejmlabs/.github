## 1. Shared layer

- [x] 1.1 Add `templates/lint/eslint.strict.mjs`, `ruff.strict.toml`, `.shellcheckrc`, `cargo-lints.toml` and `README.md` (drafts in `data/strict-lint/templates/lint/`).
- [x] 1.2 Add `scripts/sync_lint.py <target> <name>... [--check]`; refuse symlinked targets; for `cargo-lints:<Cargo.toml>` compare the `[workspace.lints]` or `[lints]` tables with `tomllib` (a repository level may be stricter: `forbid` over `deny`).
- [x] 1.3 `tests/test_sync_lint.py`: copy, unchanged check, drift, symlink refusal, stricter and looser Rust levels.

## 2. Verification and documentation

- [x] 2.1 Unit tests, `build_workflows.py --check`, and the standards check of this tree at the current pin pass.
- [x] 2.2 `docs/operations.md` section "Strict lint layer" and a CHANGELOG line.
