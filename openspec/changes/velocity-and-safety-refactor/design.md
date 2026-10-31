## Context

This PR's own Repository standards check runs the standards at the pin its `pr.yml` already holds (`8230ef8`), so nothing here may change `pr.yml`, `release.yml`, the workflow scaffolds that pin checks, `templates/community/` or the root community files. A `pull_request` run takes its workflow from the PR merge ref, so a consumer PR that moves its pin is judged by the new pin.

## Decisions

- **Bind every decision to the event head.** Admission, approval and revoke act on `event.pull_request.head.sha`. If the live head differs, or the PR is closed, a draft or not on main, the run prints a notice and exits 0 with no write, because a newer event handles the new head. The cost is that a lost event leaves the head unadmitted until a maintainer pushes or adds a label.
- **Ownership over a rerun ban.** Each status carries its run URL, and verify and finish proceed only when the newest statuses of both contexts belong to the current run. That replaces the admission id and makes reruns safe. Re-running the admission job needs a maintainer as the actor, because it replays an old event. The trust is unchanged: only this workflow holds `statuses: write`.
- **Fork policy, not fork admission.** A fork's `pull_request` token is read-only and `pull_request_target` would run untrusted code with a write token, so forks are not admitted. A maintainer who reviewed an outside change pushes it to a branch in the repository. The cost is one manual step per outside contribution.
- **Credential-free extra workflows.** The standards allow any workflow whose shape is provably credential-free (read-only top-level permissions, no job permissions, environments or secrets, safe triggers, pinned actions) in a restricted YAML subset. It is a shape lint, not proof of what steps do, so review stays. The alternative, an allowlist of file names, blocked ordinary product CI.
- **Presence-only community files.** Byte comparison forced every wording change to move the pin and the files in lock step, and kept stale text alive. The check now needs the files to exist and be non-empty. `sync_community.py --check` reports drift on demand. The cost is that drift is no longer a failure.
- **Structural UI package rules.** A digest of the packing fields needed a new shared revision for every manifest change. Name, lifecycle, bundling and path-prefix rules keep logos and artwork out of the tokens tarball and leave `exports` and `types` free. Fields outside the rules are not checked.
- **PR-scoped cache keys.** GitHub scopes a pull request run's cache to its merge ref, so the gate only restores (exact key, then a toolchain and OS prefix) and the warm job on main is the only saver. The discard step goes. The design relies on a GitHub rule that this repository does not test.
- **Reviewed deploy config.** Deploy jobs check out `github.sha` and require the artifact's Wrangler config to be byte-identical to it, so a build step cannot change what is deployed. Environments are read before the token is in play and fail closed.
- **Product-owned gate and site build.** An executable `.github/quality`, `.github/quality-registry` or `.github/site-build` replaces the built-in commands, so a product changes its gate in its own PR. The built-ins stay as the fallback until each product has one, and duplicate commands for that time.
- **One PR per consumer.** Pin move, caller form and community resync are one PR, judged by the new pin. A bad pin blocks that consumer only, and re-pinning to the previous revision recovers.

## Risks

Nothing here is verified in GitHub yet: the hosted gate on a moved pin, a Dependabot actions PR, deploys with configured environments and settings read-back are the verification tasks. The fork and ownership paths have unit tests only.
