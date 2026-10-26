# Spec Delta

## Purpose

Stop false results from blocking a change, never let a class of change skip review, and keep every security label under human control.

## ADDED Requirements

### Requirement: Benign-looking changes pass a deterministic check and are still reviewed

The gate MUST NOT report a blocking result for a change that only moves a full-hash pin, for a lockfile that passes the lockfile check, or for a binary asset that passes the allowlist check. Such a change MUST NOT skip review: the check result MUST be attached to the review, and a failed check MUST block. Fixtures for each case MUST run in the test suite.

#### Scenario: A pins-only change

- **WHEN** a PR changes only full-hash workflow pins and the value derived from them, and the diff equals the generator output
- **THEN** the gate result is not blocked for missing context, and the change still needs review and approval

#### Scenario: A lockfile that matches its manifest

- **WHEN** regenerating the lockfile from the manifest in the pinned environment gives the same hash as the PR's lockfile
- **THEN** the lockfile check passes and the change goes to review

#### Scenario: A lockfile that does not match

- **WHEN** the regenerated hash differs, or the lockfile adds an entry the manifest does not require
- **THEN** the check fails and the gate blocks

#### Scenario: A listed binary

- **WHEN** a binary asset's path and content hash are on the repository allowlist
- **THEN** the allowlist check passes and the change goes to review

#### Scenario: An unlisted or altered binary

- **WHEN** a binary's path is not listed, or its content hash differs from the listed one
- **THEN** the check fails and the gate blocks

### Requirement: Only a human clears a security label

A security label that blocks merge MUST be cleared only by a human with maintain or admin rights acting on GitHub. A bot sender, the operator identity and any automated reviewer MUST NOT clear it, and the gate MUST NOT accept such a clear. A pass from another reviewer, human or automated, MUST NOT clear the label by itself; the clear is the owner's own action. A record MUST state who cleared it and when, from the GitHub event.

#### Scenario: A human clears the label

- **WHEN** the owner removes the label on GitHub
- **THEN** the record names the owner and the time, and the gate result updates

#### Scenario: An automated actor removes the label

- **WHEN** a bot or the operator identity removes the label
- **THEN** the gate result stays blocked

#### Scenario: Another reviewer passed

- **WHEN** an automated reviewer reports a pass for the exact head and nobody has cleared the label
- **THEN** the label stays

### Requirement: Re-enabling a model review needs a security review first

An automated model review MUST NOT be turned back on as a required check or as a source of any label until a security review of that change has been done and recorded. Turning it on MUST NOT alter the rule that only a human clears a security label.

#### Scenario: A model review is proposed

- **WHEN** a change would re-enable a model review
- **THEN** it is not merged until the security review is recorded

### Requirement: The caller form can re-run the gate on a label clear

The consumer workflow form MUST include the event that lets a label removal by a human re-run the gate, so that a cleared label updates the gate result without a new commit. That event MUST NOT carry secrets.

#### Scenario: The label is removed

- **WHEN** a human removes the label from a PR
- **THEN** the gate result updates without a new commit
