## Why

The owner wants time to merge as low as possible. Measured on 2026-10-28, the harness gate took about 25 minutes: Windows waited 7 minutes for a matrix slot, and every Rust job spent 3 to 5 minutes compiling `cargo-deny` and `cargo-machete` and the rest compiling every dependency from scratch on two cores. CLI and IDE gates took 14 to 18 minutes for the same reasons. A PR also needed three separate maintainer visits: `/ready`, `/approve` after the checks, and the merge.

## What Changes

- Remove `max-parallel` from the Quality matrix.
- Set `CARGO_BUILD_JOBS=default` in the Quality and registry jobs, overriding the products' local two-job cap.
- Install `cargo-deny` and `cargo-machete` from digest-pinned prebuilt archives (`scripts/tools.py`) instead of `cargo install`.
- Add `warm-cache.yml`, the only cache writer, and an optional canonical `cache.yml` caller for Rust profiles. The gate restores only main's exact build for the admitted base.
- Enable auto-merge in `scripts/configure_repositories.py`.

## Capabilities

### New Capabilities

- `fast-gate`: the shared gate starts every platform at once, installs prebuilt audit tools and reuses main's trusted dependency builds.

## Impact

`scripts/build_workflows.py`, `scripts/tools.py`, `scripts/prepare.py`, `scripts/standards.py`, `scripts/configure_repositories.py`, the generated workflows, their tests, `docs/operations.md` and `CHANGELOG.md`. Consumers get the gate changes by moving their pin; Rust consumers adopt the cache by adding `cache.yml` after that.
