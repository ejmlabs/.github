# Spec Delta

## Purpose

Deploy reviewed code soon after it merges.

## ADDED Requirements

### Requirement: The reviewed tree is recorded before merge

Before a merge that will deploy, a review MUST cover the exact tree that `main` will hold after the merge, and the tree hash MUST be recorded with the review record.

#### Scenario: A review is recorded

- **WHEN** a review passes on the tree that main would hold
- **THEN** the review record includes that tree hash

### Requirement: Deploy only a matching tree

After the merge, the deploy step MUST compare the `main` tree hash with the recorded one and MUST deploy only on a match. Sibling inputs MUST be at their protected pins.

#### Scenario: The trees match

- **WHEN** the hashes are equal and the batch file names the deploy and the owner has started it
- **THEN** the site deploys from `main` at that commit

#### Scenario: The trees differ

- **WHEN** the hashes differ
- **THEN** nothing deploys and the operator reports why

### Requirement: Deploys are reversible and recorded

Each deploy MUST record the deployed commit, the tree hash, the time, and the previous version.

#### Scenario: A deploy completes

- **WHEN** a deploy finishes
- **THEN** the record lets the previous version be restored

### Requirement: A deploy is started by the owner or by the owner's merge

A deploy MUST start from the owner's merge or from a step the owner starts. A tool or agent MUST NOT start a deploy with the owner's credential.

#### Scenario: A deploy without an owner action

- **WHEN** nothing the owner did started the deploy
- **THEN** it does not run
