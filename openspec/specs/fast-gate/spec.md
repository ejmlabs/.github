# fast-gate Specification

## Purpose

The shared gate starts every platform at once, installs prebuilt audit tools and reuses main's trusted dependency builds.

## Requirements

### Requirement: The gate never waits on its own configuration

Quality SHALL start every matrix entry at once, SHALL let Cargo use every runner core, and SHALL install `cargo-deny` and `cargo-machete` from prebuilt archives whose SHA-256 matches a reviewed pin.

#### Scenario: Changed archive

- **WHEN** a tool archive's digest differs from its pin
- **THEN** installation fails before the binary is written

### Requirement: Only reviewed main writes gate caches

Gate build caches SHALL be saved only by `warm-cache.yml` on a push to main, and only when the exact key is missing and the build passed. Gate jobs SHALL only restore, and SHALL never save. Keys SHALL hold the toolchain, the runner OS and a hash of the profile's `Cargo.lock`; a restore MAY fall back to the newest entry with the same toolchain and OS prefix. GitHub scopes a pull request run's cache to that PR's merge ref, so PR code cannot write what main or another PR restores.

#### Scenario: Exact hit

- **WHEN** the entry for the lockfile exists
- **THEN** the gate restores it, and Cargo rebuilds every local crate from the admitted source

#### Scenario: Warm entry already exists

- **WHEN** main's warm job finds its exact key
- **THEN** it skips the build and saves nothing
