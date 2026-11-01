# Design

## Context

All numbers come from GitHub timelines, workflow run jobs and review records for 2026-10-25 (Pacific time). Times are in the report that accompanies this change. Two facts shape the design:

- The gate itself worked well once repaired. Changes with no problem took 6.5 to 16.9 minutes from `/ready` to merge, with a median last mile of 9 minutes.
- The cost is repeated work. 24 `/ready` comments were posted for 14 merged PRs, so 10 were repeats. 9 `/approve` comments, 5 recorded decision rounds and 2 manual label clears covered one day.

## Goals / Non-Goals

Goals:

- Cut the median time from first `/ready` to merge from 78 minutes to about 12.
- Cut maintainer touches from about 38 per day (24 `/ready`, 9 `/approve`, 5 decision rounds) to one OK per batch.
- Keep every hard line.

Non-Goals:

- No weaker review. Fewer waits, not fewer checks.
- No change to the review rules, to admin-merge scope, or to branch protection in this change.
- No new merge method.

## Decisions

Each decision lists the choices. The recommended choice is first and marked.

### D1. How the maintainer approves

- A. One `/approve` per PR (today).
- B. One OK for a named set of PRs at exact head SHAs, plus a deploy from `main` when green. (recommended)
- C. B plus a standing OK for a named low-risk class (patch dependency bumps, docs, copy).

B keeps the approval explicit: the OK lists SHAs, and a PR whose head moves leaves the set. C removes the per-batch look at that class, so it needs a written scope from the maintainer. Revisit C after two weeks of B data.

### D2. The security label

- A. The maintainer clears the label by hand each time (today).
- B. The operator clears it as a maintainer check inside the batch OK, only when a fresh security PASS names the same head. (recommended)
- C. Make the label advisory in the gate.

C changes reviewer infrastructure and removes a second opinion. A costs hours when the maintainer is away. B uses the current rule with no new code.

### D3. Stale pins

- A. Re-pin by hand in each repository (today: five repositories, each with a branch, a review and an override).
- B. A job in the shared workflow repository opens one pin-only PR per consumer when its `main` moves. Each PR goes through the normal gate and the batch OK. (recommended)
- C. Follow `main` without pins.

C is rejected: every consumer would run unreviewed gate code. B keeps pins and removes the hand work. The security review of a pin-only PR is short because the diff is three lines and byte-checkable against the generator output.

### D4. Head drift and serial merges

- A. Re-ask the maintainer each time `main` moves (today).
- B. Short-lived branches (one day), disjoint files in a batch, and a carry-over rule: if only `main` moved, the PR's own patch is identical (same patch id), and a fresh security review passes on the new exact tree, the batch OK still covers the PR. (recommended)
- C. A merge queue.

The carry-over rule is safe because the fresh review still runs on the exact code shipped. Today's second merge of `main` into one dependency PR had the same patch id as the reviewed head. C needs a repository settings change by the maintainer and gate support for the queue event, so it is a later step.

### D5. Deploys

- A. Manual after merge (today: 59 minutes on one site).
- B. Review the exact `main` tree before merge and record its tree hash. After merge, deploy only if the tree hash matches, within minutes. (recommended)
- C. Deploy from CI on every merge to `main`.

C needs a deploy credential in CI, which is a larger trust change. B needs no new credential.

### D6. External writes

- A. The operator relays each push, comment, merge and deploy by hand (today).
- B. A scoped permission rule that allows only: pushing an exact SHA named in the approved batch; `/ready` and `/approve` comments on named PRs and SHAs; squash-merging named PRs; deploying a named SHA. (recommended)
- C. A separate bot account with the same scope.

The cost of today's permission checks could not be measured from the records. The first task logs every blocked or prompted external write for one day, so the next review has a number.

## Picks

The maintainer picked on 2026-10-25: D1 B, D2 B, D3 B, D4 B, D5 B, D6 B. D1 C (standing OK for a low-risk class) is not picked, so task group 3 is skipped. D6 B is built as a proposal and files only: the permission rule is applied by the maintainer, never by the build.

| Decision | Pick | Task groups |
| --- | --- | --- |
| D1 | B, batch OK for named PRs at exact heads plus a deploy | 2 |
| D2 | B, label cleared only inside that OK after a fresh check | 4 |
| D3 | B, a job opens pin-only PRs when `main` moves | 5 |
| D4 | B, one-day branches, carry-over only for an identical patch | 6 |
| D5 | B, review before merge, deploy only on a tree-hash match | 7 |
| D6 | B, a narrow permission rule tied to the approval (proposal only) | 8 |

## Risks / Trade-offs

- A batch OK is a larger grant than a single `/approve`. The SHA list, the carry-over test and the guard that checks the list before each write limit it.
- A pin job opens PRs without a human. It only writes three lines, to a branch, and the PR still needs a security PASS and the maintainer's OK.
- The numbers after the change are a model. They assume four maintainer check-ins a day, as seen today, and a queue of seven, the peak seen at 12:58 Pacific.

## Migration Plan

1. The maintainer picks a choice for each decision.
2. Build the chosen items in small PRs, each through the normal gate.
3. Run one day in shadow: record stage times without changing the flow.
4. Switch on batch approval for one repository, then all.
5. Compare the next day's numbers with today's.

## Open Questions

- Does the maintainer want a standing OK for a low-risk class (D1 C)? If so, what is the exact class?
- Which check-in times does the maintainer prefer for batch OKs?
