# Spec Delta

## Purpose

Give the operator exactly the rights it needs to prepare work, and none of the rights that ship it.

## ADDED Requirements

### Requirement: The operator has its own narrow identity

The operator MUST act only as its own GitHub App or machine user, never as the owner and never with the owner's credential or token. Its rights MUST be limited to pushing branches and opening or updating pull requests in the listed repositories. It MUST NOT hold rights to approve, merge, change settings, read secrets or push workflow files.

#### Scenario: The operator pushes a branch

- **WHEN** the operator pushes a branch of a listed commit to a listed repository
- **THEN** the push is allowed and the push and the pull request show the operator identity

#### Scenario: The operator pushes any other commit

- **WHEN** the operator pushes a commit that the batch file or task does not list
- **THEN** the push is refused

### Requirement: Shipping steps stay with the human

`/ready`, `/approve`, merge and the resolution of a security concern MUST be actions by the owner's own account on GitHub. The operator MUST NOT post, call or script any of them, and the gate MUST refuse such a command from a bot sender or from a user without maintain rights.

#### Scenario: The operator posts an approval command

- **WHEN** the operator identity posts `/approve` or `/ready`
- **THEN** the gate refuses it and no state changes

#### Scenario: The operator tries to merge

- **WHEN** the operator identity attempts to merge
- **THEN** the merge is refused, because only the owner may push or merge to `main` and the restriction has no bypass actors

### Requirement: No other writes

The operator MUST NOT force-push, delete branches outside a merged PR, change settings, access secrets, or comment commands the gate treats as owner commands.

#### Scenario: A force-push is tried

- **WHEN** a force-push is attempted
- **THEN** it is refused whatever any file says

### Requirement: Blocked writes are logged

Every external write that is refused or prompts the operator MUST be logged with the time and the wait, so that the cost of the checks can be measured.

#### Scenario: A write waits for a prompt

- **WHEN** an external write waits for a prompt
- **THEN** the log records when it started and when it was answered
