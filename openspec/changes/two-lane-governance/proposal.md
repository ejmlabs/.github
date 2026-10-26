# Two-lane PR governance

## What changes for the owner, day to day

- **One click, no SHA.** On your own PRs and your maintainer agents' PRs, checks and the automated review start by themselves. When you are happy, click **Ship** on the PR, or type `/ship` yourself. The org's governance App merges it, squashed, once everything is green. You no longer need to rebase just because `main` moved. Only humans ship: no agent, including the Chief of Staff, can ship, approve, adopt or waive.
- **A new commit needs a new Ship.** Nothing else needs resetting. `/unship` stops a merge.
- **Plain docs are cheap.** Plain Markdown or text changes are reviewed at their risk tier's cap (one small pass for short docs at T0; larger docs PRs are T2 or T3) and still need a Ship. Skipping the review is allowed only for an actual T0 PR, after a clean 50-PR shadow and your recorded decision (G12, under re-review).
- **Reviewer outages are visible and have a way out.** If the reviewer is out of quota or times out, the PR shows "unavailable" and retries automatically. During a real outage you, and only you, can choose **Waive review and ship** on the owner page. That never applies to release or community work.
- **Community contributions stay walled off.** Fork PRs get free, secret-less CI and automatic triage, and spam is closed with an appeal path. Nothing paid runs until a maintainer posts `/adopt`, and that still ends with your Ship.

| Who | Maintainer PR | Release-affecting PR | Community PR |
| --- | --- | --- | --- |
| Owner / maintainer | Ship (1 action) | Ship | `/adopt`, then Ship |
| Security lead | none | security approval (1 action) | none (sees held findings) |
| Maintainer agent or Chief of Staff | pushes or comments; cannot ship | pushes; a non-pushing human must ship | none |
| Owner during outage | Waive review and ship (1 action) | not allowed | not allowed |

Public text says "maintainer PRs" and "community PRs" (the design's trusted and outside lanes), and calls the reviewer only "automated review".

## Why

The current gate needs `/ready <full SHA>`, then a review limited to 9 minutes, then `/approve <full SHA>`, repeated after every push or rebase. Quota and timeout failures leave PRs stuck with no defined way forward, and docs edits pay the full price. The owner's verdict: "This PR system is super cumbersome for me and my agents." The repositories are public and open source, so slop and abuse must still be kept out. An independent adversarial review of the first draft showed that commit checks and PR comments cannot hold PR-specific authority. So this version moves authority into a small service run by the org's governance App, which also performs every merge.

## What changes

- New **governance-control-plane**: a service holding the Governance App key and all decision state, with each PR's decisions handled in order and tied to its current push. It has a defined trust root (source, deploy, key custody, webhooks). Quality runs in a public quality runner repository that holds nothing; paid review runs in a private review runner repository that never executes PR code. Product repositories hold no secrets once migration finishes (two enumerated, per-repository, time-boxed exceptions until then), and their workflows, including the built-in token, confer no authority or publication ability; agents hold no write credential and push only through the service's branch broker, and releases are immutable. The service performs every merge with an expected-head squash, after validating the exact merge tree and claiming a fresh merge permit. Every human action is bound to the epoch in which the human acted (by GitHub-assigned time), so old clicks, approvals and comments never regain authority. The squash text is validated and sent explicitly at merge. Runner dispatch uses its own minimal App. One required `Governance` check replaces five statuses.
- **pr-lanes**: trusted, inert (strict plain-docs) or outside, decided from authenticated push records. A deterministic risk-tier classifier (T0 to T3, no model scoring, failing closed to T3) sets each review's input cap. Quarantine is sticky and carries over to the same code in other PRs.
- **trusted-merge**: Ship button, native approval or a human-typed `/ship`. Only humans ship, approve, adopt or waive. Independent security approval for release-affecting changes, from a versioned policy file. One evidence template for both lanes; DCO sign-off in every lane.
- **outside-contributions**: credential-free community CI, fresh triage with limits and event caps, a real appeals path with response targets, and adoption only after every triage rule passes.
- **review-cost-controls**: outcomes are classified, retries are durable, budgets are reserved atomically under a hard per-calendar-month (UTC) cap equal to the current stage balance ($50 in M0, rising by recorded owner decision to $1,525 in M5), held by one service ledger that every paid pass uses, legacy and shadow included; purchases may never take the provider balance above the cap (the prepaid balance alone is not a monthly cap); input caps follow the risk tier (32k to 160k tokens, never above 180k); there is a kill switch, the waiver is owner-only, raw output is never public, and every security finding is held privately.
- **Reviewer engine and provider** (owner decisions): an open-source, diff-only PR review tool, run as its CLI. The chosen interim reviewer is option (iii), a direct pay-per-token model API provider running a high-reasoning model at high effort through the engine's built-in client, under the security lead's conditions (dedicated team, invoiced limit $0, auto top-up off, the owner as the only team administrator, model-restricted key, zero data retention, input cap 160,000 tokens with a hard ceiling of 180,000, no public result artifact, a private scratch-repository dry run). The subscription gateway (i) and its pay-as-you-go offering (ii) remain compared alternatives only. The planned CLI pilot was skipped, so review quality is measured in shadow and the pilot.
- **governance-audit**: append-only records with set retention, a privacy note and quarterly public aggregate counts. Revocations never wait for the audit store.
- `release.py`, `configure_repositories.py`, `standards.py`, the community templates (adding `GOVERNANCE.md` and `MAINTAINERS`) and docs all migrate. `ejm-chess` gets full profiles.
- **BREAKING**: `/ready`, `/approve`, `/revoke` and the five legacy statuses are retired once migration finishes. The current review action is removed now (decision 26, decided): it is replaced in the same shared-workflow change by a job on the chosen reviewer that publishes the same required status, and each repository re-pins through its own gate. The legacy automated-review status is never dropped from the required checks while the legacy gate is authoritative.

## Impact

- New: the governance service and its governed source repository, `ejmlabs/governance-quality` (public), `ejmlabs/governance-review` (private, on the lab's existing GitHub Team plan), a Chief of Staff App identity, a community CI caller in each repository, a Runner-dispatch App, and (interim, until each repository's cutover) a `main`-only `legacy-review` environment key in each product repository for the replacement legacy review job.
- Changed: `scripts/governance.py` (ported into the service), `build_workflows.py`, `governance.yml`, `pr.yml`, `review_result.py`, `standards.py`, `release.py`, `configure_repositories.py`, `prepare.py` bounds reused, `docs/operations.md`, the CONTRIBUTING files and README, the PR template, new `GOVERNANCE.md` and `MAINTAINERS` templates, and the tests.

## GitHub settings only the owner can change

Set in one sitting right after GitHub sign-in (items 2 to 8); the ruleset cutover (item 5) waits until preflight passes.

1. **Preflight**: confirm organization or per-repository rulesets, the two-ruleset `main` pattern (A: no bypass; B: only the Governance App may update), the private audit mirror, and the Team-plan features the private review repository relies on (environments, environment secrets, deployment branch restrictions, rulesets). Record each repository's `pull_request_target`, `workflow_run` and fork-approval policy.
2. Create the **Governance App** (including `workflows: write`, no statuses or actions permission), the **Runner-dispatch App** (`actions: write` only, on the two runner repositories), the **Maintainer-agent App** (approved for creation now, installed only on the seven product repositories, with contents read only: no contents write, `workflows` or `packages` permission) and the **Chief of Staff App** (comment-level only). The Maintainer-agent and Chief of Staff Apps are never installed on the runner repositories.
3. Host the **governance service** on the lab's existing edge/serverless hosting provider inside an enforced $25/month envelope (hardware-key two-factor for its administrators, audit-log streaming, OIDC-only deploys), with the App keys in a non-exportable signing key or a managed secret store; preflight verifies the provider can do this.
4. Create `ejmlabs/governance-quality` (public, no secrets) and `ejmlabs/governance-review` (private) with a `review` environment limited to `main` and holding `MODEL_API_KEY` (this runner's key only; product repositories never use that name). Retire each repository's legacy direct-provider key right after that repository's re-pin merges (decision 17).
5. Apply rulesets through the guarded cutover: ruleset A on `main` (PR required, `Governance` required from the Governance App, squash only, linear history, no bypass) and ruleset B (only the Governance App may update `main`). On `contrib/**`: no force push or deletion, and only the Governance App may create or update. On all tags: only the governed release actor may create, update or delete. Enable immutable releases, and restrict package creation to the governed release actor where GitHub can enforce it; a trusted human's branch workflow publishing a package remains a decision-14 residual. Code-owner review dismisses stale approvals and requires approval of the most recent push; `@ejmlabs/security` is the sole code owner of governance paths, and both teams must exist with write before that takes effect. Code-owner review from `@ejmlabs/security` with no bypass on `.github`, the runner repositories and the service repository.
6. Set org Actions policy: approval for outside contributors' runs, no fork secrets, read-only default token, the full-SHA allowlist, GitHub-hosted runners only, retention of 30 days or less, and no debug secrets. Set org base permission to `read`.
7. Create the `maintainers` and `security` teams (at least one `security` member, and the owner not a member: a hard prerequisite, re-checked hourly, on every membership event and at every backstop merge permit) and require two-factor authentication.
8. Set up the chosen provider (iii): a dedicated team, invoiced billing limit $0, **auto top-up off**, the owner as the only team administrator (so only the owner can buy credit), the balance never above the current stage cap, one key restricted to the pinned model and endpoint, zero data retention on; record every credit purchase. Enable Discussions with an Appeals category, and confirm `security@ejmlabs.com` and an org-wide code-of-conduct role alias.

## Migration (details in design.md)

1. **Preflight and setup** (the legacy gate stays authoritative). The legacy admission and approval first refuse PRs whose head repository differs from the base.
2. **Remove the current review action now** (decision 26; G7 settled), without a waiver, by dated, validator-first steps (design.md). The key keeps its legacy name until the switch (owner, 3:02 PM PT) and is renamed only inside it, with no fallback between names. Steps: budget ledger live, holding every remaining old key's verified limit, and the isolated switch change S built and verified (2026-11-04); a validator-only change V lands on `.github` (2026-11-04) and `.github`'s caller moves to V (2026-11-05); S lands on `.github` (2026-11-06); `.github`'s caller moves to S and its old key is retired (2026-11-09); ejm-cli, ejm-ide, ejmlabs and ejm-harness re-pin to V then S through their own gates (2026-11-13); `ejm-ui` re-pins under the named exception (2026-11-13). Each deadline ends that repository's log-leak exposure: a missed deadline revokes its old key even though that freezes it. The named exception lifts only the automated-review context, by one logged script for at most 10 minutes, with an independent deadline page at 7 to 8 minutes and a restore from the owner's administrator account: on `ejm-ui` performed by the lab's automation under a named, owner-accepted exception to decision 11 that ends by 2026-11-20 (the automation can act with the owner's administrator rights on `ejm-ui` meanwhile, through a fine-grained token limited to `ejm-ui` that GitHub expires by then, held by a separate restore runner with no model in its loop; every call allowlisted to the lift, the merge and the restore or lock built from the saved protection; every use logged with a read-back and paged to the owner), elsewhere by the owner in person (no App holds administration write; a crash leaves the requirement off until that restore, with the branch lock as the fallback), on a digest-verified mechanical re-pin diff, never covers V or S, and expires 2026-11-20 or at the last re-pin.
3. **Shadow** for two weeks: the service reports but never merges; its paid passes reserve against the same ledger. The tier classifier is built in M0.
4. **Pilot on `.github`**: guarded cutover and the full scenario list, including a real release and the key-revocation runbook.
5. **Roll out** to ejm-ui, ejm-cli, ejm-harness, ejm-ide, ejmlabs, then ejm-chess once its profiles exist.
6. **Retire** the legacy commands, statuses and release evidence two weeks after the last cutover. Rollback per repository reverses the ruleset cutover and never puts a key back into a product repository.

## Open questions and blockers

**Open blockers** (rollout waits on these)
- **Second human for the security role** (hard prerequisite): independent security approval, the code-owner backstop and the two-person service deploy need a `security` member who is not the owner; a single-person acceptance no longer passes preflight.
- **`legacy-review` key placement**: security review condition met in text (environment-only key declared by S's review job alone, no repository or organization secret visible to product repositories, crash-safe switch exception); awaiting the security lead's confirmation.
- **Hosting fit (decision 5)**: key custody, OIDC-only deploys and the enforced $25 envelope are unverified; the budget ledger must be live by 2026-11-06 for removal to proceed on schedule.

**Closed or no longer gating**
- Decision 26 vs 7: **decided, remove now**. Option (a), keep until proven, was rejected because it leaves the log leak open with no end date; option (b), a waivable "reviewer unavailable" check, was rejected because its waive is a bypass, contrary to decision 7.
- Stopgap key exception and stopgap reachability: **closed (moot)**; there is no interim fork. Decision 3 (stopgap provider) is moot.
- Gateway written CI-use confirmation (decision 4) and gateway cap (decision 23): superseded by the choice of (iii); they apply only if the gateway is ever used.
- `ejm-ui` re-pin: **resolved** by a named exception to decision 7, the owner's one-time switch authorization (1:26 PM PT): per qualifying V or S re-pin PR, only the automated-review context is lifted by one logged script for at most 10 minutes, on a mechanically generated, digest-verified diff, with every other check passing and a single-commit proof; it never covers V or S and expires 2026-11-20 or at the last re-pin, after which an unpinned repository stays frozen until a new owner decision (any other use is a policy violation). It also covers a repository whose old key fails or misses its deadline. Decision 32 stands (no top-up; the exhausted key is revoked).
- Scale decisions (owner): G1 stage balances $50 / $125 / $325 / $625 / $975 / $1,525 (M0 to M5), re-set after the first 50 PRs; G9 deterministic classifier; G10 tier caps; G18 classifier in M0; G12 (T0 skip after a clean 50-PR shadow) under re-review. G2 and G13 withdrawn: the separate model-session security review applies only to the owner's own direct work and is not a pipeline gate.
- Public-history fixes outside this change (task 9.9): done locally; live-dependency name exceptions (legacy key name, current action reference and model id, byte-pinned community templates) remain until the switch, with neutral templates staged in `templates/community-next/`.
- Key name (owner, 3:02 PM PT): legacy name kept until the switch; renamed only inside the switch sequence, validator-first, never with a fallback.

**Owner**
- Which config files, if any, should join the inert lane later (decision 8: deferred, specific files only after review)?
- Revisit the no-bypass decision at retirement (decision 7).
- Add a reviewer key for `ejm-chess` once its governance profiles exist (decision 24).

**Security lead**
- Re-review this revision (decision 19), including the GitHub Team residual (admins can bypass environment rules in private repositories on Team).
- Confirm the (iii) conditions and the weekly billing read-back or attestation in preflight.
- Confirm the hosting provider meets the key-custody rule (decision 5) once preflight reports.

**Board**
- Ownership of generated code is left to a lawyer, especially before any relicensing.
