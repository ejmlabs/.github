## ADDED Requirements

### Requirement: Fork PRs are not admitted

A pull request from a fork SHALL NOT be admitted, because its `pull_request` token is read-only. The gate SHALL print a notice naming the policy and make no API write.

#### Scenario: A fork opens a PR

- **WHEN** a fork PR is opened, updated or marked Ready
- **THEN** the gate prints a notice and starts no checks

### Requirement: Decisions bind the event head

Admission, approval and revoke SHALL act on the event's head SHA. When the live head differs, or the PR is closed, a draft or not based on main, the run SHALL print a notice and write nothing, except that it removes a gate label.

#### Scenario: A stale event

- **WHEN** an event's head is no longer the PR head
- **THEN** the run prints a notice and writes no status or review

A decision SHALL also be skipped, with a notice and no status or review write, when a run with a higher run id has already written a required status for the head. Run ids are assumed to grow with the order events were created.

#### Scenario: An older event runs after a newer decision

- **WHEN** a Ready, approve or draft event reaches its job after a newer run's revoke or admission has written statuses
- **THEN** the older event admits, approves and stops nothing

### Requirement: Status ownership and reruns

Every status SHALL carry its run URL, and verify and finish SHALL act only when the newest required statuses on the head belong to the current run and no other run has written one since this run's first, so a stop ends a run's claim for good. Reruns SHALL be allowed, and re-running the admission job SHALL need a current human maintainer as the actor. Admission jobs SHALL be serialized per repository and head SHA, and a finish job SHALL NOT start for a cancelled run.

#### Scenario: A rerun of a stopped run

- **WHEN** a maintainer revokes a head and then reruns the original run's jobs
- **THEN** the rerun publishes nothing and admits nothing, and the head stays failed until a new Ready or `gate:approve`

#### Scenario: Another run owns the checks

- **WHEN** a newer run wrote the newest statuses
- **THEN** the older run's verify stops it and its finish writes nothing

### Requirement: Admission has no size cap

The gate SHALL NOT refuse a PR for its number of changed files or lines.

#### Scenario: A large PR

- **WHEN** a PR changes more than 200 files
- **THEN** admission proceeds

### Requirement: A product owns its gate commands

When the product has an executable, regular `.github/quality`, Quality SHALL run it instead of the profile's built-in commands.

#### Scenario: Product gate present

- **WHEN** an admitted head has an executable `.github/quality`
- **THEN** Quality runs it with lifecycle scripts disabled

## MODIFIED Requirements

### Requirement: One-label approve and admit

A current human maintainer SHALL approve and admit the current head with `gate:approve`: automation records a bot approval bound to the event head, admits the head when no live run holds it, and removes the label.

#### Scenario: A maintainer approves a bot PR

- **WHEN** a maintainer adds `gate:approve` on the current non-draft head of a Dependabot PR
- **THEN** automation records an approving review for that head and admits it

### Requirement: Authoritative stop

`gate:revoke` and conversion to draft SHALL fail both statuses, cancel this workflow's other runs for the head, dismiss bot approvals even when cancelling fails, wait at most 45 seconds for the runs it listed to complete, and fail both statuses again as the last write. A stop SHALL end within 120 seconds; if its last write fails, the job SHALL fail and say the head must not be merged. `gate:revoke` SHALL stay on the PR until its stop has completed: while it is there, verify and finish fail closed and admission and approval write nothing. Every admission event SHALL admit only when its sender is a current human maintainer.

#### Scenario: A finishing job races a revoke

- **WHEN** a finish job writes success while a stop runs
- **THEN** the last status for each required context is a failure

#### Scenario: A finish job running when its cancel lands

- **WHEN** a stop cancels an older run whose finish job is still running and that job then writes success
- **THEN** the stop's last write comes after that run has completed, so the newest statuses are failure

## REMOVED Requirements

### Requirement: Outsider and fork PRs need a maintainer Ready action

**Reason**: Forks cannot be admitted, and other same-repo PRs are admitted by Ready or `gate:approve`.
**Migration**: See "Fork PRs are not admitted" and "Other same-repo PRs need a maintainer" in `openspec/specs/pr-gate/spec.md`.

### Requirement: New commits need a fresh admission

**Reason**: Replaced by "Decisions bind the event head".
**Migration**: A new commit is a new event with its own head.
