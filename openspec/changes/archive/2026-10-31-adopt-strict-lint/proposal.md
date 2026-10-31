## Why

The owner asked for strict type checking and strict linting in every ejmlabs repository where they apply, from one shared layer, enforced by CI. The scripts behind the shared gate are untyped and unlinted: `mypy --strict` reports 949 errors in 17 of 18 files and ruff with the shared layer reports 709.

## What Changes

- Add a root `pyproject.toml` (no package; development group `ruff==0.17.0`, `mypy==2.4.0`) with `uv.lock`, a `ruff.toml` that extends `templates/lint/ruff.strict.toml`, and `[tool.mypy]` with `strict`, `warn_unreachable` and Python 3.12.
- Annotate and fix `scripts/*.py` and `tests/*.py` until both tools pass.
- Add `tests/test_strict.py`, which runs both tools through `uv run --locked --group dev`, so the gate's existing unit-test step enforces them.
- Regenerate the shared workflows that embed the scripts.

## Capabilities

### New Capabilities

- `strict-lint`: the strict type-checking and lint settings this repository holds, how CI enforces them, and how suppressions are allowed.

## Impact

`scripts/*.py`, `tests/*.py`, new `pyproject.toml`, `uv.lock`, `ruff.toml`, `tests/test_strict.py`, regenerated `.github/workflows/*.yml`, CHANGELOG. Behaviour is unchanged and no pin moves.
