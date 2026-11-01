# no-size-caps Specification

## Purpose

The shared gate and standards do not cap download size, dependency count or PR size.

## Requirements

### Requirement: No download-size, dependency-count or admission-size caps

The shared Quality gate and standards SHALL NOT cap bundle bytes, download size or dependency count for any profile, and admission SHALL NOT cap a PR's files or lines. Runtime safety bounds and every security rule SHALL remain.

#### Scenario: ejm-ui gate

- **WHEN** the `ejm-ui` Quality gate runs
- **THEN** it runs no shared size or budget command; the commands it runs belong to each product

#### Scenario: Safety bounds remain

- **WHEN** a job time limit, source-tree bound or standards input limit is reached
- **THEN** it still applies
