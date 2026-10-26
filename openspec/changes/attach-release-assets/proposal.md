## Why

The shared draft-release flow produces source archives only. The first public releases add native builds, which run project code, so their files must reach the draft release through a separate, reviewed path that holds the write token, runs no project code, and refuses anything not built from the commit being tagged.

## What Changes

- Add a shared reusable workflow `verify-build.yml` that checks, before the tag exists, that a named build workflow run succeeded on the exact main commit about to be tagged.
- Add a shared reusable workflow `attach-assets.yml` that, after Draft release, re-verifies the run and the tag, downloads only that run's artifacts, recomputes every digest, and attaches the files and an extended `SHA256SUMS` to the draft release, with optional build attestations.
- Generate both from `scripts/build_workflows.py` and allow them in the repository standards check. `draft-release.yml` and the consumer templates are unchanged, so existing consumers keep working.
- `RELEASING.md` is unchanged: it already requires platform builds, signing and notarization where relevant, and smoke tests, and forbids claiming artifacts before they are verified.

## Capabilities

### New Capabilities

- `release-attach`: how built release files are verified and attached to a draft release.

## Impact

`scripts/attach.py`, `scripts/build_workflows.py`, `scripts/standards.py`, `scripts/configure_repositories.py`, two generated workflows, tests and `docs/operations.md`. Product repositories adopt the workflows later through their own changes and pin updates.
