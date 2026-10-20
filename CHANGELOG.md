# Changelog

Changes follow [Semantic Versioning](https://semver.org/). Each repository is versioned independently.

## [Unreleased]

### Added

- Govern `ejm-chess` as a public repository profile. Its version source is
  `VERSION`, its contributor guide is `README.md#development`, and its quality
  gate is a no-op until application code exists.
- Pass the pull-request model key as `MODEL_API_KEY`. Generated callers use
  that name. Callers that still forward the previous secret name keep working
  after their pin moves to this revision.
- Optional public UI source assembly from protected-main commit pins, with
  static reviewer source and credential-free consumer installation.
- Shared repository standards, explicit human admission, protected merge gates, two-pass Codex review, and a draft source release pipeline.
- A CLI-only prerequisite hook in the credential-free quality job, with standards checks that reject other local action paths and execution scopes.
- Fixed Linux harness keyring build prerequisites before its credential-free quality gate; other profiles and platforms skip this package setup.
- Staged standards support for one exact shared-only missing-model-key acceptance caller. Installation and live verification require separate protected changes.
- A bounded offline exporter for exact old and new shared workflow sources and Git object metadata, so consumer pin changes can receive static review without new credentials.

### Fixed

- Adopt the reviewed byte-preserving archive validator in this repository's
  canonical PR and source-release callers. Older pins can reject original
  notices with CRLF line endings even when their source archives are exact.
- Prepare CLI harness-pin updates against the proposed immutable dependency only after verifying that it belongs to the fixed harness repository's protected main history. Bind the selected source and archive to review context. Consumers must adopt the reviewed workflow revision before this behavior is active.
- Require an explicit boolean completion result before accepting either AI review pass. Reject incomplete reviews even when they report no findings.
- Clear inherited GitHub token variables on the Codex action step while preserving trusted admission rechecks.
- Bind the CLI setup allowance to its actual quality step; literal YAML text and comment dashes cannot authorize another local action or hide extra step fields.

## [0.1.0] - 2026-10-18

- Initial development baseline. This entry documents source version metadata; it does not assert a published release or production readiness.
