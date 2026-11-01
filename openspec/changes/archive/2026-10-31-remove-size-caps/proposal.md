## Why

The owner decided that download size and dependency count are not quality bars: where an established, actively maintained package does the job it is used, however large. Load time is the only performance bar. The shared gate still runs the `ejm-ui` size steps (`node scripts/size.mjs`, `npm run size -w @ejm/demos`) and the docs require bundle-size checks, so a product repository that drops its size scripts would fail the required Quality check.

## What Changes

- Remove `node scripts/size.mjs` and `npm run size -w @ejm/demos` from the `ejm-ui` profile of the required Quality gate.
- Remove "bundle-size" from the checks the `ejm-ui` owner commands must cover, and from the documented command list.
- State that no shared gate, standard or review criterion caps bundle bytes or dependency counts, and that load time is measured in each product repository.
- Keep every runtime and review-tooling safety bound (admission budgets, review-context byte limits, PR size bounds, standards file-read and manifest-count limits) and every security rule.
- Regenerate the shared workflows.

## Capabilities

### New Capabilities

- `no-size-caps`: the shared gate and standards do not cap download size or dependency count.

## Impact

`scripts/build_workflows.py`, the generated `governance.yml`, `tests/test_workflows.py`, `docs/operations.md` and `CHANGELOG.md`. `ejm-ui` may delete its size scripts once it pins the revision that carries this change.
