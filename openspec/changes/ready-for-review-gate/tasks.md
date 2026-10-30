# Tasks

## 1. Preconditions

- [ ] 1.1 Confirm the six gate repos either pin `5b7c9836fa4fa91e197baf584d7c74981660bb12` (or newer review-free tip) with the post-AI caller form, or land the open re-pin PRs first; verify with `gh api` on each main `pr.yml` that no caller still passes `XAI_API_KEY` to a pre-removal pin
- [ ] 1.2 Decide fork admission path for this revision (trusted same-repo `pull_request` only vs narrow fork Ready path) and record the choice in design.md if it differs from "maintainer Ready with actor permission check"; verify the choice is reflected in the workflow trigger list before coding

## 2. Gate implementation

- [ ] 2.1 Rewrite admission in `scripts/governance.py` for draft skip, maintainer auto-admit, maintainer-Ready for outsiders, head rebinding on synchronize, and `/approve` / `/revoke` without requiring `/ready FULL_SHA`; verify unit tests in `tests/test_governance.py` cover maintainer push, outsider Ready ignored, maintainer Ready admitted, draft skipped, and self-approve
- [ ] 2.2 Update `scripts/build_workflows.py` triggers and job `if` conditions for the new events; regenerate workflows; verify `python3 scripts/build_workflows.py --check` and `python3 -m unittest discover -s tests -v` pass
- [ ] 2.3 Update `scripts/configure_repositories.py` required contexts to `Quality` and `Repository standards` only; verify the script's expected context list matches the spec
- [ ] 2.4 Dual-accept old and new caller forms in `scripts/standards.py` for one generation if needed for staged rollout; verify standards tests accept both the comment-only caller and the new lifecycle caller against a sample pin

## 3. Docs and agent policy

- [ ] 3.1 Update `docs/operations.md` decision log and admission section for Ready-for-review, auto-admit, and `/approve`; verify the doc no longer requires `/ready FULL_SHA` for ordinary maintainer PRs
- [ ] 3.2 Update `templates/agents/skills/ejmlabs-workflow/SKILL.md` and `references/pr-gate.md` so agents may `gh pr ready` / `/approve` only when the user explicitly asks, and describe the new required checks; verify skill body still meets sync_agents length and link rules via `tests/test_sync_agents.py`
- [ ] 3.3 Update `templates/community/CONTRIBUTING.md` for the new gate (separate adoption PR later is fine); verify the template text matches the spec's contributor-visible behavior

## 4. Rollout

- [ ] 4.1 Merge the shared revision, retain `workflow-pins/FULL_SHA`, and verify the pin branch exists
- [ ] 4.2 For each gate repo, land a pin (and form) PR to the new revision; verify main's `pr.yml` pin and that an admitted maintainer PR publishes only Quality and Repository standards as required contexts
- [ ] 4.3 After each repo's new pin is live, set branch protection required checks to those two contexts and confirm read-back; verify `enforce_admins` and one approving review remain
- [ ] 4.4 Fixture or manual check: maintainer non-draft PR runs checks without a `/ready` comment; outsider Ready alone does not; maintainer `/approve` records a bot approval; verify with Actions run links in the PR

## Workflow follow-up

- Archive this change after verification and sync `pr-gate` into main specs
- Sync community CONTRIBUTING and agent templates into consumers through their normal adoption PRs
- Then enable advisory Bugbot org-wide (separate change)
