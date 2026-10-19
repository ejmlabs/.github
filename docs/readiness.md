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
The final retry guard becomes active for each consumer after its pin update
merges. A fresh admitted PR must verify that revised workflow after rollout.

### Shared workflow recovery

[PR #4](https://github.com/ejmlabs/.github/pull/4) merged as
`a692cb5e6e141103f7c312dc9c42a201184fadf6` on 2026-10-19 UTC. The shared
repository's main caller then pinned repaired revision
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

At that point, a fresh human-admitted PR still needed to verify the repaired
reviewer and model access. The four product main callers still use the older
revision until their separate adoption PRs merge. This exception did not change
their settings or waive their remaining quality gates.

The first acceptance attempt on [PR #5](https://github.com/ejmlabs/.github/pull/5)
failed before jobs started: Actions reported that the pinned reusable workflow
`8e888752e00a29363fb8ae125658159b5c2dee58` was not found. The Contents API still
returned that file, but the squash merge had deleted its retaining branch.
No model call occurred. See the [startup failure](https://github.com/ejmlabs/.github/actions/runs/39191146628).

The recovery implementations, including
`5fae851502c2e3c31d4df9a44f8d56c2cb49e098`, received `workflow-pins/FULL_SHA`
retention branches. Active rules block updates and deletion, with no bypass
actors. Main protection still matches its fully restored snapshot. Creating
these references triggered no CI or AI runs. Reference retention alone did not
verify workflow resolution or model access.

### Corrected CLI validator and caller adoption

[PR #6](https://github.com/ejmlabs/.github/pull/6) passed its
[admitted run](https://github.com/ejmlabs/.github/actions/runs/39234908854) for
reviewed head `b0c4a01a346b22ac9539e6552706145beba7cbbf`. Admission,
preparation, Ubuntu quality, registry, standards, both independent AI passes and
finalization all succeeded. All five required commit statuses succeeded and
GitHub recorded an approved, clean review state. The maintainer's separate
[approval command](https://github.com/ejmlabs/.github/pull/6#issuecomment-6264790709)
preceded the protected squash merge at 2026-10-19 10:11:55 UTC, producing actual
main commit `f58c0225d5d54efcec6dae018cf58a127ecc8544`.

The reviewed implementation remains reachable at
`workflow-pins/b0c4a01a346b22ac9539e6552706145beba7cbbf`, whose object is the
exact reviewed head. Readback confirmed active ruleset `25369476` blocks updates
and deletion for retained workflow pins, with no bypass actors. These results
cover the central change. They do not establish CLI, relay, browser, Linux or
macOS product acceptance.

The successful run used the previously installed shared revision
`5fae851502c2e3c31d4df9a44f8d56c2cb49e098`. This source adopts retained
`b0c4a01a346b22ac9539e6552706145beba7cbbf` in both central caller `uses`
references and the draft-release `standards-ref`. It changes no reusable job,
permission, admission gate, action policy or setup execution. Protected merge
and a fresh admitted run are still required to verify the new caller pin.

The separate CLI setup hook must be rebased onto the actual merge of this
adoption before human admission. Keep it in a private draft until this validator
is active and the trusted CLI baseline has its reviewed setup action and
working immutable harness pin. No product or stage-two caller is changed here.

Human commands bind to the full current PR head:

```text
/ready FULL_40_CHARACTER_HEAD_SHA
/approve FULL_40_CHARACTER_HEAD_SHA
/revoke FULL_40_CHARACTER_HEAD_SHA
```

Readiness admits one bounded run. Approval records the human maintainer's
decision, including self approval, through a native bot review. New commits
need new decisions. Never post these commands on a human's behalf.

The configured reviewer uses two independent serial `gpt-6.1-sol` passes with
medium reasoning. Builds receive no model key or write token. Static review
uses trusted configuration in an isolated read-only environment. Missing
credentials, incomplete output, or blocking findings prevent a passing gate.
The first human-admitted shared PR run passed admission, preparation, Quality,
Repository standards, and the registry adapter. Both AI passes stopped before
model execution because our extra arguments repeated the pinned action's
`--skip-git-repo-check` flag. The required AI review status correctly failed.
The repair removes that duplicate and adds a regression check. A fresh admitted
run using the installed repaired caller was still needed at that point to
establish account and model access.
See the [first admitted run](https://github.com/ejmlabs/.github/actions/runs/39188464933).

OPENAI_API_KEY exists separately in all five repositories. It was collected
through a hidden local prompt. No private harness access token was provisioned.
Total provider spending limits and GitHub budgets still need owner verification.

## Local evidence

| Area | Evidence | Remaining verification |
| --- | --- | --- |
| Shared standards | All 62 Python policy tests, generator freshness, actionlint and uniform standards validation passed for this caller adoption. PR #6 passed every hosted job, including both AI passes, before its protected merge. The corrected implementation is retained under a protected immutable reference | Protected merge of this caller adoption and a fresh admitted run using the corrected validator; separate product and setup-hook adoption |
| Studio | Isolated design kit consistency check, all three site tests, site build, shared standards/version checks, and strict OpenSpec validation passed | Admitted GitHub run |
| CLI | Complete assembled `./scripts/check` passed on macOS arm64 at `e287e3bbab83e4cc0d2eea94e61d0d819a6acf1f` against reviewed sibling harness `35205aa49b9261d133395c4d6116c37c456ecb95`: 35 unit and 5 integration tests, strict Clippy, release build, Rustdoc, dependency/license checks, and real PTY interaction/restoration. Shared standards/version and strict OpenSpec validation passed | Updated hosted harness pin, Linux acceptance, and admitted GitHub run; private harness CI remains blocked |
| Harness | Assembled macOS workspace gate passed: 157 Rust tests, 4 policy tests, 11 runtime tests, 16 Python SDK tests, 15 TypeScript SDK tests, strict Clippy, formatting, builds, rustdoc, dependency/license checks, generated protocol, lint, types, and Python distributions. One subprocess fixture test was deliberately ignored. The separate registry gate passed after one import reorder: native and WebAssembly Clippy, 2 Rust tests, 10 schema tests, 24 Worker tests, audits, and both actual Worker dry-run builds. Shared standards/version and strict OpenSpec validation passed | Linux and Windows acceptance and admitted GitHub run |
| IDE | Before the final dependency update: 205 native library tests, 8 integration tests, Clippy, native formatting, and site checks/build passed. The updated npm lock audit reports zero vulnerabilities. After the update, all 611 frontend tests, formatting, lint, strict TypeScript, the frontend build, and both real extension-template build/import restriction tests passed on Node 24.19.0 with at most two test workers | Assembled native gate, trust UI acceptance in both themes and by keyboard, and admitted GitHub run |

The IDE lock uses DOMPurify 3.4.16 and esbuild 0.28.1. Linux still depends on
glib 0.18.5 through GTK, with RUSTSEC-2024-0429. Linux support remains unaccepted
until a compatible upstream change and native verification resolve that limit.

All-ref secret scans of the four original repositories reported no leaks.
Partial source security scans found and led to a fix for automatic execution
of untrusted IDE workspace tooling. These checks do not certify the absence of
other vulnerabilities. Unrelated concurrent product work was excluded from the
adoption patches and requires its own checks.

## Acceptance order and remaining gates

1. Merge this central validator-pin adoption through the required gates, then
   verify a fresh admitted run under the retained corrected validator. Rebase
   the separate setup-hook change onto the actual adoption merge before human
   admission. Review the four product adoption PRs separately. Each exact head
   needs a fresh human readiness command and a separate approval decision.
2. Confirm live delivery, native bot self approval, stale commit rejection,
   revocation, missing-secret failure, failed-check blocking, and refused
   duplicate release tags before claiming live enforcement. Local tests alone
   cannot establish these GitHub integrations.
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

The release pipeline validates independent SemVer metadata, dated notes, an
exact checked main commit, live human decisions, and unchanged reviewed source.
It creates a new tag and a draft source release with archives, checksums, and
provenance. Native installers, signing, registry publication, and deployment
need separate product-specific acceptance. No product tag or release was
created during this setup.
