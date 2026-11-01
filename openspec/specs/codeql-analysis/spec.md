# CodeQL analysis specification

## Purpose

Provide a reusable CodeQL scan and scan this repository's Python and Actions code.

## Requirements

### Requirement: Shared CodeQL analysis

The generated reusable workflow SHALL accept a string languages input defaulting to `javascript-typescript`, run the security-extended queries and pin its actions to full commit SHAs. Its analysis job SHALL grant only `contents: read` and `security-events: write`.

#### Scenario: A caller selects languages

- **WHEN** a caller passes supported languages
- **THEN** CodeQL initializes for those languages, builds where needed and uploads the analysis

### Requirement: Scan the shared standards repository

The generated local caller SHALL scan Python and Actions on pushes to main and on a weekly schedule. The standards check SHALL accept this caller only in the shared standards repository and only with its exact reviewed content.

#### Scenario: Caller permissions are changed

- **WHEN** the local caller differs from the reviewed content
- **THEN** the standards check rejects it
