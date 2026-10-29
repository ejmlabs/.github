# Changelog

Changes follow [Semantic Versioning](https://semver.org/). Each repository is versioned independently.

## [Unreleased]

### Added

- Shared agent guidance in `templates/agents/`: the `ejmlabs-*` skills (workflow, engineering, security, testing and writing, plus one per language and platform stack) and the AGENTS.md house rules block, with `scripts/sync_agents.py`, which copies them into a repository, links each skill for Claude Code discovery, and reports drift. No shared workflow changes.
- Continuous site deploys: the shared `deploy-site.yml`, called by an optional canonical `deploy.yml`, builds each push to main without credentials, deploys it to staging, and deploys the same files to production after the `production` environment's required reviewer approves. Deploy jobs run only a pinned Wrangler and `scripts/deploy.py`.
- A trusted build cache for the Rust gates: the shared `warm-cache.yml`, called by an optional canonical `cache.yml` on pushes to main, builds reviewed main in the gate's layout and is the only cache writer. Quality and the registry gate restore only the exact entry for the admitted base and discard anything else.
- `scripts/tools.py`, which installs prebuilt `cargo-deny` and `cargo-machete` after checking each archive against a reviewed SHA-256.
- Shared strict lint layer in `templates/lint/` (ESLint, ruff, ShellCheck and Rust lint tables) and `scripts/sync_lint.py`, which copies it into a repository and reports drift. No shared workflow changes.
- Let `ejm-ui` publish exactly `@ejm/tokens`, `@ejm/core`, `@ejm/ui` and `@ejm/ssg` to npm with provenance: they may omit `private` only with `publishConfig` `{"access": "public", "provenance": true}`, their name and packing fields (`files`, `main`, `exports`, `bin`, `directories`, lifecycle scripts and the rest) must equal the reviewed values, which keeps brand logos and artwork out of the tokens tarball, and `publish.yml` is accepted only at its reviewed SHA-256. Every other UI package stays private.
- Shared `verify-build.yml` and `attach-assets.yml` workflows that bind native build output to the tagged commit, recompute every digest and attach the files to the draft release.
- Accept exactly one supported review model key name in canonical workflows; reject extra, unknown or fallback key forwarding.
- Optional public UI source assembly from protected-main commit pins, with
  static reviewer source and credential-free consumer installation.
- Shared repository standards, explicit human admission, protected merge gates, two-pass independent automated review, and a draft source release pipeline.
- A CLI-only prerequisite hook in the credential-free quality job, with standards checks that reject other local action paths and execution scopes.
- Fixed Linux harness keyring build prerequisites before its credential-free quality gate; other profiles and platforms skip this package setup.
- Staged standards support for one exact shared-only missing-model-key acceptance caller. Installation and live verification require separate protected changes.
- A bounded offline exporter for exact old and new shared workflow sources and Git object metadata, so consumer pin changes can receive static review without new credentials.

### Changed

- Faster shared gate: every Quality matrix entry starts at once (no `max-parallel`), Cargo uses every runner core (`CARGO_BUILD_JOBS=default`), and the audit tools are no longer compiled from source on every run.
- `scripts/configure_repositories.py` enables auto-merge, so an approved PR merges itself when its required statuses pass.
- Type-annotate the scripts and tests, and enforce `mypy --strict` and ruff with the shared strict layer through a unit test run by the existing gate command. Behaviour is unchanged; the generated workflows differ only in the embedded script bytes.
- Repository standards accept both pull request caller forms (with and without the review key and the label trigger) and a shared workflow with or without the review job, so the review can later be removed from the shared gate in a separate change.
- Remove the `ejm-ui` bundle-size steps from the required Quality gate and the bundle-size wording from the operations guide; no shared check caps download size or dependency count. Safety bounds and security rules are unchanged.
- Instruct the automated review not to report a changed full-hash pin of this repository's shared workflows as missing context or a security concern; other references, moves to older revisions and widened permissions are still to be reported. Pin provenance remains a maintainer check.
- Replace the custom automated review gate with the pinned reviewer's documented GitHub Action runner and label blocking: one review per admission, its own security and effort labels, a merge recommendation, and a required label check. Removing the security label is the maintainer override; callers also trigger on label removal to re-evaluate. Removed the result adapter, two passes, coverage and negative-answer rules, and static review data.
- Publish blocking review findings to the job summary as inert, size-bounded text, and treat only a fixed list of negative security answers as no concern.
- Cover two classes of reviewer-skipped files with narrow fail-closed checks: `package-lock.json` changes that only mirror the sibling `package.json` dependency ranges (`lock-manifest-mirror v1`), and strictly allowlisted SVG assets under `packages/tokens/assets/` (`svg-allowlist v1`). All other skipped text stays incomplete.
- Allow each automated review model call up to 225 seconds, so slow high-effort responses complete within the existing two-attempt and 480-second reviewer limits instead of failing as incomplete.
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

- Treat ejmlabs/.github build-generated workflow paths and deleted SVG files
  as not model-reviewed so reviews complete when the remaining text is covered.
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
