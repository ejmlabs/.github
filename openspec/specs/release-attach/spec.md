# release-attach Specification

## Purpose

How draft releases are bound to protected main and how built release files are verified and attached to a draft.

## Requirements

### Requirement: Drafts come from main and the commit's own pin

A draft release SHALL accept the main head or any earlier commit on main, and `standards-ref` SHALL equal every shared workflow pin in that commit's own `release.yml`. An approval SHALL count only as a reviewer's latest decision on the merged head. Release SHALL run only on its first attempt.

#### Scenario: Commit off main

- **WHEN** the commit is not on main
- **THEN** the release fails before any draft or tag exists

### Requirement: A draft is created without a tag

The draft release SHALL target the release commit and SHALL NOT write a tag ref, so GitHub creates the `v<version>` tag only when a human publishes the draft. The release SHALL refuse a version that already has a tag, a published release or a draft.

#### Scenario: A failed run

- **WHEN** a release run fails after it created the draft
- **THEN** no tag exists, and the draft blocks a second release of that version until the owner removes it

#### Scenario: A draft already exists

- **WHEN** a draft or published release already exists for the version
- **THEN** the release fails before it creates anything

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

The attach job SHALL hold the write token, run no project code, and modify only the one draft release whose `tag_name` is `v<version>` and whose `target_commitish` is the release commit, while no tag exists. It SHALL read the draft again right before the first upload and SHALL NOT replace an existing asset. It SHALL hold neither `id-token` nor `attestations`.

#### Scenario: Published or mismatched release

- **WHEN** the release is not a draft, targets another commit, has a twin for the tag, or a tag already exists, or the draft changed during the checks
- **THEN** the job fails and attaches nothing

### Requirement: Attestation is a separate job

An optional attestation SHALL run in its own job that needs the attach job, holds only `id-token`, `attestations`, `actions: read` and `contents: read`, downloads the same `release-files` artifact and recomputes every digest. It SHALL attest only when each digest equals the digest the attach job attached. It SHALL cover the attached files and SHALL NOT be described as code signing.

#### Scenario: A file differs from the attached one

- **WHEN** a recomputed digest differs from the attach job's, or the file set differs
- **THEN** the job fails before it attests

#### Scenario: No attestation requested

- **WHEN** `attest` is false
- **THEN** the attestation job does not run, and no job holds an OIDC or attestation permission

### Requirement: Native products use one canonical release flow

A repository that opts in with a `build.yml` SHALL use the canonical native `release.yml` (verify, Draft release, attach, one pin) and a `build.yml` that passes the stricter build lint.

#### Scenario: Mismatched pair

- **WHEN** a repository has `build.yml` with the plain `release.yml`, or the native one without `build.yml`
- **THEN** the repository standards check fails
