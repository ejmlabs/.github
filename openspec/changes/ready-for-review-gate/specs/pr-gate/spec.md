# Spec Delta

## Purpose

Control when paid PR checks run and how a pull request becomes mergeable on protected main, without a SHA comment ritual.

## ADDED Requirements

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

#### Scenario: A maintainer opens a non-draft PR

- **WHEN** a current maintainer or admin opens a same-repository non-draft PR targeting main
- **THEN** the gate admits the head and starts the bounded paid checks

### Requirement: Outsider and fork PRs need a maintainer Ready action

A pull request from a fork, or whose author is not a current maintainer or admin, SHALL be admitted only when a current human maintainer or admin marks that PR Ready for review. The author's own Ready action SHALL NOT admit paid checks.

#### Scenario: An outsider marks their own PR Ready

- **WHEN** a non-maintainer author converts their PR from draft to Ready for review
- **THEN** paid checks do not start

#### Scenario: A maintainer marks an outsider PR Ready

- **WHEN** a current maintainer or admin converts that PR to Ready for review
- **THEN** the gate admits the current head and starts the bounded paid checks

### Requirement: New commits need a fresh admission

An admission SHALL bind to one head SHA. A new commit SHALL require a new admission under the rules above. Converting a PR back to draft SHALL stop further auto-admission until it is Ready again under those rules.

#### Scenario: A new commit lands after admission

- **WHEN** the PR head changes after an admission
- **THEN** the previous admission does not authorize checks for the new head

### Requirement: Required merge checks are Quality and Repository standards

Protected main SHALL require **Quality** and **Repository standards** and SHALL NOT require **Human readiness** or **Maintainer approval** statuses. GitHub's required approving review count SHALL remain enforced for administrators too.

#### Scenario: Checks on a mergeable head

- **WHEN** a maintainer merges to main
- **THEN** Quality and Repository standards must be successful for that head, and at least one current approving GitHub review must apply to that head

### Requirement: One-click maintainer self-approve

A current human maintainer or admin SHALL be able to approve the current head of a same-repository non-draft PR by posting `/approve` or `/approve FULL_SHA`. Trusted automation SHALL record a GitHub approval for that head so a solo maintainer can satisfy the required review. Agents SHALL post this only when the maintainer explicitly asks.

#### Scenario: Solo maintainer self-approves

- **WHEN** a current maintainer posts `/approve` for the current head after review
- **THEN** automation records an approving review for that head and the required review gate can pass

#### Scenario: An agent posts approve without being asked

- **WHEN** an agent would admit or approve on its own initiative
- **THEN** it does not post Ready, `/approve`, or `/revoke`

### Requirement: Maintainer revoke

A current human maintainer or admin SHALL be able to post `/revoke` or `/revoke FULL_SHA` to cancel an admitted run and fail merge authorization for that head until a fresh admission.

#### Scenario: Maintainer revokes an admitted head

- **WHEN** a current maintainer posts `/revoke` for the admitted head
- **THEN** active admitted work for that head is cancelled and that head is not mergeable under a stale admission

## REMOVED Requirements

### Requirement: SHA-bound /ready comment admission

**Reason**: Replaced by Ready-for-review and maintainer auto-admission.
**Migration**: Callers and docs stop instructing `/ready FULL_SHA` for ordinary admission.

### Requirement: Required Human readiness and Maintainer approval statuses

**Reason**: Admission is expressed by draft/Ready plus who triggered it; merge approval uses GitHub reviews plus optional `/approve`.
**Migration**: Branch protection drops those two contexts before or as callers adopt the new gate.
