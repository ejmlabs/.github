## REMOVED Requirements

### Requirement: AI review status
**Reason**: The owner turned off the AI PR reviewer.
**Migration**: Repositories stop requiring "AI review" before the gate stops publishing it.

## ADDED Requirements

### Requirement: Four required statuses
The PR gate SHALL publish exactly four required statuses: Human readiness, Maintainer approval, Quality and Repository standards, and SHALL NOT run a model review or pass a model key.

#### Scenario: A PR is admitted
- **WHEN** a maintainer admits a PR with /ready
- **THEN** the gate publishes the four statuses and no "AI review" status
- **AND** no job receives a model key

#### Scenario: Required checks match the gate
- **WHEN** the change is rolled out
- **THEN** no repository requires a status the gate does not publish at any step

### Requirement: No administrator bypass and gated re-enablement
The four required statuses SHALL be enforced for administrators too, and re-enabling any model review SHALL need the security review's sign-off first.

#### Scenario: An administrator merges
- **WHEN** an administrator opens a PR to main
- **THEN** the same four statuses are required with no bypass

#### Scenario: A model review is proposed again
- **WHEN** a change adds a model review as a status, a label or a comment
- **THEN** it does not merge without the security review's sign-off
