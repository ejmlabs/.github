# pr-gate Specification

## Purpose

Control when paid PR checks run and how a pull request becomes mergeable on protected main, using GitHub PR state and labels instead of comment-text commands.

## Requirements

### Requirement: Draft PRs spend no paid check budget

A draft pull request targeting main SHALL NOT start Quality, Repository standards, or other paid gate jobs.

#### Scenario: Someone opens or updates a draft

- **WHEN** a draft PR targeting main is opened or receives a new commit
- **THEN** the gate does not start paid checks for that head

### Requirement: Maintainer same-repo PRs auto-admit

A non-draft, same-repository pull request whose live author is a current human maintainer or admin SHALL be admitted for the current head on open, reopen, synchronize, and ready_for_review, and paid checks MAY run for that head. Every admission event SHALL admit only when its sender is a current human maintainer or admin.

#### Scenario: A maintainer pushes to their non-draft PR

- **WHEN** a current maintainer or admin who authors a same-repository non-draft PR targeting main pushes a new commit
- **THEN** the gate admits that head once and starts the bounded paid checks

#### Scenario: Someone else reopens a maintainer's stopped PR

- **WHEN** an account that is not a current maintainer or admin reopens, pushes to or marks Ready a maintainer's PR whose head a maintainer stopped
- **THEN** nothing is admitted and the head stays failed

### Requirement: Other same-repo PRs need a maintainer

A same-repository pull request whose author is not a current maintainer or admin, such as a bot or an outsider, SHALL be admitted only when a current human maintainer or admin marks it Ready for review or adds `gate:approve`. The author's own Ready action SHALL NOT admit paid checks.

#### Scenario: A non-maintainer author marks their own PR Ready

- **WHEN** a non-maintainer author converts their PR from draft to Ready for review
- **THEN** paid checks do not start

#### Scenario: A maintainer marks a PR Ready

- **WHEN** a current maintainer or admin converts that PR to Ready for review
- **THEN** the gate admits the current head and starts the bounded paid checks

### Requirement: Fork PRs are not admitted

A pull request from a fork SHALL NOT be admitted, because its `pull_request` token is read-only. The gate SHALL print a notice naming the policy and make no API write. A maintainer who reviewed the change SHALL push it to a branch in the repository, where the gate runs.

#### Scenario: A fork opens or updates a PR

- **WHEN** a fork PR is opened, updated or marked Ready
- **THEN** the gate prints a notice and starts no checks

### Requirement: Decisions bind the event head

Admission, approval and revoke SHALL act on the head SHA of the event. When the live PR head differs, or the PR is closed, a draft or not based on main, the run SHALL print a notice and write nothing, except that it removes a gate label. A new commit SHALL need a new admission under the rules above.

#### Scenario: A new commit lands after admission

- **WHEN** the PR head changes after an admission
- **THEN** the previous admission does not authorize checks for the new head

#### Scenario: A stale event

- **WHEN** an event's head is no longer the PR head
- **THEN** the run prints a notice and writes no status or review

A decision SHALL be skipped, with a notice and no status or review write, when a run with a higher run id has already written a required status for the head. Run ids are assumed to grow with the order events were created. This covers events that reach their job out of order and reruns of older runs, and it replaces any check of the PR's current draft state for a delayed draft event.

#### Scenario: An older event runs after a newer decision

- **WHEN** a Ready, approve or draft event reaches its job after a newer run's revoke or admission has written statuses
- **THEN** the older event admits, approves and stops nothing

### Requirement: Required merge checks are Quality and Repository standards

Protected main SHALL require **Quality** and **Repository standards** and SHALL NOT require **Human readiness** or **Maintainer approval** statuses. GitHub's required approving review count SHALL remain enforced for administrators too.

#### Scenario: Checks on a mergeable head

- **WHEN** a maintainer merges to main
- **THEN** Quality and Repository standards must be successful for that head, and at least one current approving GitHub review must apply to that head

### Requirement: One-label approve and admit

A current human maintainer or admin SHALL be able to approve the current head by adding the label `gate:approve`. Trusted automation SHALL record a bot approval bound to the event head, admit that head when no live run holds it, and remove the label. Control flow SHALL use exact label name equality from the labeled event, not comment text. Agents SHALL add this label only when the maintainer explicitly asks.

#### Scenario: A maintainer approves a bot PR

- **WHEN** a current maintainer adds `gate:approve` on the current non-draft head of a Dependabot PR
- **THEN** automation records an approving review for that head, admits it, and removes the label

#### Scenario: A non-maintainer adds the approve label

- **WHEN** an account without maintain or admin permission adds `gate:approve`
- **THEN** automation removes the label and does not record an approval

### Requirement: Authoritative stop

A current human maintainer or admin SHALL be able to stop the current head with the label `gate:revoke`, and converting a PR to draft SHALL stop it the same way. A stop SHALL fail both required statuses, cancel this workflow's other queued and in-progress runs for that head, dismiss bot approvals even when cancelling fails, wait a bounded time (at most 45 seconds) until the runs it listed have completed, and then fail both statuses again as its last write, even when a run is still going or a step above failed. The current run SHALL never be waited on. A stop SHALL end within 120 seconds whatever GitHub does, so it fits the 3-minute admission job. Status writes SHALL retry five times in all, 10 seconds per attempt. If the last write still fails, the job SHALL fail with an error saying the head may still read success and must not be merged, and `gate:revoke` SHALL stay on the PR.

`gate:revoke` SHALL stay on the PR until its stop has completed, or until the event is found stale or superseded. While the label is on the PR, verify and finish SHALL fail closed, and admission and approval SHALL write nothing and print a notice. Nothing SHALL clear the label except a completed stop or a maintainer.

#### Scenario: A stop that cannot complete

- **WHEN** a revoke job fails before its stop completes, or its job never runs
- **THEN** the label stays, finish fails the checks, and a Ready or `gate:approve` admits nothing until a maintainer reruns the revoke job or removes the label

#### Scenario: A finishing job races a revoke

- **WHEN** a finish job writes success while a stop runs
- **THEN** the last status written for each required context is a failure

#### Scenario: A finish job running when its cancel lands

- **WHEN** a stop cancels an older run whose finish job is still running and that job then writes success
- **THEN** the stop's last write comes after that run has completed, so the newest Quality and Repository standards statuses are failure

#### Scenario: A cancelled run that does not end

- **WHEN** a run the stop listed is still going after 45 seconds
- **THEN** the stop still writes its last failure statuses and prints a warning that names the run ids

#### Scenario: A last write that fails

- **WHEN** the stop's last status writes fail after their retries
- **THEN** the job fails with an error saying the head may still read success and must not be merged, and `gate:revoke` stays on the PR

### Requirement: Status ownership and reruns

Every status SHALL carry the URL of the run that wrote it. Verify and finish SHALL act only when the newest Quality and Repository standards statuses on the head belong to the current run and no other run has written one since this run's first, so a stop ends a run's claim for good. Reruns SHALL be allowed: re-running failed jobs keeps the admission, and re-running the admission job needs a current human maintainer as the actor. A pending pair whose run finished SHALL be stale and admitted again. Admission jobs SHALL be serialized per repository and head SHA, not per PR, so two PRs at one commit cannot admit it at once. A finish job SHALL NOT start for a cancelled run.

#### Scenario: A rerun of a stopped run

- **WHEN** a maintainer revokes a head and then reruns the original run's jobs
- **THEN** the rerun publishes nothing and admits nothing, and the head stays failed until a new Ready or `gate:approve`

#### Scenario: Another run owns the checks

- **WHEN** a newer run wrote the newest statuses for the head
- **THEN** the older run's verify stops it and its finish writes nothing

### Requirement: A product owns its gate commands

When the product has an executable, regular `.github/quality`, the credential-free Quality job SHALL run it from the product root instead of the profile's built-in commands, which remain the fallback.

#### Scenario: Product gate present

- **WHEN** an admitted head has an executable `.github/quality`
- **THEN** Quality runs it with lifecycle scripts disabled and not the built-in commands

### Requirement: Admission has no size cap

The gate SHALL NOT refuse a PR for the number of changed files or lines. Job time limits SHALL remain.

#### Scenario: A large PR

- **WHEN** a PR changes more than 200 files
- **THEN** admission proceeds and the job time limits bound the run

### Requirement: No comment-text or status-token control plane

Admission, approval, and revoke SHALL NOT depend on matching slash-command regexes in comment bodies or on parsing opaque tokens out of commit status descriptions. Later jobs SHALL re-validate live PR API state and workflow outputs.

#### Scenario: A comment contains /ready or /approve text

- **WHEN** someone comments `/ready` or `/approve` on a PR
- **THEN** the gate does not treat that comment as an admission or approval signal

### Requirement: Advisory next-action guidance

The governance workflow SHALL render deterministic next-action guidance from live PR metadata and the two required statuses for same-repository PRs. It SHALL preserve author text outside its marked section and SHALL NOT grant admission or approval. It SHALL refresh after admission and after check finalization, without executing PR code.

#### Scenario: A PR head has passed the required statuses

- **WHEN** the current head has passed Quality and Repository standards
- **THEN** the guidance directs the reader to review and check other configured results before merging

#### Scenario: A description has malformed guidance markers

- **WHEN** the markers are duplicated or incomplete
- **THEN** the renderer fails without rewriting the description
