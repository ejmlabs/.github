# Spec Delta

## Purpose

Deploy reviewed code soon after it merges.

## ADDED Requirements

### Requirement: The reviewed tree is recorded before merge

Before a merge that will deploy, the security review MUST cover the exact tree that `main` will hold after the merge, and the tree hash MUST be recorded with the PASS.

#### Scenario: A PASS is recorded

- **WHEN** a security review passes on the tree that main would hold
- **THEN** the PASS record includes that tree hash

### Requirement: Deploy only a matching tree

After the merge, the deploy step MUST compare the `main` tree hash with the recorded one and MUST deploy only on a match. Sibling inputs MUST be at their protected pins.

#### Scenario: The trees match

- **WHEN** the hashes are equal and the batch OK names the deploy
- **THEN** the site deploys from `main` at that commit

#### Scenario: The trees differ

- **WHEN** the hashes differ
- **THEN** nothing deploys and the operator reports why

### Requirement: Deploys are reversible and recorded

Each deploy MUST record the deployed commit, the tree hash, the time, and the previous version.

#### Scenario: A deploy completes

- **WHEN** a deploy finishes
- **THEN** the record lets the previous version be restored
