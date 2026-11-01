## 1. Gate

- [x] 1.1 Remove `max-parallel` and set `CARGO_BUILD_JOBS=default` in `scripts/build_workflows.py`.
- [x] 1.2 Add `scripts/tools.py` and use it for `cargo-deny` and `cargo-machete` in Quality and the registry gate.
- [x] 1.3 Restore only the exact trusted cache, delete any other hit, and mark extracted sources newer than any restored build.

## 2. Cache writer

- [x] 2.1 Add `warm-cache.yml` with shared build steps and the `warm-pins` preparation step.
- [x] 2.2 Accept `warm-cache.yml` as a shared reusable and the canonical `cache.yml` caller for Rust profiles in `scripts/standards.py` and `scripts/configure_repositories.py`.

## 3. Settings

- [x] 3.1 Enable auto-merge in `scripts/configure_repositories.py`.

## 4. Verification

- [x] 4.1 Unit tests, `python3 scripts/build_workflows.py --check` and the standards check pass; each consumer's main passes the new standards with a moved pin.
- [x] 4.2 Admitted gate timings on each consumer after its pin moves, cold and with a warm cache. Moved to `velocity-and-safety-refactor` task 2.5.

## 5. Documentation

- [x] 5.1 Document the gate speed changes and the trusted cache in `docs/operations.md` and add the CHANGELOG entries.
