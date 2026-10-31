# Proposal

## Why

The owner wants high velocity with safety and security, and no ceremony that buys no safety. A review of the gate, standards, release and deploy paths found real gaps and friction. The gate admitted by a status id and banned reruns, capped PR size, and could not admit a Dependabot PR without a draft toggle. Deploys trusted the Wrangler config in the build artifact. Community files were compared byte for byte, so any wording change forced a lock-step pin move, and each public UI package manifest change needed a new shared revision.

## What Changes

- Gate: act on the event's head SHA, own statuses by run URL instead of an admission id, allow reruns, stop authoritatively, admit a bot PR with one `gate:approve` label, and drop the size cap. **BREAKING**: fork PRs are not admitted; a maintainer pushes the reviewed change to a branch.
- Standards: require callers to equal the canonical text except the pin, allow any other workflow that passes a credential-free lint, require community files only to exist, and check public UI packages by structure. Every problem is reported at once.
- Prepare and cache: raw `git archive` bytes, a tested `scripts/extract.py`, Rust caches keyed by lockfile and only restored by the gate, and product-owned `.github/quality` and `.github/site-build` with the built-in commands as fallback.
- Release and deploy: draft from any commit on main with no tag until a human publishes it, attestation in its own least-privilege job, deploy only the reviewed Wrangler config, check environments fail closed, and pass the Cloudflare token through `secrets: inherit` in the canonical `deploy.yml`.
- Settings: a read-only `--check`, `staging` and `production` environments limited to `main`, and a fix for the missing-label bug.
- Action pins move to a root `action.yml` so Dependabot bumps them with the generated workflows.

## Capabilities

### New Capabilities

- `repository-standards`: what the Repository standards check requires of callers, other workflows, documents and UI packages.

### Modified Capabilities

- `pr-gate`: event-head binding, fork policy, one-label approve and admit, authoritative stop, ownership and reruns, no size cap, product-owned gate.
- `fast-gate`: cache keys, restore-only gate jobs, PR-scoped writes.
- `site-deploys`: reviewed config, environment checks, product-owned build, `secrets: inherit`.
- `release-attach`: drafts from any main commit, no tag before publication, attestation in its own job.
- `ui-publish`: structural rules replace per-package digests.
- `no-size-caps`: admission size cap removed.

## Impact

`scripts/` (governance, standards, prepare, extract, release, deploy, configure_repositories, build_workflows), the generated workflows, root `action.yml`, `.github/dependabot.yml`, `docs/operations.md`, README, CHANGELOG, the PR template and OpenSpec. Shared agent skills, the lint layer and the sync tools change in a separate PR.

This PR does not change `pr.yml`, `release.yml`, `templates/community/` or the root community files, because its own Repository standards check runs the pin it already has (`8230ef8`). Consumers adopt the revision in one PR each, checked by the new pin.
