## Why

The owner wants merges to reach staging automatically, with production one human approval away. Every ejmlabs site is deployed by hand today with `wrangler deploy` from a maintainer's machine, so time to deploy is however long it takes someone to remember and run it.

## What Changes

- Add the shared `deploy-site.yml`: a credential-free build of each push to main, an automatic staging deploy, and a production deploy of the same files gated by the `production` environment's required reviewer.
- Add `scripts/deploy.py` (site table, config checks, production reviewer check) and the pinned deployer lockfile in `deploy/`.
- Accept `deploy-site.yml` as a shared reusable whose staging and production jobs alone declare environments, and the canonical `deploy.yml` caller for site profiles.

## Capabilities

### New Capabilities

- `site-deploys`: continuous staging deploys and approved production deploys for the ejmlabs sites.

## Impact

`scripts/build_workflows.py`, `scripts/deploy.py`, `deploy/`, `scripts/standards.py`, `scripts/configure_repositories.py`, the generated workflows, tests, `docs/operations.md` and `CHANGELOG.md`. Each site adopts it after moving its pin by adding `env.staging` to its Wrangler config and `deploy.yml`, once its environments and token exist.
