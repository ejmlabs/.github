# Tasks

## 1. Shared change (`.github`)

- [ ] 1.1 With the owner's approval, run a throwaway workflow in a scratch repository to confirm GitHub rejects a caller job that grants fewer permissions than a skipped job in the called workflow. Record the result in the PR. If it does not, narrow the caller `override` job to the three scopes.
- [ ] 1.2 `scripts/governance.py`: `relabel` compares `event["label"]["name"]` to `SECURITY_LABEL` exactly; takes the number and `head.sha` from `event["pull_request"]`; returns without a status when the payload head is not the live head, before the sender check.
- [ ] 1.3 `scripts/build_workflows.py`: add `github.event.label.name == 'Possible security concern'` to the `override` job `if:` in `governance.yml`; regenerate `.github/workflows/governance.yml`.
- [ ] 1.4 `scripts/standards.py`: new `consumer_workflows` with `governance` (and `missing_model_key`) limited to `issue_comment` and a secretless `override` job (repository-scoped in the `.github` fixture form); add `previous_consumer_workflows` (the #40 text) and accept either in `workflows`.
- [ ] 1.5 `scripts/configure_repositories.py`: `installed_consumers` accepts either form.
- [ ] 1.6 `docs/operations.md`: replace the override paragraph and "Adopting the documented reviewer gate" with the sequence in the design.

## 2. Tests

- [ ] 2.1 `tests/test_governance.py`: `relabel` ignores a label differing only in case and any other label; fails for a triage/write sender, a bot, and a PR author who is not a maintainer; makes no status change when the payload head is stale, including when the sender is not a maintainer; works for a fork PR (head repository differs) without reading the head.
- [ ] 2.2 `tests/test_workflows.py`: the `override` caller job has no `secrets`; `governance` and `missing_model_key` jobs do not mention `pull_request_target`; no caller `if:` on the unlabeled path contains `github.event.issue`; the `.github` fixture `override` job carries the repository guard; the `governance.yml` `override` job has no `secrets.`, no `uses:` step, `statuses: write` as its only write, and the label test in its `if:`; update the publisher list at `tests/test_workflows.py:494` only if the publisher set changes.
- [ ] 2.3 `tests/test_standards.py`: both forms are accepted; a caller with `secrets:` on the override job, `secrets: inherit`, an `issue.*` condition on it, or the label test removed is rejected naming `pr.yml`; the missing-key fixture form is accepted with the new job. Transition: the #40 form at a new pin passes, and the new form at the old pin passes under the old standards.
- [ ] 2.4 `tests/test_configure.py`: `installed_consumers` accepts both forms.
- [ ] 2.5 Run the full test suite and confirm regenerating the workflows leaves the tree unchanged.

## 3. Rollout (per `docs/operations.md`)

- [ ] 3.1 Merge section 1 with ordinary review; retain the commit under `workflow-pins/FULL_SHA`.
- [ ] 3.2 Re-pin the six callers to that commit, keeping the #40 form.
- [ ] 3.3 Change each caller to the new form (no community text change). Any order.
- [ ] 3.4 Read back all six mains on the new form. Then drop `previous_consumer_workflows`, cut a new pin, and re-pin all six in PRs that change only the pins.
- [ ] 3.5 With the owner's approval, run the live check from the design in a scratch repository.
