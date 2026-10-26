# Spec Delta

## Purpose

Stop false results from blocking a change, never let a class of change skip review, and keep any security concern under human control.

## ADDED Requirements

### Requirement: Pins-only, lockfile and binary changes pass a deterministic check and are still reviewed

A lockfile change MUST pass the lockfile check and a binary asset MUST pass the allowlist check. Such a change MUST NOT skip review: the check result MUST be attached to the review, and a failed check MUST block. Fixtures for each case MUST run in the test suite.

#### Scenario: A pins-only change

- **WHEN** a PR changes only full-hash workflow pins and the value derived from them, and the diff equals the generator output
- **THEN** the pin check passes, and the change still needs review and approval

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

### Requirement: The gate has no security label

The gate MUST NOT add, require, enforce or accept a security label, a label override, or a caller trigger on label removal. A security concern raised by a human reviewer MUST be handled as an ordinary review comment that only a human resolves, and a bot, the operator identity or an automated reviewer MUST NOT resolve it.

#### Scenario: A human reviewer raises a concern

- **WHEN** a human reviewer reports a security concern on a PR
- **THEN** the owner resolves it on GitHub before approving, and no automated actor can resolve it

### Requirement: Re-enabling a model review needs a security review first

An automated model review MUST NOT be turned back on as a required check or as a source of any label until a security review of that change has been done and recorded. Turning it on MUST NOT let any automated pass clear a block: only a human with maintain or admin rights clears one.

#### Scenario: A model review is proposed

- **WHEN** a change would re-enable a model review
- **THEN** it is not merged until the security review is recorded
