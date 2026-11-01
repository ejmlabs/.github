# Tasks

Nothing here starts until the maintainer picks a choice for each decision in `design.md`. Tasks are grouped by decision. Skip the groups for choices not picked.

## 1. Measure first (all choices)

- [ ] 1.1 Record `/ready`, review result, security PASS, `/approve`, merge and deploy times for every PR and deploy in one place.
- [ ] 1.2 Log every external write that was blocked or prompted, with its wait, for one day.
- [ ] 1.3 Publish a daily table with median and 90th percentile time from first `/ready` to merge.

## 2. Batch approval (D1 B)

- [ ] 2.1 Define the batch file: PR URLs, exact head SHAs, security PASS report ids, and the deploy target.
- [ ] 2.2 Make the operator post `/ready` and `/approve` only for entries whose head and PASS still match.
- [ ] 2.3 Drop any PR from the set when its head moves, and say so in the report.
- [ ] 2.4 Test: a moved head, a missing PASS and a PR not in the file are each refused.

## 3. Low-risk class (D1 C, only if picked)

- [ ] 3.1 Write the class in `docs/operations.md` in the maintainer's words.
- [ ] 3.2 Test that a PR outside the class never takes this path.

## 4. Security label (D2 B)

- [ ] 4.1 Document the label as a maintainer check cleared only inside a batch OK.
- [ ] 4.2 Record who cleared it, when, and the PASS id.

## 5. Pin maintenance (D3 B)

- [ ] 5.1 Add a job that opens a pin-only PR per consumer when the shared workflow repository's `main` moves.
- [ ] 5.2 Check that the PR diff equals the generator output for the new SHA, and nothing else.
- [ ] 5.3 Keep the retained `workflow-pins/<sha>` ref for each new pin.
- [ ] 5.4 Add gate fixtures for a pins-only change, a lockfile change and a binary asset.

## 6. Head drift (D4 B)

- [ ] 6.1 Write the one-day branch rule and the disjoint-files rule for a batch.
- [ ] 6.2 Add a script that compares patch ids before and after a merge of `main`.
- [ ] 6.3 Start a fresh security review automatically on the new exact tree.
- [ ] 6.4 Test that a changed patch drops the PR from the batch.

## 7. Deploy from main (D5 B)

- [ ] 7.1 Record the tree hash that the pre-merge security review covered.
- [ ] 7.2 After merge, compare the `main` tree hash with the record and deploy only on a match.
- [ ] 7.3 Record the deployed version and the previous one, for rollback.

## 8. Scoped external writes (D6 B)

- [ ] 8.1 Write the permission rule for the four allowed writes.
- [ ] 8.2 Make the pre-push guard read the approved batch file before it allows a push.
- [ ] 8.3 Test that a push of any other SHA, branch or repository is refused.

## 9. Close out

- [ ] 9.1 Run one day in shadow, then switch on for one repository, then all.
- [ ] 9.2 Compare the new daily table with 2026-10-25 and report it.
- [ ] 9.3 Archive this change after the work merges.
