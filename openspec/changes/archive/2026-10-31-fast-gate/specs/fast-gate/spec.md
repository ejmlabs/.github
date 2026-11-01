## ADDED Requirements

### Requirement: The gate never waits on its own configuration
Quality SHALL start every matrix entry at once, SHALL let Cargo use every runner core, and SHALL install `cargo-deny` and `cargo-machete` from prebuilt archives whose SHA-256 matches a reviewed pin.

#### Scenario: Harness gate
- **WHEN** an admitted harness PR runs Quality
- **THEN** Linux, macOS and Windows start together and no audit tool is compiled

#### Scenario: Changed archive
- **WHEN** a tool archive's digest differs from its pin
- **THEN** installation fails before the binary is written

### Requirement: Only reviewed main writes gate caches
Gate build caches SHALL be written only by `warm-cache.yml` on a push to main, and the gate SHALL restore only the exact entry for the admitted base commit.

#### Scenario: Exact hit
- **WHEN** the entry for the admitted base exists
- **THEN** the gate restores it and Cargo rebuilds every local crate from the admitted source

#### Scenario: Any other entry
- **WHEN** the restore misses or matches only a prefix
- **THEN** the gate deletes the restored directories and builds from scratch
