# Design

## Caller shape

`consumer_workflows` emits (new lines marked; `missing_model_key` exists only in this repository's fixture form):

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
    permissions: { contents: read, pull-requests: read, statuses: write }
    uses: ejmlabs/.github/.github/workflows/override.yml@<SHA>
```

`github.event.label.name` is in the `unlabeled` payload. No `issue.*` field is read on the `pull_request_target` path. The `acceptance:missing-model-key` test stays on the comment jobs only, where `issue.labels` exists.

## Requirement (a): where the label test lives

Both places.

- **Caller `if:`**: stops a runner from starting for the removal of unrelated labels, so those removals leave no skipped or red check rows and cost no minutes. It is the cheap, early filter.
- **Shared `override.yml` job `if:`** (`github.event.label.name == 'Possible security concern'`, plus the existing `run_attempt == 1` and `action == 'unlabeled'`): the shared file is the trust boundary and must not rely on the caller. Callers are held to the canonical text by **Repository standards**, but that check runs at a pin and can be late or bypassed by a failed rollout.
- **`relabel` in `scripts/governance.py`**: exact comparison, `event["label"]["name"] == SECURITY_LABEL`. Actions expressions compare strings case-insensitively, so the two `if:` tests cannot prove "exactly". Python can. GitHub does not allow two labels differing only in case, so this is a defence, not a live risk. `blocking_labels` keeps its case-insensitive match on the PR's labels because that direction fails closed.

## Requirement (b): no secret, no PR code

- Secrets are set per calling job. A separate `override` caller job with no `secrets:` is the only way to keep keys off the `pull_request_target` event while the comment job keeps them. A single job with event checks cannot do it.
- The shared job moves to a new `override.yml`. Reason: GitHub validates the permissions of every job in a called workflow against the caller job, including jobs that would be skipped. `governance.yml` has jobs that need `pull-requests: write` and `actions: write`. Calling it from a job granted `statuses: write` and reads only would fail at startup, so the caller would have to hold write scopes the override does not need. `override.yml` has one job and needs only `contents: read`, `pull-requests: read`, `statuses: write`. It declares no `secrets` and no `inputs`, so a caller that adds `secrets:` or `secrets: inherit` gets nothing in it, and the standards check fails that caller anyway.
- `override.yml` has no checkout and no `uses:` step. The only code it runs is the trusted script embedded from `scripts/governance.py`, as today. It reads the PR through the API and never fetches the head.
- The automatic `github.token` remains, scoped to the three permissions above. It is not a secret input and the PR cannot read it.
- Fallback if the permission rule turns out not to apply (task 1.1 checks it with a throwaway run): keep the job in `governance.yml` and give the caller `override` job the permissions that file needs. Still secretless; only the least-privilege claim weakens. Choose this only on evidence.

## Requirement (c): payload fields

- Caller: `github.event.label.name` only.
- Shared job: concurrency group already uses `github.event.pull_request.number`. `relabel` takes `pull_request.number` and `pull_request.head.sha` from the payload. It re-reads labels and the head from `GET /pulls/{n}`, because labels and head in a payload can be older than the job. If the payload `head.sha` is not the live head, `relabel` prints that nothing is re-evaluated and returns; the new head will get its own review.

## Fork and non-maintainer analysis

- `pull_request_target` always runs the workflow file on the base repository's default branch, never the PR's. A fork PR cannot change it.
- Only users with triage or higher on the base repository can remove a label. A fork author cannot. The trigger is therefore reachable only by people who can already edit the PR's labels.
- `relabel` then requires a human sender whose live permission is `maintain` or `admin`. Triage and write users, bots and the PR author (unless a maintainer) fail.
- A fork of `.github` has its own copy of the callers and its own `github.token`; it cannot reach this repository's statuses.
- Reruns: `run_attempt == 1` stays, so a rerun by someone else cannot re-use an old event.

## Standards check and transition

`consumer_workflows` returns the new text. A new `previous_consumer_workflows` (the #40 text) is accepted by the check beside it, in `standards.py` where the exact-compare loop is (`for name, expected in consumers.items()`) and in `configure_repositories.installed_consumers`. `override.yml` joins the allowed shared files for the `.github` profile (`allowed.update(...)` and `_reusable_workflow`). A hand-edited caller matches neither and fails with the existing "Workflow differs from the canonical consumer" message, which names the file.

`governance.yml` keeps its `override` job for this generation, with the same exact label test, so a repository still on the #40 caller keeps a working override at the new pin. A later change removes the previous caller form and that job together, after all six repositories are on the new form (see tasks section 3).

## Rollout and the stuck-between-steps problem

The gap the repositories hit came from step 2 landing a pin whose standards rejected the form still on main. Here the new pin accepts both forms, so no repository fails between steps and the order across repositories does not matter.

1. `.github`: merge the shared change; retain the commit under `workflow-pins/FULL_SHA`. This PR is checked by the old standards and changes no caller.
2. Each of `.github`, `ejm-ui`, `ejm-cli`, `ejm-ide`, `ejm-harness`, `ejmlabs`: re-pin the governance and release pins to that commit, keep the #40 form. The old standards accept it. After merge, the new standards accept it too.
3. Each repository: change `pr.yml` to the new form. No community text changes. The new standards accept it. A repository may do this the same day it finishes step 2; none is blocked on the others.
4. After all six: `.github` removes the previous caller form from the standards and the `override` job from `governance.yml`, new pin, re-pin all six again (callers do not change).

Consumers on a pin older than the new one are unaffected until they re-pin.

## Alternatives

- Keep one job, drop the secrets: breaks the comment path.
- Keep the job in `governance.yml` (the earlier draft): works only if the caller grants write scopes the override does not use.
- Accept the previous form permanently: leaves the secret-bearing `pull_request_target` shape allowed.
- Do nothing: the next caller edit repeats the stall seen in #40.

## Verification of fork and non-maintainer limits

Unit tests (below) cover the sender and head-repository cases offline. Local tests do not prove event delivery. After the build is approved, one scratch repository under the same standards, a second account with only triage and a fork PR, prove it in GitHub: a triage user removing the label leaves **AI review** failed; a maintainer removing it succeeds; a fork author has no label control. This touches live repositories and needs Everett's approval before it is run.
