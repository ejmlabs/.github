# Changelog

Changes follow [Semantic Versioning](https://semver.org/). Each repository is versioned independently.

## [Unreleased]

The net change since 0.1.0:

- A human-gated PR pipeline as reusable workflows: a maintainer's PR admits itself, any other PR is admitted by a maintainer's Ready or `gate:approve`, and comments control nothing.
- The `gate:approve` and `gate:revoke` labels, with two required statuses (Quality and Repository standards) plus one approving review, enforced for administrators. No model review runs.
- Repository standards for versions, licenses, documents and workflow callers.
- A settings tool, `scripts/configure_repositories.py`, that applies the repository controls and reads them back.
- Draft source releases from checked main commits, and native release files that are verified before the tag and attached after the draft, with optional provenance attestation.
- Continuous site deploys: staging on every push to main, production after a reviewer approves.
- A faster Quality gate: every matrix entry starts at once, Cargo uses every core, and `cargo-deny` and `cargo-machete` come from prebuilt archives checked against SHA-256 digests.
- A trusted Rust build cache written only by reviewed main.
- CLI and harness support: a harness pin checked against protected harness history, Linux keyring packages and a CLI setup hook.
- `ejm-ui` support: an owner profile, an optional public UI source pin and a reviewed public npm package set.

### Velocity and safety refactor

#### Added

- The gate acts on the event's head SHA and prints a notice, with no write, when the PR head moved or the PR is closed, a draft or not based on main.
- `gate:approve` records a bot approval bound to the event head and admits that head, so one label approves and admits a Dependabot PR.
- Every status carries its run URL, and the verify and finish steps act only when the current run owns the newest Quality and Repository standards statuses.
- Each rerun attempt uploads its own `admitted-sources-<attempt>` artifact.
- A pending pair whose run finished is treated as stale and admitted again.
- `scripts/extract.py` validates every source archive member, extracts with the data filter and stamps each file with the extraction time.
- A product's executable `.github/quality`, `.github/quality-registry` and `.github/site-build` replace the profile's built-in commands, which stay as the fallback.
- Deploy jobs check out the reviewed commit and require the artifact's Wrangler config to be byte-identical to it.
- Deploy jobs also fail closed unless the environment's deployment branch policy is exactly `main`.
- `configure_repositories.py` creates the `staging` and `production` environments with a deployment branch policy of `main`.
- `configure_repositories.py --check` reads back the settings, labels, environments, collaborators and installed callers without writing.
- A root `action.yml` holds the action pins, so one Dependabot actions PR can bump them with the generated workflows (to be confirmed on the first such PR), and Dependabot waits 14 days before proposing a version.
- Repository standards require `pr.yml` and `release.yml` to equal the canonical callers except for the pin, with every caller on the same pin.
- Repository standards accept optional `cache.yml` (`ejm-cli`, `ejm-harness`, `ejm-ide`, `ejm-ui`), `deploy.yml` (any site, with or without `secrets: inherit`) and `publish.yml` (`ejm-ui` only, at its reviewed SHA-256, which the error prints).
- Repository standards accept any other workflow that passes a credential-free lint: safe triggers, read-only top-level permissions, no job permissions, environments or secrets, no secret or token expressions, pinned actions and a restricted YAML subset.
- Repository standards lint `build.yml` more strictly: dispatch and push to main only, `contents: read`, exactly one `release-files` artifact and no local action.
- Repository standards report every problem in one run, with a bounded diff for caller mismatches.
- Repository standards check public `ejm-ui` packages by structure: `name` equal to `@ejm/<directory>`, no lifecycle scripts, bundling or workspaces, and packing fields inside reviewed prefixes.

#### Changed

- Fork PRs are not admitted, because their token is read-only. A maintainer who reviewed an outside change pushes it to a branch in the repository.
- A maintainer's PR admits itself on open, reopen, push and Ready, and any other same-repo PR is admitted by a maintainer's Ready or `gate:approve`. The author type comes from the live PR.
- `gate:revoke` and conversion to draft fail both statuses, cancel this workflow's other runs for the head, dismiss bot approvals and fail both statuses again as the last write.
- Reruns are allowed. Re-run failed jobs keeps the admission, and re-running the admission job needs a current human maintainer as the actor.
- Admission runs one at a time per PR and head, and a push cancels this workflow's runs for the replaced head.
- Gate API calls retry 429, 5xx and network errors (three attempts in all), and embedded trusted Python runs as `python3 -I`.
- Rust gate caches are keyed by toolchain and the hash of the profile's `Cargo.lock`, restored with a prefix fallback, and only restored by gate jobs. The warm job on main checks the exact key first and saves only when it is missing.
- `ejm-ide` selects its harness pin from the admitted head, with the same protected-main ancestry check as `ejm-cli`.
- The canonical `deploy.yml` passes `secrets: inherit`, so the environment's `CLOUDFLARE_API_TOKEN` reaches the deploy jobs. The older form is still accepted.
- Deploy jobs validate tar members before extraction and run Wrangler with a minimal environment that holds no GitHub token.
- Draft releases accept any commit on main, not only its head, and require `standards-ref` to equal every pin in that commit's own `release.yml`. An approval counts only as a reviewer's latest decision on the merged head.
- Repository standards require community files only to exist and be non-empty. `scripts/sync_community.py --check` reports drift on demand.
- `governance.yml` is accepted with or without the unused `XAI_API_KEY` declaration, which this revision still emits because the standards at pin `8230ef8` require it.

#### Fixed

- The settings tool PATCHed a missing gate label instead of creating it.
- `site_config` parses JSONC comments and trailing commas outside strings only.
- A finishing job can no longer replace a revoke or draft conversion with a success.
- Re-running all jobs no longer collides on the source artifact name.
- Gate and release archives no longer rewrite committed bytes through the `text`, `eol`, `ident`, `filter` and `working-tree-encoding` attributes.

#### Removed

- The 200-file and 12,000-line admission cap.
- The admission id and the rerun ban.
- The previous caller form and the missing-model-key fixture from the standards check.
- The cache discard step, the unused `current_pr` helper and the debug-log step in the gate.
- Byte-for-byte comparison of community files, and the README heading list, from the standards check.
- The reviewed per-package digests for public `ejm-ui` packages, replaced by the structural rules.

## [0.1.0] - 2026-10-18

- Initial development baseline. This entry documents source version metadata; it does not assert a published release or production readiness.
