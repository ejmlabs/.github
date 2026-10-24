# Changelog

Changes follow [Semantic Versioning](https://semver.org/). Each repository is versioned independently.

## [Unreleased]

### Added

- Accept exactly one supported review model key name in canonical workflows; reject extra, unknown or fallback key forwarding.
- Generate current-head PR next-action guidance from live metadata. After merge and validator pin adoption, a follow-up PR generates and adds `pr-guidance.yml`; consumers adopt the opt-in guided caller only at a pin containing that file.
- Optional public UI source assembly from protected-main commit pins, with
  static reviewer source and credential-free consumer installation.
- Shared repository standards, explicit human admission, protected merge gates, two-pass independent automated review, and a draft source release pipeline.
- A CLI-only prerequisite hook in the credential-free quality job, with standards checks that reject other local action paths and execution scopes.
- Fixed Linux harness keyring build prerequisites before its credential-free quality gate; other profiles and platforms skip this package setup.
- Staged standards support for one exact shared-only missing-model-key acceptance caller. Installation and live verification require separate protected changes.
- A bounded offline exporter for exact old and new shared workflow sources and Git object metadata, so consumer pin changes can receive static review without new credentials.

### Changed

- Removed the previous hosted review action, its key and its allowance.
- Configure the pinned reviewer with a restricted provider key, prepaid credits,
  no automatic top-up or fallback model, and a 160,000-token cap.
- Keep review output local to the job, sanitize findings, and remove result
  artifact uploads while preserving status-only logs and human approval gates.
- Switch the shared reviewer to a pinned open-source reviewer with hash-locked
  dependencies, bounded model calls, two serial passes, and fail-closed output
  adaptation. Reviewer logs remain private files at INFO level; preparation and
  review refuse runner debug mode. Fork PRs require manual review.

### Fixed

- Confine the review model key to a protected environment restricted to main.
- Keep debug guards in the first workflow steps with valid job conditions.
  Isolate reviewer installation from caches and workspace configuration, remove
  linked source entries, reject silently excluded text changes, and tighten
  credential redaction, coverage detection, and reviewer output controls.
- Adopt the reviewed byte-preserving archive validator in this repository's
  canonical PR and source-release callers. Older pins can reject original
  notices with CRLF line endings even when their source archives are exact.
- Prepare CLI harness-pin updates against the proposed immutable dependency only after verifying that it belongs to the fixed harness repository's protected main history. Bind the selected source and archive to review context. Consumers must adopt the reviewed workflow revision before this behavior is active.
- Require an explicit boolean completion result before accepting either AI review pass. Reject incomplete reviews even when they report no findings.
- Clear inherited repository token variables on the independent automated review step while preserving trusted admission rechecks.
- Bind the CLI setup allowance to its actual quality step; literal YAML text and comment dashes cannot authorize another local action or hide extra step fields.

## [0.1.0] - 2026-10-18

- Initial development baseline. This entry documents source version metadata; it does not assert a published release or production readiness.
