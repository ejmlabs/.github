# Proposal

## Why

The agents site repository (`ejm-agents`) is blocked at the shared gate: `governance / admission` fails with "Repository has not adopted the ejmlabs policy" on both open PRs, because the adopted-repository list `REPOS` in `scripts/governance.py` and the `PROFILES` map in `scripts/standards.py` do not name it. Its GitHub environments (`staging`, `production`, each limited to `main`) and the deploy credential are already in place, and the owner wants the setup PR to merge once the checks are green. The enrollment follows the `ejm-calm` precedent (commit `7b605ee`), which went through exactly these files.

## What Changes

- Add `ejm-agents` to `REPOS` in `scripts/governance.py`, so the shared gate admits `ejmlabs/ejm-agents` instead of raising "Repository has not adopted the ejmlabs policy".
- Add an `ejm-agents` site profile to `PROFILES`: MIT license, `package.json` and its lock at `VERSION`, contributor guide `README.md#development`, owns its Quality gate in `.github/quality`, deploys through the canonical `deploy.yml` caller.
- Add the `ejm-agents` deploy recipe to `scripts/deploy.py`: build with `npm ci --ignore-scripts` then `npm run build`, config `wrangler.jsonc`, paths `wrangler.jsonc` and `dist` (identical to `ejm-calm`).
- Add `ejm-agents` to `SUPPORTED_NAMES` in `scripts/configure_repositories.py`, so repository settings reach it with `--repository ejm-agents`.
- Update `docs/operations.md` (settings scope note, the Quality table row, the site deploys list), `CHANGELOG.md` and the tests that enumerate profiles and names.
- Regenerate the shared workflows that embed the changed scripts (`governance.yml`, `draft-release.yml`, `attach-assets.yml`, `verify-build.yml`, `deploy-site.yml`).

No capability requirement changes: the enrollment is a data row for the repository that the existing `repository-standards`, `pr-gate` and `site-deploys` rules already govern, so this change adds no spec deltas.

## Impact

`scripts/governance.py`, `scripts/standards.py`, `scripts/deploy.py`, `scripts/configure_repositories.py`, the regenerated workflows, `tests/repo_tree.py`, `tests/test_standards.py`, `tests/test_configure.py`, `docs/operations.md`, `CHANGELOG.md` and OpenSpec. The consumer adoption is outside this repository: the `ejm-agents` PRs re-pin their callers to the merged commit (in bias to `pr.yml`, `release.yml` and the canonical `deploy.yml` that replaces the local deploy copy).

This PR does not verify anything on GitHub: consumers adopt the revision through their own re-pin PRs, checked by the new pin.
