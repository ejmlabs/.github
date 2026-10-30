## ADDED Requirements

### Requirement: Generated workflows fit GitHub limits
The generator SHALL reject workflows and steps exceeding its bounded budgets before writing generated files, with margin below GitHub's published file and run-step limits.

#### Scenario: Oversized step
- **WHEN** a trusted generated step exceeds the permitted run budget
- **THEN** its payload is split into bounded static step-local values or generation fails before writing

### Requirement: Embedded source remains trusted
The generated command SHALL decode static step-local payloads and SHALL retain source expressions as literal data.

#### Scenario: Missing or invalid payload
- **WHEN** a split payload chunk is missing or invalid
- **THEN** the command fails without executing the payload
