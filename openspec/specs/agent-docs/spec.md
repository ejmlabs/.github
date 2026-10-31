# agent-docs Specification

## Purpose

A repository's shared agent files match its `ejmlabs/.github` pin, and the CI deploy is described once, in the shared skill.

## Requirements

### Requirement: Shared agent files match the pin
The Repository standards job SHALL fail when a repository's shared `ejmlabs-*` skills, house rules block, skills routing block or skill links differ from `templates/agents` at the commit of the shared workflow that runs it. It SHALL fetch that commit from the public `ejmlabs/.github` without a token, and SHALL refuse to run from any other repository or from a revision that is not a full commit SHA. `ejmlabs/.github` SHALL check against its own templates.

#### Scenario: A repository in sync
- **WHEN** a PR leaves the shared agent files as `sync_agents.py` writes them from the pinned commit
- **THEN** the check passes

#### Scenario: A local edit to a shared skill
- **WHEN** a PR edits a synced `ejmlabs-*` skill or the house rules block
- **THEN** the check fails, names the file and gives the sync command

#### Scenario: A pin move without a resync
- **WHEN** a PR moves the pins to a commit whose agent templates differ and does not resync
- **THEN** the check fails until the PR runs `sync_agents.py` from that commit

#### Scenario: Templates carried by the PR
- **WHEN** a consumer PR adds its own `templates/agents` directory
- **THEN** the check still uses the fetched templates at the pin

### Requirement: One description of the CI deploy
The shared `ejmlabs-cloudflare` skill SHALL describe the CI deploy pipeline in `references/ci-deploys.md`, updated in the same change as any change to the deploy. Repository docs SHALL keep only their own site facts and link to it. The reference SHALL tell an agent to approve a production deployment only when the user explicitly asks, and only after confirming, from the Worker's active version and the version a recorded production job on main printed, that production serves a build of main that the deployment moves forward from.

#### Scenario: A deploy change
- **WHEN** a change alters `scripts/deploy.py` or the deploy workflow
- **THEN** the same change updates `ci-deploys.md`, and each site repository receives it with its next pin move

#### Scenario: Production ahead of main
- **WHEN** production serves no build of a main commit, for example after a deploy by hand from a branch
- **THEN** an agent does not approve the production job and reports the gap; the branch lands through the gate first
