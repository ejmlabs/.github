# Spec Delta

## Purpose

Keep the pins to the shared workflows current without hand work.

## ADDED Requirements

### Requirement: A pin-only PR opens when the shared workflows move

When the shared workflow repository's default branch moves to a new commit, a job MUST open one pin-only pull request per consumer repository, as the operator identity. Each PR MUST change only the pins and the values derived from them.

#### Scenario: The shared repository merges a change

- **WHEN** a change merges to the shared repository's default branch
- **THEN** each consumer repository gets one pin-only PR for the new commit

### Requirement: The pin diff is checked against the generator

The diff of each pin PR MUST equal the generator output for the new commit. Any other change MUST fail the check.

#### Scenario: A pin PR carries an extra change

- **WHEN** the diff contains a line the generator did not produce
- **THEN** the check fails and the PR is not offered in a batch file

### Requirement: The pinned commit is retained

The pinned commit MUST stay reachable through a retained ref in the shared repository.

#### Scenario: A pin names a commit with no retained ref

- **WHEN** the retained ref for the pinned commit does not exist
- **THEN** the pin job fails and opens no PR

### Requirement: A pin PR is a normal PR

A pin PR MUST pass the gate, a fresh review and the owner's explicit approval on GitHub like any other change. It MUST NOT be admin-merged or overridden, including when it repairs reviewer infrastructure. A repair of reviewer infrastructure MUST follow the validator-first sequence or the separate infrastructure ruleset defined in the operations guide.

#### Scenario: A pin PR passes the gate

- **WHEN** the gate passes and a review passes on the exact head
- **THEN** it waits for the owner's approval on GitHub, alone or in a batch

### Requirement: The pin job cannot approve or merge

The pin job MUST NOT hold a credential that approves, merges or clears a label. If it needs to push workflow files, it MUST use a separate short-lived credential created by the owner for that purpose, or the owner MUST push the branch.

#### Scenario: The pin job needs to change a workflow file

- **WHEN** a pin PR changes files under `.github/workflows/`
- **THEN** the push uses the owner-created short-lived credential or the owner's own push, and never the owner's login
