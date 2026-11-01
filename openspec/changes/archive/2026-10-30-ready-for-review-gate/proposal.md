# Proposal

## Why

The `/ready FULL_SHA` and `/approve FULL_SHA` comment ritual blocks the maintainer and every agent session on paste-the-SHA friction. The real goal of the gate is cost control: outsiders must not start paid Actions runs. GitHub already has the right primitive for that: draft versus Ready for review, plus required pull request reviews.

## What Changes

- **BREAKING**: Stop requiring `/ready FULL_SHA` to admit CI. Non-draft PRs are admitted by GitHub Ready-for-review rules instead.
- Auto-admit same-repository, non-draft PRs whose author is a current maintainer or admin on every open, synchronize, and ready_for_review event for the current head.
- For fork PRs and non-maintainer authors, admit only when a current maintainer or admin marks the PR Ready for review (the actor who leaves draft must be a maintainer). Draft PRs never run paid checks.
- **BREAKING**: Drop the required **Human readiness** and **Maintainer approval** commit statuses from branch protection. Required checks become **Quality** and **Repository standards**.
- Keep GitHub's required approving review (already configured). Other people approve with a normal GitHub review.
- Keep a one-click maintainer self-approve via label `gate:approve` (exact name); trusted automation records a bot approval for the current head and removes the label.
- Revoke via label `gate:revoke` or by converting the PR back to draft.
- Do not use slash-command comment protocols or status-description tokens for control flow.
- Update shared agent skills and community docs: agents may mark Ready for review or add `gate:approve` when the maintainer explicitly asks; they must not admit or approve on their own.
- Sequence after (or with) finishing `remove-ai-review` consumer re-pins so callers are not still on the old AI-review pin while this ships.

## Capabilities

### New Capabilities

- `pr-gate`: Human-gated PR admission and merge controls for ejmlabs repositories (who can start paid checks, how approval is recorded, what statuses main requires).

### Modified Capabilities

- (none in main `openspec/specs/` yet; `remove-ai-review` carries an in-flight `pr-gate` delta that this change supersedes for admission and approval)

## Impact

- Shared: `scripts/governance.py`, `scripts/build_workflows.py`, `scripts/configure_repositories.py`, `scripts/standards.py`, generated `governance.yml`, tests, `docs/operations.md`, community `CONTRIBUTING` template, agent skills under `templates/agents/skills/ejmlabs-workflow/`.
- Consumers: all six gate repositories re-pin callers and update protection to the two remaining statuses; contributor docs change after the template sync.
- Maintainer workflow: open a non-draft PR (or mark Ready) → checks run → someone reviews, or post `/approve` for self-merge → squash merge.
- Does not enable Bugbot; advisory Bugbot remains a follow-on after the custom AI reviewer is fully retired.
