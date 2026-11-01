# ui-publish Specification

## Purpose

Which UI packages may be public, what they may ship, and which publish workflow is accepted.

## Requirements

### Requirement: Only the owner's public set may be public

The standards SHALL accept a UI npm package without `private: true` only when it is one of `packages/core`, `packages/ssg`, `packages/tokens` or `packages/ui`, has no `private` key, and has `publishConfig` equal to `{"access": "public", "provenance": true}`.

#### Scenario: Other packages and the root stay private

- **WHEN** the root or any other UI package is not `private: true`, or a public package sets `"private": false` or a different `publishConfig`
- **THEN** the standards fail

### Requirement: Public packages are checked by structure

A public package's `name` SHALL equal `@ejm/<directory>`. It SHALL declare no pack, publish or install lifecycle script, no bundled dependencies and no workspaces, and its `files`, `main`, `browser`, `bin`, `man` and `directories` SHALL stay inside the reviewed prefixes for that package. The tokens package SHALL reach `assets` only through `assets/fonts`, `assets/brand` and `assets/icons`. Packages SHALL be found by globbing, and fields outside this list MAY change without a shared revision.

#### Scenario: A file outside the reviewed prefixes

- **WHEN** a public package's `files` entry points outside its reviewed prefixes
- **THEN** the standards fail

### Requirement: The publish workflow is accepted only at its reviewed hash

The standards SHALL allow `.github/workflows/publish.yml` only in the `ejm-ui` profile, as a regular file whose SHA-256 equals the recorded reviewed hash, and SHALL print the actual digest when it differs.

#### Scenario: Changed, misplaced or linked workflow

- **WHEN** the file has other content, appears in another repository, or is a symlink
- **THEN** the standards fail
