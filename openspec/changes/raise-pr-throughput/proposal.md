# Proposal

## Why

Shipping is slow because of waiting, not work. On 2026-10-25, 14 pull requests went through the review gate. Together they waited 28.2 hours. Only 0.6 hours (2%) was real machine work: AI review, admission and merge. The median time from the first `/ready` to merge was 78 minutes, and the slowest was 350 minutes. A change that met no problem took 6 to 17 minutes.

The measured causes, largest first:

1. Waiting for a gate fix, rollout or re-pin (9.3 hours). Four gate revisions landed in one day, and each one needed a new pin in five repositories.
2. A blocking security label that only a maintainer could clear (7.9 hours, mostly overnight).
3. Head drift (4.2 hours). Each merge moved `main`, so every other open change had to merge `main`, get a new security pass and a new `/ready`.
4. Waiting on the maintainer (4.0 hours) for pushes, `/approve` and override calls.
5. False gate results (2.2 hours). 15 gate runs ended with a failed AI review (28 failed review passes: blocked, or incomplete on lockfile and binary changes).

Ten of the 21 merges that day were admin merges of reviewer infrastructure. They were needed only because the gate blocked its own repair. Deploys are slow too: one site deployed 59 minutes after its merge, while another deployed within a minute of merge because its review was finished first.

The hard lines stay as they are. Every change still needs a fresh independent security PASS on the exact code shipped, the maintainer's explicit approval, no force-push, and admin merges only for reviewer infrastructure.

## What Changes

Each item below is an option. The maintainer picks one per decision. Nothing is built before the pick.

- Batch approval: one explicit maintainer OK names a set of PRs at exact head SHAs, and a deploy from `main`. Optional: a standing OK for a named low-risk class.
- Pin maintenance: when `main` moves in the shared workflow repository, a job opens one pin-only PR per consumer repository.
- Review gate results: the security label becomes a maintainer check cleared inside the batch OK. Pins-only, lockfile and binary changes get fixtures so they cannot block again.
- Head drift: short-lived branches, and a carry-over rule for the OK when only `main` moved and the PR's own patch is identical and passes a fresh review.
- Deploy from `main`: the review runs on the exact `main` tree before merge, and a deploy follows right after merge if the tree is unchanged.
- Scoped external writes: a narrow permission rule lets the operator push, comment, merge and deploy only what an approved batch names.
- Flow metrics: every stage timestamp is recorded, so the next measurement is a query and not an investigation.

## Capabilities

### New Capabilities

- `batch-approval`: One explicit maintainer OK covers a named set of PRs at exact SHAs.
- `pin-maintenance`: Pins to the shared workflows stay current without hand work.
- `review-gate-results`: The gate never blocks on known false results, and the security label has one clear path.
- `deploy-from-main`: A deploy follows a merge of reviewed code with no extra wait.
- `scoped-external-writes`: External writes are allowed only for items an approved batch names.
- `flow-metrics`: Stage times are recorded for every PR and deploy.

### Modified Capabilities

None. This repository has no existing capability specs.

## Impact

Workflow generator and consumer templates, the pin update job, the gate's label handling and tests, operator permission settings, deploy runbooks, and `docs/operations.md`. Repository settings such as a merge queue are not changed by this proposal.
