## Why

GitHub limits each workflow file to 500 KB and each `run` step to 21,000 characters. Several generated steps exceed the latter limit, and larger reliability workflows would exceed the former.

## What changes

- Encode trusted embedded scripts compactly and split large payloads into bounded step-local values.
- Reject missing or invalid split payload chunks and generated workflows that exceed conservative size budgets.
- Preserve the existing trust boundaries, script arguments, outputs and pinned actions.

## Impact

The workflow generator, generated reusable workflows, behavioral tests, and operational guidance change. Consumers adopt the fix through separately reviewed full-SHA pin updates.
