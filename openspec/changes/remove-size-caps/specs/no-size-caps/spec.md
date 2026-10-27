## ADDED Requirements

### Requirement: No download-size or dependency-count caps
The shared Quality gate, standards and review criteria SHALL NOT cap bundle bytes, download size or dependency count for any profile. Runtime and review-tooling safety bounds and every security rule SHALL remain.

#### Scenario: ejm-ui gate
- **WHEN** the `ejm-ui` Quality gate runs
- **THEN** it runs check, build, Rust check and pack proof and no size or budget command

#### Scenario: Safety bounds remain
- **WHEN** admission budgets, review-context byte limits, PR size bounds or standards input limits are reached
- **THEN** they still apply
