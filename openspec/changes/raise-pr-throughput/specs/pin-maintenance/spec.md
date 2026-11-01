# Spec Delta

## Purpose

Keep the pins to the shared workflows current without hand work.

## ADDED Requirements

### Requirement: A pin-only PR opens when the shared workflows move

When the shared workflow repository's default branch moves to a new commit, a job MUST open one pin-only pull request per consumer repository. Each PR MUST change only the pins and the values derived from them.

#### Scenario: The shared repository merges a change

- **WHEN** a change merges to the shared repository's default branch
- **THEN** each consumer repository gets one pin-only PR for the new commit

### Requirement: The pin diff is checked against the generator

The diff of each pin PR MUST equal the generator output for the new commit. Any other change MUST fail the check.

#### Scenario: A pin PR carries an extra change

- **WHEN** the diff contains a line the generator did not produce
- **THEN** the check fails and the PR is not offered for a batch OK

### Requirement: The pinned commit is retained

The pinned commit MUST stay reachable through a retained ref in the shared repository.

#### Scenario: A pin names a commit with no retained ref

- **WHEN** the retained ref for the pinned commit does not exist
- **THEN** the pin job fails and opens no PR

### Requirement: A pin PR is a normal PR

A pin PR MUST pass the gate, a fresh security review and the maintainer's explicit approval like any other change. It MUST NOT be admin-merged unless it repairs reviewer infrastructure.

#### Scenario: A pin PR passes the gate

- **WHEN** the gate passes and the security review passes on the exact head
- **THEN** it waits for the maintainer's OK, alone or in a batch
