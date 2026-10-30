## 1. Workflow

- [x] 1.1 Add `deploy_workflow` to `scripts/build_workflows.py`, `scripts/deploy.py` and the `deploy/` lockfile.
- [x] 1.2 Accept `deploy-site.yml` and the canonical `deploy.yml` caller in `scripts/standards.py` and `scripts/configure_repositories.py`.
- [x] 1.3 Pass the environment token: the canonical caller adds `secrets: inherit`, the previous form is accepted for one generation, and `scripts/deploy.py` refuses an empty token.
- [ ] 1.4 Re-pin each site to this revision, then switch its `deploy.yml` to the inheriting form.

## 2. Verification

- [x] 2.1 Unit tests for config parsing, staging and build-command refusal, the reviewer check and the workflow's credential boundaries.
- [x] 2.2 The pinned Wrangler dry-runs the current `ejmlabs` and `ejm-ide` configs.
- [ ] 2.3 First staging deploy and approved production deploy for each adopting site.

## 3. Documentation

- [x] 3.1 Document site deploys in `docs/operations.md` and add the CHANGELOG entry.
