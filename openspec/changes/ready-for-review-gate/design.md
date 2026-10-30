# Design

## Context

Today `scripts/governance.py` and the generated `governance.yml` admit work only from `issue_comment` `/ready|/approve|/revoke` with a full head SHA, `sender.type == User`, and maintain/admin permission. Branch protection requires four contexts including **Human readiness** and **Maintainer approval**. The bot records a native APPROVE on `/approve` so a solo maintainer can merge under `enforce_admins` and `required_approving_review_count: 1`. See proposal.md for why that ritual is being replaced.

`remove-ai-review` already removed the AI job from the shared gate tip; four consumer mains still pin the pre-removal revision. This change assumes those re-pins land first (or in the same rollout window) so no caller still invokes the old AI job.

## Goals / Non-Goals

**Goals:**

- Stop paid checks on drafts and on outsider Ready actions.
- Auto-run checks for maintainer-authored same-repo non-draft PRs on each head.
- Replace the two custom human statuses with GitHub draft/Ready + required reviews.
- Preserve solo-maintainer merge via a simple `/approve`.
- Update agent guidance so explicit maintainer requests can mark Ready or `/approve`.

**Non-Goals:**

- Enabling or requiring Cursor Bugbot (follow-on).
- Changing Quality/Repository standards job contents.
- Admitting fork PRs without a maintainer Ready action.
- Letting agents admit or approve without an explicit human request in-session.

## Decisions

### 1. Trigger on `pull_request` / `pull_request_target` carefully

**Choice:** Drive admission from PR lifecycle events (`opened`, `synchronize`, `ready_for_review`, `converted_to_draft`, `reopened`) in addition to `/approve` and `/revoke` comments. Prefer the trusted caller pattern already used: thin consumer `pr.yml` calling the shared reusable workflow with minimal permissions.

**Why:** Ready-for-review is the native cost-control switch. Comment-only admission cannot see draft transitions.

**Alternatives:** Label `ok-to-test` only — familiar in OSS, but an extra custom concept when draft/Ready already exists. Keep `/ready` forever — rejected for friction.

**Security note:** Do not run untrusted PR code with write tokens. Keep prepare/quality isolation as today. For fork PRs, evaluate admission from event actor + collaborator permission API, never from PR head code. Prefer `pull_request` for same-repo and a narrow trusted path for forks if the current caller model cannot see fork events safely; if fork support stays comment/`workflow_dispatch`-only until a trusted path exists, document that explicitly in tasks and ops.

### 2. Admission predicate

Admit head `H` when all hold:

1. PR open, targets `main`, not draft, same-repository branch (forks: only after maintainer Ready — see below).
2. Either:
   - **Maintainer-authored same-repo:** author has maintain/admin, or
   - **Maintainer Ready:** event is `ready_for_review` and `sender` is a User with maintain/admin (author Ready is ignored when author lacks that role).
3. Size limits still apply (files/lines) before starting paid work.
4. First attempt only; no Actions rerun replay of admission.

On `synchronize` for an already-Ready maintainer-authored PR, re-admit the new head automatically. On `synchronize` for an outsider PR, do **not** auto-admit; require a maintainer to mark Ready again (convert to draft and back, or an explicit maintainer `/ready` retained only as an escape hatch — prefer draft toggle to avoid two admission APIs). **Decision:** outsider re-admission = maintainer converts to draft then Ready again, or posts `/ready` without SHA (current head) as a rare escape hatch. Prefer documenting the draft toggle as the primary path; keep `/ready` (no SHA, current head) as optional escape for one release if tests need it, then drop.

### 3. Status publishing

**Choice:** Stop publishing **Maintainer approval** as a required context. Optionally keep an informational **Human readiness** / **CI admitted** status for UI clarity, but remove it from required checks so merge depends on Quality, Repository standards, and GitHub reviews only.

**Why:** Missing Quality/standards already block merge under strict checks. Two extra contexts force the SHA ritual.

**Self-approve:** `/approve` or `/approve FULL_SHA` → validate maintainer → create `github-actions[bot]` APPROVE review on that commit (existing mechanism). `dismiss_stale_reviews` already clears it on new pushes.

### 4. Branch protection updates

**Choice:** `configure_repositories.py` sets required contexts to `Quality` and `Repository standards` only; keep `required_approving_review_count: 1`, `dismiss_stale_reviews: true`, `enforce_admins: true`.

**Rollout:** Change protection in each repo only when that repo's caller pin runs the new gate (or immediately after, if the new gate no longer publishes the old statuses — never require a status the gate stopped publishing).

### 5. Agent policy

**Choice:** Update `ejmlabs-workflow` skill and `pr-gate.md`: when the user explicitly asks to admit/approve/merge, the agent MAY run `gh pr ready`, `gh pr comment ... /approve`, and merge after green checks, using the user's `gh` auth. Agents MUST NOT do those steps unprompted.

## Risks / Trade-offs

- **[Risk] Fork Ready by author starts CI if we only key off `ready_for_review`** → Mitigation: require maintain/admin on the event actor for non-maintainer-authored PRs.
- **[Risk] `pull_request_target` misuse** → Mitigation: no checkout of PR head for privileged jobs; reuse existing trusted prepare path; prefer same-repo `pull_request` where sufficient.
- **[Risk] Solo maintainer forgets `/approve`** → Mitigation: docs and agent skill prompt for `/approve` after green when no other review exists.
- **[Risk] Overlap with open remove-ai-review pins** → Mitigation: land consumer re-pins to `5b7c983` first; then ship this as the next shared revision.
- **[Trade-off] Outsider new commits need another maintainer Ready** → Acceptable cost-control trade; document draft toggle.

## Migration Plan

1. Finish `remove-ai-review` re-pins on the six gate repos (drop `XAI_API_KEY` / unlabeled).
2. Implement and merge the new gate in `ejmlabs/.github`; retain under `workflow-pins/FULL_SHA`.
3. Owner updates branch protection to the two contexts (script or UI) as each repo adopts, never requiring removed statuses.
4. Pin-only then docs/template sync PRs per consumer (staged if standards still dual-accept).
5. Delete obsolete `/ready FULL_SHA` docs; teach Ready + `/approve`.
6. Rollback: re-pin callers to the previous retained pin and restore the four contexts if needed.

## Open Questions

- Whether to keep a no-SHA `/ready` escape hatch for outsider re-admission after synchronize, or rely only on draft→Ready toggles (default: draft toggle only unless implementation proves awkward).
