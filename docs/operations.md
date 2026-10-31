# Repository operations

How the shared gate, releases and site deploys are set up and run. The scripts are the exact
specification; this guide holds what a maintainer has to decide or do.

## Settings and permissions

Protect main with PRs, one approving GitHub review, and two strict required
statuses bound to GitHub Actions: Quality and Repository standards. They are
enforced for administrators too: `scripts/configure_repositories.py` sets
`enforce_admins`, and there is no administrator bypass. Require resolved
conversations, linear history and stale approval dismissal. Block force pushes
and branch deletion. Use squash merges and delete merged branches. Allow
auto-merge: after checks are admitted, a maintainer may add the `gate:approve`
label for self-approve under `enforce_admins`, arm auto-merge, and let the PR
merge once every required status passes. Strict statuses still hold it until
it is up to date with main.

Default workflow tokens are read-only. Allow only full-SHA actions from
`actions/*`, `astral-sh/setup-uv` and `ejmlabs/.github`. Enable bot review
recording so an explicit human self-approve can be represented as a native
review via the `gate:approve` label. Fork PR workflows get no secrets or write
tokens. Re-enabling any model review needs the security review's sign-off first.

Every account with write access must be a human with maintain or admin
permission. The settings tool rejects ordinary writers and bots. GitHub
Actions identity alone cannot prove which workflow published a status: a
writer can add a branch workflow with that identity. Before granting ordinary
write access, move required result publication to a dedicated GitHub App with
credentials confined to a protected environment.

Revoke open PR decisions before removing or demoting a maintainer. Admission,
labels and releases check current roles, but GitHub sends no continuous
role-change event to this pipeline. Organization administrators remain trusted
because they can change repository policy.

Apply settings, or read them back, with authenticated `gh`:

```sh
python3 scripts/configure_repositories.py [--hold-actions | --protect-main] [--repository NAME ...] [--standards-revision SHA]
python3 scripts/configure_repositories.py --check [--repository NAME ...] [--standards-revision SHA]
```

The default scope is `.github`, `ejmlabs`, `ejm-cli`, `ejm-harness` and `ejm-ide`; `ejm-ui` needs
`--repository ejm-ui`. Apply refuses to enable Actions until reviewed callers are on main
(`--hold-actions` keeps them off for bootstrap). `--protect-main` adds branch protection and the
`v*` tag ruleset. For a repository with `deploy.yml` on main, apply also creates the `staging` and
`production` environments, each allowing deployment from `main` only. It never sets reviewers: add
the production reviewer by hand. `--check` writes nothing and exits 1 on any failure. It asserts
the settings above, collaborator roles, and that main's workflows pass the standards workflow
check on a pin that is on `ejmlabs/.github` main or a retained `workflow-pins/` branch
(`--standards-revision` requires one exact SHA).

## Admission, approval and reruns

Admission uses pull request fields, labels and collaborator permissions, never comment text.
Comments such as `/ready` or `/approve` do nothing. Draft PRs spend nothing.

| Event | Who admits | Result |
| --- | --- | --- |
| Same-repo non-draft PR by a human maintainer or admin: opened, reopened, pushed, Ready | The PR itself | Checks run for the event head |
| Same-repo non-draft PR by a bot (Dependabot) or a non-maintainer | A maintainer marks it Ready or adds `gate:approve` | Checks run for the head |
| `gate:approve` by a maintainer on the current non-draft head | That maintainer | Bot approval bound to the head, head admitted if no live run holds it, label removed |
| `gate:revoke` by a maintainer, or conversion to draft | That maintainer | Stop |
| Fork PR | Nobody | Notice only, no API write |
| A gate label added by a non-maintainer | Nobody | Label removed, run fails |

- Every action binds to the event's head SHA. If the live PR head differs, or the PR is closed, a
  draft or not based on main, the run prints a notice and writes nothing (a gate label is still
  removed). A newer event handles the new head. A new commit needs a new admission: the push for a
  maintainer's PR, a new Ready or `gate:approve` for any other.
- Stop. `gate:revoke` and conversion to draft fail both statuses, cancel this workflow's other
  queued and in-progress runs for that head, dismiss bot approvals, then fail both statuses again
  as the last write, so a finishing job cannot replace the failure with a success.
- Ownership. Every status carries the URL of the run that wrote it. The verify and finish steps
  act only when the newest Quality and Repository standards statuses on the head belong to the
  current run and no other run has written one since this run's first. A stop therefore ends a
  run's claim for good: its later writes and its reruns cannot take the head back. Finish reads
  the history again after writing, fails the checks it wrote if a stop landed first, and fails
  closed when that read is impossible. To admit a stopped head again, mark it Ready or add
  `gate:approve`.
- Reruns are allowed. Re-run failed jobs keeps the admission, and finish re-checks ownership and
  the live head. Re-running the admission job itself needs a current human maintainer as the
  actor. Rerun for infrastructure failures; fix code in a new commit.
- A run holds its head from admission until it completes, whatever its statuses say, so a Ready
  or `gate:approve` while it runs admits nothing beside it; `gate:revoke` stops it.
- A no-op prints a notice and exits 0: a stale head, a head that already passed or is already
  admitted, a fork, a PR nobody has admitted. A pending pair whose run finished, or whose URL is
  not a run of this repository, is stale, and the next admission event admits the head again.

A maintainer who has reviewed an outside change pushes it to a branch in the repository, because a
fork's token is read-only and the gate could write no status. Dependabot PRs take one label:
review the PR, then add `gate:approve` to approve and admit its head. Agents add gate labels only
when the user explicitly asks.

A PR has no file or line cap. Time limits: admission, Repository standards and finish 3 minutes
each, preparation 5, Quality 45, the separate registry gate 25. Builds receive no model key,
source-read secret, deployment credential or write token. Never enable step or runner debug
logging on this path. Set a workflow execution budget and alerts: per-run limits do not cap
aggregate spending.

## Credentials

- No job receives a model key. `governance.yml` still declares an optional, unused `XAI_API_KEY`
  secret only because the standards at pin `8230ef8` require it; the next revision drops it. Then
  the owner deletes the stored key and closes the prepaid provider account.
- `EJM_HARNESS_TOKEN` is optional. Preparation reads the pinned harness with
  `secrets.EJM_HARNESS_TOKEN || github.token`, using read-only calls. A public harness needs no
  token. For a private one use an expiring fine-grained token with Contents read on that repository
  alone, and never give it to PR code.
- `CLOUDFLARE_API_TOKEN` is an environment secret in `staging` and `production`. It reaches the
  deploy jobs through `secrets: inherit` in the canonical `deploy.yml`, and only the final deploy
  step of each job reads it. Scope it to Workers scripts, routes and custom domains on
  `ejmlabs.com`, plus R2 read for sites that bind a bucket. The build job gets no secret.

## Quality profiles

The Quality job is credential-free with no token permissions. Every profile gets Node 24 and uv
0.9.26. Rust profiles also get Rust 1.99.1 with Clippy and rustfmt, and all but `ejm-ui` get
`cargo-deny` and `cargo-machete` from prebuilt archives that `scripts/tools.py` checks against
reviewed SHA-256 digests. Every matrix entry starts at once and Cargo uses every core. No shared
check caps bundle bytes, download size or dependency count.

| Profile | Runners | Built-in commands (fallback) | Also |
| --- | --- | --- | --- |
| `.github` | ubuntu-24.04 | `python3 -m unittest discover -s tests -v`; `python3 scripts/build_workflows.py --check` | Tests run ruff and mypy |
| `ejmlabs` | ubuntu-24.04 | `node scripts/check.mjs`; `npm --prefix site test`; `npm --prefix site run build` | Studio owns the entry |
| `ejm-cli` | ubuntu-24.04, macos-15 | `./scripts/check` | Setup hook, harness pin |
| `ejm-harness` | ubuntu-24.04, macos-15, windows-2025 | `npm ci --ignore-scripts` (root, `registry`); `./scripts/check` | Keyring packages, registry gate |
| `ejm-ide` | macos-15 | `npm ci --ignore-scripts`; `npm run verify`, `site:check`, `site:build` | Harness pin |
| `ejm-ui` | ubuntu-24.04 | the owner commands below | |

- Product-owned gate. An executable, regular (not symlinked) `.github/quality` replaces the
  built-in commands. It runs from the product root with `npm_config_ignore_scripts=true` and needs
  a shebang, because Windows legs run it under Git Bash. `.github/quality-registry` does the same
  for the harness registry gate. Toolchains stay shared. The built-ins are the fallback until
  every product has its own.
- Harness pin. `ejm-cli` and `ejm-ide` select the harness from `.github/harness-revision` in the
  admitted head: a blob holding one full lowercase SHA. Trusted preparation asks the GitHub API
  about `ejmlabs/ejm-harness` only, requires its `main` to be protected, and accepts the pin only
  if it equals main's head or is an ancestor. A pin bump and its lockfile are one PR. An optional
  `.github/ui-source.json` pins `ejmlabs/ejm-ui` the same way, read from trusted main.
- Keyring packages and setup hook. The harness profile installs `pkg-config` and `libdbus-1-dev` on
  Linux without recommended packages. Only the CLI profile runs `./product/.github/actions/setup-ci`
  (credential-free Quality and the cache warm job); the standards accept that one step form and no
  other local action. Land and verify the action before adopting source that needs it.

## UI owner profile

`ejm-ui` uses the contributor guide `README.md#development`. Its Quality commands stop at the first
failure: `npm ci --ignore-scripts`, `npm rebuild node-pty --ignore-scripts=false` (the one
lifecycle exception), `npm run check`, `npm run build`, `npm run check:rust`,
`node scripts/pack-proof.mjs`. `VERSION` must equal the root and every `packages/*` manifest, their
lock entries and `crates/ejm-tui`.

The public npm set is `core`, `ssg`, `tokens` and `ui`. Each may omit `private` only with
`publishConfig` exactly `{"access": "public", "provenance": true}`; `"private": false` is refused.
The root and every other package stay `private: true`. Packages are found by globbing
`packages/*/package.json`. A public package must also:

- have `name` equal to `@ejm/<directory>`;
- declare no pack, publish or install lifecycle script (`UI_LIFECYCLE_SCRIPTS` in
  `scripts/standards.py` lists them) and no `bundleDependencies` or `workspaces`;
- list `files`, and point `main`, `browser`, `bin`, `man` and `directories` only inside the reviewed
  prefixes in `UI_PACKING_PREFIXES`. For `tokens`, `assets` is reachable only through
  `assets/fonts`, `assets/brand` and `assets/icons`, which keeps logos and artwork out of the
  tarball.

Other fields, such as `exports` and `types`, change without a shared revision. Every package keeps
its scoped license and notices, and token font notices keep the original OFL bytes
([public notices](../tests/fixtures/font-notices/README.md)). `.github/workflows/publish.yml` is
allowed only in `ejm-ui`, as a regular file whose SHA-256 equals `UI_PUBLISH_SHA256`; the error
prints the actual digest, so a reviewed update is one copy.

## Repository standards

The check runs from the pinned revision against the admitted tree and reports every problem in one
run, with a bounded diff for caller mismatches. It is a consistency lint, not a security boundary:
a `pull_request` run uses the caller in the PR, so the PR chooses its pin and with it the standards
that judge it. Human review of the pin line is the control.

- Callers. `pr.yml` and `release.yml` equal the canonical callers except for the pin, and every
  caller is on the same 40-hex pin. The native `release.yml` is required when `build.yml` exists.
- Optional callers. `cache.yml` in `ejm-cli`, `ejm-harness`, `ejm-ide` and `ejm-ui`. `deploy.yml` in
  any site repository, with or without `secrets: inherit`. `build.yml` in `ejm-cli` and
  `ejm-harness`. `publish.yml` only in `ejm-ui`, at its reviewed SHA-256.
- Any other workflow must be credential-free: triggers only `push`, `pull_request`,
  `workflow_dispatch`, `schedule` and `merge_group`; top-level `permissions` exactly
  `contents: read` or `{}`; no job-level `permissions`, `environment` or `secrets`; no expression
  reading `secrets` or the GitHub token; no `persist-credentials: true`; every `uses` a full SHA or
  a local `./.github/actions/...` path; and a restricted YAML subset (block mappings and lists, no
  anchors, aliases, tags, flow mappings, quoted or duplicate keys). This reads the file's shape;
  review still covers what the steps run.
- `build.yml` is stricter: only `workflow_dispatch` and pushes to main, `contents: read`, exactly
  one `release-files` artifact, no local action. Reusable workflows here keep their generated
  scaffold: only the staging and production deploy jobs declare an environment.
- Versions and documents. `VERSION` is SemVer and agrees with manifests, locks and licenses, and
  `CHANGELOG.md` has a dated entry for it. README, CONTRIBUTING, SECURITY, SUPPORT,
  CODE_OF_CONDUCT, RELEASING, THIRD_PARTY_NOTICES, CHANGELOG and LICENSE exist and are non-empty;
  these nine contain no em dash, and relative links in the Markdown ones resolve. Community files
  are not compared byte for byte and the README needs no particular headings. `.github/CODEOWNERS`,
  `dependabot.yml`, `pull_request_template.md` and `ISSUE_TEMPLATE/config.yml` must exist, and
  `ejm-cli` and `ejm-ide` need a valid `.github/harness-revision`.

## Trusted build cache

Rust profiles (`ejm-cli`, `ejm-harness`, `ejm-ide`, `ejm-ui`) adopt the cache by adding the canonical
`cache.yml` caller. On each push to main it runs `warm-cache.yml` with `contents: read` and no
secrets.

- Key. `gate-<job>-<OS>-rust1.99.1-<hash of the Cargo.lock beside the target directory>`, where job
  is `quality` or `registry`. A gate job restores the exact key, or else the newest entry with the
  prefix before the hash. It never saves, and setup-uv's cache is off in gate jobs. A miss costs a
  cold build. Extraction stamps every file with the current time, so Cargo rebuilds every local
  crate and reuses only dependency artifacts.
- PR scope. GitHub scopes the cache of a pull request run to that PR's merge ref, so PR code can
  write entries only that PR's own runs restore, never entries main or another PR restores. This
  is a GitHub rule that this repository relies on and does not test, so the gate has no discard
  step. The earlier residual-risk note was written for the removed comment caller.
- Warm job. Main pushes only. It builds reviewed main in the gate's layout, looks up the exact key
  first, skips the build on a hit, and saves only when the key was missing and the build passed.
  Release builds never restore a cache. Remove `cache.yml` to stop restores.

## Site deploys

Site repositories (`ejmlabs`, `ejm-cli`, `ejm-harness`, `ejm-ide`, `ejm-ui`) adopt continuous deploys
with the canonical `deploy.yml` caller, which passes `secrets: inherit`. Each push to main runs the
shared `deploy-site.yml`:

1. `build` checks out that main commit and main's pinned `ejm-ui`, builds with `contents: read` and
   no secrets, and uploads one artifact (kept 7 days). It runs the product's executable, regular
   `.github/site-build` (shebang required, `npm_config_ignore_scripts=true`) if there is one,
   else the commands for the site in `SITES` in `scripts/deploy.py`, which also holds each site's
   config path and output paths.
2. `staging` deploys the artifact with `wrangler deploy --env staging`.
3. `production` waits for the `production` environment's required reviewer, then deploys the same
   files with the top-level config.

A deploy job trusts nothing in the artifact. It checks out the reviewed `github.sha` (sparse,
`persist-credentials: false`, `contents: read`), validates every tar member before extraction,
and requires the artifact's Wrangler config to be byte-identical to the reviewed one (for
`ejm-ide`, the whole `distribution` directory, which holds its Worker). `account_id` must match,
`assets.directory` must stay inside the declared output paths, and a Worker `main` must be
committed source. A Wrangler `build` command is refused, and staging needs its own Worker name and
routes, because `--env staging` otherwise inherits the production custom domain. Wrangler runs
from the lockfile in `deploy/` with a minimal environment that holds no GitHub token. A separate
step first reads the environment and fails closed unless it has exactly one deployment branch
policy, `main`; production also needs at least one required reviewer.

Before a site moves to the new pin, create `staging` and `production` with
`configure_repositories.py`, add a human reviewer to `production`, set `CLOUDFLARE_API_TOKEN` as an
environment secret in both, and read the result back with `--check`. Change `deploy.yml` to the
`secrets: inherit` form (the older form leaves the token empty) and give the Wrangler config
`env.staging` with its own Worker name and routes, on fresh staging hostnames: a custom domain
whose DNS record exists makes Wrangler prompt, and CI cannot answer. A newer main commit replaces a
production deploy still waiting for approval. Roll back by redeploying an earlier Worker version
in Cloudflare, or by approving an earlier run's production job while it is still available.

## Releases and native build files

The shared workflow creates a draft source release from the main head or any earlier commit on
main, with the repository's SemVer `VERSION` and dated notes. See [Releasing](../RELEASING.md) for
the dispatch contract. Only a current human maintainer may run it, and only on the first attempt,
because tag creation is not idempotent. `standards-ref` must equal every `ejmlabs/.github` pin in
that commit's own `release.yml`. The commit must be the merge commit of exactly one merged PR with
the same tree as the PR head, whose required statuses passed on that head and on which some
reviewer's latest decision is an approval of it. Source archives hold the committed bytes.

`ejm-cli` and `ejm-harness` may ship native builds. A repository opts in by adding
`.github/workflows/build.yml`, which the standards then require alongside the native `release.yml`.
It uploads exactly one artifact, `release-files`: the release files plus one `build-sha256.txt` in
`sha256sum` format, names `[A-Za-z0-9._-]`, no subdirectories. The release jobs are:

1. `verify-build.yml` (`actions: read`) before Draft release: a successful run of `build.yml` on
   this commit, from main in this repository, with a `release-files` artifact, so a failed smoke
   check never burns the tag.
2. `attach-assets.yml` after Draft release. It holds the release write token and runs no project
   code. It re-verifies the run, the lightweight `vVERSION` tag and the single draft, recomputes
   every SHA-256 against `build-sha256.txt`, and uploads the files, then an extended `SHA256SUMS`.
   It refuses a changed digest, an extra, missing or linked file, and a file that would replace an
   asset. With `attest`, it attests the attached files (`built/*`, including `build-sha256.txt`):
   provenance for what it attached for that commit, not for the build run, and not code signing.

Prereleases such as `1.2.3-rc.1` have Latest disabled. Build metadata does not
change classification: `1.2.3+build-alpha` is stable;
`1.2.3-rc.1+build-2` is a prerelease. Stable drafts keep GitHub's default Latest
behavior. Review drafts before explicit publication.

Tag creation, draft creation and asset upload are separate writes. A failed
or canceled run may leave a tag without a draft or an incomplete draft. Inspect
the run, tag commit, draft state, assets, checksums and provenance. Record the
repository, version, commit and proposed recovery; obtain explicit owner
authorization before recovery writes. Do not move or delete tags, replace
released assets, retry automatically or publish incomplete drafts. Existing
versions remain blocked. If integrity is uncertain, prepare a new version
through a checked PR.

## Action pins and Dependabot

The root `action.yml` is a composite action whose steps never run. It lists each action the shared
workflows use once, pinned to a full SHA. `scripts/build_workflows.py` reads it, and Dependabot
scans it beside the generated workflows, so one PR is meant to bump both and pass `--check`; the
first Dependabot actions PR must confirm that. Updates are weekly and grouped (minor and patch)
with a 14-day cooldown that security updates ignore. Dependabot ignores this repository's own
`ejmlabs/.github` caller pins, which move by hand. Wrangler in `deploy/` is also updated by hand:
edit `deploy/package.json`, run `npm install --package-lock-only --ignore-scripts` there, then
regenerate the workflows.

## Synced templates

`templates/community/`, `templates/lint/` and `templates/agents/` (the shared `ejmlabs-*` skills and
the house rules block) are copied into each repository by `scripts/sync_community.py`,
`scripts/sync_lint.py` and `scripts/sync_agents.py`, and this repository's own
`.agents/skills/ejmlabs-*` copies come from the same templates. Each script's `--check` reports
drift without writing, for example `python3 scripts/sync_agents.py ../REPOSITORY --check`. No
template is embedded in a shared workflow, so changing one moves no pin. The tests hold the
authoring rules. Edit a template, never a synced copy.

## Adopting a new shared revision

1. Merge the revision here and retain the merged commit as the branch `workflow-pins/FULL_SHA`,
   protected against update and deletion with no bypass actors. Callers pin the commit, not the ref.
2. This repository's own PR is checked by the pin its `pr.yml` already has, so a change to what the
   standards enforce must pass that older check. After the merge, one PR moves `pr.yml` and
   `release.yml` to the new SHA and drops the `XAI_API_KEY` declaration.
3. A `pull_request` run takes its workflow from the PR merge ref, so a consumer PR that moves its
   pin is checked by the new pin. Use one PR per consumer that moves every `ejmlabs/.github` pin,
   switches `deploy.yml` to the `secrets: inherit` form, and resyncs the community files and other
   templates. The community templates still describe the previous gate in places: fix them first
   (open follow-up in `openspec/changes/velocity-and-safety-refactor/tasks.md`).
4. After each merge, run `configure_repositories.py --check --repository NAME`.
5. Before claiming a path verified, see it work in GitHub: maintainer auto-admit, a Dependabot PR
   with `gate:approve`, a fork PR notice, `gate:revoke`, conversion to draft, a push that replaces
   the head, a rerun of failed jobs, a stale pending pair, a duplicate release tag, staging and
   production deploys, and a Dependabot actions PR that passes `--check`.

## Public visibility checklist

Audit source refs and history, discussions, reviews, retained Actions logs and artifacts, and
release assets for private data. Review licenses, asset rights and vulnerability findings, bind
the reviewed snapshot to exact source and output identities, and obtain the owner's visibility
decision. Pause Actions and confirm the pause, restore and verify the full-SHA Actions policy and
allowlist while paused, recheck reviewed source and retained output before changing visibility, and
stop on drift.

GitHub cannot set public fork approval while a repository is private, so keep Actions paused across
the change. After publication, require `approval_policy=all_external_contributors`, keep fork
secrets and write tokens disabled, and verify read-only default tokens, main protection and
protected refs. Enable and verify free secret scanning, push protection, private vulnerability
reporting, dependency alerts and security updates. Enable Actions last and read everything back
independently.

The gate does not control other workflow files a PR adds; the standards check only lints them.
Publish shared workflow and source dependencies before public consumers, because public callers
cannot resolve private reusable workflows, and add no private credentials to make a public checkout
work. Do not enable CodeQL default setup or other automatic PR or scheduled checks without a
reviewed plan that preserves human admission and spending controls.

## Acceptance limits

Inspect actual runs, immutable artifacts and source identities before claiming installed behavior.
This repository's own PR runs the pin it already has, so its green check says nothing about the new
caller; a consumer PR that moves its pin runs the new pin. Outside-contributor, fork and Dependabot
events, first real draft releases, duplicate-tag refusal, installers, signing, registry
publication and deployments each need their own GitHub evidence.

## Recovery

For `workflow was not found` before jobs start, inspect the exact caller pin,
access policy and run annotation. A Contents API read alone does not establish
Actions resolution. Restore a missing protected `workflow-pins/FULL_SHA` ref
only to its reviewed commit. Keep caller pins and main protection unchanged;
verify resolution through fresh human admission.

For a stuck pending check, open the run in the status link. If it finished or is gone, add
`gate:approve` (which also records your approval) or push a commit: a stale pending pair is
admitted again. If it still runs, `gate:revoke` stops it first. After a stop, read the head's
statuses: both must be failed with no later success.

Revoke a suspect head, cancel admitted work and inspect its isolated artifacts.
For a failed shared revision, re-pin callers to the previous shared revision
through an ordinary reviewed PR. Do not move a revision or release tag. Keep
budget notifications enabled. Source-release jobs make drafts and do not deploy or
publish packages.
