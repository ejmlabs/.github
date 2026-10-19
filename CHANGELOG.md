# Changelog

Changes follow [Semantic Versioning](https://semver.org/). Each repository is versioned independently.

## [Unreleased]

### Added

- Shared repository standards, explicit human admission, protected merge gates, two-pass Codex review, and a draft source release pipeline.
- A CLI-only prerequisite hook in the credential-free quality job, with standards checks that reject other local action paths and execution scopes.
- Staged standards support for one exact shared-only missing-model-key acceptance caller. Installation and live verification require separate protected changes.

### Fixed

- Clear inherited GitHub token variables on the Codex action step while preserving trusted admission rechecks.
- Bind the CLI setup allowance to its actual quality step; literal YAML text and comment dashes cannot authorize another local action or hide extra step fields.

## [0.1.0] - 2026-10-18

- Initial development baseline. This entry documents source version metadata; it does not assert a published release or production readiness.
