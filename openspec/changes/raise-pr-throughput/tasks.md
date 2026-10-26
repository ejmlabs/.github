# Tasks

Starts after remove-ai-review tasks 3.2 and 5.1 are done. Nothing here starts until the owner confirms a choice for each decision in `design.md`. Tasks are grouped by decision. Skip the groups for choices not picked. No task adds a step that posts a command, approves, merges, or resolves a security concern as anyone but the owner.

## 1. Measure first (all choices)

- [x] 1.1 Record `/ready`, review result, `/approve`, merge and deploy times for every PR and deploy in one place. (Script and table only: the operator assembles `records.json` from the PR timelines.)
- [ ] 1.2 Log every external write that was blocked or prompted, with its wait, for one day.
- [x] 1.3 Publish a daily table with median and 90th percentile time from first `/ready` to merge.

## 2. Batch list (D1 B)

- [ ] 2.1 Define the batch file: PR URLs, exact head SHAs, review ids, tree hashes and the deploy target.
- [ ] 2.2 Define the owner's SSH signature over the canonical bytes (the only proof built), and record the signer and time in the repository.
- [ ] 2.3 Write a read-only script that verifies the signature and shows, per entry, whether the head and review still match. It posts nothing.
- [ ] 2.4 Drop any PR from the list when its head moves, and say so in the report.
- [ ] 2.5 Test: an unsigned file, a bad signature, a moved head, a missing review and a PR not in the file are each refused.

## 3. Low-risk class (D1 C, only if picked)

- [ ] 3.1 Write the class in `docs/operations.md` in the owner's words, with the deterministic check that tests membership.
- [ ] 3.2 Test that a PR outside the class never takes this path.

## 4. Security concerns (D2 A)

- [ ] 4.1 Document in `docs/operations.md` that the gate has no security label, that a human reviewer's concern is resolved only by a human, and that no other reviewer's result is enough.
- [ ] 4.2 Check that no caller or workflow carries a label trigger, a label override or a model key.
- [ ] 4.3 Only if a model review or label is ever re-enabled, after a recorded security review: test that a bot sender or a user without maintain rights cannot clear it, and record who cleared it from the GitHub event.

## 5. Pin maintenance and deterministic checks (D3 B, D8 B)

- [ ] 5.1 Add a job that opens a pin-only PR per consumer when the shared workflow repository's `main` moves, under the operator identity.
- [ ] 5.2 Check that the PR diff equals the generator output for the new SHA, and nothing else.
- [ ] 5.3 Keep the retained `workflow-pins/<sha>` ref for each new pin.
- [ ] 5.4 Settle how the job pushes workflow files without giving the operator identity the Workflows permission, as an owner choice.
- [ ] 5.5 Add a lockfile check: regenerate from the manifest in a pinned environment and compare hashes. Fixtures: matching, mismatching and an extra dependency.
- [ ] 5.6 Add a binary allowlist of path plus content hash. Fixtures: listed, listed with changed content, and unlisted.
- [ ] 5.7 Add gate fixtures so a pins-only change, a passing lockfile and a listed binary are not blocked as false results, and still reach review.

## 6. Head drift (D4 B)

- [ ] 6.1 Write the one-day branch rule and the disjoint-files rule for a batch.
- [ ] 6.2 Add a script that compares patch ids before and after a merge of `main`.
- [ ] 6.3 Require a fresh review on the new exact tree before the entry is offered again.
- [ ] 6.4 Test that a changed patch drops the PR from the list.

## 7. Deploy from main (D5 B)

- [ ] 7.1 Record the tree hash that the pre-merge review covered.
- [ ] 7.2 After merge, compare the `main` tree hash with the record and deploy only on a match.
- [ ] 7.3 Record the deployed version and the previous one, for rollback.

## 8. Operator identity (D6 B, proposal only)

- [ ] 8.1 Write the identity and permission list: push branches and open or update PRs; no approval, merge, label, settings, secrets or workflow rights.
- [ ] 8.2 Make the pre-push guard allow only branch pushes of SHAs the batch file lists, and refuse force-push.
- [ ] 8.3 Test that the identity's `/ready` and `/approve` are refused by the gate.
- [ ] 8.4 Test that a push of any other SHA, branch or repository is refused.
- [ ] 8.5 Owner action: restrict who can push or merge to `main` with classic branch protection restrictions that list the owner as the only user, with admin enforcement on. Set it in `scripts/configure_repositories.py` so a settings run sets it and never resets it, and assert it in the standards or readback check. Test that the operator's merge of an approved, green PR is refused. Mirror the restriction in the identity spec.
- [ ] 8.6 The owner creates the identity and applies the permissions. The build never does.

## 9. Gate self-repair (D7 B or C)

- [ ] 9.1 Write the validator-first sequence in `docs/operations.md`: accept both forms, switch consumers, remove the old form.
- [ ] 9.2 Test that each step passes the gate with no override and no admin merge.
- [ ] 9.3 If D7 C is picked, the owner and the second human set up the infrastructure ruleset. The build only writes the proposal.
- [ ] 9.4 Confirm admin enforcement stays on for every required check.

## 10. Close out

- [ ] 10.1 Run one day in shadow, then switch on for one repository, then all.
- [ ] 10.2 Compare the new daily table with 2026-10-25 and report it.
- [ ] 10.3 Archive this change after the work merges.
