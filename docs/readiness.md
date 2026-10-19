# Public readiness rollout

Evidence recorded on 2026-10-19. A fresh settings audit at 16:18-16:23 UTC
found all five repositories private with their required protections intact.
The source-history scan below records its exact scope; later draft preparation
and earlier hosted acceptance are described separately.
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
The revised studio and harness refreshes merged normally after two complete
reviews of both pinned implementations and all required checks. They install
the earlier completion-only revision `aa4144fa978d711a5e009b384718b4cf27cf87bf`.
Shared PR #14 then merged the combined
`c4f2873ef0eef5bc3c7d75cf71fa3489a911d134` adoption after complete reviews,
including the CLI and harness prerequisites and canonical source pair. Studio
PR #4 verified the installed completion boolean at `aa4144fa...`; its passing
run does not prove execution of the combined caller. CLI PR #4 then adopted
the combined revision as `d5113beb9c42565e6dc124052dbd633d0d12d25d`, and
harness PR #13 adopted it as `99ba4575ad9070a7a0f3296a35e746858af904b0`.
Their protected checks passed. The required API source and atomic CLI
dependency update remain separate from those caller changes. IDE repairs and
the owner's public visibility work follow their separate rollout.

### Proposed CLI dependency selection

The CLI dependency update has a concrete lockfile constraint. An offline
metadata check used protected CLI `d5113beb9c42565e6dc124052dbd633d0d12d25d`,
the current harness pin `4a751c6a3f24d7d143140f79ff53517fb93e3531` and
proposed harness API head `90aa7350e30eaad908d14e8b3260610d5f15f2fe`.
The old pair passed with the original lock. The new pair required a resolved
lock, which then failed against the old harness under `--locked`. Both source
fixture locks were restored. These metadata results are not product gates or
acceptance of that unmerged API head.

The proposed shared preparation change verifies a CLI head's harness pin
against the fixed repository's protected main history and binds the selected
source archive to its review context. IDE retains trusted-base selection.
See [the selection contract and adoption order](operations.md#cli-harness-pin-updates).
The current C4 callers do not contain this change. Shared review, retained
implementation identity, CLI caller adoption and a fresh atomic pin/lock
consumer gate remain pending. No policy exception is part of this change.
The owner's separate public-source rollout controls repository visibility.
Earlier entries below retain their named source snapshots; later adoption
records above supersede their then-current caller status.

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
Studio and harness adopted this earlier repair through the protected merges
below. Their adoption runs used older validators. Studio PR #4 later exercised
the installed completion field; shared PR #14 adopted the combined revision.
Both revised product heads include the canonical old and new shared source
and received complete reviews under their previous default callers. No
exception or automatic model retry is authorized by this repair. Both original
product heads were converted to drafts
to block merging while this gap is repaired. Their reviewed heads and recorded
human comments were preserved.

The original completion-only implementation passed all 75 policy tests,
generated workflow checks, actionlint, repository standards,
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

Head `c0505e774fd57497e226dd244ff9caf1f464f139` added the missing old and new
source pair. Its admitted
[run 39270766743](https://github.com/ejmlabs/.github/actions/runs/39270766743)
was canceled after protected main advanced and the PR conflicted. Pass 1 was
interrupted; pass 2 never started under the serialized review strategy. This
run does not establish two complete reviews or acceptance of a later head.
PR #14 was returned to draft.

Protected main advanced to
`8c304c8cdfc8b6fe50f3e442507215e615944f2b`, adding the scoped CLI setup action
and Linux harness `pkg-config` and `libdbus-1-dev` prerequisites while retaining
the trusted default caller's `965cd684713ae91a7804745eddd452cc392af11d` pin.
Combined implementation `c4f2873ef0eef5bc3c7d75cf71fa3489a911d134` merges that
main with the completion boolean and exporter hardening, preserving both
prerequisite steps and their regression tests. Its tree is
`dc440b03159b377979b6b76dde119eec98aa75cb`. Its protected retention reference
was verified at 14:46:29 UTC under active rule `25369476`, with updates and
deletion blocked and no bypass actors. All 77 policy tests, generated workflow
checks, the four named workflow actionlint checks, and repository standards
passed locally for the integrated source.

The shared adoption selects that combined revision for both PR routes and
the draft release caller, including `standards-ref`. Its own
`.github/review-context/` now contains the exact old
`965cd684713ae91a7804745eddd452cc392af11d` and new
`c4f2873ef0eef5bc3c7d75cf71fa3489a911d134` implementations, using the same
16-file source list per revision and a manifest. Local checks compare the
bytes, manifest, and modes against canonical Git objects and enforce the
750,000-byte bound. These files are static review data and are never executed
or imported.

After fresh exact-head human decisions, PR #14 at
`daaf7148e5c229a6c543b24ffecbd47ad70cb131` passed all five required statuses in
[run 39274644494](https://github.com/ejmlabs/.github/actions/runs/39274644494).
Both actual Sol 6.1 medium reviews completed with no findings. Artifact digests
matched; 55 canonical source checks passed. It merged normally at 15:14:26 UTC
as `d00d8bbc7231485eb918008c562d835f394e82ea`, with matching reviewed and
merged trees and unchanged full protection. No exception was used. This run
used the old `965cd684...` validator, so completeness was verified from both
actual outputs and transcripts. The merge installs `c4f2873e...`; it does not
prove hosted execution of that combined implementation.

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

Studio [PR #4](https://github.com/ejmlabs/ejmlabs/pull/4) tested that installed
guard at head
`da9c01d6138f1757cda9109431c32fd59a581a29`, based on
`a1b3fa068b7147410d0f72217d522b47ecd36759`. It changes only OpenSpec evidence;
its caller remains at `aa4144fa978d711a5e009b384718b4cf27cf87bf`. After fresh
human decisions, [run 39274657683](https://github.com/ejmlabs/ejmlabs/actions/runs/39274657683)
passed all five required statuses. Both distinct Sol 6.1 medium sessions
returned `complete: true`, no findings, and matching result artifact digests.
It merged normally at 15:08:54 UTC as
`c91bd8640895d186355bae72d8d7bb8ae487fed2`. The reviewed and merged trees
matched, and full protection stayed unchanged. This verifies positive hosted
execution of the installed guard, not the combined `c4f2873e...` caller.

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
had passed; Windows Quality was still active. The run then completed
successfully with all five required statuses, Linux, macOS, Windows, and
registry checks passing. Both complete review artifacts and their digests,
separate exact-head human decisions, and the native approval were verified.

PR #12 merged normally at 14:47:32 UTC as
[`09b779ee0452dda07b7f52503be22e65fe238373`](https://github.com/ejmlabs/ejm-harness/commit/09b779ee0452dda07b7f52503be22e65fe238373).
The reviewed and merged trees both equal
`c98793042e99e9a7c716aee39e69b05428edfaa8`, and full main protection was
unchanged. No exception was used. The run executed old pin
`5fae851502c2e3c31d4df9a44f8d56c2cb49e098`; the merge installs
`aa4144fa978d711a5e009b384718b4cf27cf87bf`. It does not establish hosted
enforcement of the new completion boolean or adoption of the combined
prerequisite revision.

CLI [adoption PR #1](https://github.com/ejmlabs/ejm-cli/pull/1) also merged as
`4b263d4cb2a50a3641d566d6c18fdf7a0551b759`. Current CLI dependency access and
setup follow their separate rollout, including shared
[PR #11](https://github.com/ejmlabs/.github/pull/11), which merged into shared
main as `8c304c8cdfc8b6fe50f3e442507215e615944f2b`. Consumer adoption of its
prerequisites and actual two-pass acceptance of the current CLI caller remain
separate from that shared merge. The current CLI callers pin
`ae903129564926a14287f75d2012610c59cccb65`, which lacks the completion guard.
Its reviewed update and consumer acceptance belong to the separate CLI rollout.

IDE [PR #2](https://github.com/ejmlabs/ejm-ide/pull/2) now has head
`c3e17d59e47683286675ef631bf9069883d4066a`, preparing the combined guarded
caller, its exact old/new static sources, and reviewed harness main
`09b779ee0452dda07b7f52503be22e65fe238373` as its proposed dependency pin.
Its 24 consumed core/auth/exec production files and harness lock match the
previously verified dependency source. Seven unchanged generated OpenSpec
skills are preserved separately in [draft PR #3](https://github.com/ejmlabs/ejm-ide/pull/3)
at `703f4bce5b2f691cae7f9238d95c459eda1ad841` to keep both changes within
review bounds. The exact GitHub diff for PR #2 is 940,823 bytes across 92 files,
within its 1,000,000-byte and 200-file limits. Product source and locks remain
unchanged from the locally tested preparation. PR #2 had zero head-specific
runs, statuses, and check runs after its update; PR #3 had zero at its 15:32 UTC
readback. Neither is admitted. This PR's Quality job still uses the old pin
from trusted base; a submitted dependency pin cannot replace that checkout.
IDE main still uses the old broken caller. Hosted acceptance waits for public
harness access, fresh human decisions, and a separately authorized recovery
for the final exact repair head; no IDE exception is authorized. After PR #2
merges, refresh PR #3 and use it to verify the installed caller and harness pin.

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
| Shared standards | The earlier accepted implementation passed all 67 Python policy tests, generator check, actionlint, and uniform standards validation. PRs #5, #7, #9, and #10 verified both actual AI passes and normal protected merges. PR #12 verified missing-key failure as the sole unmet merge requirement and active revocation, cancellation, and native approval dismissal without model calls; it closed unmerged. Combined retained revision `c4f2873e...` passed 77 local policy tests and focused checks. PR #14 adopted it after two complete reviews and all five checks, with matching trees and unchanged protection | Hosted execution of the combined caller remains separate. Public security settings, outside-actor cases, owner budgets, and release acceptance remain unverified |
| Studio | Isolated design kit consistency check, all three site tests, site build, shared standards/version checks, and strict OpenSpec validation passed. PR #2 verified both actual AI passes. Revised PR #3 supplied both canonical workflow implementations, received two complete actual Sol 6.1 medium reviews and all five statuses, then merged normally with matching trees and unchanged full protection. PR #4 verified both actual reviews with `complete: true` through installed `aa4144fa...`, then merged normally | Current-source publication checks and the remaining live acceptance cases below |
| CLI | Complete assembled `./scripts/check` passed on macOS arm64 at `e287e3bbab83e4cc0d2eea94e61d0d819a6acf1f` against reviewed sibling harness `35205aa49b9261d133395c4d6116c37c456ecb95`: 35 unit and 5 integration tests, strict Clippy, release build, Rustdoc, dependency/license checks, and real PTY interaction/restoration. Shared standards/version and strict OpenSpec validation passed. Adoption PR #1 merged as `4b263d4cb2a50a3641d566d6c18fdf7a0551b759`. Shared PR #11 merged its prerequisites into shared main | Reviewed consumer adoption of the combined prerequisites and actual two-pass hosted acceptance of current CLI source; earlier local and shared-source evidence do not establish those results |
| Harness | Earlier assembled macOS workspace gate passed: 157 Rust tests, 4 policy tests, 11 runtime tests, 16 Python SDK tests, 15 TypeScript SDK tests, strict Clippy, formatting, builds, rustdoc, dependency/license checks, generated protocol, lint, types, and Python distributions. One subprocess fixture test was deliberately ignored. The separate registry gate passed after one import reorder: native and WebAssembly Clippy, 2 Rust tests, 10 schema tests, 24 Worker tests, audits, and both actual Worker dry-run builds. Shared standards/version and strict OpenSpec validation passed. Final hosted run 39239206945 passed Linux, macOS, Windows, registry, and standards; all six Windows hook tests passed. PR #1 completed its approved AI-only recovery with matching trees and restored full protection. Live stale-head admission rejection and native approval dismissal after a push were verified. Revised PR #12 supplied canonical workflow sources, received two complete actual reviews and all five statuses in run 39267669806, then merged normally with matching trees and unchanged full protection | Current-source publication checks. Harness has not exercised its installed completion field; Studio verified the same guard. Adoption of the combined prerequisites remains separate and precedes acceptance of the new native keyring backend |
| IDE | The assembled gate at `267ad8aa2e42debf5d97ff7ce5ad8dd1c48eb0d8` passed 611 frontend tests, 205 native library tests, 8 integration tests, strict Clippy, formatting, lint, TypeScript, and production builds. Both real extension-template build/import restriction tests passed on Node 24.19.0 with at most two test workers. The proposed npm lock audit reported zero vulnerabilities. Browser fixture checks covered trust in both themes and by keyboard; native tests covered canonical-root trust and expiry. Draft PR #2 prepares the combined caller and exact source context; draft PR #3 preserves generated OpenSpec skills. Product source, dependencies, locks, and trust UI remain unchanged from the tested preparation | Both drafts remain unadmitted. Public harness access, current hosted checks, installed-caller repair, default-branch npm fixes, the Linux advisory, and other platform acceptance remain open |

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

At 16:22 UTC, Gitleaks 8.30.1 reported no secret-pattern matches in fresh
mirrors of the five publication-path repositories. Each scan recorded its
exact fetched ref manifest, main SHA, reachable commits, scanner version,
configuration hash, and redacted result. The scan used built-in rules, an empty
trusted ignore file, disabled inline suppressions, full redaction, and explicit
merge-resolution diffs through
`--all --full-history --diff-merges=first-parent`.

| Repository | Fetched refs | Reachable commits | Merge commits | Candidates |
| --- | ---: | ---: | ---: | ---: |
| `.github` | 33 | 48 | 5 | 0 |
| Harness | 36 | 43 | 12 | 0 |
| Studio | 5 | 18 | 0 | 0 |
| IDE | 10 | 17 | 3 | 0 |
| CLI | 4 | 19 | 0 | 0 |

That snapshot does not cover later draft commits. Refresh the affected scope
before publication. Pattern detection cannot establish the absence of all
secrets; unreachable Git objects and Git LFS object contents were outside the
history scan. Discussions, Actions logs, retained artifacts, and release assets
need their own exposure review.
Partial source security scans found and led to a fix for automatic execution
of untrusted IDE workspace tooling. These checks do not certify the absence of
other vulnerabilities. Unrelated concurrent product work was excluded from the
adoption patches and requires its own checks.

## Acceptance order and remaining gates

No source repository has been made public by this rollout. The source critical
path is:

1. Audit current refs, history, private data, discussions, and retained assets.
   Review licenses and current dependency findings. Earlier clean scans do not
   cover unrecorded later source or refs.
2. With owner approval, disable Actions and verify it is disabled before each
   visibility change. Publish `.github` before harness. GitHub permits a
   public caller to use reusable workflows only from public repositories; see
   [its access matrix](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#access-to-reusable-workflows).
   Verify anonymous access to the exact source and retained workflow pins.
3. Keep Actions disabled across each visibility change. Set and read back
   approval for all external Actions contributors after the repository becomes
   public, then verify pinned allowed sources, read-only tokens, disabled fork
   secrets/write tokens, and main protections before re-enabling Actions. Enable
   and verify available free public secret scanning, push protection, private
   vulnerability reporting, and dependency alerts/updates. Dependency review
   and code scanning must preserve human admission; automatic CodeQL default
   setup is not part of this cutover. Public controls and owner verification
   of OpenAI spending limits and GitHub budgets remain pending. Do not enroll
   private repositories in billed security products.
4. Use public harness access to finish the reviewed CLI and IDE caller/pin
   changes and their human-admitted checks. IDE needs its own exact-head
   recovery authorization before any exception, then both real reviews through
   the installed repaired caller. Keep shared UI dependencies accessible where
   consumers require them. Current harness source and its SDKs have no ejm-ui
   build dependency.

Genuine outsider, bot, nonmaintainer, and fork admission tests remain unverified.
Shared PR #12 covered missing keys and active revocation; harness covered stale
heads. Those cases do not prove other identities or public event delivery. Keep
the missing live tests open without treating them as binary-release work.

First-release creation and real duplicate-tag refusal remain release acceptance.
Native builds, signing/notarization, package registries, and deployments need
their own authorization and evidence; they do not block publishing audited
source. The separate new harness host-auth feature is not required to publish
the already-reviewed main. Keep OpenSpec verification tasks open until their
own work is verified, then sync and archive.

The release pipeline validates independent SemVer metadata, dated notes, an
exact checked main commit, live human decisions, and unchanged reviewed source.
It creates a new tag and a draft source release with archives, checksums, and
provenance. Native installers, signing, registry publication, and deployment
need separate product-specific acceptance. No product tag or release was
created during this setup.

The accepted SemVer correction is retained in combined implementation
`72379a74a1d7c264b2805d8fab87a808c2144458`, whose 63 local policy tests,
generation, actionlint, and whitespace checks passed. PR #7 verified its two
actual AI passes and normal protected merge. The accepted shared caller now pins
`c4f2873ef0eef5bc3c7d75cf71fa3489a911d134`, which preserves that correction.
The earlier product completion repair at
`aa4144fa978d711a5e009b384718b4cf27cf87bf` and the combined shared implementation at
`c4f2873ef0eef5bc3c7d75cf71fa3489a911d134` also preserve it. Product callers
still need reviewed pin updates where
applicable. Live release
creation and recovery remain unverified; no release workflow was dispatched.
