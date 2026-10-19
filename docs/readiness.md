# Public readiness rollout

Evidence snapshot recorded on 2026-10-19 at 11:16 UTC. All five repositories remain private.
Caller review and adoption updates below include evidence through 14:30 UTC.
Product source fixes require protected adoption PRs.
This record does not declare the products ready for public release.

## Active repository settings

GitHub API readback confirmed these settings for `.github`, `ejmlabs`,
`ejm-cli`, `ejm-harness`, and `ejm-ide`:

- Main requires a PR, one native approval, stale approval dismissal, strict
  required checks, resolved conversations, and linear history. Administrators
  must follow the same gates. Force pushes and branch deletion are blocked.
- Required statuses are Human readiness, Maintainer approval, Quality,
  Repository standards, and AI review. They are bound to GitHub Actions.
- Actions use selected sources, full SHA pins, and read-only default tokens.
  Bot approval recording is enabled at the organization and repository levels.
- Squash merge is the only merge method. Merged branches are deleted.
  Automatic merge is disabled.
- Dependency alerts, automatic security updates, and immutable releases are
  enabled. An active tag rule prevents changing or deleting `v*` tags.

A fresh readback at 11:12:48 UTC checked all five repositories after recovery.
All 60 assertions passed, including strict enforcement of the five required
statuses under GitHub Actions app `15368`. All repositories remained private
with no tags or releases.

The writer audit found only human administrator `everettmorgan`. The policy
requires every writer to be a human maintainer or administrator. An ordinary
writer could forge GitHub Actions statuses through a branch workflow, so adding
ordinary writers first requires a dedicated protected publication credential.
See [operations](operations.md) for this boundary and role-removal procedure.

## Installed automation

Main contains trusted issue-comment and manual release entry points. Product
fixes enter through adoption PRs. Each consumer pins an immutable shared
workflow revision. New PRs and pushes have no automatic quality or AI trigger.
The retry guard becomes active for each consumer after its pin update merges.
Fresh admitted PRs verified the repaired caller in the shared repository and
an earlier studio revision. Harness recovery and CLI adoption have merged.
The revised studio refresh merged normally after two complete reviews of both
pinned implementations and all required checks. Harness's revised refresh has
two complete reviews; its Windows Quality job is still active. Shared PR #14
was held after incomplete reviews and now includes its own canonical source
pair, pending fresh decisions and complete reviews. Hosted enforcement of the
new completion boolean remains unverified. CLI acceptance follows its separate rollout. IDE hosted
Quality remains blocked under the owner's public-harness-only policy.

### Shared workflow recovery

[PR #4](https://github.com/ejmlabs/.github/pull/4) merged as
`a692cb5e6e141103f7c312dc9c42a201184fadf6` on 2026-10-19 UTC. That merge changed
the shared repository's main caller to repaired revision
`8e888752e00a29363fb8ae125658159b5c2dee58`.

Fresh human readiness, Quality, and Repository standards passed for the exact
reviewed head. A separate human approval command produced a native bot approval,
which verified explicit maintainer self review. Both admitted runs used the
older main caller and stopped at the duplicate Codex argument before model use.

The owner approved a one-time exception for that exact recovery PR. Only the
AI review requirement became advisory during its protected merge. All other
checks and administrator enforcement stayed active. Immediately after merging,
the full protection response matched its original snapshot, including required
AI review.

The subsequent acceptance below verified the repaired reviewer and model
access. This recovery exception did not change product settings or waive their
remaining quality gates.

The first acceptance attempt on [PR #5](https://github.com/ejmlabs/.github/pull/5)
failed before jobs started: Actions reported that the pinned reusable workflow
`8e888752e00a29363fb8ae125658159b5c2dee58` was not found. The Contents API still
returned that file, but the squash merge had deleted its retaining branch.
No model call occurred. See the [startup failure](https://github.com/ejmlabs/.github/actions/runs/39191146628).

Both implementation revisions, `8e888752e00a29363fb8ae125658159b5c2dee58` and
`5fae851502c2e3c31d4df9a44f8d56c2cb49e098`, have `workflow-pins/FULL_SHA`
retention branches. Active rules block updates and deletion, with no bypass
actors. Creating these references triggered no CI or AI runs.

### Verified shared acceptance

[PR #5](https://github.com/ejmlabs/.github/pull/5) then passed all five required
statuses for reviewed head `f6bd997d56994fe54218876768303a9921121291` in
[run 39193254280](https://github.com/ejmlabs/.github/actions/runs/39193254280).
Both actual `gpt-6.1-sol` passes ran independently and serially with medium
reasoning and returned no findings. Human readiness, separate human approval,
and native bot approval were verified for that head.

The PR merged normally as
[`ad29c94d9be09ddd4b18d037657f088eeafc26e8`](https://github.com/ejmlabs/.github/commit/ad29c94d9be09ddd4b18d037657f088eeafc26e8),
with all protections enforced and no exception. Its installed caller pins
`5fae851502c2e3c31d4df9a44f8d56c2cb49e098`. This verifies shared workflow
resolution and model access. It does not complete product acceptance or the
negative cases listed below.

### Verified SemVer update

[PR #7](https://github.com/ejmlabs/.github/pull/7) passed at reviewed head
`de1fc39a3fa11ae62be6acf754fe92cdd54fa769` in
[run 39236669549](https://github.com/ejmlabs/.github/actions/runs/39236669549).
Both actual `gpt-6.1-sol` medium passes returned no findings, and all five
required statuses passed. Separate unedited human decisions, the current
maintainer role, and the exact-head native approval were verified.

It merged normally as
[`300a975bfa4b323285c1aaa6db234e74d601b96b`](https://github.com/ejmlabs/.github/commit/300a975bfa4b323285c1aaa6db234e74d601b96b).
The reviewed and merged trees matched, and the full protection response was
unchanged. No exception was used. This adopted retained implementation
`72379a74a1d7c264b2805d8fab87a808c2144458`, preserving the merged CLI validator
fixes and correcting SemVer prerelease classification. Its 63 policy tests and
generation, standards, and workflow checks passed. No release was created.

### Missing-key caller support

[PR #9](https://github.com/ejmlabs/.github/pull/9) passed all five required
statuses at reviewed head `c1db1f8802acaf1a58066d1f32849d7ce95bb6e8` in
[run 39238618299](https://github.com/ejmlabs/.github/actions/runs/39238618299).
Both actual `gpt-6.1-sol` medium passes returned no findings. Separate human
decisions and the current-head native approval were verified. It merged
normally as `8a33398f5569edb21ebc9b2e4b3d7d97087aef4a`; the reviewed and merged
trees matched, and full main protection was unchanged. No exception was used.

That merge adopted retained implementation
`965cd684713ae91a7804745eddd452cc392af11d` through the normal caller.

[PR #10](https://github.com/ejmlabs/.github/pull/10) installed the exact
shared-only alternate caller. At reviewed head
`688807eb598245bf0aa1b45a132361cc5c157924`, all five required statuses passed in
[run 39239510733](https://github.com/ejmlabs/.github/actions/runs/39239510733).
Both actual `gpt-6.1-sol` medium passes returned no findings. Separate unedited
human decisions and the exact-head native approval were verified. Both the
action and CLI-step logs showed empty `GH_TOKEN` and `GITHUB_TOKEN` values.
The pinned action's internal permission check retained its own token.

PR #10 merged normally as `f557478a0a681bae21e2579783d7b57ce7b668db`.
Its reviewed and merged trees matched, and full main protection stayed
unchanged. No exception was used. Validator adoption and caller installation
were followed by the separate live negative tests below. See
[the fixture procedure](operations.md#missing-model-key-acceptance-staging).

### Verified missing-key and revocation acceptance

The dedicated [PR #12](https://github.com/ejmlabs/.github/pull/12) tested the
shared caller with label `acceptance:missing-model-key`. Each fixture head
received its own separate, unedited human readiness and approval commands.
The normal route skipped; the alternate route forwarded no model key.

Fixture A, `8f39767cff0a58559dbd6cebdcf6cf89c7d84ecc`, completed
[run 39240795382](https://github.com/ejmlabs/.github/actions/runs/39240795382).
Both AI jobs reported `OPENAI_API_KEY is required; review fails closed` and
skipped their Codex review steps. The other four required statuses and the
exact-head native approval passed. Current main was fully included, the PR
had no conflicts or unresolved reviews, and no other merge rule was unmet.
AI review was the sole unmet merge requirement. No model call occurred.

Fixture B, `d1c9f1e447293b80ea4bd892e8bf6de8485d4629`, added one hosted
180-second hold in the secret-free Quality job. In
[run 39241261759](https://github.com/ejmlabs/.github/actions/runs/39241261759),
the terminal job log recorded `EJM_ACCEPTANCE_CANCELLATION_ARMED` at
10:59:05.8936625 UTC. The explicitly authorized exact-head revoke comment was
created at 10:59:34 UTC, 28.1063375 seconds into the hold. The active Quality
step, job, and admitted run were cancelled before the hold could finish.

Both human statuses failed, and the native bot approval was dismissed with
reason `Revoked by a current human maintainer`. The finalizer failed with
`Readiness was revoked or superseded` and did not restore either human status.
The separate revoke-event
[run 39241394569](https://github.com/ejmlabs/.github/actions/runs/39241394569)
ran only admission; preparation, builds, AI, and finish all skipped. Both
original AI passes stopped at the missing-key guard before Codex. No model
call occurred. The terminal marker, rather than job metadata alone, proved
that revocation happened during the active hold.

Full main protection matched before and after both tests. The active-rules
readback showed no additional main rules. PR #12 was then closed without
merging, and its fixture label was removed; neither fixture entered main.
These results cover the shared fixture. Outside-actor and real duplicate-tag
acceptance remain open below.

### Review completeness guard

The evidence update in shared [PR #13](https://github.com/ejmlabs/.github/pull/13)
merged normally as `d8b31f1debf095b104f6de76193bf531ec4ddd2c`. Its two actual
Sol 6.1 medium passes completed the static documentation review in
[run 39244763017](https://github.com/ejmlabs/.github/actions/runs/39244763017).
All five required statuses and the exact-head native approval passed. The
reviewed and merged trees matched, and full main protection was unchanged.
Those model passes did not independently verify hosted evidence claims.

After fresh, separate human readiness and approval, studio PR #3 at
`662765b7031637bcdc70fb2f414d18e81761cabd` and harness PR #12 at
`7a409665b4259135c85ca55c83bc5815cba237aa` ran the admitted checks. Studio
received five successful statuses; harness's full Quality and registry gates
were still running when the completion defect was found. Both runs executed
two actual `gpt-6.1-sol` medium passes with empty findings.
However, all four model summaries explicitly said their reviews were incomplete:
the old and new shared workflow implementations were absent from the source
archive. The validator accepted a nonempty summary without a blocking finding,
despite the prompt's instruction that incomplete work must not claim success.
This was a defect in completion enforcement. Neither product PR was merged.

The actual studio
[run 39244751207](https://github.com/ejmlabs/ejmlabs/actions/runs/39244751207)
and harness
[run 39244757531](https://github.com/ejmlabs/ejm-harness/actions/runs/39244757531)
used the trusted default caller's pin
`5fae851502c2e3c31d4df9a44f8d56c2cb49e098`. Their proposed pin
`965cd684713ae91a7804745eddd452cc392af11d` did not execute merely because it
appeared in each PR. Earlier shared acceptance does not turn these explicitly
incomplete product reviews into complete reviews.

Retained implementation `aa4144fa978d711a5e009b384718b4cf27cf87bf` adds a
required boolean `complete` result and rejects missing,
nonboolean, or false completion before accepting a pass. The prompt requires
`false` when needed source or context is absent. Local regression coverage
reproduces acceptance of the actual incomplete output by the old validator.
Studio has now adopted the repair through the protected merge below. Shared
and harness adoption and fresh execution of the new completion field remain
pending in this snapshot. Both revised product heads include the canonical
old and new shared source and received complete reviews under their previous
default callers. No exception or automatic model retry is authorized by this
repair. Both original product heads were converted to drafts
to block merging while this gap is repaired. Their reviewed heads and recorded
human comments were preserved.

The shared adoption updates both caller pins to that same retained revision.
All 75 policy tests, generated workflow checks, actionlint, repository standards,
relative documentation links and anchors, and whitespace checks passed locally.
The added offline exporter supplies exactly the selected old and new canonical
Git blobs as inert review data. Its six regression tests cover byte identity,
archive-attribute bypass, missing and unsafe sources, bounds, and destination
collisions. Consumer source exports and their fresh hosted acceptance are
separate from local validation of this shared repair.

Shared [PR #14](https://github.com/ejmlabs/.github/pull/14) exposed the same
missing-source gap at head `8eb9de97f060e165bc58a98b2916b6db65d89cc2` in
[run 39267653240](https://github.com/ejmlabs/.github/actions/runs/39267653240).
Both actual `gpt-6.1-sol` medium passes ran serially and returned empty findings,
but both explicitly declared their reviews incomplete because the exact old
and new workflow implementations were absent. The executing trusted caller
pinned `965cd684713ae91a7804745eddd452cc392af11d`; the proposed completion-guard
pin `aa4144fa978d711a5e009b384718b4cf27cf87bf` did not govern that run.
The older validator accepted both outputs. PR #14 was returned to draft, and
those outputs do not establish two complete reviews or merge readiness.

This revision adds both exact implementations to this repository's own
`.github/review-context/`, with the same 16-file source list per revision and a
manifest. The pair covers old pin `965cd684713ae91a7804745eddd452cc392af11d`
and new pin `aa4144fa978d711a5e009b384718b4cf27cf87bf`. Local checks compare
the bytes, manifest, and modes against canonical local Git objects and enforce
the 750,000-byte bound. These files are static review data. This preparation
does not change the caller pins, execute the snapshots, or establish hosted
acceptance. The changed head needs fresh human decisions and two complete
model reviews before any protected merge.

### Product caller acceptance

Studio [adoption PR #1](https://github.com/ejmlabs/ejmlabs/pull/1) installed the
repaired caller through an explicitly approved AI-only recovery exception.
The reviewed head `fe32db61781b35f1e6dac4dfc1cc6bfc5ccdf48b` merged as
[`9529e97ce7a48d3edaed5cda9cb3c18c42b6b6e1`](https://github.com/ejmlabs/ejmlabs/commit/9529e97ce7a48d3edaed5cda9cb3c18c42b6b6e1).
All other required gates stayed enforced, the merged tree matched the reviewed
tree, and full protection was restored and matched its saved snapshot. The
recovery did not count as AI review of that adoption patch.

Studio [PR #2](https://github.com/ejmlabs/ejmlabs/pull/2) tested the installed
caller at head `4c7d95789c62da13afb4a274245774769e3ae0d8`. All five required
statuses passed in
[run 39198778017](https://github.com/ejmlabs/ejmlabs/actions/runs/39198778017),
including both actual medium-reasoning Sol 6.1 passes with no findings. The
human commands and native bot approval were verified. The PR merged normally as
[`dc4d2680dcd308916b2686e310e1ade0d18efb7b`](https://github.com/ejmlabs/ejmlabs/commit/dc4d2680dcd308916b2686e310e1ade0d18efb7b).
Fresh full administrative protection responses matched before and after the
merge. The merged tree matched the reviewed tree. No exception was used.

Studio [PR #3](https://github.com/ejmlabs/ejmlabs/pull/3) was revised to
`fdfbf0203d348e37750bc14eae12cd4d3d434b08`, based on
`dc4d2680dcd308916b2686e310e1ade0d18efb7b`. It includes both exact old and new
shared implementations as static review data. After fresh human decisions,
[run 39267660933](https://github.com/ejmlabs/ejmlabs/actions/runs/39267660933)
passed all five required statuses. Both actual Sol 6.1 medium passes explicitly
completed the scoped static review, including both supplied workflow
implementations and embedded code, with no findings. Both result artifact ZIP
digests matched GitHub's metadata. The exact-head human commands, current
maintainer role, and native approval were reverified. The PR merged normally as
[`a1b3fa068b7147410d0f72217d522b47ecd36759`](https://github.com/ejmlabs/ejmlabs/commit/a1b3fa068b7147410d0f72217d522b47ecd36759).
The reviewed and merged trees both equal
`acc81ea509770f973c083b27cc35b16d300c3079`, and the full protection response
was unchanged. No exception was used. This run executed the old `5fae8515...`
caller; the merge installs `aa4144fa...` but does not establish hosted
enforcement of its new completion boolean.

Harness [PR #1](https://github.com/ejmlabs/ejm-harness/pull/1) previously tested
head `b97d5838a68a56495ba17f413a566b7122aabb24`. In
[run 39198836714](https://github.com/ejmlabs/ejm-harness/actions/runs/39198836714),
Linux and macOS Quality jobs, the registry job, and Repository standards passed.
The Windows product gate failed in
`hooks::hook_deadlines_and_run_end_observers_are_bounded` with
`deadline has elapsed`. The final required Quality status failed. Both AI jobs
used the old default caller and stopped at the known duplicate flag before
model execution, so AI review also failed. The owner approved an AI-only
recovery exception for that exact head, but it remained unused because Quality
failed. That exception does not cover the newer repair below. Every
non-AI gate must pass before any newly authorized recovery, followed by
immediate protection restoration and a fresh PR to verify both real AI passes
through the installed repaired caller.

At 04:44 UTC, API readback showed the PR blocked from merging with all five
required statuses present. Human readiness, Maintainer approval, and Repository
standards succeeded; Quality and AI review failed. The unchanged human comments
and exact-head native bot approval were reverified. The branch summary required
all five statuses for everyone, bound to GitHub Actions app `15368`. This
demonstrates required-check failure blocking with both failed checks present;
it does not isolate the effect of either failed check. No recovery exception or
merge was attempted.

A test-only repair was pushed as
`112767287394be2cf519db5d79dde780808eb2b8`. A controlled
100 ms SQLite journal hold reproduced the old hook-entry timeout and passed
with the repaired fixture; the temporary probe was then removed. On macOS
arm64, the final focused test, ten repeated runs, all six hook tests, scoped
strict Clippy, rustfmt, shared standards, Prettier, strict OpenSpec validation,
and whitespace checks passed. Production deadlines and the test assertions are
unchanged. The full local native gate was not repeated. After the push, the new head had no commit statuses
or automatic workflow run. GitHub dismissed native review `5566851420` from
the previous head.

The owner then reviewed that full head and authorized separate readiness and
approval commands and an AI-only recovery. Both commands remained unedited,
and native approval `5569972356` recorded the current approval comment. In
[run 39235095968](https://github.com/ejmlabs/ejm-harness/actions/runs/39235095968),
Linux, macOS, registry, and standards jobs passed. Windows passed the repaired
deadline test but failed
`cancellation_during_tool_hooks_preserves_effect_and_recovery_boundaries` with
`deadline has elapsed`. Required Quality failed. Both AI jobs again stopped on
the old caller's duplicate flag before model execution. The recovery exception
remained unused because Quality failed; protection was not weakened. A further
fixture repair and fresh hosted checks were required. The changed head needed
new human decisions and a new exact-head recovery authorization.

The final reviewed repair, `6da46394f29b3d0d1f068175b1715e8c6b048d23`, passed
all non-AI jobs in
[run 39239206945](https://github.com/ejmlabs/ejm-harness/actions/runs/39239206945).
Quality passed on Linux, macOS, and Windows; registry and Repository standards
also passed. Windows passed all six hook tests, including both previously
failing deadline and cancellation cases. The separate exact-head human
commands and native approval passed. Both AI jobs still used the old default
caller and failed on the duplicate argument before model execution.

The owner approved recovery for that exact head. Only AI review became
advisory for the merge; all non-AI gates and administrator enforcement stayed
active. PR #1 merged as
[`ee1d2e3df5d77027be226d20830f6c5ea84d0d1d`](https://github.com/ejmlabs/ejm-harness/commit/ee1d2e3df5d77027be226d20830f6c5ea84d0d1d).
The merged tree matched reviewed tree
`8cd865538c50004973aed13162759859f73bf907`. Full protection was restored on
the first attempt and matched its saved snapshot. This recovery did not
provide two actual AI reviews of the adoption patch. A fresh admitted PR must
still verify both real passes through the repaired caller with every gate
enforced.

Harness [PR #12](https://github.com/ejmlabs/ejm-harness/pull/12) was revised to
`8343142b01622d588d98dddbb3ef5f94c26f2785`, based on
`ee1d2e3df5d77027be226d20830f6c5ea84d0d1d`, with the same exact source pair as
studio. Fresh human readiness and approval admitted
[run 39267669806](https://github.com/ejmlabs/ejm-harness/actions/runs/39267669806).
Both actual Sol 6.1 medium passes explicitly completed the scoped static
review, including both supplied implementations and affected call paths, with
no findings. At 14:30 UTC, standards, registry, Linux Quality, and macOS Quality
had passed; Windows Quality was still active. The PR remains unmerged until
every required check passes. The run executes old pin `5fae8515...`, so it does
not establish hosted enforcement of the proposed completion boolean.

CLI [adoption PR #1](https://github.com/ejmlabs/ejm-cli/pull/1) also merged as
`4b263d4cb2a50a3641d566d6c18fdf7a0551b759`. Current CLI dependency access and
setup follow their separate rollout, including shared
[PR #11](https://github.com/ejmlabs/.github/pull/11), whose shared changes
remain pending. Actual two-pass acceptance of the current CLI caller remains
separate from that merge.

IDE [PR #2](https://github.com/ejmlabs/ejm-ide/pull/2) now has head
`0b221630db35100b6a0ced1f877b2617cfa9b880`. Since
`ad97a401ac956ab7dac167e08d9459b9317309c6`, only its two normal callers and
OpenSpec evidence changed. Product source, dependencies, and locks remain
unchanged. It remains unadmitted under the owner's public-harness-only policy;
neither earlier local checks nor these caller changes establish hosted
acceptance for the current head.

In a separate test on harness PR #1, the owner explicitly authorized a new
`/ready` comment naming the older
`2a7dbf189b9e4a93b5db9c501f49f95883678f63` commit. In
[run 39233021628](https://github.com/ejmlabs/ejm-harness/actions/runs/39233021628),
admission rejected it because the command did not name the current PR head.
Preparation, Quality, registry, Repository standards, AI, and finish jobs all
skipped. Existing commit statuses were unchanged. No model call occurred.

Human commands bind to the full current PR head:

```text
/ready FULL_40_CHARACTER_HEAD_SHA
/approve FULL_40_CHARACTER_HEAD_SHA
/revoke FULL_40_CHARACTER_HEAD_SHA
```

Readiness admits one bounded run. Approval records the human maintainer's
decision, including self approval, through a native bot review. New commits
need new decisions. A human must review and make both decisions for the full
current head. An assistant may record the separate commands only with that
human's explicit authorization for that exact SHA. A generic request to
continue does not grant consent or let the assistant make either decision.

The configured reviewer uses two independent serial `gpt-6.1-sol` passes with
medium reasoning. Builds receive no model key or write token. Static review
uses trusted configuration in an isolated read-only environment. Missing
credentials, invalid output, or blocking findings prevent a passing gate. The
completion-field repair above is required to reject a syntactically valid result
that reports an incomplete review.
The first human-admitted shared PR run passed admission, preparation, Quality,
Repository standards, and the registry adapter. Both AI passes stopped before
model execution because our extra arguments repeated the pinned action's
`--skip-git-repo-check` flag. The required AI review status correctly failed.
The repair removes that duplicate and adds a regression check. The successful
shared and studio acceptance runs above established model access through their
installed repaired callers.
See the [first admitted run](https://github.com/ejmlabs/.github/actions/runs/39188464933).

The model keys used for acceptance were collected through a hidden local
prompt. Current CLI credential configuration and hosted Quality need their
own live evidence; the separate CLI rollout owns that verification. IDE
hosted Quality remains blocked until the harness is public under the owner's
existing access policy. Total provider spending limits and GitHub budgets
still need owner verification.

## Local and hosted evidence

| Area | Evidence | Remaining verification |
| --- | --- | --- |
| Shared standards | All 67 Python policy tests, generator check, actionlint, and uniform standards validation passed for the accepted implementation. PRs #5, #7, #9, and #10 verified both actual AI passes and normal protected merges. PR #12 verified missing-key failure as the sole unmet merge requirement and active revocation, cancellation, and native approval dismissal without model calls; it closed unmerged | Outside-actor admission rejection and real duplicate-tag release acceptance below |
| Studio | Isolated design kit consistency check, all three site tests, site build, shared standards/version checks, and strict OpenSpec validation passed. PR #2 verified both actual AI passes. Revised PR #3 supplied both canonical workflow implementations, received two complete actual Sol 6.1 medium reviews and all five statuses, then merged normally with matching trees and unchanged full protection | The adopted completion boolean needs fresh hosted execution; other live acceptance limits remain below |
| CLI | Complete assembled `./scripts/check` passed on macOS arm64 at `e287e3bbab83e4cc0d2eea94e61d0d819a6acf1f` against reviewed sibling harness `35205aa49b9261d133395c4d6116c37c456ecb95`: 35 unit and 5 integration tests, strict Clippy, release build, Rustdoc, dependency/license checks, and real PTY interaction/restoration. Shared standards/version and strict OpenSpec validation passed. Adoption PR #1 merged as `4b263d4cb2a50a3641d566d6c18fdf7a0551b759` | Current dependency-access and setup rollout, including shared PR #11, and actual two-pass hosted acceptance of current CLI source; earlier local evidence does not establish those results |
| Harness | Earlier assembled macOS workspace gate passed: 157 Rust tests, 4 policy tests, 11 runtime tests, 16 Python SDK tests, 15 TypeScript SDK tests, strict Clippy, formatting, builds, rustdoc, dependency/license checks, generated protocol, lint, types, and Python distributions. One subprocess fixture test was deliberately ignored. The separate registry gate passed after one import reorder: native and WebAssembly Clippy, 2 Rust tests, 10 schema tests, 24 Worker tests, audits, and both actual Worker dry-run builds. Shared standards/version and strict OpenSpec validation passed. Final hosted run 39239206945 passed Linux, macOS, Windows, registry, and standards; all six Windows hook tests passed. PR #1 completed its approved AI-only recovery with matching trees and restored full protection. Live stale-head admission rejection and native approval dismissal after a push were verified. Revised PR #12 supplied canonical workflow sources and received two complete actual reviews; standards, registry, Linux, and macOS passed in run 39267669806 | Windows Quality and protected merge are pending. The proposed completion boolean still needs hosted execution |
| IDE | The assembled gate at `267ad8aa2e42debf5d97ff7ce5ad8dd1c48eb0d8` passed 611 frontend tests, 205 native library tests, 8 integration tests, strict Clippy, formatting, lint, TypeScript, and production builds. Both real extension-template build/import restriction tests passed on Node 24.19.0 with at most two test workers. The proposed npm lock audit reported zero vulnerabilities. Browser fixture checks covered trust in both themes and by keyboard; native tests covered canonical-root trust and expiry. PR #2 head `0b221630db35100b6a0ced1f877b2617cfa9b880` adds only caller and OpenSpec changes since `ad97a401ac956ab7dac167e08d9459b9317309c6`, which changed only OpenSpec evidence from the tested source. Product source, dependencies, locks, and trust UI remain unchanged | PR #2 remains unadmitted until authorized public dependency access; current hosted checks, default-branch dependency alerts, Linux advisory, and other platform acceptance remain open |

The unmerged IDE PR #2 lock uses DOMPurify 3.4.16 and esbuild 0.28.1. At
11:14 UTC, GitHub listed four open dependency advisories on IDE main
`2395ddfbe7d4d252e3985267bf5924317c821cce`: two low advisories for DOMPurify
3.4.15, one low advisory for esbuild 0.27.7, and one medium advisory for glib
0.18.5. The three npm fixes remain in that unmerged PR. Linux still depends
on glib 0.18.5 through GTK, with RUSTSEC-2024-0429 / GHSA-wrw7-89jp-8q8g.
Linux remains unsupported pending a compatible upstream change and native
verification.

The IDE browser checks used fixed fixture responses; they do not verify native
process execution or the desktop host's trust boundary. Seven optional native
tests remained ignored: the disposable Harbor index test and six installed
language-server tests. Windows, installer signing, and distribution remain
unverified by the local gate.

All-ref secret scans of the four original repositories reported no leaks.
Partial source security scans found and led to a fix for automatic execution
of untrusted IDE workspace tooling. These checks do not certify the absence of
other vulnerabilities. Unrelated concurrent product work was excluded from the
adoption patches and requires its own checks.

## Acceptance order and remaining gates

1. Adopt the completion guard and supply canonical old and new shared workflow
   source before resuming studio PR #3 and harness PR #12. Their human decisions
   were recorded, but their actual model summaries were incomplete. Both PRs
   remain drafts. Revised heads need fresh human decisions, both complete AI
   passes, and every required check. Harness recovery is complete; shared and
   earlier studio positive acceptance is recorded above.
2. Verify outsider, bot, and non-maintainer admission rejection and a refused
   duplicate release tag in GitHub. Those cases remain open. Shared PR #12
   verified missing-secret failure, isolated AI-check blocking, revocation,
   native dismissal, and active cancellation. The harness also verified stale
   admission rejection. A new commit dismissed the previous native approval
   and inherited no successful statuses. Local tests alone cannot establish
   untested GitHub integrations.
3. Complete the separately reviewed CLI dependency-access and setup rollout,
   including shared PR #11, then verify its current hosted source and both
   actual AI passes. IDE hosted Quality remains blocked until a separately
   approved visibility change makes the harness public. Its reviewed harness
   pin and admitted checks still need acceptance after that access is available.
   This shared record does not establish current CLI credential configuration
   or private hosted Quality.
4. Complete the remaining local and platform checks above. Keep OpenSpec
   verification tasks open until their evidence exists, then sync and archive.
5. Before any repository becomes public, review all refs and release assets
   again. Activate available public secret scanning, push protection, private
   vulnerability reporting, dependency review, and CodeQL without enrolling in
   a billed private security product. Require approval for all external
   contributors and keep fork secrets/write tokens disabled.

The release pipeline validates independent SemVer metadata, dated notes, an
exact checked main commit, live human decisions, and unchanged reviewed source.
It creates a new tag and a draft source release with archives, checksums, and
provenance. Native installers, signing, registry publication, and deployment
need separate product-specific acceptance. No product tag or release was
created during this setup.

The accepted SemVer correction is retained in combined implementation
`72379a74a1d7c264b2805d8fab87a808c2144458`, whose 63 local policy tests,
generation, actionlint, and whitespace checks passed. PR #7 verified its two
actual AI passes and normal protected merge. The accepted shared caller pins
`965cd684713ae91a7804745eddd452cc392af11d`, which preserves that correction.
This completion repair proposes `aa4144fa978d711a5e009b384718b4cf27cf87bf`,
which also preserves it. Product callers still need reviewed pin updates where
applicable. Live release
creation and recovery remain unverified; no release workflow was dispatched.
