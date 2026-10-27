## ADDED Requirements

### Requirement: Only the owner's public set may be public
The standards SHALL accept a UI npm package without `private: true` only when it is one of `packages/core`, `packages/ssg`, `packages/tokens` or `packages/ui`, has no `private` key, and has `publishConfig` equal to `{"access": "public", "provenance": true}` with `provenance` exactly boolean `true`.

#### Scenario: Public package with the exact configuration
- **WHEN** one of the four packages has no `private` key and the exact `publishConfig`
- **THEN** the standards pass

#### Scenario: Other packages and the root stay private
- **WHEN** the root or any other UI package is not `private: true`, or a public package sets `"private": false` or a different `publishConfig`
- **THEN** the standards fail

### Requirement: Public packages ship exactly the reviewed files
The standards SHALL require each public UI package's name, every manifest field that decides what npm packs, and its pack, publish and install lifecycle scripts to equal the reviewed values exactly, and SHALL treat a field or script absent from the reviewed manifest as forbidden. The reviewed tokens `files` SHALL keep brand logos and artwork out of the tarball.

#### Scenario: Any deviation in a packing field
- **WHEN** one of those fields is added, removed, reordered or changed in any way, including any of the lifecycle scripts `preprepare`, `prepare`, `postprepare`, `prepack`, `postpack`, `prepublish`, `prepublishOnly`, `publish`, `postpublish`, `preinstall`, `install` or `postinstall`, a case variant, a `directories` entry, an extra `files` entry or a re-including `!!` entry
- **THEN** the standards fail

#### Scenario: Reviewed manifest
- **WHEN** the four public packages carry the reviewed values for those fields
- **THEN** the standards pass

### Requirement: The publish workflow is accepted only at its reviewed hash
The standards SHALL allow `.github/workflows/publish.yml` only in the `ejm-ui` profile, as a regular file whose SHA-256 equals the recorded reviewed hash.

#### Scenario: Changed, misplaced or linked workflow
- **WHEN** the file has any other content, appears in another repository, or is a symlink
- **THEN** the standards fail
