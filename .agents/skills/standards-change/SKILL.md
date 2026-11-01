---
name: standards-change
description: Use before you change anything in ejmlabs/.github - shared workflows, governance, standards checks, community, lint or agent templates, sync scripts - or roll a new pin out to consumer repositories.
---

# Changing the shared standards

Every ejmlabs repository runs this code or copies these templates. A mistake here breaks every
gate at once, so keep changes small, tested and rolled out one consumer at a time.

## Where things live

| Change | Edit | Then |
| --- | --- | --- |
| Gate logic, admission, release, site deploys | `scripts/*.py` | `python3 scripts/build_workflows.py`, review the generated `.github/workflows/` diff |
| Repository standards (versions, community files, docs) | `scripts/standards.py` | tests in `tests/test_standards.py` |
| Community files (`CONTRIBUTING.md` and friends) | `templates/community/` | `scripts/sync_community.py` in each consumer |
| Strict lint layer | `templates/lint/` | `scripts/sync_lint.py` in each consumer |
| Agent skills and house rules | `templates/agents/` | `python3 scripts/sync_agents.py .` here, then in each consumer's pin-move PR |

Never hand-edit `.github/workflows/*.yml`; they are generated with the trusted scripts embedded.

## Rules

- Run `python3 -m unittest discover -s tests -v` and `python3 scripts/build_workflows.py --check`
  before handoff. The strict test runs ruff and mypy through `uv`.
- Python follows `ejmlabs-python`; shell follows `ejmlabs-shell`. Scripts use only the standard
  library and refuse symlinked targets.
- Changing an embedded script or workflow moves the pin: consumers adopt it through their own
  PRs, pinned to a full SHA retained under `workflow-pins/FULL_SHA`. Templates are not
  embedded, and `templates/lint/` moves no pin. The Repository standards job checks a
  consumer's agent skills and house rules against `templates/agents/` at its pin, so an agent
  template change reaches a consumer in the PR that moves its pins and resyncs.
- A change to site deploys (`scripts/deploy.py`, the deploy workflow) updates
  `templates/agents/skills/ejmlabs-cloudflare/references/ci-deploys.md` in the same PR. Agents in
  every site repository read it, and repository docs keep only their own site facts.
- A `pull_request` run takes its workflow from the PR merge ref, so a consumer PR that moves its
  pin is checked by the new pin. A pin move, any caller form change and the community resync are
  one PR per consumer. Only this repository's own PR is checked by its current pin, so a change
  to what the standards check enforces must still pass the current pin's check.
- Widening permissions, secrets, triggers or the set of allowed actions needs a stated reason
  and the owner's review. Default tokens stay read-only. Actions stay pinned to full SHAs.
- Shared agent skills follow the authoring rules that `tests/test_sync_agents.py` checks: a
  description of at most 300 characters, a `SKILL.md` of at most 5,000 bytes, links only inside
  the skill, no em dashes. Put task detail in `references/`. Edit the template, never the synced
  copy under `.agents/skills/ejmlabs-*`.
- After a template change merges, open one PR per consumer that resyncs it (for agent templates,
  the pin-move PR). Land them one at a time per repository.

## Read next

- The repository's `docs/operations.md`: permissions, admission limits, credentials, rollout and
  recovery.
