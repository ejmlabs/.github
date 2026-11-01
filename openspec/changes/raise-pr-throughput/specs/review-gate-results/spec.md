# Spec Delta

## Purpose

Stop known false results from blocking a change, and give the security label one clear path.

## ADDED Requirements

### Requirement: Known benign changes do not block

The gate MUST NOT report a blocking result for a change that only moves a full-hash pin, edits a lockfile that mirrors its manifest, or adds an allowed binary asset. Fixtures for each case MUST run in the test suite.

#### Scenario: A pins-only change

- **WHEN** a PR changes only full-hash workflow pins and the value derived from them
- **THEN** the gate result is not blocked for missing context

#### Scenario: A lockfile-only change

- **WHEN** a PR changes a lockfile that mirrors a manifest change
- **THEN** the gate result is not blocked as incomplete

### Requirement: The security label has one clear path

A security label that blocks merge MUST be cleared only by the maintainer or by the operator inside a batch OK. A record MUST state who cleared it, when, and which security review covered the same head.

#### Scenario: The label is cleared in a batch

- **WHEN** the operator clears the label under a batch OK
- **THEN** the record names the PASS for that exact head

#### Scenario: No PASS covers the head

- **WHEN** no security review passed on the exact head
- **THEN** the label stays

### Requirement: The caller form can clear the label

The consumer workflow form MUST include the event that lets a label removal re-run the gate, so that a cleared label updates the gate result without a new commit.

#### Scenario: The label is removed

- **WHEN** the label is removed from a PR
- **THEN** the gate result updates without a new commit
