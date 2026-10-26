# Design

## Caller shape

`consumer_workflows` emits (`missing_model_key` exists only in this repository's fixture form):

```yaml
on:
  issue_comment:
    types: [created, edited, deleted]
  pull_request_target:
    types: [unlabeled]
permissions: {}
jobs:
  governance:
    if: ${{ github.event_name == 'issue_comment' && github.event.issue.pull_request }}   # no pull_request_target
    permissions: { contents: read, pull-requests: write, statuses: write, actions: write }
    uses: ejmlabs/.github/.github/workflows/governance.yml@<SHA>
    secrets: { XAI_API_KEY: ..., EJM_HARNESS_TOKEN: ... }
  override:                                                                                # new
    if: ${{ github.event_name == 'pull_request_target' && github.event.label.name == 'Possible security concern' }}
    permissions: { contents: read, pull-requests: write, statuses: write, actions: write }
    uses: ejmlabs/.github/.github/workflows/governance.yml@<SHA>
```

`github.event.label.name` is in the `unlabeled` payload. No `issue.*` field is read on the `pull_request_target` path. The `acceptance:missing-model-key` test stays on the comment jobs only, where `issue.labels` exists.

In the `.github` fixture form, the `override` job carries `github.repository == 'ejmlabs/.github'` like its siblings, so the three jobs are scoped alike. Tests assert it.

## Requirement (a): where the label test lives

- **Caller `if:`** stops a runner starting for the removal of unrelated labels, so those removals leave no skipped or red check rows and cost no minutes.
- **`override` job `if:` in `governance.yml`** (`github.event.label.name == 'Possible security concern'`, plus the existing `run_attempt == 1` and `action == 'unlabeled'`) makes the shared file the trust boundary; it does not rely on the caller. Callers are held to the canonical text by **Repository standards**, but that check runs at a pin and can lag a rollout.
- **`relabel` in `scripts/governance.py`** compares exactly: `event["label"]["name"] == SECURITY_LABEL`. Actions expressions compare strings case-insensitively, so the two `if:` tests cannot prove "exactly"; Python can. GitHub does not allow two labels differing only in case, so this is a defence, not a live risk. `blocking_labels` keeps its case-insensitive match on the PR's labels because that direction fails closed.

## Requirement (b): no secret, no PR code

- Secrets are set per calling job. A separate `override` caller job with no `secrets:` is the only way to keep keys off the `pull_request_target` event while the comment job keeps them. A single job with event checks cannot do it.
- The shared job stays in `governance.yml`. GitHub validates every job in a called workflow against the calling job's permissions, including jobs that would be skipped, so the caller `override` job grants the union that file needs (`pull-requests: write`, `actions: write`). That is the one cost: the token on this path is wider than the three scopes the job itself declares. It is still the automatic `github.token`, it is not a secret input, and the job runs only trusted code. A separate `override.yml` would narrow the token but needs a preparatory pin generation, because the standards at the current pin reject any workflow file they do not know (reproduced); it is left out as the larger change for a small gain.
- The `override` job in `governance.yml` keeps its own `permissions` (`contents: read`, `pull-requests: read`, `statuses: write`), has no checkout and no `uses:` step, and reads no `secrets.` expression. It runs the trusted script embedded from `scripts/governance.py` and reads the PR through the API only. It never fetches the head.
- With the caller job secretless, even `secrets: inherit` is the only way a secret could be present in the called workflow's context. Safety therefore rests on the `override` job never referencing `secrets.` (a test asserts it) and on **Repository standards** rejecting any caller that sets `secrets:` or `inherit` on that job.
- Task 1.1 checks the permission rule with a throwaway run before the build relies on it. If the rule does not exist, the caller `override` job can take the narrower three scopes with no other change.

## Requirement (c): payload fields

- Caller: `github.event.label.name` only.
- Shared job: the concurrency group already uses `github.event.pull_request.number`. `relabel` takes `pull_request.number` and `pull_request.head.sha` from the payload. It re-reads labels and the head from `GET /pulls/{n}`, because a payload can be older than the job. If the payload `head.sha` is not the live head, `relabel` prints that nothing is re-evaluated and returns; the new head gets its own review. This check runs before the sender check, so a stale event from a non-maintainer is ignored rather than failed. A test pins the order.

## Fork and non-maintainer analysis

- `pull_request_target` always runs the workflow file on the base repository's default branch, never the PR's. A fork PR cannot change it.
- Only users with triage or higher on the base repository can remove a label. A fork author cannot. Label edits made with the automatic `GITHUB_TOKEN`, such as the reviewer's own, start no workflow.
- `relabel` then requires a human sender whose live permission is `maintain` or `admin`. Triage and write users, bots and a PR author who is not a maintainer fail.
- A fork of `.github` has its own copy of the callers and its own `github.token`; it cannot reach this repository's statuses.
- `run_attempt == 1` stays, so a rerun by someone else cannot replay an old removal.

## Standards check and transition

`consumer_workflows` returns the new text. A new `previous_consumer_workflows` (the #40 text) is accepted beside it, in `standards.py` where the exact-compare loop is (`for name, expected in consumers.items()`) and in `configure_repositories.installed_consumers`. A hand-edited caller matches neither and fails with the existing "Workflow differs from the canonical consumer" message, which names the file. No new shared file, so no change to the allowed-workflow sets.

`governance.yml` changes only the `override` job's `if:`. The structural check of `governance.yml` at the current pin accepts that (reproduced), so the shared PR passes the standards on `.github` main.

The `override` job stays in `governance.yml` for good, because the new caller calls it. Only the previous caller form leaves the standards, in the cleanup step.

## Rollout and the stuck-between-steps problem

The gap the repositories hit came from a pin whose standards rejected the form still on main. Here the new pin accepts both forms, so no repository fails between steps and the order across repositories does not matter.

1. `.github`: merge the shared change (standards, generator, `governance.yml`, `relabel`, docs); retain the commit under `workflow-pins/FULL_SHA`. It adds no workflow file and changes no caller, and passes the standards at the current pin.
2. Each of `.github`, `ejm-ui`, `ejm-cli`, `ejm-ide`, `ejm-harness`, `ejmlabs`: re-pin the governance and release pins to that commit, keeping the #40 form. The current standards accept it; after merge the new standards accept it too.
3. Each repository: change `pr.yml` to the new form. No community text changes. The new standards accept it. No repository waits on another.
4. Cleanup: read back all six mains and confirm each is on the new form. Only then cut the next pin that drops `previous_consumer_workflows`, and re-pin all six in PRs that touch only the pins. A repository still on the previous form would pass its own PR (the old standards on its main accept it) and then be stuck after merge, which is why the read-back comes first.

Repositories on a pin older than the new one are unaffected until they re-pin.

## Alternatives

- Keep one job, drop the secrets: breaks the comment path.
- A separate `override.yml`: narrows the token to three scopes, but the current standards reject the new file, so it needs an extra pin generation first. Choose it later if token width on this path matters.
- Accept the previous form permanently: leaves the secret-bearing `pull_request_target` shape allowed.
- Do nothing: the next caller edit repeats the stall seen in #40.

## Verification of fork and non-maintainer limits

Unit tests (see tasks) cover the sender and head-repository cases offline. Local tests do not prove event delivery. After the build is approved, one scratch repository under the same standards, a second account with only triage and a fork PR, prove it in GitHub: a triage user removing the label leaves **AI review** failed; a maintainer removing it succeeds; a fork author has no label control. The check also records whether deleting the label from the repository emits `unlabeled` for open PRs; the sender is then a maintainer, so the gate holds either way. This touches live repositories and needs the owner's approval before it is run.
