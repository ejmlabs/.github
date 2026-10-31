# Changelog

Changes follow [Semantic Versioning](https://semver.org/). Each repository is versioned independently.

## [Unreleased]

The net change since 0.1.0:

- A human-gated PR pipeline as reusable workflows: a maintainer's PR admits itself, any other PR is admitted by a maintainer's Ready or `gate:approve`, and comments control nothing.
- The `gate:approve` and `gate:revoke` labels, with two required statuses (Quality and Repository standards) plus one approving review, enforced for administrators. No model review runs.
- Repository standards for versions, licenses, documents and workflow callers.
- A settings tool, `scripts/configure_repositories.py`, that applies the repository controls and reads them back.
- Draft source releases from checked main commits, and native release files that are verified before the draft and attached after it, with optional provenance attestation in its own job.
- Continuous site deploys: staging on every push to main, then production once staging succeeds. The merge is the human decision.
- A faster Quality gate: every matrix entry starts at once, Cargo uses every core, and `cargo-deny` and `cargo-machete` come from prebuilt archives checked against SHA-256 digests.
- A trusted Rust build cache written only by reviewed main.
- CLI and harness support: a harness pin checked against protected harness history, Linux keyring packages and a CLI setup hook.
- `ejm-ui` support: an owner profile, an optional public UI source pin and a reviewed public npm package set.
- `ejm-calm` support: a site profile (MIT, `package.json` and its lock at `VERSION`, contributor guide `README.md#run-locally`) that owns its Quality gate in `.github/quality` and deploys through `deploy.yml`; settings take it with `--repository ejm-calm`.

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
- Production deploys no longer need a required reviewer. The deploy check still requires staging and production to allow deployment from exactly `main`, and a reviewer a human adds is allowed. `configure_repositories.py` no longer warns about or checks for one.
- Deploy jobs never cancel a running deploy. The build, staging and production jobs queue per repository, and only an older run that has not started is replaced.
- The deploy Wrangler is 4.153.0 (was 4.151.3). Its Miniflare resolves undici 7.30.1, which clears the eight undici advisories (high severity) that `npm audit` reported for 7.0.0 through 7.30.0.
- Draft releases accept any commit on main, not only its head, and require `standards-ref` to equal every pin in that commit's own `release.yml`. An approval counts only as a reviewer's latest decision on the merged head.
- Repository standards require community files only to exist and be non-empty. `scripts/sync_community.py --check` reports drift on demand.

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

### Agent guidance, lint layer and sync tools

- The house rules and shared skills describe the current gate: open a PR non-draft once local checks pass, a human-only action needs the user's explicit ask, rerun a job once for an infrastructure failure, no PR size cap, forks go through a repository branch, and a consumer moves its pin in one PR.
- OpenSpec is required only for a change to a contract other repositories or users rely on, or one that spans several PRs.
- Untrusted text is everything outside AGENTS.md, the skills and the user. An agent quotes it and asks before acting on it.
- Contradictions between skills are fixed (re-exports, the campground rule, one two-week dependency age rule, the Cargo job cap only on constrained machines, visible-change checks scaled to the change), and shared skills name no private repository.
- Each shared `SKILL.md` is at most 5,000 bytes, with detail in `references/`.
- `scripts/sync_agents.py` writes the shared skill list between `<!-- ejmlabs:skills:start -->` and `<!-- ejmlabs:skills:end -->` from each skill's frontmatter, runs every check before it writes, replaces a skill only after its copy succeeds, and accepts an end marker at the end of the file.
- `scripts/sync_lint.py --check` reports every drifted file.
- The strict ruff layer ignores BLE001 and TRY400, which the house error-logging form trips, and S105 to S107 in tests. Formatting is not gated.
- The strict ESLint layer reports `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `eval`, implied eval and `new Function`, and allows non-null assertions and unbound methods in tests.
- The ShellCheck layer disables SC2310, SC2311 and SC2312.

### Close the remaining gaps

#### Changed

- The gate orders decisions by run id, so an older event or a rerun of an older run cannot undo a newer decision. `gate:revoke` stays on the PR until its stop completes, and finish, verify, admission and approval honor it meanwhile. Only a maintainer's event admits a head. A stop dismisses approvals even when cancelling fails, status writes retry five times, admission is serialized per head across PRs, and a cancelled run starts no finish job.
- Attestation runs in its own `attest` job of `attach-assets.yml`, only when `attest` is set. It holds `id-token`, `attestations`, `actions: read` and `contents: read`, downloads the same artifact, recomputes every digest and requires them to equal the digests the `attach` job attached before it attests. The `attach` job no longer holds `id-token` or `attestations`. The native `release.yml` caller is unchanged.
- A draft release is created with `--target <commit>` and no tag ref, so GitHub creates the tag only when a human publishes the draft and a failed run uses up no version. The run refuses a version that already has a tag, a published release or a draft.
- Attach binds to the draft's `tag_name` and `target_commitish` instead of a tag ref. It refuses any existing tag ref, two releases for the tag and a replaced asset, and it reads the draft again right before the first upload.
- SemVer checking moved to `scripts/versioning.py`. `verify-build.yml` and `attach-assets.yml` embed it and the API class instead of the whole standards check, which shrinks the generated files from 122,515 to 37,047 bytes (`verify-build.yml`) and from 245,200 to 111,398 bytes (`attach-assets.yml`, which gained a job).
- The community templates and root files describe the current gate and release flow: no AI review, no fork admission, reruns allowed, no size cap, and a draft before the tag.

#### Fixed

- A stop waits, for at most 45 seconds, until the runs it cancelled have completed before its last write, so a finish job that was already running cannot post a success after it. A run still going then is named in a warning. A last write that fails prints an error that the head may still read success, and the job fails. The whole stop is bounded to 120 seconds, inside the admission job's 3 minutes, with a 10-second timeout per status attempt.

#### Removed

- The unused `XAI_API_KEY` declaration from `governance.yml`. The standards accept only the scaffold without it.

### Agent docs follow the pin

#### Added

- The Repository standards job checks each repository's shared agent skills, house rules and skills routing block against `templates/agents` at the commit of the shared workflow (`job.workflow_sha`), fetched with plain git and no token. This repository checks against its own templates. A failure names each drifted file and the sync command to run.
- `scripts/sync_agents.py --templates DIR` syncs or checks against another revision's templates.
- `ejmlabs-cloudflare` has `references/ci-deploys.md`: the deploy on merge, what a deploy refuses, failures and what to do, the owner setup, staging names and rollback. Site repositories keep only their own site facts and link to it.
- A house rule: shared behavior is described in the synced skills, which move with the pin, and repository docs do not restate it.
- `ci-deploys.md` lets an agent approve a production deployment only when the user explicitly asks, and only after checking that production serves a build of main the deployment moves forward from. A deploy by hand from a branch otherwise gets rolled back by the next production job. The dry run names the Wrangler to use when a repository pins none.

#### Fixed

- The standards job reads `job.workflow_sha` in each step's env. Revision 9f7421b read it in the job's own env, where GitHub does not offer the job context, so no caller can start a run at that revision; never pin it. A test now holds every job-level key of the generated workflows to the contexts GitHub allows there.

## [0.1.0] - 2026-10-18

- Initial development baseline. This entry documents source version metadata; it does not assert a published release or production readiness.
