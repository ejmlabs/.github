## 1. Rule

- [x] 1.1 Add the public set, exact `publishConfig` and packing-field digests, and the publish workflow hash to `scripts/standards.py`.
- [x] 1.2 Regenerate the shared workflows with `python3 scripts/build_workflows.py`.

## 2. Verification

- [x] 2.1 Tests cover the accepted public set, refused `"private": false`, other packages staying private, the packing-field deviations, and the publish workflow hash, location and symlink cases.
- [x] 2.2 Unit tests, `python3 scripts/build_workflows.py --check` and the standards check pass, including the current consumer trees.

## 3. Documentation

- [x] 3.1 CHANGELOG entry and the operations note.
