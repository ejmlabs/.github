# Tasks

## 1. Implementation

- [x] 1.1 Add `ejm-agents` to `REPOS` in `scripts/governance.py` (`scripts/governance.py`)
- [x] 1.2 Add the `ejm-agents` site profile to `PROFILES` in `scripts/standards.py` (`scripts/standards.py`)
- [x] 1.3 Add the `ejm-agents` deploy recipe to `scripts/deploy.py` (`scripts/deploy.py`)
- [x] 1.4 Add `ejm-agents` to `SUPPORTED_NAMES` in `scripts/configure_repositories.py` (`scripts/configure_repositories.py`)
- [x] 1.5 Regenerate the shared workflows with `python3 scripts/build_workflows.py` (`.github/workflows/`)

## 2. Verification

- [x] 2.1 `python3 -m unittest discover -s tests` matches unmodified main exactly: the only failures are the 16 pre-existing local fixture errors in `test_prepare.py` (git fixture commits exit 77 in this container); the strict ruff and mypy tests pass
- [x] 2.2 `python3 scripts/build_workflows.py --check` is clean
- [x] 2.3 The new `standards.py` passes for the checkout of `ejmlabs/ejm-agents` at `96d1c57528e39d7f2f0782499a3865be4c98897a` (PR 1) and at `c2988c198b974da9d8744e521aee67bf812ecd87` (PR 2) with the canonical caller texts for the new revision in place of their `340178d4bf7d7c1fc8fbbe6ab5731ff2e54825a1` pins
- [x] 2.4 The deploy config checks in `scripts/deploy.py` accept the PR 1 `wrangler.jsonc` for both environments

## 3. Documentation

- [x] 3.1 `docs/operations.md` scope note, Quality table row and the site deploys list
- [x] 3.2 `CHANGELOG.md` entry under `[Unreleased]`

## 4. Re-declaration

- [x] 4.1 Re-declare the deploy source with the reviewed Access-authenticated post-deploy checks and the `ALLOWED_SERVICE_IDENTITIES` deploy-time derivation (`scripts/deploy.py`, `.github/workflows/deploy-site.yml`)
- [x] 4.2 Bump the canonical caller pins in this repository's own `pr.yml` and `release.yml` to this branch's head (`.github/workflows/pr.yml`, `.github/workflows/release.yml`)
- [x] 4.3 `python3 scripts/build_workflows.py --check` is clean and the unittest suite matches the unmodified-main baseline (the 16 pre-existing `test_prepare.py` fixture errors)
