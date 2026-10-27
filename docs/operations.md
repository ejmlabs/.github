# Repository operations

## Permissions and required settings

Protect main with PRs, one native approval recorded from an explicit human
maintainer decision, and five strict required statuses bound to GitHub Actions:
Human readiness, Maintainer approval, Quality, Repository standards and AI
review. Require resolved conversations, linear history and stale approval
dismissal. Enforce administrators. Block force pushes and branch deletion. Use
squash merges and delete merged branches.

Default workflow tokens are read-only. Allow only full-SHA actions from the
selected core and dependency setup sources and this shared repository. Enable
bot review recording so an explicit human approval can be represented as a
native review, including self approval.

Every account with write access must be a human with maintain or admin
permission. The settings tool rejects ordinary writers and bots. GitHub
Actions identity alone cannot prove which workflow published a status: a
writer can add a branch workflow with that identity. Before granting ordinary
write access, move required result publication to a dedicated GitHub App with
credentials confined to a protected environment.

Revoke open PR decisions before removing or demoting a maintainer. Commands,
finalization and releases check current roles, but GitHub sends no continuous
role-change event to this pipeline. Organization administrators remain trusted
because they can change repository policy.

## Admission and budget controls

Trusted main handles issue-comment events. Bot and unrelated comments are
filtered before a runner starts. Admission checks the human's current
maintain/admin role, full current head, non-draft PR, main target and original
command. Decisions must be separate, unedited comments. New commits require
new decisions.
The head repository must match the base repository. Fork PRs and deleted-fork
heads require manual review instead of automated admission.

Admission is serialized per PR. Replayed events and Actions reruns are
rejected; each command is consumed once. A commit can be readmitted only after
explicit revocation and a new human command.

| Limit | Bound |
| --- | --- |
| Changed files | 200 |
| Added and deleted lines | 12,000 |
| Preparation | 5 minutes |
| Quality | 45 minutes |
| Separate registry gate | 25 minutes |
| AI review job | 12 minutes |
| Each model call | 225 seconds |
| Source handoff artifacts | 3 days |

The AI review gate uses the pinned open-source reviewer's documented GitHub
Action setup and label blocking, with no custom result rules:

- `ai` (needs admission, protected environment `legacy-review`) rechecks
  admission, requires the model key, installs the hash-locked reviewer, runs
  its GitHub Action runner for the admitted PR and rechecks admission. Only
  review runs, at high reasoning effort with no fallback model. The runner's
  fail-on-tool-errors setting stays at its default, so the job fails when no
  review happens. Its token has `contents: read`, `pull-requests: write` (for
  the review comment and labels) and `statuses: read`. It reads the PR through
  the API and never checks out or runs PR code. File handling and prompts are
  the reviewer's defaults, plus one extra instruction: the review is told not
  to report a changed pin of this repository's shared workflow
  (`ejmlabs/.github/.github/workflows/...@` a full 40-character hash, or the
  matching `standards-ref`) as missing context or a security concern, because
  it never sees those workflows. It is still told to report other references,
  moves to an older revision, and changes that widen permissions, secrets or
  triggers. The instruction is guidance, not a check: it does not verify where
  the pinned commit came from, so the maintainer must confirm the commit is
  retained under `workflow-pins/FULL_SHA` before `/approve`. The model context cap stays 160,000 tokens and the
  output cap 16,000. Repository and global reviewer settings files are
  ignored. The reviewer's documented action output (`review`, this run's
  review data) is exposed as the job output.
- The review publishes the reviewer's own labels: `Possible security concern`
  and `Review effort N/5`, and a merge recommendation in its comment.
- `labels` (needs `ai`, `pull-requests: read`) receives that output through
  its environment only, never in a script. It fails when the output is missing
  or unparsable, has no security verdict, or the verdict is not "no" under
  the reviewer's own negative-answer rule (empty, no, none or false). The
  reviewer applies the same rule to set its label, so removing the label
  before this job runs cannot pass. It also fails while the PR carries the
  `Possible security concern` label. Effort labels and the merge
  recommendation are advisory.
- `finish` publishes **AI review** as success only when both jobs passed for
  the admitted commit. A `labels` failure gets the fixed description "Blocked
  by the review's security verdict or label; a maintainer may remove the
  label to override".
- Override: a maintainer reviews the concern and removes the label. GitHub
  records the removal in the PR timeline. Callers also trigger on
  `pull_request_target` `unlabeled`, which runs the `override` job from
  trusted main with no secrets, no checkout and `statuses: write`. It changes
  **AI review** to success only when the current head's status is that
  label-blocked failure, the removed label is `Possible security concern`,
  the remover is a current human maintain or admin user, and no blocking
  label remains. It never runs before a completed review of the current head.
  Any other removal leaves the status unchanged. If the label is absent, for
  example because publication failed or the verdict was missing, a maintainer
  adds it and then removes it.

`scripts/configure_repositories.py` creates the `Possible security concern`
label and reads it back, because the review token may be unable to create it.

Automated review covers only what the reviewer sends to the model. It does not
cover files the reviewer always excludes (lockfiles such as
`package-lock.json`, `pnpm-lock.yaml` and `yarn.lock`, minified files and
maps, images, SVG and other assets, binaries) or files clipped by the token
budget. The review comment's coverage footer lists files left out. Maintainer
approval must cover them: inspect every excluded or clipped file, especially
lockfile `resolved` and `integrity` changes, before `/approve`. This is an
owner decision to keep the reviewer's default file handling.

The model reads attacker-controlled PR title, description, commits and diff,
which can steer its security verdict to "no". This residual risk is accepted;
human Maintainer approval is the backstop.

A failed required check blocks merge. These checks cannot prove correctness,
so human review and the other gates remain necessary. Metadata-only PRs remain
fail-closed and require a human review.

Builds receive no model key, source-read secret, deployment credential or
write token. Never reuse a cache produced by PR code in a privileged job.
Installation has no token or model key. Only the review step receives the model
key and the job token. Use INFO logging. Never enable step or runner debug
logging on this path. Preparation and review jobs reject runner debug mode
before processing sources or using the model key.

Use only provider prepaid credits on a dedicated account, invoiced billing limit $0,
automatic top-up off, and an ACL-restricted key limited to the configured model and chat
endpoint, with request and token rate limits. Review provider audit logs weekly.
The service sends alerts at 50% and 80% of the credit balance. Hostile diffs
reaching the provider are an accepted defensive-use risk. These provider-side
controls are REQUIRED. The model token cap is 160,000 and the output cap
16,000; files clipped by the cap are listed in the review comment and need
human review.
The prepaid balance is raised by stage and is currently $50.
Set a separate workflow execution budget and
alerts. Per-run limits do not cap aggregate spending. Restrict repository
roles and permitted dispatches; organization owners retain control of policy.

## UI owner profile

The explicit `ejm-ui` profile defines the requirements for a future adoption
by the owner of the `@ejm/*` UI contracts, tokens, themes, and shared site tools.
It requires `README.md#development` as the contributor guide and uses the same
five required statuses, human maintainer decisions, exact-commit approval and
revocation rules, the automated review gate, spending bounds,
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
limit, two Cargo build jobs, and no repository or model credentials. It installs Node 24
and Rust 1.99.1 with Clippy and rustfmt. It does not install the Cargo audit
binaries used by the other Rust profiles. An adopting owner must provide these
command interfaces. They run in order and stop at the first failure:

```sh
export npm_config_ignore_scripts=true
npm ci --ignore-scripts
npm rebuild node-pty --ignore-scripts=false
npm run check
npm run build
node scripts/size.mjs
npm run size -w @ejm/demos
npm run check:rust
node scripts/pack-proof.mjs
```

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
test, build, bundle-size, terminal, and packed-consumer checks. The profile does
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
AI review, result publication and source-release jobs never execute this
product action. The allowlist accepts only the complete canonical step under
the CLI profile condition.

The action supplies pinned Node/npm, wasm-bindgen, its Rust WebAssembly target,
Chrome and Linux libdbus development files. Keep system installation here;
product checks must not invoke sudo. Guard the browser npm/Playwright setup on
`relay/package.json`: absence skips that step, but a present manifest without
its lockfile fails. Keep Cargo build jobs at two.

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

## Missing model key acceptance staging

The shared-only caller supports label `acceptance:missing-model-key`. The
normal and fixture routes are restricted to `ejmlabs/.github` and pin the same
immutable governance revision. With the label, the fixture forwards no
secrets; without it, the normal route forwards its declared secrets. Neither
uses `secrets: inherit`. Changing the label starts no workflow. Product callers
do not accept this fixture form.

Use a dedicated, unmerged acceptance PR with fresh exact-head human readiness
and approval. Verify that the model job stops at the missing-key guard before
the reviewer runs. Inspect step states, all five statuses and the native review.
Keep the fixture unmerged and remove its label when closing it.

For active revocation, put a bounded hold in credential-free Quality and
require a flushed log marker before the exact-head revoke comment. Verify
cancellation of the original step, job and run, failed human statuses, native
approval dismissal and no later successful human status from finalization.
The revoke event must skip source preparation, builds and AI. Model steps must
remain skipped or unstarted. In-progress metadata alone does not prove the
hold was active.

## Credentials

Store the review model key only as an environment secret of `legacy-review`.
Restrict that environment's deployment branches to main only. Never store the
review model key as a repository or organization secret. Enforce the required
prepaid-credit controls. Missing keys fail closed. Rotate a leaked key at the provider, remove its stored value,
audit affected runs and readmit work only after containment.

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

## Bootstrap and rollout

1. Test the shared implementation and retain its exact commit under
   `workflow-pins/FULL_SHA`. Protect `workflow-pins/*` against updates and
   deletion with no bypass actors. Callers still pin the commit, not the ref.
2. Add callers pinned to that retained revision. A main comment workflow must
   exist before GitHub can deliver PR comment events to it.
3. Pause existing automatic workflows during initial adoption. Obtain explicit
   acceptance of the exact bootstrap source; do not silently weaken active
   protection. Review consumer updates without overwriting concurrent work.
4. Read back main protection, Actions policy, ref rules, dependency alerts and
   security controls. Test the installed caller through a fresh admitted PR.
5. Test human readiness, stale pushes, self approval, revocation, missing keys,
   failed checks and duplicate release tags in GitHub before claiming those
   paths verified. Local policy tests do not establish event delivery.

### Adopting the documented reviewer gate

The label-removal trigger changes the canonical caller, and each repository's
required **Repository standards** check runs the standards embedded at the pin
on its main. Adopt in three steps, each through an ordinary admitted PR with
no administrator bypass:

1. Merge the shared change here and retain its commit under
   `workflow-pins/FULL_SHA`.
2. In every caller, including this repository's own `pr.yml`, change only the
   governance and release pins to that commit. Keep the old caller form and
   the old `CONTRIBUTING.md`; the old standards accept them.
3. Once main runs the new pin, change the caller to the new form (the
   `pull_request_target` `unlabeled` trigger and job condition) and run
   `scripts/sync_community.py` for `CONTRIBUTING.md` in the same PR. The new
   standards accept it.

Between steps 2 and 3, other PRs in that repository fail **Repository
standards** and the label override is unavailable, because label removal
starts no workflow. Keep that window short and land step 3 first.

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

Inspect actual runs, immutable artifacts, reviewer transcripts and source
identities before claiming installed behavior. A green adoption PR may have
run the previous caller; it does not prove execution of the new one. Actual
reviews must match the admitted head. Recheck every required status, native approval and exact head before
normal protected merge.

Keep genuine outside-contributor, bot, nonmaintainer and fork event tests open
until their own identities and GitHub evidence exist. Maintainer tests do not
establish those paths. First real draft releases, duplicate-tag refusal,
installers, signing, registry publication and deployment also need their own
evidence. Product-specific vulnerability and platform limits belong in the
product's security and contributor guides.

## Decision log

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
