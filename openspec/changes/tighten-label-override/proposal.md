# Proposal

## Why

Callers trigger on `pull_request_target` `unlabeled` (added in #40) through the same `governance` job that handles `issue_comment`. Three things are wrong with that shape:

- The job runs for the removal of **any** label, not only `Possible security concern`. The shared `relabel` step discards the others, but only after a runner has started.
- The job passes `XAI_API_KEY` and `EJM_HARNESS_TOKEN` on the `pull_request_target` event. Today the shared `override` job reads neither, but `secrets:` is set per calling job, so nothing but the shared file's current content keeps them out.
- The job condition tests `github.event.issue.*`, which a `pull_request_target` payload does not contain. On that path `!contains(github.event.issue.labels.*.name, ...)` is always true, so a repository staged for a missing model key would send an unlabeled event to the keyed job.

The reviewer raised the second and third points on #40 (a "Possible security concern"). An independent review found them harmless today. The next PR that edits a caller or the shared gate meets the same flag, and the docs promise an override path "with no secrets" that the caller does not enforce.

This change builds on the earlier `secretless-override-caller` draft. It keeps its two-job split and adds what that draft left out: a label test, a transitional standards check that removes the rollout gap, and the event-field change.

## What Changes

- Split the canonical `pr.yml` into `governance` (and, in this repository only, `missing_model_key`), both `issue_comment` only, and a new `override` job that runs only for `pull_request_target` when `github.event.label.name` is `Possible security concern`. The `override` job has no `secrets:` block and the permissions `governance.yml` needs (its jobs cannot exceed the calling job's grant), but no secrets.
- Test the label name in two places: the caller `if:` and the `override` job `if:` in `governance.yml`; make `relabel` compare the removed label exactly.
- Read `github.event.pull_request.number` and `head.sha` from the payload; read labels live.
- Teach **Repository standards** to accept the new caller, and for one pin generation also the #40 caller, so no repository is stuck between rollout steps.
- Update `docs/operations.md`.

Every consumer needs the rollout again. That cost is the point of the design file.

## Capabilities

### New Capabilities

- `label-override`: The label-override path runs only for the removal of the reviewer's security label, holds no secret, checks out no PR code, and reads its own event payload.

## Impact

- `scripts/standards.py`, `scripts/build_workflows.py`, `scripts/governance.py`, `scripts/configure_repositories.py`, `.github/workflows/{pr,governance}.yml`, `docs/operations.md`, tests.
- All six callers (`.github`, `ejm-ui`, `ejm-cli`, `ejm-ide`, `ejm-harness`, `ejmlabs`) change in the rollout. No change to required checks, admission, budgets or secrets.
