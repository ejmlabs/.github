# Tasks

## 1. Implementation

- [x] 1.1 Gate: event-head binding, fork notice, one-label approve and admit, authoritative stop, status ownership, reruns, no size cap, stale pending recovery, bounded retries (`scripts/governance.py`, `scripts/build_workflows.py`)
- [x] 1.2 Standards: canonical callers on one pin, optional callers, credential-free lint of other workflows, stricter `build.yml`, presence-only community files, structural UI rules, all problems reported (`scripts/standards.py`)
- [x] 1.3 Prepare and cache: raw `git archive`, `scripts/extract.py`, lockfile-keyed restore-only caches, product-owned `.github/quality`, one harness pin selector for `ejm-cli` and `ejm-ide`
- [x] 1.4 Release and deploy: drafts from any main commit, reviewed Wrangler config, environment checks, `.github/site-build`, `secrets: inherit` caller
- [x] 1.5 Settings: `--check`, `staging` and `production` environments limited to `main`, missing-label fix
- [x] 1.6 Root `action.yml` for action pins and a 14-day Dependabot cooldown
- [x] 1.7 Docs: `docs/operations.md`, README, CHANGELOG and PR template; archive the finished changes and sync their specs, including `pr-gate`
- [x] 1.8 Release hardening: attestation in its own `attest` job, a draft with no tag until a human publishes it, attach bound to the draft's `tag_name` and `target_commitish`, and `semver` in `scripts/versioning.py` so `verify-build.yml` and `attach-assets.yml` embed less
- [x] 1.9 Close the stop residuals and the deploy setup gaps: a stop waits at most 45 seconds for the runs it cancelled before its last write, fails the job when that write fails, and ends within 120 seconds; production follows staging with no required reviewer and deploy jobs queue instead of cancelling; the deploy Wrangler is 4.153.0; `scripts/set_deploy_token.py` sets the deploy token in every site repository

## 2. Verification (hosted)

- [ ] 2.1 Hosted gate run after the pins move: a maintainer PR in each consumer is admitted and merges; a Dependabot PR is admitted by `gate:approve`; a fork PR prints the notice; `gate:revoke` and conversion to draft stop a head; a rerun of failed jobs keeps the admission
  - [x] Maintainer PRs admitted on 863bd13 and merged with a `gate:approve` bot approval: ejmlabs/ejm-ui#52, ejmlabs/ejmlabs#52, ejmlabs/ejm-ide#54, ejmlabs/ejm-harness#66 (Linux, macOS and Windows Quality) and ejmlabs/.github#74; ejmlabs/ejm-ide#55 admitted a 501-file, 84,000-line deletion with no size cap
  - [x] A Dependabot PR admitted by `gate:approve`: ejmlabs/.github#71 got the bot approval and an admitted run on its head, then merged
  - [ ] A fork PR prints the notice (needs an outside account)
  - [x] `gate:revoke` and conversion to draft stop a head: on ejmlabs/.github#75 at 863bd13, `gate:revoke` (run 41230746207) failed both statuses twice, as the first and last write, and the label came off after the stop. A draft conversion (run 41230790635) failed both again, and Ready (run 41230822005) admitted the head and passed. Neither stop run started a check job
  - [ ] A rerun of failed jobs keeps the admission
- [x] 2.2 A Dependabot actions PR passes `python3 scripts/build_workflows.py --check`: ejmlabs/.github#71 changed `action.yml` and the generated `attach-assets.yml` together, and its admitted Quality and Repository standards passed
- [ ] 2.3 First staging and production deploy for each adopting site, with its environments configured
- [ ] 2.4 `python3 scripts/configure_repositories.py --check` passes for every repository
- [ ] 2.5 Admitted gate timings on each consumer after its pin moves, cold and with a warm cache
- [ ] 2.6 First native draft release with `attest`: the draft exists with no tag, `target_commitish` is the commit, `attach` and `attest` run with their own permissions, and publishing the draft creates the tag

## 3. Follow-ups

- [x] 3.1 This repository adopts the new revision
  - [x] Retain the merged SHA under `workflow-pins/` and move `pr.yml` and `release.yml` to it (0180b449b34537f1cc368bdd5dd05a2fbc1c64b6)
  - [x] Drop the `XAI_API_KEY` declaration from `governance.yml`, and make the standards accept only that form
  - [x] Fix the community text (3.3)
- [ ] 3.2 One PR per consumer (`ejm-cli`, `ejm-harness`, `ejm-ide`, `ejm-ui`, `ejmlabs`) that moves every pin, switches `deploy.yml` to `secrets: inherit` where present, and resyncs community files and other templates
  - [x] ejm-harness#66, ejm-ide#54, ejm-ui#52 and ejmlabs#52 on 863bd13
  - [ ] The b342040 revision (ejmlabs/.github#75): ejm-ui#57, ejmlabs#55, ejm-ide#60 and ejm-harness#76, which also adopt deploy-on-merge where it is new
  - [ ] ejm-cli, which needs push access for the agent
- [x] 3.3 Fix stale community text in `templates/community/` and the root files: SECURITY.md ("before checks or AI run"), CODE_OF_CONDUCT.md ("AI review"), CONTRIBUTING.md ("Address findings", forks admitted by Ready, "Do not use Actions rerun to replay an admission")
- [ ] 3.4 Archive this change, skipping the `pr-gate` sync (already done here), and sync `repository-standards` into `openspec/specs/`

## 4. Owner tasks

- [x] 4.1 No production reviewer is required: the merge is the human decision, and a reviewer is allowed
- [ ] 4.2 Delete the `legacy-review` environment in each repository (from `remove-ai-review` 4.1)
- [ ] 4.3 Delete the stored model key and close or empty the prepaid provider account, after every caller is on a pin without `XAI_API_KEY` (from `remove-ai-review` 4.2)
