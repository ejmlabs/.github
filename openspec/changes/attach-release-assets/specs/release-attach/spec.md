## ADDED Requirements

### Requirement: Build runs are bound to the release commit
The shared workflows SHALL accept build output only from a completed, successful run of the named build workflow, triggered by `workflow_dispatch` or a push on main in the same repository, whose `head_sha` equals the release commit.

#### Scenario: Wrong commit
- **WHEN** the run's `head_sha` differs from the release commit
- **THEN** the gate and the attach job fail before any file is downloaded or attached

#### Scenario: Wrong workflow or trigger
- **WHEN** the run belongs to another workflow file, another branch, or an event other than `workflow_dispatch` or `push`
- **THEN** the gate and the attach job fail

### Requirement: Digests are recomputed
The attach job SHALL recompute the SHA-256 of every downloaded file and compare it to the build manifest.

#### Scenario: Changed digest
- **WHEN** a file differs from its manifest digest, or the file set differs from the manifest
- **THEN** the job fails and attaches nothing

### Requirement: Attach changes only a matching draft
The attach job SHALL hold the write token, check out and run no project code, and modify only a draft release whose `v<version>` tag is a lightweight ref to the release commit.

#### Scenario: Published or mismatched release
- **WHEN** the release is not a draft, or the tag points elsewhere
- **THEN** the job fails and attaches nothing
