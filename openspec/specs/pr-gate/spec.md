# pr-gate Specification

## Purpose

Control when paid PR checks run and how a pull request becomes mergeable on protected main, using GitHub PR state and labels instead of comment-text commands.

## Requirements

### Requirement: Draft PRs spend no paid check budget

A draft pull request targeting main SHALL NOT start Quality, Repository standards, or other paid gate jobs.

#### Scenario: Someone opens or updates a draft

- **WHEN** a draft PR targeting main is opened or receives a new commit
- **THEN** the gate does not start paid checks for that head

### Requirement: Maintainer same-repo PRs auto-admit when Ready

A non-draft, same-repository pull request whose author is a current human maintainer or admin SHALL be admitted for the current head on open, synchronize, and ready_for_review, and paid checks MAY run for that head.

#### Scenario: A maintainer pushes to their non-draft PR

- **WHEN** a current maintainer or admin who authors a same-repository non-draft PR targeting main pushes a new commit
- **THEN** the gate admits that head once and starts the bounded paid checks

### Requirement: Outsider and fork PRs need a maintainer Ready action

A pull request from a fork, or whose author is not a current maintainer or admin, SHALL be admitted only when a current human maintainer or admin marks that PR Ready for review. The author's own Ready action SHALL NOT admit paid checks.

#### Scenario: An outsider marks their own PR Ready

- **WHEN** a non-maintainer author converts their PR from draft to Ready for review
- **THEN** paid checks do not start

#### Scenario: A maintainer marks an outsider PR Ready

- **WHEN** a current maintainer or admin converts that PR to Ready for review
- **THEN** the gate admits the current head and starts the bounded paid checks

### Requirement: New commits need a fresh admission

An admission SHALL bind to one head SHA via workflow outputs. A new commit SHALL require a new admission under the rules above. Converting a PR back to draft SHALL cancel admitted work and stop further auto-admission until it is Ready again under those rules.

#### Scenario: A new commit lands after admission

- **WHEN** the PR head changes after an admission
- **THEN** the previous admission does not authorize checks for the new head

### Requirement: Required merge checks are Quality and Repository standards

Protected main SHALL require **Quality** and **Repository standards** and SHALL NOT require **Human readiness** or **Maintainer approval** statuses. GitHub's required approving review count SHALL remain enforced for administrators too.

#### Scenario: Checks on a mergeable head

- **WHEN** a maintainer merges to main
- **THEN** Quality and Repository standards must be successful for that head, and at least one current approving GitHub review must apply to that head

### Requirement: Label-based maintainer self-approve

A current human maintainer or admin SHALL be able to approve the current head by adding the label `gate:approve`. Trusted automation SHALL record a GitHub approval for that head, then remove the label. Control flow SHALL use exact label name equality from the labeled event, not comment text. Agents SHALL add this label only when the maintainer explicitly asks.

#### Scenario: Solo maintainer self-approves

- **WHEN** a current maintainer adds `gate:approve` on the current non-draft head
- **THEN** automation records an approving review for that head and removes the label

#### Scenario: A non-maintainer adds the approve label

- **WHEN** an account without maintain or admin permission adds `gate:approve`
- **THEN** automation does not record an approval

### Requirement: Label-based revoke

A current human maintainer or admin SHALL be able to add the label `gate:revoke` to cancel an admitted run and dismiss bot approvals for that head. Automation SHALL remove the label after handling.

#### Scenario: Maintainer revokes an admitted head

- **WHEN** a current maintainer adds `gate:revoke` for the current head
- **THEN** active admitted work for that head is cancelled and bot approvals for that head are dismissed

### Requirement: No comment-text or status-token control plane

Admission, approval, and revoke SHALL NOT depend on matching slash-command regexes in comment bodies or on parsing opaque tokens out of commit status descriptions. Later jobs SHALL re-validate live PR API state and workflow outputs.

#### Scenario: A comment contains /ready or /approve text

- **WHEN** someone comments `/ready` or `/approve` on a PR
- **THEN** the gate does not treat that comment as an admission or approval signal
