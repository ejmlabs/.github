# Repository operations

## Permissions and required settings

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

No automated model review runs or is required. Maintainers review every change
themselves before approving. Turning any model review back on, as a status, a
label or an advisory comment, needs the security review's sign-off first.

Default workflow tokens are read-only. Allow only full-SHA actions from the
selected core and dependency setup sources and this shared repository. Enable
bot review recording so an explicit human self-approve can be represented as a
native review via the `gate:approve` label.

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

## Admission and budget controls

Admission is driven by pull request lifecycle fields and collaborator
permissions, not by comment text. Draft PRs spend nothing. A same-repository
non-draft PR whose author is a current human maintainer or admin is admitted
on open, synchronize and ready_for_review. Outsiders and forks are admitted
only when a current human maintainer marks the PR Ready for review. Comment
bodies that contain `/ready` or `/approve` are ignored as control signals.

Solo maintainers self-approve by adding the `gate:approve` label. Trusted
automation records a bot APPROVE for the current head and removes the label.
`gate:revoke` cancels admitted work and dismisses bot approvals for that head.
Label handling uses exact name equality from the labeled event. Later jobs
re-check live PR API state and workflow outputs; they do not parse status
description tokens.

Admission is serialized per PR with cancel-in-progress concurrency. Actions
reruns are rejected. A new commit needs a new admission under the rules above.
Converting back to draft cancels admitted work until Ready again.

| Limit | Bound |
| --- | --- |
| Changed files | 200 |
| Added and deleted lines | 12,000 |
| Preparation | 5 minutes |
| Quality | 45 minutes |
| Separate registry gate | 25 minutes |
| Source handoff artifacts | 3 days |

There is no automated model review. The gate has no model job, no review
status, no review label and no label override, and no job receives a model key.
A GitHub approving review covers every file in the diff including lockfiles,
generated files, images and other assets.

A failed required check blocks merge. These checks cannot prove correctness,
so human review and the other gates remain necessary. Metadata-only PRs remain
fail-closed and require a human review.

Builds receive no model key, source-read secret, deployment credential or
write token. Never reuse a cache produced by PR code in a privileged job.
Never enable step or runner debug logging on this path. The preparation job
rejects runner debug mode before processing sources.

Set a separate workflow execution budget and
alerts. Per-run limits do not cap aggregate spending. Restrict repository
roles and permitted dispatches; organization owners retain control of policy.

## UI owner profile

The explicit `ejm-ui` profile defines the requirements for a future adoption
by the owner of the `@ejm/*` UI contracts, tokens, themes, and shared site tools.
It requires `README.md#development` as the contributor guide and uses the same
four required statuses, human maintainer decisions, exact-commit approval and
revocation rules, spending bounds,
replay rejection, and source-release checks as the
other profiles. It needs no private harness source or cross-repository token.

This is shared policy support, not evidence that a current UI checkout meets
the contract. Its manifests and invoked scripts are not part of this change.
Before adoption, review the exact owner commit against every requirement below
and verify its admitted checks. Do not copy private owner source into public
review evidence. The public source-assembly route requires separate publication
approval and an audited public owner revision before consumer adoption.

This support does not add workflows, protection, secrets, or
community files to UI, and it does not activate checks there. The default
settings rollout remains `.github`, `ejmlabs`, `ejm-cli`, `ejm-harness`, and
`ejm-ide`. UI settings require an explicit `--repository ejm-ui` selection after
reviewed callers are installed on its protected main. Do not run the settings
tool as part of source preparation. Each repository needs its own authorized
adoption and verified settings readback.

The profile emits one Ubuntu 24.04 Quality job with the existing 45-minute
limit, Cargo builds on every runner core, and no repository or model credentials. It installs Node 24
and Rust 1.99.1 with Clippy and rustfmt. It does not install the Cargo audit
binaries used by the other Rust profiles. An adopting owner must provide these
command interfaces. They run in order and stop at the first failure:

```sh
export npm_config_ignore_scripts=true
npm ci --ignore-scripts
npm rebuild node-pty --ignore-scripts=false
npm run check
npm run build
npm run check:rust
node scripts/pack-proof.mjs
```

No shared check caps bundle bytes, download size or dependency count. The commands above belong to each product, which removes its own budgets in its own change; use well-maintained packages where they fit. Load time is the performance bar and each product repository measures it (for example with its own `npm run perf`).

The explicit `node-pty` rebuild is the single dependency lifecycle exception.
It runs only inside admitted credential-free Quality. The owner must lock that
native dependency and verify its Linux rebuild and test use. All other installs,
including any nested packed-consumer install, must preserve disabled lifecycle
scripts. The required packed-consumer proof must use the npm registry and check
six packed public interfaces in a temporary consumer.

The synthetic shell tests in `tests/test_workflows.py` exercise the emitted
command sequence, lifecycle environment and stopping at every failed command.
They do not run private owner scripts or prove UI compatibility, hosted
execution, duration or the coverage of an owner's packed-consumer proof.

The required owner commands must cover source, theme, component, TypeScript,
test, build, terminal, and packed-consumer checks. The profile does
not run model calls, product captures, product honesty checks that require sibling
repositories, or browser rendering acceptance. Those need separately reviewed
immutable product inputs and their own evidence. The separate registry job
continues to run only for `ejm-harness`.

An adopting UI owner must keep one canonical SemVer in `VERSION` and a matching
dated `CHANGELOG.md` entry. Root npm metadata, all eight owned npm packages
(`core`, `demos`, `ink`, `shots`, `site`, `ssg`, `tokens`, and `ui`), their root npm lock entries, and
`crates/ejm-tui` with its Cargo lock entry must match it. Applications, examples,
and nested test fixtures are consumers and do not set the owner's release
version. Adding an owned package requires a reviewed inventory update.

The root and the `demos`, `ink`, `shots` and `site` packages must keep
`private: true`. `core`, `ssg`, `tokens` and `ui` are the public npm set: each may
omit `private` only with `publishConfig` of exactly
`{"access": "public", "provenance": true}`, and `"private": false` is refused. Each
public package must also carry exactly the reviewed `name`, `files`, `main`,
`types`, `exports` and other packing fields (`bin`, `browser`, `module`,
`directories`, `man`, bundled or workspace lists and the pack, publish and install
lifecycle scripts must be absent unless reviewed); the validator checks a digest of them in `scripts/standards.py`, so any
change to a public package's packing manifest needs a new shared revision. The reviewed
`tokens` files reach `assets` only through `assets/fonts`, `assets/brand` and
`assets/icons`, which keeps logos and artwork out of the tarball.
`.github/workflows/publish.yml` is allowed only in `ejm-ui`, as a regular
file whose SHA-256 equals the reviewed hash in `scripts/standards.py`; changing it
needs a new shared revision. All owned packages keep
`SEE LICENSE IN LICENSE`. Each package must name its exact repository directory
and carry a complete scoped `LICENSE` and `THIRD_PARTY_NOTICES.md`. The
software and documentation must retain MIT terms, and brand assets their owners'
reserved rights. The terminal crate must keep MIT metadata and `publish = false`.
Token font notices must preserve the original Manrope and IBM Plex Mono OFL
bytes; the validator checks reviewed hashes against
[independently obtained public notices](../tests/fixtures/font-notices/README.md).
React copies must keep the same complete text after line-ending and trailing-space
normalization. A notice
update requires review of that allowlist. Source-release archives must include
these package notices, font notices, and version manifests with their committed
bytes, including original line endings. The workflow produces source drafts;
it does not publish npm packages, a crate, a binary, or a deployment.

The version and license tests use synthetic owner manifests and scoped licenses.
The public font fixtures separately exercise the unchanged hash allowlist.
Neither fixture set establishes that a private owner checkout satisfies this
contract. That requires the separate review and adoption evidence above.

## Studio quality entry

Studio must provide `scripts/check.mjs` before adopting a shared revision with
this recipe:

```sh
node scripts/check.mjs
npm --prefix site test
npm --prefix site run build
```

The entry belongs to Studio and calls its current internal checks. Shared policy
does not select the asset layout. These commands run in the admitted Quality job
without credentials and stop at the first failure. Keep the entry when replacing
retained assets. Adopt shared revisions through reviewed caller pin updates.
A shared policy test does not prove a hosted Studio run or site deployment.

## CLI quality prerequisites

Only the CLI profile runs `./product/.github/actions/setup-ci` from the exact
admitted source, in the credential-free Quality job. Privileged preparation,
result publication and source-release jobs never execute this
product action. The allowlist accepts only the complete canonical step under
the CLI profile condition.

The action supplies pinned Node/npm, wasm-bindgen, its Rust WebAssembly target,
Chrome and Linux libdbus development files. Keep system installation here;
product checks must not invoke sudo. Guard the browser npm/Playwright setup on
`relay/package.json`: absence skips that step, but a present manifest without
its lockfile fails. Shared jobs set `CARGO_BUILD_JOBS=default`, which overrides
the products' local two-job cap in `.cargo/config.toml`.

Land and verify the setup action before adopting source that needs it. Keep the
working harness pin until a separate reviewed API update passes the complete
consumer gate. Source access, local tests and a shared implementation's review
do not establish successful execution of a product hook. Require admitted
Linux and macOS Quality evidence for the affected consumer.

## CLI harness pin updates

The CLI's path dependencies and `Cargo.lock` must describe the same harness
source. Revisions that select the dependency from trusted CLI base `main`
cannot test a proposed pin and resolved lock together when the new lock is
incompatible with that older source. A pin-only pass does not establish that
the proposed pair works.

Revisions containing the CLI selector read `.github/harness-revision` from the
exact admitted CLI Git commit. The pin must be an ordinary Git blob containing
a full lowercase 40-character commit SHA with at most one final newline.
Git object lookup cannot follow a submitted symlink or symlinked parent.

Trusted preparation queries only `ejmlabs/ejm-harness` through the official
GitHub API. It requires `main` to be protected and records its exact commit.
The selected pin must equal that commit or be its ancestor. Missing,
inaccessible, unprotected, malformed or divergent source fails preparation.
API reads are bounded; later changes to harness `main` cannot substitute a
different checked-out revision.

Preparation verifies the actual harness checkout against the selected pin.
The source handoff carries that archive. Quality uses it with the admitted CLI
source and lockfile. IDE retains trusted-base harness selection.

Adopt this selector separately from a dependency update:

1. Check the shared policy tests, generated workflows and actionlint. Obtain
   a complete hosted review and all required protected checks, then retain
   the exact implementation under `workflow-pins/FULL_SHA`.
2. Adopt the retained workflow revision in a protected CLI caller change while
   keeping its working harness pin and lock.
3. Submit the new harness pin and matching lock together, based on reviewed
   protected harness history. Require fresh exact-head human decisions and the
   full hosted consumer gate.

Source changes do not activate a consumer's pinned caller. Source ancestry
establishes where a dependency was published; local and hosted product checks
remain necessary evidence for its behavior. The branch and comparison APIs
require only Contents read access. See GitHub's
[branch API](https://docs.github.com/en/rest/branches/branches#get-a-branch) and
[comparison API](https://docs.github.com/en/rest/commits/commits#compare-two-commits).

The current caller pin still requires the previous root community files.
Keep them until a reviewed caller pin includes the updated templates, then
re-sync with `scripts/sync_community.py` in the pin adoption PR.

## Harness Linux keyring prerequisites

The harness Quality profile installs `pkg-config` and `libdbus-1-dev` on Linux
with recommended packages disabled, before Rust tools and the product gate.
It starts no key service and supplies no credentials. Other platforms and
privileged jobs skip this step. Adopt a reviewed shared revision containing
this setup before adopting a harness API that needs it. Keep system installers
out of `scripts/check`.

The harness profile installs locked root and registry npm dependencies with
lifecycle scripts disabled before `./scripts/check`. Root ESLint includes
registry sources. The separate registry gate checks native, WebAssembly,
schema, auth and build behavior. Keep the product guide and its check script
in sync when those prerequisites change.

## Gate speed and the trusted build cache

Every Quality matrix entry starts at once; no job waits for a matrix slot.
`cargo-deny` and `cargo-machete` come from their prebuilt release archives,
each checked against the SHA-256 recorded in `scripts/tools.py` before the
binary is extracted. A new tool version needs new reviewed digests. Only
`worker-build`, which publishes no binaries, still compiles in the registry
job.

Rust profiles (`ejm-cli`, `ejm-harness`, `ejm-ide`, `ejm-ui`) may adopt a
build cache by adding the canonical `cache.yml` caller. On each push to main
it runs the shared `warm-cache.yml`, which checks out that main commit and its
pinned harness and UI sources in the gate's layout, runs the same toolchain
and gate commands as Quality and the registry gate, and saves the Cargo
registry and target directories under `gate-<job>-<OS>-<main SHA>`. It holds
`contents: read` and no secrets.

The gate never saves a cache. Quality and the registry gate restore only the
exact key for the admitted PR's base commit and delete whatever a prefix match
or miss leaves behind. Extraction marks every admitted source file newer than
any restored build, so Cargo rebuilds every local crate and reuses only
dependency artifacts. A miss costs a cold build, never a wrong result.
Release builds (`build.yml`) never restore a cache.

Residual risk: a job running admitted PR code can hold the job's cache token.
Such code could write the key for a main commit before that commit's warm job
saves it, and a later gate on that base would restore it. Human admission of
the exact head is the boundary that keeps such code out. Remove `cache.yml`
from a product to stop restores there.

## Missing model key acceptance staging

The shared-only caller supports label `acceptance:missing-model-key`. It was
used to check that a missing model key failed closed. No model key or model job
remains, so the fixture has no remaining purpose; its exact form stays
accepted by the standards check for one generation and is removed with the
previous caller form. The normal and fixture routes are restricted to
`ejmlabs/.github` and pin the same immutable governance revision. With the
label, the fixture forwards no secrets; without it, the normal route forwards
its declared secrets. Neither uses `secrets: inherit`. Changing the label
starts no workflow. Product callers do not accept this fixture form.

For active revocation, add the `gate:revoke` label. Verify cancellation of the
original step, job and run, failed Quality and Repository standards statuses,
native approval dismissal and no later successful status from finalization.
The revoke event must skip source preparation and builds. In-progress metadata
alone does not prove the hold was active.

## Credentials

No job receives a model key. The shared workflow no longer declares
`XAI_API_KEY`. After every caller is on a pin that omits the secret, the owner
removes the stored model key secret
and closes or empties the prepaid provider account.

Public harness source needs no private checkout token. Pin its exact revision
in `.github/harness-revision`; trusted preparation archives it for the
credential-free build jobs. Remove unused source-read secrets once
anonymous access to every required pin is verified. Never replace a missing
source contract with a broad personal token.

Legacy callers declare `EJM_HARNESS_TOKEN` for private source access. Where
such access is explicitly authorized, use an expiring fine-grained token with
Contents read for the one dependency repository. Successful checkout and
secret timestamps do not prove scope or expiry. Never give that token to PR
code or infer authorization for another private dependency.

## Public UI source assembly

The implementation supports an optional `.github/ui-source.json` in consumers:

```json
{
  "repository": "ejmlabs/ejm-ui",
  "revision": "FULL_40_CHARACTER_LOWERCASE_COMMIT_SHA"
}
```

The repository name is fixed. Branches, tags, extra fields, symlink metadata and
files above 1,024 bytes fail. The selected revision must name a commit. Publish
and audit the UI owner source before consumer adoption; this route adds no
private source secret or fallback token.

Trusted preparation reads the dependency from protected main, validates the
proposed metadata without using it to select a checkout, then archives the
exact committed UI tree with the existing source file and byte bounds. Archive
attributes cannot omit or rewrite files. Product and dependency archives share
one immutable artifact identity. Credential-free Quality and registry jobs
receive that data. Those build
jobs install the UI lockfile with lifecycle scripts disabled when needed. No
product script executes in source preparation or result publication.

Adopt this workflow through a reviewed caller pin first. Add or rotate the UI
manifest while the product still works with the trusted old dependency. Its
adoption PR is checked with the old protected-main pin, so that run does not
establish execution of the new UI revision. Verify a fresh admitted PR against
the installed pin before adopting new UI APIs or removing the live kit. Pin
changes and owner package checks do not establish site publication.

Consumers without a manifest keep their existing dependency setup. UI
governance, public source approval, package publication and site deployment
remain separate tasks; this shared implementation enables none by itself.

## Site deploys

Site repositories (`ejmlabs`, `ejm-cli`, `ejm-harness`, `ejm-ide`, `ejm-ui`)
adopt continuous deploys by adding the canonical `deploy.yml` caller. Each push
to main runs the shared `deploy-site.yml`:

1. `build` checks out that main commit and main's pinned `ejm-ui`, runs the
   site's build commands from `scripts/deploy.py` with `contents: read` and no
   secrets, and uploads the deployable files as one artifact.
2. `staging` deploys those files with `wrangler deploy --env staging`.
3. `production` waits on the `production` environment's required reviewer,
   then deploys the same files with the top-level config.

The deploy jobs check out and run no product code. They install Wrangler from
the lockfile in `deploy/`, embedded in the workflow, with install scripts
disabled. `scripts/deploy.py` refuses any config that declares a Wrangler
`build` command. It refuses a staging deploy unless `env.staging` names its
own Worker and its own routes, because `--env staging` otherwise inherits the
production custom domain. Before a production deploy it reads the environment
and fails unless a human reviewer is required. GitHub creates a missing
environment with no rules, so create both environments before adopting the
caller:

- `staging`: deployments from protected branches only, no reviewer.
- `production`: deployments from protected branches only, at least one
  required reviewer.
- A `CLOUDFLARE_API_TOKEN` environment secret in each, scoped to the account's
  Workers scripts, routes and custom domains on `ejmlabs.com`, plus R2 read
  for sites that bind a bucket.

A newer main commit replaces a production deploy still waiting for approval.
Use fresh staging hostnames: a custom domain whose DNS record already exists
makes Wrangler prompt, and CI cannot answer. Roll back by redeploying an
earlier Worker version in Cloudflare or by approving an earlier run's
production job while it is still available.

## Draft source releases

The shared workflow creates source drafts from an exact checked protected
main commit, the repository's SemVer `VERSION` and dated release notes. See
[Releasing](../RELEASING.md) for the dispatch and artifact contract.

## Attaching built files

`ejm-cli` and `ejm-harness` may ship native builds. A repository opts in by adding
`.github/workflows/build.yml`; the standards check then requires the canonical
native `release.yml` (verify, Draft release, attach, one commit input, one pin)
and a build workflow that:

- runs only on `workflow_dispatch` and pushes to `main`;
- sets top-level `permissions: contents: read` and no other permissions;
- uses no secrets, tokens, environments or pull-request triggers;
- pins every action to a full commit SHA;
- uploads exactly one artifact named `release-files`: the release files plus one
  combined `build-sha256.txt` in `sha256sum` format, names `[A-Za-z0-9._-]`, no
  subdirectories. Per-platform jobs upload their own differently named
  artifacts, which a final job collects into `release-files`; attach ignores the rest.

Without `build.yml` the plain source-release caller is required. The jobs are:

1. `verify-build.yml` (`actions: read`) before Draft release. It requires a
   completed, successful run of `build.yml` whose `head_sha` is the release
   commit, on main in the same repository, with a `release-files` artifact, so a
   failed smoke check never burns the tag.
2. `attach-assets.yml` after Draft release (`needs`). It holds the release write
   token and checks out and runs no project code. It re-verifies the run, the
   lightweight `vVERSION` tag and the single draft release, downloads
   `release-files`, recomputes every SHA-256 against `build-sha256.txt`, and
   uploads the files, then an extended `SHA256SUMS`, to the draft. It refuses a
   changed digest, an extra, missing or linked file, and a built file that would
   replace an existing asset. `attest` adds build provenance attestation; this is
   provenance, not code signing.

The caller pins all shared workflows to one reviewed commit of this repository. Signing and notarization are not claimed by either workflow.

This revision's canonical PR and release callers both pin
`6717b433c462e01abaed86e2118e4843827598cb`. Its archive validator preserves
committed notice bytes. The earlier `c4f2873ef0eef5bc3c7d75cf71fa3489a911d134`
pin normalizes line endings in expected notices. An original CRLF notice then
fails validation even though the archive contains its exact committed bytes.
Adopt the corrected caller pin through review; preserve the original notices.

The coupled PR caller update also adopts the reviewed CLI harness selector,
optional public UI source handoff, and UI owner profile. Shared checks retain
their human admission, automated review gate, required statuses, and separate
missing-model-key route. Studio keeps its public `scripts/check.mjs` quality
entry. This
change adds no UI source pin and updates no product caller. It does not prove a first draft release or
duplicate-tag refusal; those paths still require separate authorized runs.

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

## Strict lint layer

`templates/lint/` holds the strict lint layer every repository shares: the ESLint
flat config `eslint.strict.mjs`, the ruff configuration `ruff.strict.toml`, the
ShellCheck configuration `.shellcheckrc` and the Rust lint tables
`cargo-lints.toml`. TypeScript extends the published `@tsconfig/strictest`
package and mypy runs with `strict = true`; neither needs a file here. Nothing
under `templates/lint/` is embedded in a shared workflow, so changing it moves
no pin.

Copy the files into a repository checkout, or check a checkout for drift:

```
python3 scripts/sync_lint.py ../repository eslint.strict.mjs ruff.strict.toml .shellcheckrc
python3 scripts/sync_lint.py ../repository eslint.strict.mjs --check
python3 scripts/sync_lint.py ../repository cargo-lints:Cargo.toml --check
```

The Rust tables are pasted into `Cargo.toml` by hand. `--check` fails when one
is missing or set to a lower level (`forbid` over `deny` is allowed). The script
refuses symlinks. Each repository runs these tools from its own check command,
so the shared gate is unchanged. A suppression names one rule and gives a reason;
file-wide and unlimited disables, `@ts-ignore`, `@ts-expect-error`,
`@ts-nocheck` and explicit `any` are not used.

The scripts and tests here are held to the layer: `tests/test_strict.py` runs
`ruff check` and `mypy` (strict) from the locked development group in
`pyproject.toml`, so the gate's unit-test step enforces them. It fails when
`uv` is missing. Run `uv run --locked --group dev ruff check .` and
`uv run --locked --group dev mypy` locally.

## Shared agent guidance

`templates/agents/` holds the guidance every repository's coding agents load:
the shared `ejmlabs-*` skills under `skills/` and the house rules block in
`house-rules.md`. Like the lint layer, nothing here is embedded in a shared
workflow, so changing it moves no pin.

A consumer's `AGENTS.md` carries the house rules between
`<!-- ejmlabs:house-rules:start -->` and `<!-- ejmlabs:house-rules:end -->`
markers and routes every skill by its `.agents/skills/NAME/SKILL.md` path.
Every repository gets the core skills (`ejmlabs-workflow`,
`ejmlabs-engineering`, `ejmlabs-security`, `ejmlabs-testing`,
`ejmlabs-writing`); the stack skills for each language and platform a
repository uses (the other `ejmlabs-*` directories under
`templates/agents/skills/`) are added by name and kept on every later sync.

```
python3 scripts/sync_agents.py ../repository ejmlabs-rust ejmlabs-cloudflare
python3 scripts/sync_agents.py ../repository --check
```

The script copies the skills verbatim, replaces the house rules block, and
gives every skill in `.agents/skills/` a relative link at
`.claude/skills/NAME`, because Claude Code discovers project skills only
there. It removes dangling links and refuses symlinked targets and real
directories where a link belongs. `--check` reports a changed or unknown
`ejmlabs-*` skill, a changed block, a missing link and a skill that
`AGENTS.md` does not route. `tests/test_sync_agents.py` also holds the shared
skills to the authoring rules: a description of at most 300 characters, a
body of at most 100 lines, links only inside the skill, and no em dashes.

The templates are formatted with Prettier at 100 columns with prose wrap
preserved, and their code samples with ruff at 88 columns, so a consumer's
formatter passes them; the house rules block is stable under Prettier. Consumers exclude
`.agents/skills/ejmlabs-*/` from their own formatter, because `--check`, not
the formatter, owns those copies.

## Bootstrap and rollout

1. Test the shared implementation and retain its exact commit under
   `workflow-pins/FULL_SHA`. Protect `workflow-pins/*` against updates and
   deletion with no bypass actors. Callers still pin the commit, not the ref.
2. Add callers pinned to that retained revision. A main `pull_request` workflow
   must exist before GitHub can deliver lifecycle and label events to it.
3. Pause existing automatic workflows during initial adoption. Obtain explicit
   acceptance of the exact bootstrap source; do not silently weaken active
   protection. Review consumer updates without overwriting concurrent work.
4. Read back main protection, Actions policy, ref rules, dependency alerts and
   security controls. Test the installed caller through a fresh admitted PR.
5. Test maintainer auto-admit, outsider Ready ignored, `gate:approve`,
   `gate:revoke`, stale pushes, failed checks and duplicate release tags in
   GitHub before claiming those paths verified. Local policy tests do not
   establish event delivery.

### Ready-for-review admission

Each repository's required **Repository standards** check runs the standards
embedded at the pin on its main, so a change is checked by the previous pin's
standards. Roll out in this order, each step through an ordinary admitted PR
with no administrator bypass:

1. Merge this shared revision here while this repository's own `pr.yml` stays
   on the previous comment-only caller form pinned to the live review-free
   revision. Retain the merged commit under `workflow-pins/FULL_SHA`.
2. In every caller, including this repository's own `pr.yml`, change only the
   governance and release pins to the new revision, keeping the previous
   comment-only caller form. Create the `gate:approve` and `gate:revoke`
   labels (the settings script does this).
3. Once main runs the new pin, change each caller to the Ready-for-review
   form (`pull_request` lifecycle + labeled). A pin change and a form change
   in one PR fail the previous standards, so they are separate PRs.
4. The owner sets required checks to Quality and Repository standards only,
   keeps `enforce_admins` and one approving review, and reads that back.
5. The next shared revision removes the previous comment-only caller form
   from the standards check.

### Removing the AI review

Each repository's required **Repository standards** check runs the standards
embedded at the pin on its main, so a change is checked by the previous pin's
standards. Roll out in this order, each step through an ordinary admitted PR
with no administrator bypass:

1. The owner removes **AI review** from the required checks on main in all six
   repositories and reads back that exactly four remain. This comes first so
   no repository ever requires a status the gate no longer publishes. Do it in
   the repository settings UI, or with the settings script from the removal
   commit's tree. Do not run `scripts/configure_repositories.py` from main
   until the removal has merged: main's script still sets five contexts.
2. Merge the standards change here first (the commit that accepts both caller
   forms and a shared workflow with or without the review job), then change
   this repository's own `pr.yml` pins to it. The previous standards reject a
   shared workflow without the review job, so the removal cannot be the first
   change. Retain each merged commit under `workflow-pins/FULL_SHA`.
3. Merge the removal here. It is checked by the standards from step 2.
4. In every caller, including this repository's own `pr.yml`, change only the
   governance and release pins to the removal commit, keeping the previous
   caller form. The previous standards accept that PR; the new standards
   accept both forms, so the order across repositories is free.
5. Once main runs the new pin, change each caller to the new form (no
   `pull_request_target` trigger, no `XAI_API_KEY` forward). A pin change and a
   form change in one PR fail the previous standards, so they are separate PRs.
6. The owner deletes the `legacy-review` environment (its secret and branch
   rule) in each repository and closes the prepaid provider
   account.
7. The next shared revision removes the previous caller form, the optional
   secret declaration and the fixture form from the standards check.

## Public visibility checklist

Audit current source refs and history, discussions, reviews, retained Actions
logs and artifacts, and release assets for private data. Review licenses,
asset rights and vulnerability findings. Bind the reviewed snapshot to exact
source and output identities. Obtain the owner's visibility decision.

Pause Actions and confirm the pause. Restore and verify the complete selected,
full-SHA Actions policy and allowlist while paused. Recheck reviewed source and
retained output after the pause and before changing visibility. Stop on drift.

After publication, require `approval_policy=all_external_contributors`, keep
fork secrets and write tokens disabled, and verify read-only default tokens,
main protection and protected refs. Enable and verify available free secret
scanning, push protection, private vulnerability reporting, dependency alerts
and security updates. Restore the complete selected policy and allowlist while
paused, then enable Actions last and read everything back independently.

GitHub cannot set public fork approval while a repository is private. Keeping
Actions paused across the change closes that policy gap. The trusted comment
caller does not control other workflow files added by a PR. GitHub-managed
security or dependency tasks may still run while repository Actions is paused;
inspect any new retained output.

Publish shared workflow and source dependencies before public consumers.
Public callers cannot resolve private reusable workflows. Do not add private
credentials to make a public source checkout work. Package publication, native
signing and deployment need their own decisions and checks.

Do not enable CodeQL default setup or other automatic PR/scheduled checks
without a reviewed plan that preserves human admission and spending controls.
Do not enroll private repositories in billed security products by assumption.
An organization owner can require two-factor authentication after checking
member readiness and recovery access; that is a separate access change.

## Acceptance limits

Inspect actual runs, immutable artifacts and source identities before
claiming installed behavior. A green adoption PR may have run the previous
caller; it does not prove execution of the new one. Native approvals must
match the admitted head. Recheck every required status, native approval and exact head before
normal protected merge.

Keep genuine outside-contributor, bot, nonmaintainer and fork event tests open
until their own identities and GitHub evidence exist. Maintainer tests do not
establish those paths. First real draft releases, duplicate-tag refusal,
installers, signing, registry publication and deployment also need their own
evidence. Product-specific vulnerability and platform limits belong in the
product's security and contributor guides.

## Decision log

- **2026-10-26, AI review removed.** The owner turned off the AI PR reviewer
  because it added too much friction for too little value. The review job,
  its status, the security label and its override are removed; four statuses
  are required and enforced for administrators. This supersedes the
  documented reviewer gating decision below. Re-enabling any model review
  needs the security review's sign-off first.
- **2026-10-25, documented reviewer gating.** The owner decided to replace
  the custom review gate with the reviewer's documented GitHub Action runner
  and label blocking. The custom result adapter, two passes, coverage rules,
  negative-answer list and static review data were removed. This supersedes
  the interim decision below.
- **2026-10-25, deterministically covered files (interim).** The owner
  approved at 02:14 PT the two narrow checks `lock-manifest-mirror v1` and
  `svg-allowlist v1` described above, ahead of the full deterministically
  covered files requirement. Scope is exactly those two checks; all other
  skipped content stays fail-closed. The security lead ratifies or reverts
  this decision on 2026-10-25. Closing the binary, rename and mode content
  gap is a hard condition for the next release.

## Recovery

For `workflow was not found` before jobs start, inspect the exact caller pin,
access policy and run annotation. A Contents API read alone does not establish
Actions resolution. Restore a missing protected `workflow-pins/FULL_SHA` ref
only to its reviewed commit. Keep caller pins and main protection unchanged;
verify resolution through fresh human admission.

Revoke a suspect head, cancel admitted work and inspect its isolated artifacts.
For a failed shared revision, re-pin callers to the previous shared revision
through an ordinary reviewed PR. Do not move a revision or release tag. Keep
budget notifications enabled. Source-release jobs make drafts and do not deploy or
publish packages.
