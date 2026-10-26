# Design

## Context

All numbers come from GitHub timelines, workflow run jobs and review records for 2026-10-25 (Pacific time). Two facts shape the design:

- The gate itself worked well once repaired. Changes with no problem took 6.5 to 16.9 minutes from `/ready` to merge, with a median last mile of 9 minutes.
- The cost is repeated work. 24 `/ready` comments were posted for 14 merged PRs, so 10 were repeats. 9 `/approve` comments, 5 recorded decision rounds and 2 manual label clears covered one day (the label is removed with automated review).

The trust model is fixed before any speed-up:

- The owner is the only actor who posts `/ready` and `/approve`, merges, or resolves a security concern. Each is an action by the owner's own account on GitHub.
- The operator has its own identity (a GitHub App, or a machine user with the Write role only). It can push branches and open or update PRs. Only the owner may merge to `main`, enforced by a push and merge restriction with no bypass actors. The gate already refuses commands from a bot sender and from a user without maintain rights, so the operator cannot approve anything even by mistake.
- Automated review is off. A pass from any automated reviewer is advice and is never an authorization.

## Goals / Non-Goals

Goals:

- Cut the median time from first `/ready` to merge from 78 minutes to about 12.
- Cut owner touches by making them one pass through a prepared list, with the evidence next to each item.
- Keep every hard line, and close the admin-merge path.

Non-Goals:

- No weaker review. Fewer waits, not fewer checks.
- No change to branch protection in this change. Admin enforcement stays on.
- No new merge method.
- No automation that holds the owner's credential or posts as the owner.

## Decisions

Each decision lists the choices. The recommended choice is first and marked.

### D1. How the owner approves

- A. One `/approve` per PR (today).
- B. A signed batch file that names PR URLs at exact head SHAs and an optional deploy. The owner reviews the list and then clicks through `/ready`, `/approve` and merge on GitHub, one item at a time. (recommended)
- C. B plus a standing class for named low-risk changes (patch dependency bumps, docs, copy).

B keeps the approval explicit and attributable. The file is signed with the owner's key, or committed in a PR the owner approves, so it is an authenticated owner action recorded in the repository, not a chat message. The file is a checklist: a script may verify it and show which items still match, but only the owner's GitHub actions ship anything. A PR whose head moves leaves the set. C removes the per-batch look at a class, so it needs a written scope from the owner and a deterministic class check. Revisit C after two weeks of B data.

### D2. Security concerns without a gate label

- A. The gate has no security label. A concern raised by a human reviewer is resolved only by a human on GitHub. (recommended)
- B. The operator or any automated reviewer clears a label or concern after a pass.
- C. Keep a label in the gate, advisory only.

B is an automated actor clearing an automated verdict, written down as procedure. It is rejected. C keeps label machinery and a label-removal trigger that the removal of automated review deletes. A matches the gate with automated review off. If a model review or label is ever re-enabled, which needs a recorded security review first, only a human clears a block, and another reviewer's pass is evidence the owner may read but never enough to clear it.

### D3. Stale pins

- A. Re-pin by hand in each repository (today).
- B. A job in the shared workflow repository opens one pin-only PR per consumer when its `main` moves, under the operator identity. Each PR goes through the normal gate, a fresh review and the owner's approval. (recommended)
- C. Follow `main` without pins.

C is rejected: every consumer would run unreviewed gate code. B keeps pins and removes the hand work. The review of a pin-only PR is short because the diff is three lines and byte-checkable against the generator output. Pin PRs change files under `.github/workflows/`, which the operator identity cannot push (it has no Workflows permission). The job therefore needs a separate, short-lived credential created by the owner for that purpose, or the owner pushes the branch. The choice is an owner action, listed in the tasks.

### D4. Head drift and serial merges

- A. Re-ask the owner each time `main` moves (today).
- B. Short-lived branches (one day), disjoint files in a batch, and a carry-over rule: if only `main` moved, the PR's own patch is identical (same patch id), and a fresh review passes on the new exact tree, the batch entry still covers the PR. (recommended)
- C. A merge queue.

The carry-over rule is safe because the fresh review still runs on the exact code shipped and the owner still approves on GitHub. C needs a repository settings change by the owner and gate support for the queue event, so it is a later step.

### D5. Deploys

- A. Manual after merge (today: 59 minutes on one site).
- B. Review the exact `main` tree before merge and record its tree hash. After merge, deploy only if the tree hash matches, within minutes. (recommended)
- C. Deploy from CI on every merge to `main`.

C needs a deploy credential in CI, which is a larger trust change. B needs no new credential. The deploy trigger is the owner's action, or a step the owner started by merging.

### D6. External writes

- A. The owner relays each push by hand (today).
- B. The operator holds its own identity with the minimum rights: push branches, open and update PRs. It never holds a credential that can approve, merge, change labels, change settings or read secrets. (recommended)
- C. The operator uses the owner's login.

C is rejected: a command posted by an agent holding the owner credential cannot be told from the owner's, which breaks "a human ships". B is built as a proposal and files only: the owner creates the identity and applies its permissions, never the build.

### D7. Gate self-repair without an admin merge

- A. Admin-merge changes to reviewer infrastructure (today: 10 of 21 merges). Rejected.
- B. Validator-first sequence: land the validator or generator change that accepts both the old and new forms, then land the consumer change, then remove the old form. Each step passes the gate normally. (recommended)
- C. A separate infrastructure ruleset for the gate's own files, with required approval from a second human who owns that ruleset, so the owner's own PRs to it are approved by someone else.

B needs no new person or setting and is tried first. C is the fallback when a repair cannot be ordered that way. Neither path involves an admin merge or an override, and admin enforcement stays on.

### D8. Lockfile and binary changes

- A. Skip review for a lockfile that mirrors its manifest and for allowed binaries (what the first draft did). Rejected: lockfiles and binaries are supply-chain vectors.
- B. A deterministic check: regenerate the lockfile from the manifest in a pinned environment and compare hashes; for binaries, an allowlist of path plus content hash kept in the repository. A change that passes still goes to review, with the check result attached; a change that fails blocks. (recommended)

## Picks

The owner picked on 2026-10-25: D1 B, D2 B, D3 B, D4 B, D5 B, D6 B in the first draft, when D2 B was the label clear inside the batch. This revision changes the content of D1, D2 and D6, so those picks are reopened and need to be confirmed against the text above. D7 and D8 are new. Until the owner confirms, nothing in the tasks starts.

| Decision | Recommendation | Task groups |
| --- | --- | --- |
| D1 | B, signed batch file the owner clicks through | 2 |
| D2 | A, no gate label, human resolves concerns | 4 |
| D3 | B, a job opens pin-only PRs when `main` moves | 5 |
| D4 | B, one-day branches, carry-over only for an identical patch | 6 |
| D5 | B, review before merge, deploy only on a tree-hash match | 7 |
| D6 | B, operator's own narrow identity (proposal only) | 8 |
| D7 | B, validator-first, with C as fallback | 9 |
| D8 | B, deterministic check, still reviewed | 5 |

## Risks / Trade-offs

- The owner still performs every approval and merge, so the gain is in preparation, not in removing the owner. The model below assumes the list is ready when the owner checks in.
- A pin job opens PRs without a human. It only writes three lines to a branch, it cannot approve or merge, and the PR still needs a review and the owner's approval.
- The signed batch file is only as strong as the owner's key. A lost key is revoked by the owner and the file is re-signed; no tool can act on an unsigned file.
- Validator-first sequencing takes more PRs than one admin merge did. That is the price of removing the bypass.
- The numbers after the change are a model. They assume four owner check-ins a day, as seen today, and a queue of seven, the peak seen at 12:58 Pacific.

## Migration Plan

1. The owner confirms or changes the pick for each decision.
2. Build the chosen items in small PRs, each through the normal gate with no admin merge.
3. Run one day in shadow: record stage times without changing the flow.
4. Switch on the batch list for one repository, then all.
5. Compare the next day's numbers with today's.

## Open Questions

- Does the owner want a standing class for low-risk changes (D1 C)? If so, what is the exact class and its deterministic check?
- Which check-in times does the owner prefer?
- Which signing method for the batch file: a key the owner holds, or a PR the owner approves?
- For D3, does the owner prefer to push workflow-file branches, or to create a short-lived credential for the pin job?
- For D7, who is the second human if the infrastructure ruleset is needed?
