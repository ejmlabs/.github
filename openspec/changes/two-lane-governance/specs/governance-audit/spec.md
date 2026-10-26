## ADDED Requirements

### Requirement: Every governance decision is recorded

The service SHALL write one record per decision, including lane changes, quarantine, restore, ship, unship, security approval, waiver, adoption, spam close, appeal, budget, pause, unavailable outcome, retry and merge. Each record SHALL hold time, repo, PR, generation, head, base, lane, actor id and type, decision, reason code, run id and policy version. Records MUST NOT hold comment bodies, model output or secrets.

#### Scenario: Ship is recorded

- **WHEN** the owner's ship is accepted
- **THEN** a record with decision `ship`, the owner's id, the head and the generation is written

#### Scenario: Free-text reason

- **WHEN** a downgrade reason contains free text
- **THEN** the record stores only a reason code, and the text stays in the PR comment

### Requirement: Revocations never wait for the audit store

Revocations (unship, dismissal, downgrade, quarantine, edits or deletions, pause) SHALL take effect even when the audit write fails. Their records SHALL be queued durably in the same transaction as the revocation and retried until stored. While records are queued, new authorizations, restores, adoptions and merges MUST be refused.

#### Scenario: Audit store down during unship

- **WHEN** the owner unships while the audit store is unavailable
- **THEN** the ship is void at once, the record is queued, and later ship attempts are refused until the queue drains

#### Scenario: Audit store down during ship

- **WHEN** a ship arrives while audit records are queued
- **THEN** the ship is refused with "audit unavailable, retry"

### Requirement: Audit records are durable and access-controlled

Audit records SHALL be appended to the service's append-only store, and ordinary deletion SHALL be refused for every actor. Read access SHALL be limited to the owner, the security lead and the Board. A public privacy note SHALL say what is recorded, who reads it, how long it is kept, and how contributors can request their own records. A private mirror MAY be added.

#### Scenario: Attempt to rewrite history

- **WHEN** any actor tries to change or delete an existing audit record
- **THEN** the store refuses it

#### Scenario: Community record expires

- **WHEN** a community contributor's record is 12 months old and tied to no open security case
- **THEN** it is deleted by the authorized retention operation (including mirrors and backups), and the deletion is itself recorded without the personal data

### Requirement: Audit records expire only through the retention operation

Maintainer decision records SHALL be retained 2 years; community-contributor records 12 months, unless under an open security case or a recorded legal or security hold. Expiry SHALL be a separate, narrowly authorized retention operation run only by the service, covering the store, mirrors and backups, and leaving a deletion record without personal data.

#### Scenario: Record under a hold

- **WHEN** a community record reaches 12 months while under a recorded security hold
- **THEN** the retention operation keeps it until the hold is lifted

### Requirement: Anomalies are reported to the security lead

A weekly job SHALL report decision counts and list quarantines, waivers, held findings, self-ships, refused commands from untrusted or agent identities, budget hits and pauses to the security lead. Each quarter, aggregate counts of waivers, quarantines, held findings and spam closes SHALL be published.

#### Scenario: Weekly report with a waiver

- **WHEN** the owner used a waiver during the week
- **THEN** the report lists it with its PR, head and follow-up issue state
