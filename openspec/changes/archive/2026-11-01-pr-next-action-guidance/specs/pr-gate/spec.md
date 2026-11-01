## ADDED Requirements

### Requirement: Advisory next-action guidance

The governance workflow SHALL render deterministic next-action guidance from live PR metadata and the two required statuses for same-repository PRs. It SHALL preserve author text outside its marked section and SHALL NOT grant admission or approval. It SHALL refresh after admission and after check finalization, without executing PR code.

#### Scenario: A PR head has passed the required statuses

- **WHEN** the current head has passed Quality and Repository standards
- **THEN** the guidance directs the reader to review and check other configured results before merging

#### Scenario: A description has malformed guidance markers

- **WHEN** the markers are duplicated or incomplete
- **THEN** the renderer fails without rewriting the description
