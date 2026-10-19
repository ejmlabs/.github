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
repository's main caller now pins repaired revision
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

A fresh human-admitted PR must verify the repaired reviewer and model access.
The four product main callers still use the older revision until their separate
adoption PRs merge. This exception did not change their settings or waive their
remaining quality gates.

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
run using the installed repaired caller must establish account and model access.
See the [first admitted run](https://github.com/ejmlabs/.github/actions/runs/39188464933).

OPENAI_API_KEY exists separately in all five repositories. It was collected
through a hidden local prompt. No private harness access token was provisioned.
Total provider spending limits and GitHub budgets still need owner verification.

## Local evidence

| Area | Evidence | Remaining verification |
| --- | --- | --- |
| Shared standards | All 59 Python policy tests, generator check, actionlint, uniform standards validation, and secret scan passed. Live admission, non-AI checks, native bot self approval, exact merged source, repaired caller installation, and full protection restoration were verified | Successful live AI review and final pinned workflow acceptance |
| Studio | Isolated design kit consistency check, all three site tests, site build, shared standards/version checks, and strict OpenSpec validation passed | Admitted GitHub run |
| CLI | Focused parser and package lifecycle regressions, strict Clippy, architecture/skill checks, shared standards/version checks, and strict OpenSpec validation passed | Complete assembled `./scripts/check` and admitted GitHub run |
| Harness | Focused registry identity and protected-path regressions, policy self-tests, static policy checks, shared standards/version checks, and strict OpenSpec validation passed | Complete workspace, registry, and Windows gates in the assembled adoption snapshot |
| IDE | Before the final dependency update: 611 frontend tests, 205 native library tests, 8 integration tests, Clippy, format, lint, types, frontend build, and site checks/build passed. The updated npm lock audit reports zero vulnerabilities. After the update, the frontend build and both extension-template build/import restriction tests passed on Node 24.19.0 | Assembled full gate, trust UI acceptance in both themes and by keyboard, and admitted GitHub run |

The IDE lock uses DOMPurify 3.4.16 and esbuild 0.28.1. Linux still depends on
glib 0.18.5 through GTK, with RUSTSEC-2024-0429. Linux support remains unaccepted
until a compatible upstream change and native verification resolve that limit.

All-ref secret scans of the four original repositories reported no leaks.
Partial source security scans found and led to a fix for automatic execution
of untrusted IDE workspace tooling. These checks do not certify the absence of
other vulnerabilities. Unrelated concurrent product work was excluded from the
adoption patches and requires its own checks.

## Acceptance order and remaining gates

1. Verify the repaired shared reviewer through a fresh admitted PR. Review the
   four product adoption PRs. Each exact head needs a human readiness command
   and a separate approval decision.
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
