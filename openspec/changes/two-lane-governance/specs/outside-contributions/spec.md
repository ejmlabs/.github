## ADDED Requirements

### Requirement: Outside code runs only in credential-free CI

Each product repository SHALL have an outside CI workflow on `pull_request` with a read-only token, no secrets, and GitHub's approval for outside contributors' runs. Its results MUST be informational only. No paid job, secret or publication credential SHALL ever run on outside code.

#### Scenario: First-time fork PR

- **WHEN** a first-time contributor opens a fork PR
- **THEN** outside CI waits for a maintainer to approve the run in GitHub, and the approved run has no secrets

#### Scenario: Same-repository branch from an outside identity

- **WHEN** a principal outside the trusted set opens a PR from a branch in the base repository, so that GitHub's run approval does not apply
- **THEN** the PR is outside (see pr-lanes), its workflows get no secrets and their results are ignored

#### Scenario: Paid review requested on outside code

- **WHEN** any command or event would start a paid pass on an outside PR's head
- **THEN** the service refuses it

### Requirement: Triage runs automatically on metadata and bounded diffs

The service SHALL triage outside PRs without executing code, on open, push, title, body or base edits, and linked-issue changes, debounced to 2 minutes. Size limits SHALL be checked from metadata before any diff is fetched. Diff and metadata reads MUST stay within byte and page bounds.

#### Scenario: Body edited to add an issue link

- **WHEN** a contributor edits the PR body to link an accepted issue
- **THEN** triage re-runs without a new commit

#### Scenario: Huge PR

- **WHEN** PR metadata reports 5,000 changed files
- **THEN** triage fails on size without fetching the diff

### Requirement: Triage rules cover size, types, scope and template

Triage SHALL require: at most 30 files and 1,000 changed lines; no `.github/` changes, symlinks, binaries, executables, lockfile-only, vendored or new-dependency changes; for larger changes, an open same-repository issue labelled `accepted` or a maintainer's scope acceptance on the PR; all PR template sections answered; and a DCO `Signed-off-by` matching each commit author.

#### Scenario: Oversized outside PR

- **WHEN** an outside PR changes 80 files
- **THEN** triage fails the size rule and asks for a split

### Requirement: Small fixes do not need a linked issue

A PR of at most 50 changed lines with no new dependencies, no public API change and a problem statement SHALL be exempt from the linked-issue rule. Maintainers SHALL label new issues `accepted` or `declined` with a reason within about 5 business days.

#### Scenario: Unaccepted issue

- **WHEN** a 200-line PR links an issue without the `accepted` label and no maintainer accepted its scope on the PR
- **THEN** the linked-issue rule fails

#### Scenario: Small fix without an issue

- **WHEN** a 40-line PR with a problem statement adds no dependency and changes no public API
- **THEN** the linked-issue rule passes

#### Scenario: Missing sign-off

- **WHEN** a commit lacks a `Signed-off-by` matching its author
- **THEN** triage fails and the comment explains `git commit --amend -s` or `git rebase --signoff`

### Requirement: Triage feedback is one comment and never judges accounts alone

Each triage failure SHALL add `needs-work` and update a single bot comment in place. Account age or history MUST NOT on its own close a PR.

#### Scenario: New account with a clean PR

- **WHEN** a day-old account opens a PR that passes every rule
- **THEN** it stays open and is not labelled `spam`

### Requirement: Contributor and event rates are capped

Triage SHALL limit each contributor to 2 open PRs per repository and 5 new PRs per day across the org. It SHALL cap triage evaluations at 20 per PR, 50 per principal and 500 org-wide per day. When a cap is hit it SHALL label `triage:paused` until a maintainer resumes.

#### Scenario: Push storm

- **WHEN** a contributor pushes 40 times in a day to one PR
- **THEN** triage stops after 20 evaluations and labels the PR `triage:paused`

#### Scenario: Third open PR

- **WHEN** a contributor with 2 open PRs in a repository opens a third
- **THEN** the third is labelled `needs-work` with the open-PR limit explained

### Requirement: Spam is closed with an appeal path

Triage SHALL label `spam`, close and lock only outside PRs with promotional or link content, and SHALL link the appeal path. A PR over a rate or event cap by more than double SHALL get `triage:paused`, not `spam`. The spam rules SHALL be published in CONTRIBUTING. Automation MUST NOT block accounts.

#### Scenario: Promotional link PR

- **WHEN** an outside PR adds only promotional links
- **THEN** it is closed, locked and labelled `spam`, with a link to the appeal path

#### Scenario: Over-cap burst

- **WHEN** a contributor exceeds the daily PR cap by more than double
- **THEN** the extra PRs get `triage:paused`, not `spam`

### Requirement: Appeals are real and answered

Discussions with an Appeals category and the SUPPORT address SHALL be enabled and confirmed before cutover. An appeal SHALL get a response within about 5 business days, from a different maintainer than the closer where one exists.

#### Scenario: Successful appeal

- **WHEN** a maintainer accepts an appeal
- **THEN** the PR is reopened, `spam` is removed and an audit record is written

### Requirement: Stale closes count only contributor time

A PR failing triage for 14 days of time waiting on the contributor SHALL get a friendly comment and close as stale with "reopen any time". Time waiting on maintainers MUST NOT count.

#### Scenario: Waiting on a maintainer

- **WHEN** a community PR has waited 20 days, 10 of them for a maintainer's answer
- **THEN** it is not closed as stale

### Requirement: Both lanes meet the same evidence bar

The PR template for both lanes SHALL require a problem link or statement, a scoped change description, validation commands and results, regression evidence or a reason why none applies, a generated-content disclosure, and an attestation of understanding. Repository standards SHALL check that the template is complete. Generation detectors MUST NOT be used. The disclosure SHALL say what was generated, not which tool, and MUST NOT count against a PR.

#### Scenario: Missed disclosure

- **WHEN** a contributor forgot the generated-content disclosure
- **THEN** the PR is asked to edit its description and is not closed for it

#### Scenario: Missing validation

- **WHEN** a PR's validation section names no command or test
- **THEN** the template check fails in either lane

#### Scenario: Disclosed generated content

- **WHEN** a contributor discloses substantial generated content and meets every rule
- **THEN** the PR is treated like any other PR

### Requirement: Public wording uses maintainer and community PRs

Public text SHALL call the lanes "maintainer PRs" and "community PRs" and give the one-line reason that fork PRs never get secrets or paid review until adopted.

#### Scenario: Triage comment wording

- **WHEN** triage comments on a fork PR
- **THEN** it says "community PR" and never "outside" or "untrusted"

### Requirement: Adoption requires a fully passing, current triage

`/adopt` from a maintainer, bound like ship, SHALL be accepted only if every triage rule passes for the current head and metadata revision, and nothing in scope is quarantined. It is the only path from outside work to paid review.

#### Scenario: Stale green triage

- **WHEN** triage passed earlier but the body was since edited and not re-triaged
- **THEN** `/adopt` is refused until triage passes on the current metadata revision

### Requirement: Adopted heads have exclusive, recorded provenance

On adoption, the Governance App SHALL push the exact head to `contrib/**`, which only it may update, and record the origin, head, tree, adopter and evidence. The adopted PR SHALL credit each contributor with `Signed-off-by` and `Co-authored-by` trailers, and the original PR SHALL get a "landed as #N, thanks @handle" comment on merge. Any PR whose head lies in `contrib/**` without a matching adoption record MUST be outside. Adopted PRs MUST NOT be inert or waivable.

#### Scenario: Writer pushes to an adopted branch

- **WHEN** anyone other than the Governance App tries to update a `contrib/` branch
- **THEN** the ruleset rejects the push

#### Scenario: Contributor pushes after adoption

- **WHEN** the contributor pushes to their fork after adoption
- **THEN** nothing changes until a new `/adopt`, which creates a new generation needing a new ship
