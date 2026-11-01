# Spec Delta

## Purpose

Allow the operator to do exactly what an approved batch names, and nothing more.

## ADDED Requirements

### Requirement: Four writes, bound to the batch file

A permission rule MUST allow only these external writes, and only for items in the approved batch file: pushing an exact commit, posting `/ready` or `/approve` on a named PR at a named commit, squash-merging a named PR, and deploying a named commit.

#### Scenario: A push of a listed commit

- **WHEN** the operator pushes a commit that the batch file lists for that branch
- **THEN** the push is allowed

#### Scenario: A push of any other commit

- **WHEN** the operator pushes a commit the file does not list
- **THEN** the push is refused

### Requirement: No other writes

The rule MUST NOT allow force-push, branch deletion outside a merged PR, settings changes, secret access, or comments other than the two commands above.

#### Scenario: A force-push is tried

- **WHEN** a force-push is attempted
- **THEN** it is refused whatever the batch file says

### Requirement: Blocked writes are logged

Every external write that is refused or prompts the operator MUST be logged with the time and the wait, so that the cost of the checks can be measured.

#### Scenario: A write waits for a prompt

- **WHEN** an external write waits for a prompt
- **THEN** the log records when it started and when it was answered
