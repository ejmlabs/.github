## ADDED Requirements

### Requirement: Only the owner's public set may be public
The standards SHALL accept a UI npm package without `private: true` only when it is one of `packages/core`, `packages/ssg`, `packages/tokens` or `packages/ui`, has no `private` key, and has `publishConfig` equal to `{"access": "public", "provenance": true}`.

#### Scenario: Public package with the exact configuration
- **WHEN** one of the four packages has no `private` key and the exact `publishConfig`
- **THEN** the standards pass

#### Scenario: Other packages and the root stay private
- **WHEN** the root or any other UI package is not `private: true`, or a public package sets `"private": false` or a different `publishConfig`
- **THEN** the standards fail

### Requirement: Published tokens exclude brand artwork
The standards SHALL require the published tokens package to list `files`, and SHALL refuse any entry that can reach `assets` outside `assets/fonts`, `assets/brand` and `assets/icons`.

#### Scenario: Broad or indirect asset entries
- **WHEN** a tokens `files` entry is `assets`, `assets/logos`, `./assets`, an asset glob, or a leading glob, or the list is missing
- **THEN** the standards fail

#### Scenario: Allowed folders
- **WHEN** the entries reach assets only through `assets/fonts`, `assets/brand` and `assets/icons`
- **THEN** the standards pass

### Requirement: The publish workflow is accepted only at its reviewed hash
The standards SHALL allow `.github/workflows/publish.yml` only in the `ejm-ui` profile, as a regular file whose SHA-256 equals the recorded reviewed hash.

#### Scenario: Changed, misplaced or linked workflow
- **WHEN** the file has any other content, appears in another repository, or is a symlink
- **THEN** the standards fail
