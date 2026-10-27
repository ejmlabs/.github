## 1. Gate

- [x] 1.1 Remove the `ejm-ui` size steps from `scripts/build_workflows.py`.
- [x] 1.2 Regenerate the shared workflows with `python3 scripts/build_workflows.py`.

## 2. Verification

- [x] 2.1 Update the synthetic owner-gate test to the shorter `ejm-ui` sequence.
- [x] 2.2 Unit tests, `python3 scripts/build_workflows.py --check` and the standards check pass.

## 3. Documentation

- [x] 3.1 Remove the size wording from `docs/operations.md`, note that load time is measured in each product repository, and add the CHANGELOG entry.

## 4. Reviewed package digest

- [x] 4.1 Refresh `UI_PACKING_SHA256['packages/ssg']` and its test fixture to the cap-free `@ejm/ssg` manifest at `ejm-ui` 06de1b0d9a8f954b7a1a0f0405a9bade1815bb6a; `ejm-ui` pins this revision in the same PR as its cap removal.
