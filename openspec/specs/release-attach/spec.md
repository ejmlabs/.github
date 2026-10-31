# release-attach Specification

## Purpose

How draft releases are bound to protected main and how built release files are verified and attached to a draft.

## Requirements

### Requirement: Drafts come from main and the commit's own pin

A draft release SHALL accept the main head or any earlier commit on main, and `standards-ref` SHALL equal every shared workflow pin in that commit's own `release.yml`. An approval SHALL count only as a reviewer's latest decision on the merged head. Release SHALL run only on its first attempt.

#### Scenario: Commit off main

- **WHEN** the commit is not on main
- **THEN** the release fails before any tag exists

### Requirement: Build runs are bound to the release commit

The shared workflows SHALL accept build output only from a completed, successful run of the named build workflow, triggered by `workflow_dispatch` or a push on main in the same repository, whose `head_sha` equals the release commit.

#### Scenario: Wrong commit, workflow or trigger

- **WHEN** the run's `head_sha` differs, or it belongs to another workflow, branch or event
- **THEN** the gate and the attach job fail before any file is downloaded or attached

### Requirement: Digests are recomputed

The attach job SHALL recompute the SHA-256 of every downloaded file and compare it to the single `build-sha256.txt` in the one `release-files` artifact.

#### Scenario: Changed digest

- **WHEN** a file differs from its manifest digest, or the file set differs from the manifest
- **THEN** the job fails and attaches nothing

### Requirement: Attach changes only a matching draft

The attach job SHALL hold the write token, run no project code, and modify only a draft release whose `v<version>` tag is a lightweight ref to the release commit. An optional attestation SHALL cover the attached files and SHALL NOT be described as code signing.

#### Scenario: Published or mismatched release

- **WHEN** the release is not a draft, or the tag points elsewhere
- **THEN** the job fails and attaches nothing

### Requirement: Native products use one canonical release flow

A repository that opts in with a `build.yml` SHALL use the canonical native `release.yml` (verify, Draft release, attach, one pin) and a `build.yml` that passes the stricter build lint.

#### Scenario: Mismatched pair

- **WHEN** a repository has `build.yml` with the plain `release.yml`, or the native one without `build.yml`
- **THEN** the repository standards check fails
