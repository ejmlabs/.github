## 1. Stop requiring the status (owner only, first)
- [x] 1.1 In each of .github, ejm-ui, ejm-cli, ejm-ide, ejm-harness and ejmlabs, remove "AI review" from the required status checks on main (repository settings UI, or the settings script from the removal commit's tree with the owner's admin token; do not run main's script until the removal has merged, because it still sets five contexts).
- [x] 1.2 Read back each repository's required checks and confirm exactly four remain.

## 2. Stop running the review (shared gate, one revision)
- [x] 2.0 First commit, merged and pinned by this repository before the removal: the standards check accepts both caller forms and a shared workflow with or without the review job. The previous standards reject a shared workflow without the review job, so the removal cannot pass its own Repository standards check as the first change.
- [x] 2.1 Remove the AI review job and the "AI review" status from governance.yml and scripts/governance.py; remove the security-concern label, its override job and the unlabeled trigger handling; remove the reviewer lock file and its provider test.
- [x] 2.2 Drop "AI review" from CONTEXTS in scripts/governance.py and scripts/configure_repositories.py.
- [x] 2.3 Generate callers without the model key; the new pin's standards accept both the current caller and the new one for one generation. governance.yml keeps the optional, unused model key secret declared for that generation, because a caller passing an undeclared secret is rejected.
- [x] 2.4 Update docs/operations.md and tests; run unit tests, build_workflows.py --check and the standards check. Document that the four statuses are enforced for administrators too and that re-enabling any model review needs the security review's sign-off first.
- [x] 2.5 Fresh independent code and security review, then the owner approves the push and merge; tag the new pin.

## 3. Re-pin the callers
- [ ] 3.1 One pin-only PR per repository (.github, ejm-ui, ejm-cli, ejm-ide, ejm-harness, ejmlabs), keeping the current caller form, so the previous standards accept it. .github first re-pins to the 2.0 commit, then to the removal commit. Order across repositories is free.
- [ ] 3.2 One caller-form PR per repository, after its pin is on the removal commit: drop the model key forward and the unlabeled trigger. A pin change and a form change in one PR fail the previous standards, so they are separate.
- [ ] 3.3 Read back all six mains on the new pin and form.

## 4. Retire the key (owner only, after 3.2)
- [ ] 4.1 Delete the `legacy-review` environment (its secret and branch rule) in each repository.
- [ ] 4.2 Close or empty the prepaid provider account.

## 5. Clean up
- [ ] 5.1 Next gate revision drops the old caller form, the optional model key secret declaration and the missing-key fixture form from the standards check.
- [ ] 5.2 Update the shared community CONTRIBUTING template, which still names the removed status, through its own adoption (consumers compare it byte for byte).
