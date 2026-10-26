# Spec Delta

## Purpose

Make the time spent at each stage a query, not an investigation.

## ADDED Requirements

### Requirement: Record every stage time

For each PR the system MUST record the times of opening, each `/ready`, each review result, each security PASS, `/approve`, merge, and each deploy.

#### Scenario: A PR merges

- **WHEN** a PR merges
- **THEN** all its stage times are available in one record

### Requirement: Publish a daily table

A daily table MUST show, for PRs merged that day, the median and 90th percentile time from first `/ready` to merge, the count of repeat `/ready` comments, and the waiting time by cause.

#### Scenario: A day ends

- **WHEN** the day ends
- **THEN** the table is published with the counts above

### Requirement: Name the cause of each wait

Each wait longer than five minutes MUST be tagged with one cause from a fixed list: gate result, gate or pin rework, head drift, serial hold, security label, or maintainer.

#### Scenario: A wait is tagged

- **WHEN** a PR waits more than five minutes
- **THEN** the record carries one cause
