## 1. Workflow

- [x] 1.1 Add `deploy_workflow` to `scripts/build_workflows.py`, `scripts/deploy.py` and the `deploy/` lockfile.
- [x] 1.2 Accept `deploy-site.yml` and the canonical `deploy.yml` caller in `scripts/standards.py` and `scripts/configure_repositories.py`.

## 2. Verification

- [x] 2.1 Unit tests for config parsing, staging and build-command refusal, the reviewer check and the workflow's credential boundaries.
- [x] 2.2 The pinned Wrangler dry-runs the current `ejmlabs` and `ejm-ide` configs.
- [ ] 2.3 First staging deploy and approved production deploy for each adopting site.

## 3. Documentation

- [x] 3.1 Document site deploys in `docs/operations.md` and add the CHANGELOG entry.
