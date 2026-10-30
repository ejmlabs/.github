# Tasks

## 1. Preconditions

- [x] 1.1 Confirm the six gate repos pin the review-free revision with the post-AI caller form; verified via `gh api` on each main `pr.yml`
- [x] 1.2 Fork path: same-repo `pull_request` auto-admit for maintainer authors; outsiders/forks need maintainer Ready; labels for approve/revoke; recorded in design.md

## 2. Gate implementation

- [x] 2.1 Rewrite `scripts/governance.py` for event/API admission, `gate:approve` / `gate:revoke` label handling with exact name equality, and verify/finish that re-check live PR state without comment regex or status-token parsing; verify unit tests cover maintainer auto-admit, outsider Ready ignored, maintainer Ready admitted, draft skipped, label approve, label revoke, and non-maintainer label ignored
- [x] 2.2 Update `scripts/build_workflows.py` triggers (`pull_request` lifecycle + `labeled`) and job `if` conditions; regenerate workflows; verify `python3 scripts/build_workflows.py --check` and `python3 -m unittest discover -s tests -v` pass
- [x] 2.3 Update `scripts/configure_repositories.py` required contexts to `Quality` and `Repository standards` only and ensure gate labels exist; verify the script's expected context list and label names
- [x] 2.4 Dual-accept previous comment-only caller and new lifecycle caller in `scripts/standards.py`; verify standards tests accept both

## 3. Docs and agent policy

- [x] 3.1 Update `docs/operations.md` for Ready-for-review, auto-admit, and `gate:approve` / `gate:revoke`; verify slash-command admission is no longer documented as required
- [x] 3.2 Update `templates/agents/skills/ejmlabs-workflow/SKILL.md` and `references/pr-gate.md` for labels and explicit-ask agent policy; verify `tests/test_sync_agents.py` still passes
- [x] 3.3 Update `templates/community/CONTRIBUTING.md` for the new gate; verify template text matches contributor-visible behavior

## 4. Rollout

- [ ] 4.1 Merge the shared revision, retain `workflow-pins/FULL_SHA`, and verify the pin branch exists
- [ ] 4.2 For each gate repo, land a pin/form PR to the new revision and create the two gate labels; verify main's caller and that maintainer PRs run without slash commands
- [ ] 4.3 Set branch protection required checks to Quality and Repository standards; verify read-back with `enforce_admins` and one approving review retained
- [ ] 4.4 Manual check: maintainer non-draft PR runs checks; outsider Ready alone does not; `gate:approve` records a bot approval; verify with Actions run links

## Workflow follow-up

- Archive this change after verification and sync `pr-gate` into main specs
- Sync community CONTRIBUTING and agent templates into consumers
- Then enable advisory Bugbot org-wide (separate change)
