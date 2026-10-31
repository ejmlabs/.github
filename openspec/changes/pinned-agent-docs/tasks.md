## 1. Check

- [x] 1.1 Add `--templates DIR` to `scripts/sync_agents.py`, refusing a missing or linked directory.
- [x] 1.2 Add the fetch and check steps to the standards job and regenerate the workflows.
- [x] 1.3 Tests: the option, the generated steps, the fetch refusals, drift and a PR's own templates.

## 2. Content

- [x] 2.1 Write `references/ci-deploys.md`, link it from `ejmlabs-cloudflare`, add the house rule, and resync this repository.
- [x] 2.2 Update `docs/operations.md`, the `standards-change` skill and `CHANGELOG.md`.

## 3. Rollout

- [ ] 3.1 Merge, retain the pin under `workflow-pins/`, and move this repository's callers to it.
  - #79 merged as 9f7421b9cdf42f027828c5e481bebd880db20770. No caller can start a run at that revision: its standards job read `job.workflow_sha` in the job's own `env`, where GitHub does not offer the job context (#80 failed at startup). Never pin it. The fix reads the context in each step's `env`, and a test holds every job-level key to the contexts GitHub allows there.
- [ ] 3.2 One PR per site repository (`ejm-ui`, `ejm-ide`, `ejm-harness`, `ejmlabs`) moves the pins, resyncs, and replaces restated pipeline prose with site facts and a link; its Repository standards check passes at the new pin.
