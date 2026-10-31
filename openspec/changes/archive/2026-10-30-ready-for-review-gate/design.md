# Design

## Context

Today `scripts/governance.py` admits work by regex-matching `/ready|/approve|/revoke` comment bodies and by stuffing opaque tokens into commit-status descriptions. That is brittle. See proposal.md for why the SHA comment ritual is being replaced.

`remove-ai-review` consumer re-pins are on main. This change is the next shared gate revision.

## Goals / Non-Goals

**Goals:**

- Admit from GitHub PR lifecycle fields and collaborator permissions only.
- Use labels (not slash commands) for maintainer self-approve and explicit revoke.
- Verify later jobs by re-reading the live Pull Request API and job outputs, not by parsing status text.
- Auto-run checks for maintainer-authored same-repo non-draft PRs.
- Require a maintainer Ready-for-review action for outsiders and forks.

**Non-Goals:**

- Comment-body command protocols.
- Regex or substring matching on comment text or status descriptions for control flow.
- Enabling Bugbot (follow-on).
- Changing Quality / Repository standards job contents.

## Decisions

### 1. Admission is event + API state

**Choice:** Drive admission from `pull_request` actions `opened`, `reopened`, `synchronize`, `ready_for_review`, `converted_to_draft`.

Admit head `H` when:

1. PR is open, targets `main`, not draft.
2. Either:
   - same-repository and author has maintain/admin, or
   - event is `ready_for_review` and `sender` is a User with maintain/admin.
3. Size limits still apply before starting paid work.
4. First workflow attempt only.

On `converted_to_draft`, cancel any in-flight admitted run for that head and publish failure for orchestration statuses if present.

**Why:** Draft / Ready and actor permission are first-class GitHub fields. No comment parsing.

### 2. Labels for approve and revoke

**Choice:** Reserved labels, applied only by maintainers (enforced in the workflow by permission check, not by GitHub label ACLs):

| Label | Effect |
| --- | --- |
| `gate:approve` | If actor is maintain/admin, record `github-actions[bot]` APPROVE on the current head, then remove the label so it can be re-applied after a new push. |
| `gate:revoke` | If actor is maintain/admin, dismiss bot approvals for the head, cancel the admitted run, fail orchestration, remove the label. |

Exact full-string label name equality only (`== "gate:approve"`), no patterns.

**Why:** Labels are structured event payloads (`github.event.label.name`). Equality beats regex. Solo maintainers still get a self-approve path under `enforce_admins`.

**Alternatives rejected:** Slash commands (brittle text), status-description tokens, requiring a second human always.

### 3. No control-plane data in status descriptions

**Choice:** Commit statuses for **Quality** and **Repository standards** carry only human-readable pass/fail text. Job outputs (`run`, `pr`, `head`, `base`, `profile`) carry admission through the workflow. `finish` / `verify` re-fetch the PR and require: same head SHA, non-draft, targets main. They do not parse status descriptions for tokens.

**Human readiness** and **Maintainer approval** statuses are removed from publishing and from branch protection.

### 4. Required merge controls

**Choice:** Branch protection requires `Quality` and `Repository standards` plus one approving GitHub review (`dismiss_stale_reviews`, `enforce_admins`). Self-approve is the bot review from `gate:approve`.

### 5. Agent policy

**Choice:** When the user explicitly asks, agents may `gh pr ready`, `gh pr edit --add-label gate:approve`, and merge after green checks. Agents must not do those unprompted.

### 6. Caller rollout

**Choice:** Shared `governance.yml` gains `pull_request` + `pull_request` labeled triggers via the reusable workflow's caller. `standards.py` dual-accepts the previous comment-only caller and the new lifecycle caller for one generation. This implementation PR keeps `.github`'s own `pr.yml` on the previous form so the live pin's standards still pass; a follow-up pin adopts the new caller.

## Risks / Trade-offs

- **[Risk] Anyone with write can add labels** → Mitigation: workflow checks maintain/admin on the label event actor before approving or revoking.
- **[Risk] Outsider marks their own PR Ready** → Mitigation: admit only when the Ready actor is maintain/admin for non-maintainer authors.
- **[Risk] Label left on after approve** → Mitigation: remove `gate:approve` / `gate:revoke` after handling.
- **[Trade-off] Outsider pushes need another maintainer Ready** → Acceptable cost control; document draft toggle.

## Migration Plan

1. Land shared revision (scripts + generated workflows + docs/skills/templates).
2. Retain `workflow-pins/FULL_SHA`.
3. Pin consumers; switch callers to the lifecycle form; set protection to the two contexts.
4. Create the two labels in each gate repo (script or API).
5. Rollback: re-pin previous retained revision.

## Open Questions

None.
