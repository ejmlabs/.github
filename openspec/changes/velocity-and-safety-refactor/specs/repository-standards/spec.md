## ADDED Requirements

### Requirement: Callers equal the canonical text

`pr.yml` and `release.yml` SHALL equal the canonical callers except for the pin, and every caller SHALL be on the same 40-hex pin. `cache.yml` (`ejm-cli`, `ejm-harness`, `ejm-ide`, `ejm-ui`), `deploy.yml` (any site, with or without `secrets: inherit`) and `build.yml` MAY exist where the profile allows. `publish.yml` SHALL exist only in `ejm-ui`, at its reviewed SHA-256.

#### Scenario: A caller differs

- **WHEN** a caller differs from the canonical text beyond the pin
- **THEN** the check reports it with a bounded diff

### Requirement: Other workflows are credential-free

Any other workflow SHALL use only the triggers `push`, `pull_request`, `workflow_dispatch`, `schedule` and `merge_group`, top-level `permissions` of exactly `contents: read` or `{}`, no job-level `permissions`, `environment` or `secrets`, no expression that reads `secrets` or the GitHub token, no `persist-credentials: true`, and `uses` pinned to a full SHA or a local `./.github/actions/...` path. It SHALL use a restricted YAML subset with no anchors, aliases, tags, flow mappings, quoted keys or duplicate keys.

#### Scenario: A workflow reads a secret

- **WHEN** a workflow expression references `secrets`
- **THEN** the check fails

### Requirement: Build workflows are stricter

`build.yml` SHALL run only on `workflow_dispatch` and pushes to main, set `contents: read`, upload exactly one `release-files` artifact and use no local action.

#### Scenario: A build with a local action

- **WHEN** `build.yml` uses a local action
- **THEN** the check fails

### Requirement: Community files exist

README, CONTRIBUTING, SECURITY, SUPPORT, CODE_OF_CONDUCT, RELEASING, THIRD_PARTY_NOTICES, CHANGELOG and LICENSE SHALL exist and be non-empty, with no em dash and, in Markdown files, resolving relative links. The check SHALL NOT compare them byte for byte or require README headings.

#### Scenario: A missing document

- **WHEN** one of the nine documents is missing or empty
- **THEN** the check fails

### Requirement: Public UI packages are checked by structure

Public `ejm-ui` packages SHALL satisfy the structural rules in `ui-publish`, and the check SHALL report every problem in one run.

#### Scenario: Two problems at once

- **WHEN** a tree has a missing document and a broken caller
- **THEN** one run reports both
