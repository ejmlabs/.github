---
name: standards-change
description: Use before you change anything in ejmlabs/.github - shared workflows, governance, standards checks, community, lint or agent templates, sync scripts - or roll a new pin out to consumer repositories.
---

# Changing the shared standards

Every ejmlabs repository runs this code or copies these templates. A mistake here breaks every
gate at once, so keep changes small, tested and rolled out in steps.

## Where things live

| Change | Edit | Then |
| --- | --- | --- |
| Gate logic, admission, release, site deploys | `scripts/*.py` | `python3 scripts/build_workflows.py`, review the generated `.github/workflows/` diff |
| Repository standards (versions, community files, docs) | `scripts/standards.py` | tests in `tests/test_standards.py` |
| Community files (`CONTRIBUTING.md` and friends) | `templates/community/` | `scripts/sync_community.py` in each consumer |
| Strict lint layer | `templates/lint/` | `scripts/sync_lint.py` in each consumer |
| Agent skills and house rules | `templates/agents/` | `scripts/sync_agents.py` in each consumer |

Never hand-edit `.github/workflows/*.yml`; they are generated with the trusted scripts embedded.

## Rules

- Run `python3 -m unittest discover -s tests -v` and `python3 scripts/build_workflows.py --check`
  before handoff. The strict test runs ruff and mypy through `uv`.
- Python follows `ejmlabs-python`; shell follows `ejmlabs-shell`. Scripts use only the standard
  library and refuse symlinked targets.
- Changing an embedded script or workflow moves the pin: consumers adopt it through their own
  admitted PRs, pinned to a full SHA retained under `workflow-pins/FULL_SHA`. Templates under
  `templates/lint/` and `templates/agents/` are not embedded, so changing them moves no pin.
- A change that a consumer's Repository standards check enforces needs the staged rollout in
  `docs/operations.md` ("Bootstrap and rollout"): pin first, then the caller
  form and synced files. Keep the window where other PRs fail short.
- Widening permissions, secrets, triggers or the set of allowed actions needs a stated reason
  and the owner's review. Default tokens stay read-only. Actions stay pinned to full SHAs.
- Shared agent skills follow the authoring rules that `tests/test_sync_agents.py` checks: a
  description of at most 300 characters, a body of at most 100 lines, links only inside the
  skill, no em dashes. Put task detail in `references/`.
- After a template change merges, open one PR per consumer that resyncs it. Land them one at a
  time per repository.

## Read next

- The repository's `docs/operations.md`: permissions, admission limits, credentials, rollout,
  recovery, and the decision log.
