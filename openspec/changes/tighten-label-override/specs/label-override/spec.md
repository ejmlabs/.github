# Spec Delta

## Purpose

Keep the label-override path narrow: one label, no secrets, no PR code, the right payload.

## ADDED Requirements

### Requirement: The override runs only for the security label

The override path MUST start only for a `pull_request_target` `unlabeled` event whose `github.event.label.name` is `Possible security concern`. The caller job condition and the shared job condition MUST both test it, and the shared step MUST compare the removed label name exactly.

#### Scenario: Another label is removed

- **WHEN** a maintainer removes `acceptance:missing-model-key` or any other label
- **THEN** the caller `override` job does not start
- **AND** a caller that reaches the shared job anyway finds its condition false and the job skipped

#### Scenario: A label differing only in case is removed

- **WHEN** the removed label name differs from `Possible security concern` only in letter case
- **THEN** the shared step changes no status

### Requirement: The override path holds no secret and no PR code

The caller `override` job MUST NOT set `secrets:`. The `override` job in `governance.yml` MUST NOT reference `secrets.`, MUST contain no `uses:` step and no checkout, and MUST grant itself only `contents: read`, `pull-requests: read` and `statuses: write`. The `governance` and `missing_model_key` caller jobs MUST NOT run for `pull_request_target`.

#### Scenario: A label is removed

- **WHEN** the security label is removed from a PR
- **THEN** only the `override` caller job starts, and no model key or harness token is in its call
- **AND** no step fetches or executes the PR head

#### Scenario: A maintainer comments `/ready`

- **WHEN** an admitted maintainer comments `/ready <sha>`
- **THEN** `governance` runs with its secrets as before
- **AND** `override` does not start

### Requirement: The override reads the pull request payload

On `pull_request_target` the override MUST read `github.event.pull_request.number` and `head.sha`, and MUST NOT read `github.event.issue.*`. It MUST read the PR's current labels and head from the API, and MUST change no status when the payload head is not the current head.

#### Scenario: A push lands before the job reads the PR

- **WHEN** the payload `head.sha` differs from the PR's live head
- **THEN** the job prints that nothing is re-evaluated and sets no status

### Requirement: Only a current human maintainer can use the override

The override MUST change **AI review** only when the sender is a human with live `maintain` or `admin` permission on the repository, regardless of the PR author or head repository.

#### Scenario: A non-maintainer or a bot removes the label

- **WHEN** a sender without `maintain` or `admin`, or any bot, is recorded as removing the label
- **THEN** the job fails and **AI review** stays failed

### Requirement: The standards check accepts the new caller and, for one generation, the previous one

**Repository standards** MUST accept the new canonical caller. For the pin generation that introduces it, the check MUST also accept the #40 caller exactly. A caller that matches neither MUST fail with a message naming the file. This includes any caller other than the exact previous form that passes `secrets:` on a `pull_request_target` job.

#### Scenario: A repository is on the previous caller after the new pin lands

- **WHEN** a repository main runs the new pin with the #40 caller
- **THEN** **Repository standards** passes for that repository's other PRs

#### Scenario: A hand-edited caller

- **WHEN** a caller adds `secrets:` to the `pull_request_target` job
- **THEN** **Repository standards** fails naming `pr.yml`
