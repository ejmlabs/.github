# Public readiness rollout

Evidence recorded on 2026-10-19 UTC. All five repositories remain private.
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
studio. Harness, CLI, and IDE still need acceptance after their caller updates.

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
`965cd684713ae91a7804745eddd452cc392af11d` through the normal caller. The next
protected change installs its exact shared-only alternate caller. Neither
validator acceptance nor caller installation proves omitted-key behavior.
A dedicated unmerged fixture still needs fresh human admission and live
missing-key, revocation, dismissal, and active-cancellation evidence. See
[the staging procedure](operations.md#missing-model-key-acceptance-staging).

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
fixture repair and fresh hosted checks are required. Any changed head needs
new human decisions and a new exact-head recovery authorization.

Before that push, the owner explicitly authorized a stale-head admission test
on the same PR. A new `/ready` comment named the older
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
credentials, incomplete output, or blocking findings prevent a passing gate.
The first human-admitted shared PR run passed admission, preparation, Quality,
Repository standards, and the registry adapter. Both AI passes stopped before
model execution because our extra arguments repeated the pinned action's
`--skip-git-repo-check` flag. The required AI review status correctly failed.
The repair removes that duplicate and adds a regression check. The successful
shared and studio acceptance runs above established model access through their
installed repaired callers.
See the [first admitted run](https://github.com/ejmlabs/.github/actions/runs/39188464933).

OPENAI_API_KEY exists separately in all five repositories. It was collected
through a hidden local prompt. No private harness access token was provisioned.
Total provider spending limits and GitHub budgets still need owner verification.

## Local and hosted evidence

| Area | Evidence | Remaining verification |
| --- | --- | --- |
| Shared standards | All 59 Python policy tests, generator check, actionlint, uniform standards validation, and secret scan passed for the accepted implementation. PR #5 verified both actual AI passes, all required statuses, native bot self approval, and a normal protected merge | Negative live cases and release acceptance below |
| Studio | Isolated design kit consistency check, all three site tests, site build, shared standards/version checks, and strict OpenSpec validation passed. PR #2 verified all five statuses and both actual AI passes, then merged normally with unchanged full protection and an exact reviewed-tree match | Remaining negative live cases below |
| CLI | Complete assembled `./scripts/check` passed on macOS arm64 at `e287e3bbab83e4cc0d2eea94e61d0d819a6acf1f` against reviewed sibling harness `35205aa49b9261d133395c4d6116c37c456ecb95`: 35 unit and 5 integration tests, strict Clippy, release build, Rustdoc, dependency/license checks, and real PTY interaction/restoration. Shared standards/version and strict OpenSpec validation passed | Updated hosted harness pin, Linux acceptance, and admitted GitHub run; private harness CI remains blocked |
| Harness | Earlier assembled macOS workspace gate passed: 157 Rust tests, 4 policy tests, 11 runtime tests, 16 Python SDK tests, 15 TypeScript SDK tests, strict Clippy, formatting, builds, rustdoc, dependency/license checks, generated protocol, lint, types, and Python distributions. One subprocess fixture test was deliberately ignored. The separate registry gate passed after one import reorder: native and WebAssembly Clippy, 2 Rust tests, 10 schema tests, 24 Worker tests, audits, and both actual Worker dry-run builds. Shared standards/version and strict OpenSpec validation passed. The hosted run passed Linux, macOS, registry, and standards jobs but failed Windows Quality; combined failed-check blocking was observed. The pushed fixture repair has the focused local evidence recorded above. Live stale-head admission rejection and native approval dismissal after a push were verified | Admit the current repair, verify Windows and all non-AI statuses, then complete protected recovery and fresh repaired-caller AI acceptance |
| IDE | The assembled gate at `267ad8aa2e42debf5d97ff7ce5ad8dd1c48eb0d8` passed 611 frontend tests, 205 native library tests, 8 integration tests, strict Clippy, formatting, lint, TypeScript, and production builds. Both real extension-template build/import restriction tests passed on Node 24.19.0 with at most two test workers. The npm lock audit reports zero vulnerabilities. Browser fixture checks covered trust in both themes and by keyboard; native tests covered canonical-root trust and expiry. Current head `ad97a401ac956ab7dac167e08d9459b9317309c6` changes only OpenSpec task evidence from that tested head. The compiled source, dependency graph, locks, and trust UI are unchanged, so the existing native and browser evidence still applies | Reviewed hosted harness pin and admitted GitHub run after authorized public dependency access; Linux advisory and other platform acceptance below |

The IDE lock uses DOMPurify 3.4.16 and esbuild 0.28.1. Linux still depends on
glib 0.18.5 through GTK, with RUSTSEC-2024-0429. Linux support remains unaccepted
until a compatible upstream change and native verification resolve that limit.
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

1. Complete the pending harness recovery through its
   required gates. Verify the installed harness caller with a fresh admitted
   PR. Each exact head needs a human readiness command and a separate approval
   decision. Shared and studio positive acceptance is recorded above.
2. Verify revocation, missing-secret failure, outsider
   and bot admission rejection, and refused duplicate release tags in GitHub.
   These negative cases remain open. The harness runs above demonstrate
   stale-head admission rejection and failed-check blocking in its combined
   failure case. A new commit dismissed the previous native approval and
   inherited no successful statuses. Local tests alone cannot establish these
   GitHub integrations.
3. Merge the harness readiness fixes through the required gates. After a
   separately approved visibility change makes the harness public, update both
   host pins to the reviewed fixed commit and verify CLI and IDE. Their current
   pins predate the harness fixes, and their private cross-repository CI is
   intentionally blocked.
4. Complete the remaining local and platform checks above. Keep OpenSpec
   verification tasks open until their evidence exists, then sync and archive.
5. Before any repository becomes public, review all refs and release assets
   again. Activate available public secret scanning, push protection, private
   vulnerability reporting, dependency review, and CodeQL without enrolling in
   a billed private security product. Require approval for all external
   contributors and keep fork secrets/write tokens disabled.

Missing-key acceptance remains pending. This stage adds exact validator
support for a `.github`-only caller selected by label
`acceptance:missing-model-key`; adoption keeps the normal caller shape.
The normal route forwards existing secrets, while the mutually exclusive
fixture route forwards none. Products reject this caller. Validator adoption
and fixture installation each require their own protected PR before live
negative testing. No secret was removed, no fixture route was installed, and
no missing-key run was dispatched by this stage. See
[operations](operations.md#missing-model-key-acceptance-staging) for the sequence
and evidence required.

The release pipeline validates independent SemVer metadata, dated notes, an
exact checked main commit, live human decisions, and unchanged reviewed source.
It creates a new tag and a draft source release with archives, checksums, and
provenance. Native installers, signing, registry publication, and deployment
need separate product-specific acceptance. No product tag or release was
created during this setup.

The SemVer prerelease correction passed all 60 local policy tests, workflow
generation, actionlint, and whitespace checks. Its implementation commit
`2fa07f9e3abb5c6dd408f1fcc438e7dce553ec74` is retained under its protected
`workflow-pins/FULL_SHA` reference, with updates and deletion blocked and no
bypass actors. This patch updates the shared repository's own callers to that
revision. Product callers still need reviewed pin updates. Live release
creation and recovery remain unverified; no release workflow was dispatched.
