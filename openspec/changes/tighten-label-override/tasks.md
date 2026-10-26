# Tasks

## 1. Shared change (`.github`)

- [ ] 1.1 In a throwaway run, confirm GitHub rejects a caller job that grants fewer permissions than a skipped job in the called workflow. Record the result in the PR. If it does not, apply the design's fallback and drop 1.3 to a single job.
- [ ] 1.2 `scripts/governance.py`: `relabel` compares `event["label"]["name"]` to `SECURITY_LABEL` exactly; takes the number and `head.sha` from `event["pull_request"]`; returns without a status when the payload head is not the live head.
- [ ] 1.3 `scripts/build_workflows.py`: emit `override.yml` (one job, `workflow_call` with no secrets or inputs, `if:` testing `github.event.label.name`, no checkout, no `uses:` step); add the same label test to the `override` job kept in `governance.yml`; regenerate `.github/workflows/`.
- [ ] 1.4 `scripts/standards.py`: new `consumer_workflows` with `governance` (and `missing_model_key`) limited to `issue_comment` and a secretless `override` job; add `previous_consumer_workflows` (the #40 text) and accept either in `workflows`; allow and exact-check `override.yml` in the `.github` profile via `_reusable_workflow`.
- [ ] 1.5 `scripts/configure_repositories.py`: `installed_consumers` accepts either form and lists `override.yml` as an allowed shared file for `.github`.
- [ ] 1.6 `docs/operations.md`: replace the override paragraph and "Adopting the documented reviewer gate" with the sequence above.

## 2. Tests

- [ ] 2.1 `tests/test_governance.py`: `relabel` ignores a label differing only in case and any other label; fails for a triage/write sender, a bot, and the PR author who is not a maintainer; makes no status change when the payload head is stale; works for a fork PR (head repository differs) without reading the head.
- [ ] 2.2 `tests/test_workflows.py`: `override` caller job has no `secrets` and no `permissions` beyond the three; `governance` and `missing_model_key` jobs do not mention `pull_request_target` or `github.event.label`; no caller `if:` on the unlabeled path contains `github.event.issue`; `override.yml` has no `secrets`, `inputs`, `uses:` step or checkout, and `statuses: write` is its only write; `governance.yml` has no `secrets.` on its override job.
- [ ] 2.3 `tests/test_standards.py`: both forms are accepted; a caller with `secrets:` on the override job, `secrets: inherit`, an `issue.*` condition on it, or the label test removed is rejected naming `pr.yml`; the missing-key fixture form is accepted with the new job.
- [ ] 2.4 Run the full test suite and confirm regenerating the workflows leaves the tree unchanged.

## 3. Rollout (per `docs/operations.md`)

- [ ] 3.1 Merge section 1 with ordinary review; retain the commit under `workflow-pins/FULL_SHA`.
- [ ] 3.2 Re-pin the six callers to that commit, keeping the #40 form.
- [ ] 3.3 Change each caller to the new form (no community text change). Any order.
- [ ] 3.4 After all six: remove the previous caller form and the `governance.yml` `override` job; new pin; re-pin all six.
- [ ] 3.5 With Everett's approval, run the live check from the design in a scratch repository.
