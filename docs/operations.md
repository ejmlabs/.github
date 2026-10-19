# Repository operations

## Permissions and required settings

Main requires a PR, one native approval recorded from an explicit human maintainer comment, current Maintainer approval and Human readiness statuses, Quality, Repository standards, and AI review. Require strict status checks, resolved conversations, linear history, and stale approval dismissal. Enforce administrators. Disable force pushes and branch deletion. Use squash merges and delete merged branches.

Enable read-only default workflow tokens and bot review recording. Allow only pinned actions from actions/*, astral-sh/setup-uv, openai/codex-action, and this shared repository. Enable Actions sharing within the organization for this private shared repository. Never grant untrusted builds model keys, source-read secrets, deployment credentials, or write tokens. Do not reuse caches produced by PR code in a privileged job.

The Codex action step clears inherited `GH_TOKEN` and `GITHUB_TOKEN`; the model
needs neither. Trusted admission rechecks retain their read token. The pinned
action supplies its own token for its internal permission check and isolates
the OpenAI key behind a separate proxy. The read-only profile limits writes,
not filesystem reads, so keep unrelated credentials out of the reviewer job.

Every account with write access must be a human with maintain or admin permission. The settings tool rejects ordinary writers and bots before changing any repository. GitHub Actions app identity alone cannot prove which workflow created a status: a writer can add a branch workflow that uses the same identity. If ordinary writers become necessary, first migrate required result publication to a dedicated GitHub App whose credential is confined to a protected environment and unavailable to branch workflows.

After removing or demoting a maintainer, revoke their open PR decisions before completing the access change. Commands, finalization, and releases check current roles; GitHub does not send a continuous role-change event to this pipeline. Organization administrators can change repository policy and therefore remain trusted.

## Admission and budget controls

Only trusted main receives issue-comment events. Bot and unrelated comments are filtered before a runner starts. The script rechecks the current human's maintain/admin role, exact current head, non-draft main target, and the original command. Serialize admission per PR, reject repeated events and Actions reruns, and consume each comment once. A commit can be readmitted only after explicit revocation and a new human command.

Admission limits: 200 changed files, 12,000 added/deleted lines, 1 MB diff. Quality has a 45 minute limit, the separate registry gate 25 minutes, preparation 5 minutes, and each AI pass 9 minutes inside a 12 minute job. AI passes run independently and serially. There are no automatic model retries. Model output is capped at 64 KB and 50 findings. A failed job blocks merge. After the completion guard below is adopted, an incomplete result also fails validation. Critical, high, and medium findings block; low findings are advisory. Review artifacts are retained 7 days; source handoff artifacts 3 days.

Each review result must include `complete` as a JSON boolean. Only `true` can
pass validation. A missing field, a nonboolean value, or `false` fails the pass,
even when `findings` is empty. The reviewer must use `false` when required
source or context is absent and explain the gap in its summary. The validator
does not infer completion from prose. A reviewer can still misstate completion;
maintainer review and the other required gates remain necessary.

This guard takes effect only after a consumer adopts the retained implementation
that contains it. It cannot change results from an older pinned caller. For a
shared workflow pin change, provide the exact old and new implementation source
as bounded review data and verify it against the canonical Git objects before
admission. This also applies to the shared repository's own caller changes:
its current source tree does not replace either exact pinned implementation.
Do not enable network or repository credentials in the model step to
fill that gap. Until the source is available and both reviews complete, keep the
pin change unmerged. See [current acceptance](readiness.md#review-completeness-guard).

Harness quality installs both root and registry locked npm dependencies with lifecycle scripts disabled before running `./scripts/check`. Root ESLint includes registry sources. The separate registry job also runs its native, WebAssembly, schema, auth, and build checks.

These bounds limit each admitted run. Set a dedicated OpenAI project spending limit and GitHub Actions budget/alerts to bound total spending across admitted PRs. An organization member can still request workflows they are allowed to dispatch; restrict repository roles and revoke access when needed. GitHub administrators retain control over repository settings. No repository policy can stop an organization owner from changing the policy itself.

## Static workflow review data

Run the shared exporter on macOS or Linux, including WSL, from a local checkout
that contains both canonical implementation commits. Include the source pair
in every repository that changes a shared caller pin, including this shared
repository:

```sh
python3 scripts/export_review_context.py \
  --old FULL_OLD_IMPLEMENTATION_SHA \
  --new FULL_NEW_IMPLEMENTATION_SHA \
  --destination /path/to/repository/.github/review-context
```

The destination must be new and its parent directories must exist without
symlinks. For a later rotation, export to a fresh staging directory and review
replacement of the old pair in the same PR as both caller pin changes. Do not
keep accumulating earlier snapshots.

The exporter reads a fixed list of 16 files at each exact Git commit: both
reusable workflows, their generator and runtime scripts, the prompt and schema,
and community templates. It writes ordinary, nonexecutable files below each
commit SHA plus a manifest of commit, tree, blob, mode, SHA-256, and size. The
combined data and manifest must fit within 750,000 bytes. It neither fetches
objects nor executes exported code. Source-controlled archive attributes cannot
hide or substitute a selected blob. Exported files are review data; builds and
scripts must not import or execute them.

Verify both commit IDs against the protected canonical `workflow-pins/FULL_SHA`
references and compare the exported bytes with those Git objects before human
admission. The manifest records local object identity; it does not establish
remote provenance by itself, and the currently installed workflow does not
automatically authenticate snapshots. The fixed list covers this shared
implementation's owned workflows and code, rather than recursively downloading
other actions or dependencies. Keep the snapshot pair and caller pins in sync.
The old revision must match the trusted default caller that will evaluate the
PR; the new revision must match the proposed callers. Before admitting a changed
head, confirm that both exact implementations are present in its review data.

## CLI quality prerequisites

The generated quality job calls `./product/.github/actions/setup-ci` only for
the `ejm-cli` profile, after installing the shared Rust tools and before running
`./scripts/check`. The action comes from the exact admitted product source
artifact. It runs in the credential-free quality job, with the existing matrix,
two-build-job limit and 45 minute deadline. Privileged preparation, AI review,
publication and draft release jobs do not execute this action. External actions
still require full commit SHA pins and the existing allowed-action policy.

The CLI action supplies its pinned Node and npm, the matching wasm-bindgen CLI
and Rust WebAssembly target, Chrome, and Linux libdbus development files. Keep
package and system installation in setup; the product gate must not install
system tools or invoke sudo. The standards checker permits only the exact CLI
quality hook, including its profile condition. A missing action fails quality.
Comments and literal block contents remain data. The allowance binds to the
complete `quality.steps` entry, starting at a real sequence boundary, and its
actual `uses` line. A hook lookalike in a comment, job name or script cannot
authorize a local action or hide extra step fields.

Use the maintained Cargo installer already provided by the pinned Rust
toolchain for wasm-bindgen, without adding an action source:

```sh
cargo +1.99.1 install wasm-bindgen-cli --version 0.2.129 --locked --bin wasm-bindgen --jobs 2
```

The [wasm-bindgen guide](https://wasm-bindgen.github.io/wasm-bindgen/reference/cli.html)
supports Cargo installation. Release 0.2.129 declares Rust 1.86 and its published
crate includes a lockfile. Cargo's
[`--version` and `--locked` options](https://doc.rust-lang.org/cargo/commands/cargo-install.html)
select the exact CLI release and its packaged dependency versions. Install only
the binary the gate uses. This adds source compilation; no hosted duration has
been measured for this setup. Keep the current deadline until an admitted run
provides evidence for a change.

The prerequisite implementation merged into protected main
`8c304c8cdfc8b6fe50f3e442507215e615944f2b`, whose trusted caller still pins
`965cd684713ae91a7804745eddd452cc392af11d`. This completion repair builds on
that main and preserves the CLI validator, conditioned CLI action, Linux
harness package setup, SemVer release fixes, shared missing-model-key fixture
routes and narrowed reviewer credentials. It also preserves the dated
missing-key and active-revocation acceptance record. The completion guard
changes review-result validation; no allowed action source, permission or
human admission rule changes.

Combined implementation `c4f2873ef0eef5bc3c7d75cf71fa3489a911d134` retains both
the completion repair and these prerequisite execution steps. Its protected
`workflow-pins/FULL_SHA` reference blocks updates and deletion, with no bypass
actors. This shared adoption proposes that exact revision for the normal and
missing-key PR routes, draft release caller, and `standards-ref`. Its static
source pair contains old `965cd684713ae91a7804745eddd452cc392af11d` and new
`c4f2873ef0eef5bc3c7d75cf71fa3489a911d134`. Shared main continues to use the old
caller until the protected adoption merges.

Studio and harness adopted the earlier completion-only revision
`aa4144fa978d711a5e009b384718b4cf27cf87bf`. Neither that revision nor the old
shared trusted caller contains the prerequisite execution steps. Consumer
adoption of the combined revision requires separate reviewed pin changes; this
shared source change does not establish hosted consumer execution. See
[the integration record](readiness.md#review-completeness-guard).

Before adopting the combined implementation in the CLI, establish these
prerequisites:

1. Land the reviewed local setup action in the trusted CLI baseline while
   retaining its current reviewed working harness pin. The action must work
   before relay sources exist:
   guard only its browser npm/Playwright step on the presence of
   `relay/package.json`. A missing manifest skips that step; a present manifest
   without its lockfile must fail. Keep the other pinned setup steps unchanged.
2. Verify the CLI private checkout credential has only the scope and expiry
   described under [Credentials](#credentials). Successful source preparation
   proves access to the selected source, not least-privilege scope or adoption
   of the new harness APIs.
3. Review the shared implementation against the current protected baseline and run its
   policy and generation checks. Request fresh human readiness and approval for
   the exact new head after it leaves draft. An earlier approval does not apply
   to a rebuilt candidate. Preserve the repaired model startup, human commands,
   required checks and administrator enforcement.
4. After review and passing checks, retain the exact shared implementation under
   `workflow-pins/FULL_SHA` and merge its adoption through protected review.
   Move the CLI caller's `uses` pin and `standards-ref` together to that reviewed
   revision through its own admitted change, still retaining the working harness
   pin. Keep the shared caller's retained SemVer fixes. Do not weaken protected
   checks or reuse an earlier exception.
5. Record admitted Linux and macOS quality results before claiming this hook
   works in hosted CI. The existing successful CLI source preparation does not
   execute this proposed hook. Local tests do not prove an active or passing
   consumer.
6. Separately adopt the reviewed new harness APIs and their immutable
   `.github/harness-revision` pin after the CLI caller can run the setup hook.
   The new harness authentication manifest selects a non-vendored Linux D-Bus
   keyring backend, which needs the development files installed by the action.
   Requiring that API pin before hook adoption would block its own prerequisites.
   Review the pin change and pass the full consumer quality gate separately.

The source-only draft release needs no product setup hook. Its generated
workflow and behavior remain unchanged. Private checkout access, source/API
adoption and the full product quality run remain separate requirements.

## Harness Linux keyring prerequisites

The harness quality job installs `pkg-config` and `libdbus-1-dev` through the
runner's Ubuntu package manager, with recommended packages disabled. This fixed
step runs only when the admitted profile is `ejm-harness` and the runner is
Linux, before Rust tools and the required product gate. It starts no key service
and supplies no credentials. Other platforms and privileged jobs skip it. The
CLI keeps its reviewed product setup action. No local-action allowance changes.

Hosted harness API PR #2 at `4aeff321c3ab1148bfc92776471552308d3e62da`
confirmed the missing-header failure on Ubuntu 24.04 in job `118036420366` of
run `39245467732`; its macOS quality job passed. This source change
does not establish a passing Linux harness run. After the shared revision is
reviewed, retained and adopted through protected review, adopt both harness caller pins and `standards-ref`
through a bounded protected change on the working harness baseline. Rebuild and
readmit the API layer on that adopted parent. The old trusted caller cannot run
setup that exists only in the API PR's head. Keep the 45-minute gate and all
normal reviews and approvals. No system installer belongs in `scripts/check`.

## Missing model key acceptance staging

The shared caller uses the exact missing-key form accepted by retained
validator revision `965cd684713ae91a7804745eddd452cc392af11d`. Product callers
keep their existing form and reject the fixture form. This caller supports
negative acceptance tests; it does not establish their live results.

`missing_model_key_workflows(FULL_SHA)` generates the shared-only fixture.
Its two issue-comment routes both require repository `ejmlabs/.github` and
call the same immutable governance revision with the existing token permissions
and human admission. Without label `acceptance:missing-model-key`, only the
normal route runs and forwards the existing secrets. With that label, only the
fixture route runs and forwards no secrets. Neither route uses
`secrets: inherit`. Adding or removing the label starts no run.

Install this in two protected changes. First review and retain the validator
implementation, then update both normal caller pins to that exact SHA while
keeping their shape. Once that adoption merges, a separate reviewed PR can
install the exact fixture caller using the same SHA in both routes and the
release caller. Each setup PR needs fresh human decisions, all required checks,
and both actual AI passes. Keep secret values and repository access unchanged.

Apply the fixture label only to a dedicated, unmerged acceptance PR. Give
that exact head fresh human readiness and approval. Remove the label when
closing the fixture. Ordinary PRs keep the normal route and both real reviews.

An admitted fixture run must establish missing-secret forwarding.
Both AI jobs must stop at the existing missing-key guard before Codex executes.
Record step states, all five statuses, and the current native approval before
claiming isolated AI-check blocking. Validator tests and generation alone do
not prove this GitHub behavior. The fixture PR used for negative acceptance
must remain unmerged.

For active revocation acceptance, use a bounded hosted hold in the secret-free
Quality job. Require a flushed marker in its terminal log before the exact-head
revoke comment, within the hold window. In-progress job metadata alone cannot
prove the wait was active. Verify cancellation of the original step, job, and
admitted run, failed human statuses, dismissal of the native approval, and no
later successful human status from finalization. The revoke event must skip
preparation, builds, and AI. Both Codex steps must remain skipped or unstarted.

Shared [PR #12](https://github.com/ejmlabs/.github/pull/12) completed both the
missing-key and active-revocation cases with no model calls and unchanged main
protection, then closed unmerged with its fixture label removed. See the
[dated acceptance record](readiness.md#verified-missing-key-and-revocation-acceptance)
for exact source revisions, run IDs, timing, results, and remaining cases.

## Credentials

Store OPENAI_API_KEY as a selected organization secret or separately in the five repository secrets. Use a dedicated OpenAI project. Missing credentials fail closed. Rotate a leaked key at the provider, remove the secret, audit runs, and readmit only after the incident is contained.

IDE hosted Quality remains blocked until the harness is public under the
owner's existing access policy. Its reviewed `.github/harness-revision` and
admitted checks still need acceptance after that access is available.

CLI private harness API review and checkout are authorized. The owner attested that the existing EJM_HARNESS_TOKEN is an expiring fine-grained GitHub token with **Contents: read** for **ejmlabs/ejm-harness only**. This is owner evidence, not independent API verification of the stored credential. Secret-name timestamps and a successful source checkout cannot prove the token's scope or expiry. Hosted CLI source preparation succeeded; reviewed API adoption, the immutable `.github/harness-revision` pin and the full consumer quality gate remain separate requirements.

Keep the CLI token limited to that repository, permission and expiry, and recheck its owner-provided scope and expiry before rotation or adoption. Do not print or copy its value while checking access. The trusted preparation job archives the pinned harness revision; the untrusted build receives only source data. Once the dependency is public, remove this secret. Never copy a broad personal token into Actions or configure IDE access without its owner's authorization.

## Draft source releases

The shared release workflow creates drafts from the checked source version. SemVer prereleases such as `1.2.3-rc.1` are marked as GitHub prereleases with Latest disabled. Build metadata does not change this classification: `1.2.3+build-alpha` remains stable, while `1.2.3-rc.1+build-2` remains a prerelease. Stable drafts retain GitHub's default Latest behavior. Review the draft before explicit publication.

Tag creation and draft creation or asset upload are separate writes. A failed or canceled run may leave a tag without a draft, or an incomplete draft. Stop and inspect the run, the existing tag's exact commit, and the draft's state, assets, checksums, and provenance. Record the repository, version, commit, and proposed recovery. Obtain explicit owner authorization for that scoped recovery before any write. Do not delete or move the tag, replace released assets, retry automatically, or publish an incomplete draft. Reruns and requests for an existing version remain blocked. If source or asset integrity cannot be established, prepare a new version through a checked PR.

## Bootstrap and rollout

1. Test and commit the shared implementation. Retain that exact commit under `workflow-pins/FULL_SHA` before adding callers. The shared repository's active ruleset must block updates and deletion for `workflow-pins/*`, with no bypass actors. Keep callers pinned to the full SHA, rather than the branch name. A new implementation needs a new commit and retention reference. This keeps implementation commits reachable after squash merges and deletion of adoption branches.
2. Add the shared repository's own consumers pinned to that tested commit. Existing consumers pin the same immutable revision.
3. Review each adoption change, preserving earlier local commits and concurrent work. A trusted comment workflow must exist on main before GitHub can deliver PR comments to it. This is a one-time bootstrap requirement; installing only a branch copy cannot activate issue-comment admission.
4. During bootstrap, disable existing automatic PR/push workflows before opening adoption PRs. Do not authorize the old workflows to run unreviewed source. After explicit maintainer acceptance of the exact adoption changes, install the trusted callers on main, enable Actions, and verify the required checks using a fresh admitted PR. Do not silently weaken an active protection to merge a bootstrap PR.
5. Read back main protection, Actions policy, branch rules, dependency alerts, and security settings. Repos remain private until the public-readiness blockers are closed.
6. Test human readiness, stale pushes, self approval, revocation, missing secrets, failed checks, and a refused duplicate release tag in GitHub before claiming live enforcement. Local policy tests are not evidence of GitHub event delivery or bot review permission.

## Public visibility checklist

Before a visibility change, inspect all refs and release assets for private data and secrets; review licenses, copied brand material, and vulnerability findings. Enable GitHub secret scanning, push protection, private vulnerability reporting, dependency alerts/updates, dependency review and CodeQL where available without extra charges. Require approval for **all external contributors** in the public Actions settings, and keep write tokens/secrets disabled for fork workflows. Private fork approval and public private-reporting APIs are unavailable while these repositories are private. Do not enroll private repos in a billed security product by assumption.

Require two-factor authentication for organization members through the organization owner after checking member readiness and recovery access. This is an organization access change, separate from repository configuration. Review access, installed apps, scoped secrets, workflow pin updates, and supported release lines regularly.

## Recovery

If GitHub reports `workflow was not found` before any jobs start, inspect the exact caller pin, access policy, and run annotation. A successful Contents API read alone does not establish that Actions can resolve the reusable workflow. If its retaining branch was deleted, restore a protected `workflow-pins/FULL_SHA` reference to the exact reviewed implementation. Keep the caller SHA and main protection unchanged, then verify resolution with a fresh human command for the full current PR head. Do not treat reference retention as proof of a passing review.

Revoke the readiness comment for a suspect head, cancel its run, and inspect the isolated artifacts. A failed shared update is rolled back by an ordinary reviewed PR restoring the previous full workflow SHA. Do not move a shared revision or release tag. Keep GitHub Actions and OpenAI budget notifications enabled. Release setup makes drafts only and does not deploy or upload packages.
