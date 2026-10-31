## Context

The Quality job runs admitted PR code with no token permissions, but any job can use the runner's cache service. Caches written by an `issue_comment` run land in main's scope, where every later gate can read them. So the gate must never write, and must not trust any entry it did not expect.

## Decisions

- **One writer.** `warm-cache.yml` runs only on pushes to main, builds the reviewed main commit, and saves under `gate-<job>-<OS>-<main SHA>`. It uses the same environment and build steps as the gate (shared code in `build_steps`), the same checkout layout (`product`, `ejm-harness`, `ejm-ui`, with Git metadata removed), and the same cache paths, so the saved artifacts are the ones the gate reuses.
- **Exact restore only.** The gate restores the key for the admitted base with no `restore-keys`. GitHub also prefix-matches the primary key, so a non-exact hit is deleted before any build.
- **Rebuild local crates.** `git archive` stamps sources with the commit time, which can be older than a cached build. Extraction now sets every extracted file's mtime to the current time, so Cargo rebuilds every path crate and reuses only registry dependencies.
- **Prebuilt tools, pinned digests.** Each archive's SHA-256 is recorded and checked before extraction; the published `.sha256` files were checked when the digests were recorded. `worker-build` publishes no binaries and still compiles.
- **Every core.** No reason for the two-job cap was recorded. `CARGO_BUILD_JOBS=default` restores Cargo's default; reverting is one constant if a runner runs out of memory.
- **Auto-merge.** `/approve` already needs only current readiness, not finished checks, so one maintainer visit can admit, approve and arm auto-merge. Required statuses and strict up-to-date protection are unchanged.

## Risks

Admitted PR code could extract the job's cache token and write the key for a main commit before its warm job saves it; a later gate on that base would restore the planted build. Human admission of the exact head is the boundary. Cache entries can be large; GitHub evicts the oldest when a repository exceeds its cache limit, and a miss only costs a cold build.
