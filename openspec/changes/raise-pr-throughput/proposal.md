# Proposal

## Why

Shipping is slow because of waiting, not work. On 2026-10-25, 14 pull requests went through the review gate. Together they waited 28.2 hours. Only 0.6 hours (2%) was real machine work: review, admission and merge. The median time from the first `/ready` to merge was 78 minutes, and the slowest was 350 minutes. A change that met no problem took 6 to 17 minutes.

The measured causes, largest first:

1. Waiting for a gate fix, rollout or re-pin (9.3 hours). Four gate revisions landed in one day, and each one needed a new pin in five repositories.
2. A blocking security label that only the owner could clear (7.9 hours, mostly overnight; the label goes away with automated review).
3. Head drift (4.2 hours). Each merge moved `main`, so every other open change had to merge `main`, get a new review and a new `/ready`.
4. Waiting on the owner (4.0 hours) for pushes, `/approve` and override calls.
5. False gate results (2.2 hours). 15 gate runs ended with a failed review (28 failed passes: blocked, or incomplete on lockfile and binary changes).

Ten of the 21 merges that day were admin merges of reviewer infrastructure. They were needed only because the gate blocked its own repair. Deploys are slow too: one site deployed 59 minutes after its merge, while another deployed within a minute of merge because its review was finished first.

The hard lines are stricter than before, not looser:

- Every `/ready`, `/approve`, merge and security-concern resolution is a human action by the owner on GitHub. No tool, script or agent performs one, and none holds the owner's credential.
- There are no admin merges, including for reviewer infrastructure.
- Only a human resolves a security concern. A pass from any automated reviewer never does.
- Every change still needs a fresh review of the exact code shipped, the owner's explicit approval, and no force-push.

## What Changes

Each item is an option. The owner picks one per decision. Nothing is built before the pick.

- Batch approval: the owner publishes a signed batch file that names pull requests at exact head SHAs and a deploy. It is a list the owner clicks through on GitHub, not a grant of authority to anyone else. Optional: a standing class for named low-risk changes.
- Pin maintenance: when `main` moves in the shared workflow repository, a job opens one pin-only PR per consumer repository, as its own narrow identity.
- Review gate results: pins-only, lockfile and binary changes get deterministic checks (regenerate and compare hashes, or an allowlist with hashes) so they cannot block on a false result and cannot skip review. The gate has no security label, and a security concern is resolved only by a human.
- Gate self-repair: a defined path that needs no admin merge, either validator-first sequencing or a separate infrastructure ruleset owned by a second human.
- Head drift: short-lived branches, and a carry-over rule for the owner's approval when only `main` moved and the PR's own patch is identical and passes a fresh review.
- Deploy from `main`: the review covers the exact `main` tree before merge, and a deploy follows right after merge if the tree is unchanged.
- Scoped external writes: the operator acts only as its own App or machine identity with push and PR-open rights. It cannot comment commands, approve or merge, and only the owner may merge to `main`.
- Flow metrics: every stage timestamp is recorded, so the next measurement is a query and not an investigation.

## Context: automated review is off

The required checks are Human readiness, Maintainer approval, Quality and Repository standards, enforced for admins too. The automated review that previously set a security verdict is removed. This change assumes that state. Re-enabling any model review needs a security review first and does not change the rule that only a human clears a block.

## Capabilities

### New Capabilities

- `batch-approval`: A signed owner batch file names exact PRs and SHAs for the owner to click through.
- `pin-maintenance`: Pins to the shared workflows stay current without hand work.
- `review-gate-results`: Known false results do not block, nothing skips review, and the gate has no security label.
- `deploy-from-main`: A deploy follows a merge of reviewed code with no extra wait.
- `scoped-external-writes`: The operator holds push and PR-open rights under its own identity, and nothing else.
- `flow-metrics`: Stage times are recorded for every PR and deploy.

### Modified Capabilities

None. This repository has no existing capability specs.

## Impact

Workflow generator and consumer templates, the pin update job, the gate's deterministic lockfile and binary checks and tests, the operator identity and its permission settings, deploy runbooks, and `docs/operations.md`. Repository settings such as a merge queue or an infrastructure ruleset are not changed by this proposal; they are owner actions.
