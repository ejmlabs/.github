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

### Requirement: Native products use one canonical release flow
A repository that opts in with a `build.yml` SHALL use the canonical native `release.yml`, whose jobs run verify, Draft release and attach in that order on one pin and one commit input, and a `build.yml` that runs only on `workflow_dispatch` and pushes to main with read-only permissions, no secrets and pinned actions.

#### Scenario: Mismatched pair
- **WHEN** a repository has `build.yml` with the plain `release.yml`, or the native `release.yml` without `build.yml`
- **THEN** the repository standards check fails

#### Scenario: Build with write access
- **WHEN** `build.yml` requests a write permission, a secret or a mutable action reference
- **THEN** the repository standards check fails

### Requirement: One combined manifest
The build run SHALL upload one artifact named `release-files` holding the release files and one `build-sha256.txt`.

#### Scenario: Missing artifact
- **WHEN** the run has no unexpired `release-files` artifact
- **THEN** the gate fails before the tag exists
