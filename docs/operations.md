# Repository operations

## Permissions and required settings

Protect main with PRs, one native approval recorded from an explicit human
maintainer decision, and five strict required statuses bound to GitHub Actions:
Human readiness, Maintainer approval, Quality, Repository standards and AI
review. Require resolved conversations, linear history and stale approval
dismissal. Enforce administrators. Block force pushes and branch deletion. Use
squash merges and delete merged branches.

Default workflow tokens are read-only. Allow only full-SHA actions from the
selected sources: `actions/*`, `astral-sh/setup-uv`, `openai/codex-action` and
this shared repository. Enable bot review recording so an explicit human
approval can be represented as a native review, including self approval.

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

Admission is serialized per PR. Replayed events and Actions reruns are
rejected; each command is consumed once. A commit can be readmitted only after
explicit revocation and a new human command.

| Limit | Bound |
| --- | --- |
| Changed files | 200 |
| Added and deleted lines | 12,000 |
| Diff bytes | 1 MB |
| Preparation | 5 minutes |
| Quality | 45 minutes |
| Separate registry gate | 25 minutes |
| Each AI review | 9 minutes within a 12-minute job |
| Model output | 64 KB and 50 findings |
| Review artifacts | 7 days |
| Source handoff artifacts | 3 days |

Two independent Codex `gpt-6.1-sol` reviews run serially at medium effort,
without automatic model retries. Critical, high and medium findings block;
low findings are advisory. A failed required check blocks merge.

Revisions with the completion guard require `complete` as a JSON boolean and
accept only `true`. Missing, nonboolean or false values fail, even with no
findings. Missing review source must produce an incomplete result. Completion
cannot be inferred from a successful job or from prose. A model can still
misstate completion, so human review and the other gates remain necessary.
Older pinned revisions do not gain new validation automatically.

Builds receive no model key, source-read secret, deployment credential or
write token. Never reuse a cache produced by PR code in a privileged job.
The Codex step clears inherited `GH_TOKEN` and `GITHUB_TOKEN`. The pinned action
performs its internal permission check and supplies the OpenAI key through an
isolated proxy. Read-only execution limits writes, not filesystem reads;
keep unrelated credentials out of the job.

Set a dedicated OpenAI project spending limit and GitHub Actions budget and
alerts. Per-run limits do not cap aggregate spending. Restrict repository
roles and permitted dispatches; organization owners retain control of policy.

## UI owner profile

The explicit `ejm-ui` profile defines the requirements for a future adoption
by the owner of the `@ejm/*` UI contracts, tokens, themes, and shared site tools.
It requires `README.md#development` as the contributor guide and uses the same
five required statuses, human maintainer decisions, exact-commit approval and
revocation rules, two serial `gpt-6.1-sol` medium
reviews, spending bounds, replay rejection, and source-release checks as the
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

The root and owned npm packages must keep `private: true` and
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

## Static workflow review data

Before changing a caller pin, include the exact old and new implementations
as bounded review data. Run the exporter from a local checkout containing
both canonical commits:

```sh
python3 scripts/export_review_context.py \
  --old FULL_OLD_IMPLEMENTATION_SHA \
  --new FULL_NEW_IMPLEMENTATION_SHA \
  --destination /path/to/repository/.github/review-context
```

Use a new destination without symlink parents. For later rotations, export
to fresh staging and replace the old pair in the same PR as both caller pins.
Do not accumulate historical copies.

The exporter reads a fixed set of 16 files: reusable workflows, generator,
runtime scripts, prompt, schema and community templates. It writes ordinary,
nonexecutable files plus commit, tree, blob, mode, size and SHA-256 metadata.
The combined data must fit within 750,000 bytes. It neither fetches nor
executes source, and archive attributes cannot hide selected blobs.

Compare exported bytes with canonical Git objects and protected
`workflow-pins/FULL_SHA` refs before human admission. A local manifest alone
does not establish remote provenance; the installed workflow does not
authenticate these snapshots automatically. The old revision must match the
trusted default caller, and the new revision the proposed callers.

Builds must not import or execute review data. Keep model network and repository
credentials disabled. Keep a pin change unmerged until the required source is
available and both reviews complete.

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

For entry changes, supply the relevant consumer call path as
[bounded Studio source context](../review/consumer-sources/ejmlabs/README.md).
Its manifest pins the public owner commit and each copied blob. Keep these
read-only sources separate from canonical workflow review data, retain their
rights notice, and never execute them in shared checks. Static copies do not
replace the consumer's admitted Quality run.

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
The source handoff binds the dependency revision, tree, protected-main
authority and archive SHA-256 in `context.json`. Quality uses that archive
with the admitted CLI source and lockfile. Both AI passes receive the same
context as static data, with no checkout credential in their model steps.
IDE retains trusted-base harness selection.

Adopt this selector separately from a dependency update:

1. Check the shared policy tests, generated workflows and actionlint. Obtain
   both complete hosted reviews and all required protected checks, then retain
   the exact implementation under `workflow-pins/FULL_SHA`.
2. Adopt the retained workflow revision in a protected CLI caller change while
   keeping its working harness pin and lock. Export and verify the canonical
   old/new workflow source pair for that change.
3. Submit the new harness pin and matching lock together, based on reviewed
   protected harness history. Require fresh exact-head human decisions and the
   full hosted consumer gate.

Source changes do not activate a consumer's pinned caller. Source ancestry
establishes where a dependency was published; local and hosted product checks
remain necessary evidence for its behavior. The branch and comparison APIs
require only Contents read access. See GitHub's
[branch API](https://docs.github.com/en/rest/branches/branches#get-a-branch) and
[comparison API](https://docs.github.com/en/rest/commits/commits#compare-two-commits).

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

## ejm-chess profile

`ejm-chess` is part of the governed public set, with the same human admission,
required statuses, and caller rules as ejm-cli and ejm-harness. It is a
Cloudflare Workers TypeScript application. The repository has no application
code yet; the current work is an OpenSpec plan. The contributor guide is
`README.md#development`. The canonical version is `VERSION` (0.1.0). Package
manifests are not version sources until the application exists, because there
is no package to keep in lockstep.

Quality uses the default Ubuntu 24.04 job. It does not install the Rust
toolchain or Cargo audit tools used by the Rust profiles. The project command
is an explicit no-op (`:`). That is the whole recipe: there is no package
manifest, test script, or Workers configuration to run, and a failing fallback
would block every admitted change. The job still runs the shared Node and uv
setup steps, then succeeds without executing project code. Replace the no-op
in the same change that adds application code.

The profile does not select private harness source. It does not change the
default settings rollout (`.github`, `ejmlabs`, `ejm-cli`, `ejm-harness`, and
`ejm-ide`) and does not install callers or enable Actions by itself.

## Missing model key acceptance staging

The shared-only caller supports label `acceptance:missing-model-key`. The
normal and fixture routes are restricted to `ejmlabs/.github` and pin the same
immutable governance revision. With the label, the fixture forwards no
secrets; without it, the normal route forwards its declared secrets. Neither
uses `secrets: inherit`. Changing the label starts no workflow. Product callers
do not accept this fixture form.

Use a dedicated, unmerged acceptance PR with fresh exact-head human readiness
and approval. Verify that both model jobs stop at the missing-key guard before
Codex runs. Inspect step states, all five statuses and the native review.
Keep the fixture unmerged and remove its label when closing it.

For active revocation, put a bounded hold in credential-free Quality and
require a flushed log marker before the exact-head revoke comment. Verify
cancellation of the original step, job and run, failed human statuses, native
approval dismissal and no later successful human status from finalization.
The revoke event must skip source preparation, builds and AI. Model steps must
remain skipped or unstarted. In-progress metadata alone does not prove the
hold was active.

## Credentials

Store `MODEL_API_KEY` as a selected organization secret or scoped repository
secret. Use a dedicated provider project with spending controls. Missing keys
fail closed. Rotate a leaked key at the provider, remove its stored value,
audit affected runs and readmit work only after containment.

Generated callers pass `MODEL_API_KEY`. The reusable workflow also accepts the
previous secret, `OPENAI_API_KEY`, when a caller forwards only that name.
`MODEL_API_KEY` is used when both are present. Keep the previous organization
secret until every caller pin and secret mapping has moved; an empty key fails
review closed. Renaming the organization secret and updating each repository
caller pin are manual owner steps after this change is on main. This
repository's installed caller keeps the previous secret and its current pin so
existing admissions still resolve. Do not point that caller at `MODEL_API_KEY`
until its pin is a revision that declares the new secret.

Public harness source needs no private checkout token. Pin its exact revision
in `.github/harness-revision`; trusted preparation archives it for the
credential-free build and review jobs. Remove unused source-read secrets once
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
one immutable artifact identity. The reviewer receives their static source;
credential-free Quality and registry jobs receive the same data. Those build
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

This revision's canonical PR and release callers both pin
`6717b433c462e01abaed86e2118e4843827598cb`. Its archive validator preserves
committed notice bytes. The earlier `c4f2873ef0eef5bc3c7d75cf71fa3489a911d134`
pin normalizes line endings in expected notices. An original CRLF notice then
fails validation even though the archive contains its exact committed bytes.
Adopt the corrected caller pin through review; preserve the original notices.

The coupled PR caller update also adopts the reviewed CLI harness selector,
optional public UI source handoff, and UI owner profile. Shared checks retain
their human admission, completion guard, two medium Sol reviews, required
statuses, and separate missing-model-key route. Studio keeps its public
`scripts/check.mjs` quality entry and bounded consumer source context. This
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
reviews must match the admitted head and pass and meet the installed result
schema. Recheck every required status, native approval and exact head before
normal protected merge.

Keep genuine outside-contributor, bot, nonmaintainer and fork event tests open
until their own identities and GitHub evidence exist. Maintainer tests do not
establish those paths. First real draft releases, duplicate-tag refusal,
installers, signing, registry publication and deployment also need their own
evidence. Product-specific vulnerability and platform limits belong in the
product's security and contributor guides.

## Recovery

For `workflow was not found` before jobs start, inspect the exact caller pin,
access policy and run annotation. A Contents API read alone does not establish
Actions resolution. Restore a missing protected `workflow-pins/FULL_SHA` ref
only to its reviewed commit. Keep caller pins and main protection unchanged;
verify resolution through fresh human admission.

Revoke a suspect head, cancel admitted work and inspect its isolated artifacts.
Roll back a failed shared revision through an ordinary reviewed PR restoring
the previous full SHA. Do not move a revision or release tag. Keep budget
notifications enabled. Source-release jobs make drafts and do not deploy or
publish packages.
