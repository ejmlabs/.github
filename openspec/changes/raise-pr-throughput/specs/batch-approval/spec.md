# Spec Delta

## Purpose

Let one explicit maintainer OK cover a named set of changes, without weakening review.

## ADDED Requirements

### Requirement: A batch OK names exact items

A batch OK MUST list each pull request URL and its exact head commit, and the deploy target if any. The OK MUST come from the maintainer in an explicit message. The operator MUST NOT act on any item the OK does not name.

#### Scenario: An item is not named

- **WHEN** a pull request is ready but absent from the batch OK
- **THEN** the operator takes no admission, approval or merge step for it

### Requirement: Each item needs a fresh security PASS

An item MUST NOT be admitted, approved or merged unless an independent security review passed on the exact commit that would ship. A PASS for any other commit MUST NOT count.

#### Scenario: The head differs from the reviewed commit

- **WHEN** the pull request head differs from the commit named in the PASS
- **THEN** the item leaves the batch and the operator reports why

### Requirement: A moved head ends the OK for that item

If a pull request head changes after the OK, the OK MUST stop covering that item. The only exception is the carry-over rule: only the base branch moved, the pull request's own patch is identical, and a fresh security review passes on the new exact tree.

#### Scenario: Only the base branch moved

- **WHEN** a merge of the base branch leaves the patch id unchanged and a fresh review passes on the new tree
- **THEN** the OK still covers the item

#### Scenario: The patch changed

- **WHEN** the patch id differs from the reviewed one
- **THEN** the item leaves the batch and needs a new OK

### Requirement: Rules that never change

Every batch MUST keep these rules: no force-push, admin merges only for reviewer infrastructure, and the maintainer's explicit approval for the exact items.

#### Scenario: A batch includes a non-infrastructure PR that fails the gate

- **WHEN** the gate blocks an item that is not reviewer infrastructure
- **THEN** the operator does not admin-merge it and reports the block

### Requirement: An optional standing OK for a named class

If the maintainer grants a standing OK, it MUST be written in the operations guide with an exact class. Items outside the class MUST use a batch OK. A security PASS on the exact commit MUST still be required.

#### Scenario: A change outside the class

- **WHEN** a pull request does not match the written class
- **THEN** it waits for a batch OK
