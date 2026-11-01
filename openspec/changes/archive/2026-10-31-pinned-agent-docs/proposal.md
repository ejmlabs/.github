## Why

Agents in each site repository learn how deploys work from that repository's own docs and skills, which restate the shared pipeline. When the pipeline changes in `ejmlabs/.github`, those copies go stale until someone edits every repository by hand, and nothing notices. The synced `ejmlabs-*` skills are the right home, but nothing holds a repository's copy to the revision it runs.

## What Changes

- The Repository standards job fetches `templates/agents` from `ejmlabs/.github` at the shared workflow's own commit and runs `sync_agents.py --check` against it. This repository checks against its own templates.
- `sync_agents.py` accepts `--templates DIR`.
- `ejmlabs-cloudflare` gains `references/ci-deploys.md`, the one description of the CI deploy, and a house rule says repository docs keep only their own facts.
- Site repositories replace their restated pipeline prose with their site facts and a link, in the PR that moves their pins.

## Capabilities

### New Capabilities

- `agent-docs`: a repository's shared agent files match its `ejmlabs/.github` pin.

## Impact

`scripts/sync_agents.py`, `scripts/build_workflows.py`, the generated `governance.yml`, the agent templates, `docs/operations.md`, the `standards-change` skill, tests and `CHANGELOG.md`. Each consumer resyncs in its next pin move; one that does not move its pin is unaffected.
