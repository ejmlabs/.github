## ADDED Requirements

### Requirement: Authoritative state lives in the governance service

The governance service SHALL hold all lane, authorization, quarantine, adoption, budget and result state in its own durable store. PR comments, labels and commit checks MUST be treated as display only and MUST NOT be read back as authority.

#### Scenario: Writer edits the bot comment

- **WHEN** a repository writer edits the service's lane comment to say `trusted`, or removes `lane:outside`
- **THEN** the PR's lane is unchanged and the service rewrites the display from its store

### Requirement: Decisions are serialized per PR and bound to a generation

The service SHALL process each PR's events one at a time with compare-and-set on a log version. It SHALL increment the PR's generation on every head change, base change or retarget, close or reopen, and draft transition. Every authorization and result MUST record its generation and MUST count only in that generation.

#### Scenario: Retarget away and back

- **WHEN** a PR is retargeted from `main` to another branch and back
- **THEN** all its authorizations are void and a new ship is required

### Requirement: Human actions are bound to the generation they were taken on

Each `Ship`, `Security review` and `Adopt` check run SHALL be created for one immutable record `(repo, PR, head, base, generation, epoch)`; a click SHALL count only if its check-run id maps to the current record. Each review id SHALL count only once. `/unship`, a restore and every revocation SHALL write a tombstone and an epoch boundary time, advance the epoch, and replace the check runs.

#### Scenario: Delayed click after H to X to H

- **WHEN** a click on the `Ship` check run created for head H in an earlier generation arrives after H→X→H
- **THEN** its check-run id maps to a superseded record and nothing is recorded

#### Scenario: Old native approval after H to X to H

- **WHEN** a native approval naming H was submitted before the current generation began
- **THEN** it does not count, even though its commit is the current head

#### Scenario: Delayed ship after unship on the same head

- **WHEN** a ship click for the epoch before an `/unship` is delivered after the unship
- **THEN** the tombstone refuses it and the ship stays void

#### Scenario: Twin PR click

- **WHEN** a click arrives on another PR's `Ship` check run for the same head SHA
- **THEN** its record names the other PR and nothing is recorded on this one

### Requirement: Authorizations are bound to the epoch in which the human acted

Every authorization SHALL be judged by a GitHub-assigned action time the actor cannot set (a review's `submitted_at`, a comment's `created_at`, a click's action record). It SHALL count only if that time is at least 60 seconds after the latest epoch boundary of its generation. Earlier or ambiguous ordering MUST be rejected, never assigned the epoch current at handling time. A channel that cannot give such a time SHALL be disabled, offering the button.

#### Scenario: Delayed native approval after unship

- **WHEN** a native approval of head H submitted before `/unship` on H is delivered after it, and its review id was never seen
- **THEN** it does not count, because its `submitted_at` predates the epoch boundary

#### Scenario: Delayed comment after unship and restore

- **WHEN** a `/ship`, `/security-ok` or `/adopt` comment created before an `/unship` or a restore on the same head is processed after it
- **THEN** it is refused

#### Scenario: Pusher-set timestamp

- **WHEN** a push carries a commit or `head_commit` timestamp earlier or later than its delivery
- **THEN** epoch boundaries and generation starts use only the later of the GitHub-assigned event or delivery time and the service receive time

#### Scenario: Ambiguous ordering

- **WHEN** a review's `submitted_at` is within 60 seconds after the epoch boundary
- **THEN** it is refused and the reply offers the current Ship button

### Requirement: Only trusted runner workflows may produce results or spend secrets

From each repository's cutover, Quality SHALL run only on the quality runner's `main` and paid review only on the review runner's `main`, both dispatched by the Runner-dispatch App; before it, the legacy Quality job and the isolated legacy review job remain. PR-code jobs MUST have no `id-token`, artifact upload, environment or secret, and no quality-runner job SHALL restore a cache. The review runner MUST NOT run PR code, restore caches or download artifacts.

#### Scenario: Malicious branch workflow asks for secrets

- **WHEN** a branch in a product repository adds a workflow requesting the review runner's key or the App key
- **THEN** neither exists there and the run gets neither key; before cutover only that repository's enumerated phase exceptions exist

#### Scenario: Self-hosted runner requested

- **WHEN** any governed or runner workflow targets a self-hosted runner
- **THEN** org policy refuses it; only GitHub-hosted runners are used

#### Scenario: Runner branch dispatch

- **WHEN** a review-runner branch workflow requests the `review` environment
- **THEN** the environment refuses because only `main` may deploy to it

#### Scenario: PR code in Quality forges a result

- **WHEN** code under test in the quality runner tries to mint an OIDC token and post "review: passed" or "quality: passed"
- **THEN** the job has no `id-token`, and any token presented fails the workflow-path and run checks, so the result is refused

#### Scenario: Cache written through the runtime token

- **WHEN** PR code in Quality saves a cache entry through the Actions runtime token
- **THEN** no later quality or review job restores it and their results are unaffected

### Requirement: The review workflow runs only on dispatch

The private review workflow SHALL refuse to run, before the key enters any step, unless the triggering actor is the Runner-dispatch App's bot. Provider usage that matches no dispatch SHALL be settled into the budget ledger and alerted.

#### Scenario: Manual run by a writer

- **WHEN** a human with write starts the review workflow by hand
- **THEN** it stops before any step receives the key

### Requirement: Repository standards never run beside PR code

Repository standards and the Markdown checks SHALL run in their own job that installs its tooling first, then reads the PR tree as data and never executes PR code.

#### Scenario: PR code rewrites the standards checker

- **WHEN** a PR changes the standards script in the tree under test
- **THEN** the standards job runs its own installed checker, not the PR's copy

### Requirement: Runner results are verified before they count

Quality results SHALL be posted by a separate job that runs no PR code and reads only job conclusions. The service MUST accept a result only if its OIDC token's `iss`, service `aud`, `repository_id`, `repository_owner_id`, `job_workflow_ref` (path mapped to the result type), `ref == refs/heads/main`, `event_name == workflow_dispatch`, `run_attempt == 1`, recorded `run_id`, single-use `jti` and `exp` all verify.

#### Scenario: Replayed result token

- **WHEN** a result arrives with a `jti` the service has already accepted, or a `run_id` other than the recorded dispatch run
- **THEN** the result is refused

### Requirement: Review results travel as an authenticated bound payload

In the review runner, which runs no PR code, the review job SHALL pass the bounded result file to the result job through job outputs. The job holding the key MUST have no `id-token`. The result job SHALL post the payload with its OIDC token, bound to dispatch id, run id, generation, head, base, pass and payload digest. The service SHALL require both the payload and the review job's success.

#### Scenario: Payload digest mismatch

- **WHEN** a posted payload's digest differs from the digest bound in the request
- **THEN** the result is refused and the pass is `incomplete`

### Requirement: The private review runner relies only on GitHub Team features

The private review runner SHALL use only environments, environment secrets, deployment branch restrictions and rulesets, which GitHub Team provides for private repositories. The `review` environment's deployment policy SHALL be "selected branches" with exactly `main`. It MUST NOT rely on required reviewers, wait timers, custom deployment protection rules or blocking administrator bypass.

#### Scenario: Plan feature check

- **WHEN** preflight reads the review runner's settings
- **THEN** no required reviewers, wait timers or custom deployment protection rules are configured, and the environment secret and the `main`-only selected-branch policy are present

### Requirement: Administrator bypass on the review runner is detected

Because administrator bypass cannot be blocked on the private review runner, its only administrator SHALL be the owner, no App or agent SHALL hold administration write on it (the decision-11 exception credential is a fine-grained token limited by GitHub to `ejm-ui` and SHALL NOT reach it), and the hourly reconciliation SHALL flag every `review` deployment that matches no recorded dispatch and notify the owner and the security lead.

#### Scenario: Administrator bypasses the environment branch rule

- **WHEN** an administrator runs a non-`main` deployment to `review`
- **THEN** any result it posts is refused, and reconciliation flags the deployment to the owner and the security lead

### Requirement: Detection without audit-log streaming is enumerated

Where the plan offers no org audit-log streaming or API, the design SHALL list, for each detection that would use the audit log, its replacement (a webhook event or a reconciliation read) and the events that are lost. For the lost events the owner SHALL review the web audit log at each preflight, weekly and after every use of the switch exception, recording what was checked, and the security lead SHALL countersign once a second human exists.

#### Scenario: Plan without streaming

- **WHEN** preflight finds that audit-log streaming is not available
- **THEN** each listed replacement is read back as delivered, and the owner's audit-log review schedule is in effect before cutover

### Requirement: Org webhooks, the Governance App's installation and secret values are reconciled

The hourly reconciliation SHALL read the org webhook list, the Governance App installation's state and repository selection, and each secret's `updated_at`, and SHALL page on any change; every webhook the service receives events through SHALL subscribe to `meta`.

#### Scenario: Org webhook deleted or Governance App suspended

- **WHEN** an org webhook is deleted or changed, or the Governance App's installation is suspended or its repository selection changed
- **THEN** the `meta` event or the next hourly reconciliation pages the owner and the security lead

#### Scenario: Secret value replaced

- **WHEN** a secret keeps its name but its `updated_at` changes
- **THEN** the next hourly reconciliation pages the owner and the security lead

### Requirement: No App or agent holds administration write

No App or agent SHALL hold administration write on any governed repository, except the decision-11 exception credential (a fine-grained token limited to `ejm-ui`, held by the automation's restore runner, until 2026-11-20 at the latest). No other administration credential MAY be held by any automation. A switch-exception lift or crash restore on any other repository SHALL be done by the owner in person from the owner's own administrator account.

#### Scenario: Administration-write credential found

- **WHEN** preflight or reconciliation finds an App, agent or automation credential with administration write on any repository, other than the recorded `ejm-ui` exception credential during its window
- **THEN** preflight fails, the switch exception cannot be used, and the owner and the security lead are alerted

#### Scenario: Lift on another repository started by automation

- **WHEN** the switch-exception script is started on a repository other than `ejm-ui` by anything other than the owner in person
- **THEN** it refuses before any protection change

### Requirement: Administration-write credentials are checked by named identities

App installations SHALL be checked through the Governance App's organization administration read; admin roles and org owners through the owner's settings tool run by the owner; org fine-grained tokens by the owner reading the org's fine-grained token list in the web settings; classic tokens, OAuth grants and App user tokens, which Team cannot list, through the quarterly credential review and the owner's web audit-log review.

#### Scenario: Inventory read incomplete

- **WHEN** any of these reads is forbidden or incomplete
- **THEN** preflight fails and the switch exception cannot be used

### Requirement: The lab's automation restores ejm-ui protection under a named exception to decision 11

Under the owner's 4:53 PM PT decision, the lab's automation MAY run the `ejm-ui` switch-exception lift and perform its crash restore with an owner credential, only for that lift, its one merge and the restore or lock, and only until the switch exception ends (2026-11-20 at the latest); the credential SHALL NOT be used for anything else.

#### Scenario: Crash restore by the automation

- **WHEN** the script is killed after lifting the context on `ejm-ui`
- **THEN** the restore runner's deadline restore writes the saved `checks` with their `app_id` at 6 minutes 30 seconds, reads them back, logs the call and the read-back, and pages the owner

### Requirement: The exception credential is held by a restore runner with no model in its loop

The credential SHALL be held only by a separate restore runner, a deterministic process with no model in its loop, which alone makes every call with it. The orchestrator SHALL only request an allowlisted operation (lift, merge, restore or lock) for an `ejm-ui` PR and MUST NOT be able to read the credential.

#### Scenario: Orchestrator reads the credential

- **WHEN** an orchestrator session tries to read the restore runner's store or environment
- **THEN** the read fails, as preflight shows before the exception's first use

### Requirement: The restore runner makes only allowlisted calls

The runner SHALL build every call itself, from the saved JSON whose digest the service recorded and the head the service verified, through `scripts/branch_protection.py`, and SHALL refuse any call outside its allowlist of method, path and body digest before making it.

#### Scenario: Runner asked for anything else

- **WHEN** the orchestrator asks the restore runner for another repository, endpoint, PR or head, or supplies a body
- **THEN** the runner refuses before any call, logs the refusal and pages the owner

### Requirement: Every use of the decision-11 exception is logged, read back and paged

Every lift, merge, restore and lock by the automation SHALL be logged with a field-by-field read-back, the authenticated login and the restore runner's run id and host, and SHALL page the owner. The outside monitor SHALL page on its own reads, not on a report of a use. While it lasts, the owner's comment commands and native reviews MUST NOT count where the service is authoritative.

#### Scenario: Restore fails and its page is lost

- **WHEN** the runner's restore fails or is reported done without taking effect, and the runner's page to the owner is not delivered
- **THEN** the outside monitor's reads at 7 and 8 minutes differ from its pre-window read and it pages the owner and the security lead, and the missing page is an incident

### Requirement: The decision-11 exception's risk is stated at full width

The design SHALL state that while the automation holds the owner credential it can act with the owner's administrator rights on `ejm-ui`, that GitHub does not limit how the credential is used within its scope, and that the owner accepted this risk at full width.

#### Scenario: Unregistered change by the exception credential

- **WHEN** `ejm-ui` protection changes with no registered lift window, or a commit reaches `ejm-ui` `main` in the exception period that matches neither a legacy gate run nor a logged exception merge
- **THEN** the outside monitor pages the owner at once, reconciliation flags the commit, it is reverted or quarantined, and an incident is opened

### Requirement: The decision-11 exception credential is a fine-grained token with an enforced expiry

The credential SHALL be a fine-grained personal access token of the owner's account with repository access to `ejm-ui` only, exactly the repository permissions Administration write, Contents write, Workflows write, Pull requests read and Metadata read, no organization or account permission, and an expiry enforced by GitHub no later than 2026-11-20; its owner id, repository selection, permissions and expiry SHALL be read back in preflight.

#### Scenario: Credential is not the required token

- **WHEN** preflight finds that the exception credential is not a fine-grained token, reaches another repository, carries any permission beyond the list, or has no GitHub-enforced expiry on or before 2026-11-20
- **THEN** preflight fails and the exception is not used

### Requirement: No other credential form serves the exception

A classic token, an OAuth or CLI token, a password or a web session MUST NOT be used; if the required token cannot be issued and read back, the exception MUST NOT be used and the `ejm-ui` lift and restore stay with the owner in person.

#### Scenario: Org settings do not allow the token

- **WHEN** the org's settings do not allow the required fine-grained token, or its fields cannot be read back
- **THEN** the exception is not used and the owner does the `ejm-ui` lift and restore in person

### Requirement: The decision-11 exception is removed at expiry

When the switch exception ends, the restore runner's copy of the credential SHALL be deleted, the owner SHALL revoke it, a call with it SHALL be shown to fail, the runner SHALL refuse by clock, and the owner's web audit-log review of the period SHALL be recorded. Expiry MUST NOT count as complete until all of these are read back.

#### Scenario: Credential still works after expiry

- **WHEN** a call with the restore runner's copy of the credential succeeds after the exception ended
- **THEN** expiry is incomplete and an incident is opened

### Requirement: Runner dispatch uses its own App

A Runner-dispatch App with its own key, holding only `actions: write`, SHALL be installed only on the two runner repositories. The Governance App MUST NOT hold `actions: write`. Both keys follow the same custody rules.

#### Scenario: Governance App dispatches a runner

- **WHEN** a token minted from the Governance App calls the workflow-dispatch endpoint on a runner repository
- **THEN** the call is refused for lack of permission

### Requirement: The service trust root is defined

The service source SHALL live in a public governed repository listed as release-affecting, and SHALL deploy only from protected `main` through OIDC workload identity, with non-OIDC deploys and long-lived provider API tokens disabled. A deploy MUST need the owner's ship and a code-owner review from a `security` member who is not the owner, enforced by a no-bypass ruleset on `.github`, both runner repositories and the service repository.

#### Scenario: Deploy from a branch

- **WHEN** a deploy is attempted from any ref other than protected `main`
- **THEN** the hosting provider's workload identity refuses it

#### Scenario: Owner-only approval

- **WHEN** a change to the service repository has only the owner's approval
- **THEN** the code-owner rule is not satisfied and it does not merge

### Requirement: The independent backstop requires fresh approval

The code-owner ruleset on `.github`, both runner repositories and the service repository SHALL dismiss stale approvals on push and require approval of the most recent reviewable push by an eligible independent human, and CODEOWNERS SHALL make `@ejmlabs/security` the sole owner of every governance path, with a test of every file's last matching rule. Both teams MUST exist with write before that change lands. Preflight SHALL read these back.

#### Scenario: Push after security approval

- **WHEN** a security member approves head H and the Governance App then pushes H2 while every service check is green
- **THEN** GitHub refuses the merge until a fresh security review of H2

#### Scenario: Overriding rule on an unlisted governance file

- **WHEN** a later CODEOWNERS rule gives `scripts/configure_repositories.py` to maintainers
- **THEN** the ownership test fails

#### Scenario: Maintainer-only approval of a governance file

- **WHEN** a maintainer who is not in `security` approves a change to `scripts/standards.py` with every service check green
- **THEN** the code-owner rule is not satisfied and GitHub refuses the merge

### Requirement: The security role is held by a distinct human

`security` team members SHALL be humans whose tokens no automation holds, and the owner SHALL not be a member; preflight reads membership back. This is a hard prerequisite for preflight and cutover; a recorded single-person acceptance MUST NOT pass, and an automated reviewer never counts as the second human. A single-person alternative needs a separately defined owner policy before rollout.

#### Scenario: Only the owner in security

- **WHEN** preflight finds the owner is the only `security` member
- **THEN** preflight fails

#### Scenario: Roster proven

- **WHEN** preflight runs with the proposed roster
- **THEN** a real release-affecting merge and a service deploy each succeed with an independent security approval

### Requirement: Security membership is reconciled continuously

The hourly reconciliation and every `membership` webhook event on `security` SHALL re-read `security` membership and, if the owner, an App or an automation account is a member, freeze merges on `.github`, both runner repositories and the service repository and alert the owner and the security lead. At every backstop merge permit the service SHALL re-read the same and that the approving security reviewer is a listed human other than the owner, and refuse otherwise.

#### Scenario: Owner added to security after preflight

- **WHEN** the hourly reconciliation finds the owner, an App or an automation account in `security`
- **THEN** merges freeze on the backstop repositories and the owner and the security lead are alerted until the membership is corrected and read back

#### Scenario: Self-add between reconciliations

- **WHEN** the owner adds themself to `security` and approves a backstop PR within the hour
- **THEN** the membership event freezes backstop merges at once, and the permit-time re-check refuses the merge

### Requirement: The hosting account is controlled

The hosting account SHALL list its administrators, require hardware-key two-factor authentication for them, stream its audit log to the audit store, and be checked hourly that the running build hash equals the build from the service repository's current `main`. A mismatch SHALL freeze merges and alert the owner and security lead.

#### Scenario: Out-of-band deploy

- **WHEN** the running build hash differs from the build of current `main`
- **THEN** merges are frozen and the owner and security lead are alerted

### Requirement: Hosting cost has an enforced envelope

The service's hosting, storage, queue and logging charges SHALL sit inside a provider-enforced budget or fixed-price envelope of at most $25 per month, with bounded ingress (unsigned requests rejected before any work, request-rate limits) and alerts. Exhausting the envelope SHALL stop authorizations and merges, never pass them. If the host cannot enforce this, the limitation returns to the owner before rollout.

#### Scenario: Request flood

- **WHEN** an unauthenticated flood hits the webhook endpoint
- **THEN** requests are rejected at the edge, spend stays inside the envelope, and an alert is sent

### Requirement: The App key is custodied and rotated

The App keys SHALL be held as non-exportable signing keys or in a managed secret store readable only by the runtime identity, MUST NOT be in GitHub Actions secrets, a repository, a laptop or a log, and SHALL rotate every 90 days and at once on suspicion. Installation tokens SHALL be minted per operation, scoped down with `repositories` and `permissions`, kept in memory only and never logged.

#### Scenario: Host cannot meet custody

- **WHEN** preflight finds the hosting provider can neither sign with a non-exportable key nor restrict a managed secret to the runtime identity
- **THEN** rollout stops and hosting returns to the owner

#### Scenario: Revoked App key

- **WHEN** the revocation runbook deletes a compromised key and suspends the installation
- **THEN** new JWTs fail, merges are frozen, and every open PR is quarantined until re-keying

### Requirement: Webhooks are verified and missed events fail closed

The service MUST verify `X-Hub-Signature-256` in constant time, reject unsigned requests, keep delivery ids for the retention window and process each once, and re-fetch state through the API before acting. A `requested_action` SHALL count only on a Governance App check run from a trusted human sender. If the live head differs from the ledger head, the service SHALL start a new generation, treat the PR as outside until reconciled, and refuse ship.

#### Scenario: Forged or replayed webhook

- **WHEN** a webhook arrives with a bad or missing signature, or a delivery id already processed
- **THEN** it is rejected or ignored and no state changes

#### Scenario: Missed push webhook

- **WHEN** reconciliation finds a PR whose live head is not in the ledger
- **THEN** a new generation starts, the PR is outside until reconciled, and ship is refused

### Requirement: Interim secrets are enumerated and time-boxed

A pinned repository MAY hold the old provider key, under the legacy name and narrowed to still-pinned repositories, only until its switch re-pin or deadline; and the switch's key, under the switch's name, separate from the runner's key and only as a `main`-only `legacy-review` environment secret declared by S's review job alone, from right after that repository's S re-pin merges until cutover or 2027-01-31. No other secret is allowed. The zero-secret check SHALL run per repository at cutover.

#### Scenario: Secret outside the exceptions

- **WHEN** preflight finds a stored secret in a product repository that is not its current phase's exception
- **THEN** preflight fails for that repository

#### Scenario: Switch key visible outside the environment

- **WHEN** preflight finds a repository or organization secret with the switch key name visible to a product repository, or an S job other than review declares `legacy-review`
- **THEN** preflight and standards fail

#### Scenario: Exhausted old key

- **WHEN** a repository's old key cannot be used
- **THEN** it is revoked at once rather than kept until re-pin

#### Scenario: Phase-A exposure

- **WHEN** a writer's branch workflow requests the old key before that repository's switch re-pin
- **THEN** this is the enumerated, accepted exposure, ending at the switch re-pin or deadline; an environment-held switch key is not readable from branch or PR refs

#### Scenario: Phase B stalls

- **WHEN** a repository has not cut over by 2027-01-31 and no dated extension is recorded
- **THEN** its switch key is revoked and its merges wait

### Requirement: The switch key is added only after the S re-pin

The switch key MUST NOT be added to a repository's `legacy-review` environment before that repository's S re-pin has merged, so that S's validator is installed there whenever the key exists.

#### Scenario: Switch key added before the S re-pin

- **WHEN** a repository's `legacy-review` environment holds the switch key while its installed caller is still on the old pin or V
- **THEN** preflight fails for that repository and the key is removed

### Requirement: The switch key is added only after a zero-hit scan

Before the key is added, S's standards SHALL be run over `main`'s tree at the S re-pin commit and the repository's workflows and `legacy-review` deployments listed; the key SHALL be added only when that reads back zero hits. Each key SHALL be issued at the provider when it is added and MUST NOT be held anywhere in between.

#### Scenario: Earlier workflow names the switch environment

- **WHEN** the scan at the S re-pin commit finds a `push` or `schedule` workflow, merged earlier under the old pin or V, that names `legacy-review`, or a `legacy-review` deployment exists
- **THEN** the key is not added until the finding is removed and the scan reads back zero hits

### Requirement: No product workflow names the switch environment

Standards in every product repository SHALL reject any workflow file there that names `legacy-review` in any letter case, under any trigger; only the shared workflow's review job at S declares it. Preflight and reconciliation SHALL flag any `legacy-review` deployment that matches no S review run.

#### Scenario: Product workflow names the environment

- **WHEN** a product repository's workflow on any trigger (push, schedule, `workflow_dispatch` or other) names `legacy-review`
- **THEN** standards fails there, and any `legacy-review` deployment that matches no S review run is flagged by preflight and reconciliation

### Requirement: Product workflows cannot reach the switch environment indirectly

In every product-repository workflow other than the canonical caller, standards SHALL reject any `environment` value that is an expression or a literal not on an allowlist, in both the string and the object (`name:`) form, and any reusable-workflow call other than the canonical one. Environment names SHALL be compared case-insensitively, as GitHub does; the allowlist SHALL be a security-owned governance file and MUST NOT contain any case variant of `legacy-review`.

#### Scenario: Environment by indirection

- **WHEN** a product workflow sets `environment` through `${{ ... }}`, `vars.*`, `format()` or `{name: ...}`, or calls a reusable workflow other than the canonical one
- **THEN** standards fails there

#### Scenario: Case variant of the switch environment

- **WHEN** a product workflow names `Legacy-Review` or another case variant, or the allowlist contains one
- **THEN** standards fails

### Requirement: Governed repositories ban risky triggers

Governed repositories MUST NOT use `pull_request_target` or `workflow_run`, and Repository standards SHALL fail on either.

#### Scenario: Workflow adds pull_request_target

- **WHEN** a PR adds a workflow triggered by `pull_request_target`
- **THEN** Repository standards fails

### Requirement: Branch workflows confer nothing

After its cutover, a product repository SHALL hold no stored secrets, environments with secrets or publication credentials; before it, only the enumerated migration exceptions. A branch workflow's built-in `GITHUB_TOKEN`, even when raised to the repository maximum, MUST confer nothing: no required check, status or governance decision SHALL be satisfiable by it. Only the Governance App's `Governance` check and OIDC-verified runner-`main` results SHALL count.

#### Scenario: Same-repository branch workflow requests every secret and environment

- **WHEN** a workflow on a same-repository branch runs on `pull_request` or `push` and requests every known secret name and every environment
- **THEN** it reads no secret (after cutover none exists; before it, the old key is the only accepted exception until re-pin and the `legacy-review` key is unreadable from branches), and the token's writes count for nothing and are blocked on protected refs

#### Scenario: Branch workflow posts a check with a governance name

- **WHEN** a branch workflow posts a check run or status named `Governance`, `Quality`, `Automated review`, `Security review` or `Ship` on the PR head
- **THEN** the ruleset does not count it, the service does not read it, and no lane, authorization or merge decision changes

### Requirement: Branch execution cannot publish

No agent credential SHALL hold `contents: write`, `workflows` or `packages`; agents SHALL write only `agent/**` branches through the service's branch broker, which exposes no release, tag, asset or package operation. Releases SHALL be immutable, tags restricted to the governed release actor, no product repository SHALL use a package namespace, and product `pull_request`/`push` workflows SHALL be limited to `contents: read`.

#### Scenario: Agent creates a release on an existing tag

- **WHEN** an agent credential creates a release or draft on an existing tag, or uploads, deletes or replaces an asset on an existing release
- **THEN** GitHub denies it for lack of permission

#### Scenario: Agent branch adds a publishing workflow

- **WHEN** an agent asks the broker to push a branch that adds or changes a workflow
- **THEN** the broker refuses and nothing is pushed

#### Scenario: Published release changed

- **WHEN** any token tries to change a published release's assets or tag
- **THEN** the immutable-release setting refuses it

#### Scenario: Human branch workflow drafts a release

- **WHEN** a trusted human's branch workflow raises its token and creates a draft release or publishes a package
- **THEN** it is the accepted decision-14 residual, and the `release` or `package` webhook (audit-log streaming where available) alerts the owner and security lead

#### Scenario: Release published before immutability

- **WHEN** preflight finds a release published before immutable releases were enabled
- **THEN** it is republished or accepted on the record, and deleting an immutable release and recreating one on its tag with a branch token is tested

#### Scenario: Branch workflow mints an OIDC token

- **WHEN** a branch workflow with `id-token: write` presents its token to the service or any external trust
- **THEN** it is refused, because only runner `main` and the dated reservation exception are accepted

### Requirement: The branch broker validates the resulting tree

The broker SHALL compute refusals from the full resulting tree diff against the target branch, never from client-supplied paths, and SHALL refuse changes under `.github/workflows/**` or `.github/actions/**`, symlinks or submodules anywhere, renames into those paths, tag refs and non-`agent/**` refs.

#### Scenario: Symlink into the workflows directory

- **WHEN** an agent submits a tree that adds a symlink pointing into `.github/workflows/`
- **THEN** the broker refuses and nothing is pushed

### Requirement: Credentials follow a tested permission matrix

Each App and token SHALL have only the permissions in the design's credential matrix, and rulesets SHALL enforce its ref restrictions. Preflight MUST record each token's effective permissions and show protected-ref and publication calls denied, while allowed display writes (statuses, checks, comments, labels) change no service state and never satisfy the integration-bound required check.

#### Scenario: Agent App tries to merge

- **WHEN** the Maintainer-agent App calls the merge endpoint on a PR
- **THEN** the merge is refused by rulesets A and B

#### Scenario: Branch token posts a display write

- **WHEN** a raised branch token creates a status named `Governance` and a comment
- **THEN** GitHub may accept them, but the required check stays unsatisfied and no service state changes

### Requirement: Every merge validates the exact merge tree

For every merge, including the first attempt, the service SHALL run Quality on the exact proposed merge tree against a recorded base SHA. A result SHALL be reused only while the proposed tree and base are identical. Review evidence SHALL be reused only when the PR's patch-id against the new merge base is unchanged.

#### Scenario: Branch already behind main

- **WHEN** a head passes Quality but its merge with the current `main`, which has not moved since dispatch, fails
- **THEN** the service does not merge and reports the failure

#### Scenario: Main moved, patch unchanged

- **WHEN** another PR merges first and this PR's patch-id is unchanged
- **THEN** only the free merge validation runs, the existing ship and review remain valid, and no rebase is needed

### Requirement: Merges need a fresh permit

Validation SHALL not block revocations. Just before merging, the service SHALL atomically claim a permit against the PR log version, re-verify every gate and write the merge intent. Any revocation SHALL void pending permits. After setting `Governance` to success, a compare-and-set SHALL confirm the permit is still valid before the merge call; if void, `Governance` is set to failure. A revocation after the merge call is issued cannot stop it.

#### Scenario: Unship during merge validation

- **WHEN** validation is paused, the ship is revoked on the same head, and validation then resumes and passes
- **THEN** the permit claim fails and no merge occurs

#### Scenario: Head moves during merge

- **WHEN** a push lands between the permit and the merge call
- **THEN** the expected-head merge fails, `Governance` is set to failure and the new generation needs a new ship

#### Scenario: Revocation between success and merge call

- **WHEN** `/unship` lands after `Governance` is set to success but before the merge call
- **THEN** the permit re-check fails, no merge call is made and `Governance` is set to failure

### Requirement: The squash text is validated and sent explicitly

At permit time the service SHALL compose the squash title and message, including trailers, from a fresh read, run the free template, public-history and sign-off checks on exactly that text, bind its digest to the permit and merge intent, and send that text explicitly to the merge API. An edit SHALL re-run only the free checks.

#### Scenario: Body edited after Ship

- **WHEN** an agent edits the PR body after Ship to add a forbidden name
- **THEN** the free checks fail on the new text and nothing merges until it passes

#### Scenario: Edit races the merge

- **WHEN** the title is edited after the permit is claimed
- **THEN** the merge carries the validated text, and the edited text never enters history

### Requirement: No lasting green check

If a merge fails, `Governance` SHALL be set to failure. On startup and every minute, a sweep SHALL fail `Governance` for every intent with no recorded merge. After a merge, the service SHALL post a newer `Governance` check run on that head with a non-success conclusion, "merged in #N; not reusable". A head with an earlier Governance record SHALL start pending in any other PR. GitHub auto-merge MUST NOT be used.

#### Scenario: Crash between success and merge

- **WHEN** the service stops after setting `Governance` to success and before merging
- **THEN** ruleset B stops anyone else merging that SHA and the sweep sets `Governance` to failure

#### Scenario: Same SHA in two PRs

- **WHEN** a second PR has the same head SHA as a PR that was just merged
- **THEN** the head's latest `Governance` check is not success, the second PR has no authorization and is not merged

### Requirement: Merged trees are checked

The service SHALL record the merged tree against the merge intent. A merged tree that differs from the validated tree SHALL freeze merges in that repository, alert the owner and security lead, and open a revert PR.

#### Scenario: Tree mismatch

- **WHEN** the merged tree differs from the validated merge tree
- **THEN** the repository's merges are frozen and a revert PR is opened

### Requirement: Rulesets are cut over without an unprotected interval

For each repository, the new rules SHALL be added while legacy branch protection is still active. The legacy protection SHALL be removed only after the effective rules, App binding and bypass lists are read back and match. On `contrib/**`, ruleset A SHALL only forbid force push and deletion, and ruleset B SHALL restrict creation and update to the Governance App. Rollback SHALL follow the same order in reverse.

#### Scenario: Read-back mismatch

- **WHEN** the effective rules after adding the rulesets do not show the `Governance` check bound to the Governance App, ruleset A with no bypass actors, and ruleset B with only the Governance App as bypass actor
- **THEN** the cutover stops with legacy protection still in place

### Requirement: Platform capabilities are verified before cutover

Before cutover, preflight SHALL verify plan support for the ruleset form and ruleset B, each repository's `pull_request_target`, `workflow_run` and fork-run approval policy, check-run action delivery, dispatch-to-run correlation, the Governance App's `workflows` permission and the expected-head merge, and SHALL pass the design's acceptance suite. Without ruleset B there MUST be no cutover.

#### Scenario: Organization rulesets unavailable

- **WHEN** preflight finds the plan does not support organization rulesets
- **THEN** per-repository rulesets are used, or the owner approves a plan change, before any cutover

#### Scenario: Ruleset B unavailable

- **WHEN** preflight cannot restrict updates of `main` to the Governance App
- **THEN** cutover does not start

### Requirement: The legacy automated-review status stays required until cutover

While the legacy gate is authoritative, its automated-review status MUST NOT be dropped from the required checks. The current review action SHALL be removed only in the same shared-workflow change that adds a replacement job, built and verified beforehand, publishing the same context from the same integration with the chosen provider. Rollback MUST NOT put a reviewer key back into a product repository.

#### Scenario: Removal without replacement

- **WHEN** a change removes the current review action without the same-context replacement in the same change
- **THEN** it does not land

#### Scenario: Legacy key unusable

- **WHEN** the legacy reviewer key is exhausted or missing in a repository still on the legacy gate
- **THEN** the legacy automated-review status fails with a reason and the PR waits; nothing passes silently

### Requirement: The legacy replacement job is isolated from PR code

The replacement legacy review job SHALL restore no cache, install the engine from a hash lock without cache, download only the trusted preparation artifact by id, read no output of jobs that run PR code, and have no `id-token` or write permission. A separate keyless job that `needs` admission SHALL reserve each pass before the review job runs, and SHALL be the only job requesting `id-token: write`; with no grant, the review job MUST NOT run.

#### Scenario: Cache poisoning beside the key

- **WHEN** PR code in the legacy Quality job saves a cache under the reviewer engine's cache key
- **THEN** the review job restores no cache and is unaffected

#### Scenario: Ledger refuses

- **WHEN** the ledger refuses the reservation
- **THEN** the review job does not call the provider and the status fails as `budget`

### Requirement: Legacy reservations are a dated OIDC exception

The service SHALL accept a product-repository token only for reservation grants, never a result, only with the exact claims below, and only for a repository in phase B before its cutover or 2027-01-31. Grants SHALL be single-use and bound to `run_id` and pass.

#### Scenario: Branch workflow calls the shared workflow

- **WHEN** a branch workflow calls the shared workflow at S and presents its token for a reservation
- **THEN** the service refuses it on `ref`

#### Scenario: Reservation token presented as a result

- **WHEN** a reservation-job token is presented with a review or quality result
- **THEN** the result is refused

### Requirement: Legacy reservation tokens carry exact claims

A reservation token SHALL carry `iss`, a service-specific `aud`, an unexpired `exp`, a single-use `jti`, the org's `repository_owner_id`, `job_workflow_ref` exactly the shared workflow at S with `job_workflow_sha` equal to S, `ref` `refs/heads/main`, `event_name` `issue_comment`, `run_attempt` 1 and a pinned `repository_id`.

#### Scenario: Claim mismatch

- **WHEN** any listed claim is missing or differs, or the `jti` was used before
- **THEN** the reservation is refused and no grant is issued

### Requirement: The key name changes only inside the switch, validator-first

The generator, regenerated workflows, the validator's canonical caller and installed callers SHALL keep the legacy key name until the switch. A validator-only change V SHALL first accept exactly the legacy and switch caller forms, each with a single key; the switch S SHALL then rename to the switch's single provider key name, and S's validator SHALL accept only the switch form. No step SHALL add a fallback between names.

#### Scenario: Shared rename without the validator step

- **WHEN** a shared change declares the new key name while `.github`'s installed validator only knows the legacy form
- **THEN** its standards check fails and it does not land

#### Scenario: Secret fallback proposed

- **WHEN** a change passes the key as the new name or else the old one
- **THEN** standards fails and the change does not land

### Requirement: V's compatibility window closes by mechanism

S's validator SHALL reject any caller pinned to V. V's compatibility authorization SHALL close when the final required re-pin completes or on 2026-11-20, whichever is first. V's own validator SHALL self-expire: after 2026-11-20 UTC it rejects every caller in both forms, reading the run's clock with no override input.

#### Scenario: Legacy form after the switch window

- **WHEN** a caller is still pinned to V, or uses the legacy form, after 2026-11-20
- **THEN** standards rejects it

#### Scenario: V's validator at its cutoff

- **WHEN** V's validator runs under an injected clock just before and just after 2026-11-20 UTC
- **THEN** it accepts a valid caller before the cutoff and rejects every caller, in both forms, after it

#### Scenario: Downgrade to V after the switch

- **WHEN** a switch-form caller in a repository already on S selects V, including after the final re-pin completed early
- **THEN** S's validator rejects it

### Requirement: Removal follows a dated, gated re-pin sequence

V and then S SHALL land on `.github`, each checked by the validator installed there; `.github`'s caller SHALL move to V and then, separately, to S, verifying the new status before its old key is retired. Each other pinned repository SHALL re-pin to V, then to S, through its own gate, retiring its old key after the S re-pin. Each repository SHALL have a dated deadline; on a miss its old path is disabled even if that freezes it.

#### Scenario: Shared workflow lands but the caller does not move

- **WHEN** S is on `.github`'s `main` but `.github`'s `pr.yml` still pins an older SHA
- **THEN** `.github` still runs the current action, its old key is not retired, and the re-pin step is still owed

#### Scenario: Each installed validator accepts its step

- **WHEN** a step is prepared
- **THEN** tests run the validator installed in each target repository against that step's real tree, on the normal and missing-key routes, and the step lands only if they pass

#### Scenario: S with no switch key in its environment

- **WHEN** S runs in an isolated scratch repository whose `legacy-review` environment has no switch secret and the caller mapping is empty
- **THEN** no provider call is made and the required status fails; with the key only in that environment and the caller mapping empty, the review runs and publishes; this evidence is required before S lands

#### Scenario: Deadline missed

- **WHEN** a repository has not re-pinned by its deadline
- **THEN** its old key is revoked, every merge there waits, and the weekly report lists it

### Requirement: The one-time switch authorization is a named exception

A V or S re-pin PR that cannot get the legacy status because its old key failed or was revoked MAY be merged under the owner's one-time switch authorization, a named exception to decision 7. It never covers V or S themselves. It SHALL expire on 2026-11-20 or at the last re-pin, whichever is first, and from then the script SHALL refuse every lift before any protection change; a repository still unpinned then stays frozen until a new recorded owner decision. Any other use is a policy violation.

#### Scenario: Lift after expiry

- **WHEN** a lift is attempted after 2026-11-20 or after the last re-pin
- **THEN** the script refuses before any protection change

#### Scenario: Exception used for the UI repository's re-pin

- **WHEN** the lab's automation, with the owner's account through its restore runner, merges `ejm-ui`'s re-pin PR under the switch authorization
- **THEN** the audit record names the repository, PR, head and base, generated and actual diff digests and who verified them, the protection JSON before and after, times, the authenticated login with the runner's run id and host, reason and the authorization

#### Scenario: Exception used for anything else

- **WHEN** the switch authorization is used for V, S, any PR that is not a qualifying re-pin, or after it expired
- **THEN** it is a policy violation reported to the security lead and the Board

### Requirement: The switch exception is narrowly executed

The service SHALL generate the re-pin diff itself (the pin set to the recorded V or S plus the enumerated secret-mapping and, for S, `id-token: write` lines), fetch the PR diff itself and verify the digests before any lift, by the security lead once a second human exists, else as a recorded owner-only check. One logged script SHALL lift only the automated-review required context for at most 10 minutes, then prove `main` moved by exactly that one commit.

#### Scenario: Diff digest mismatch

- **WHEN** the PR's diff digest differs from the generated re-pin diff
- **THEN** no lift happens and nothing merges

#### Scenario: Extra commit during the window

- **WHEN** `main` moved by any commit other than the logged merge during the lift
- **THEN** the context is restored at once, the commit is reverted or quarantined, and an incident is opened

#### Scenario: Other PR ready to merge

- **WHEN** another open PR in that repository has its remaining checks green
- **THEN** no lift happens until it is not, and agent merges are paused during the lift

#### Scenario: Forged legacy status

- **WHEN** reconciliation finds a legacy status on a frozen repository not created by the shared workflow's own run
- **THEN** it is flagged as a policy violation to the owner and security lead

### Requirement: The switch exception lift is crash-safe

Before any lift, the script SHALL persist the protection JSON and arm a deadline page, as a durable service job and with a monitor outside the service. It SHALL refuse to lift unless the page is armed and read back on both paths, an end-to-end test page has been delivered, the owner has recorded being on hand for the window (on `ejm-ui` too), and the service is healthy. Restoration and read-back SHALL run on every exit path; unfinished lifts SHALL be flagged first on restart.

#### Scenario: Script killed after the lift

- **WHEN** the script is killed right after removing the automated-review context
- **THEN** the saved `checks` are restored with their `app_id` and read back (on `ejm-ui` by the automation's deadline restore at 6 minutes 30 seconds; elsewhere, or if that fails, by the owner by hand after the page to the owner and the security lead at 7 to 8 minutes), and every other protection setting equals the saved JSON

#### Scenario: Recovery not armed

- **WHEN** the deadline page is not armed on both paths, its arming cannot be read back, or the owner has not recorded being on hand
- **THEN** the script does not lift

#### Scenario: Merge not done by minute 6

- **WHEN** the merge has not completed 6 minutes after the lift
- **THEN** the script stops waiting, restores and reads back before the deadline page fires, and the single-commit check settles the outcome

### Requirement: The deadline restore runs first on ejm-ui and the deadline page reaches the owner

On `ejm-ui` the automation's deadline restore SHALL run first, at 6 minutes 30 seconds after the lift. At 7 minutes (retry by 8), the service SHALL page unless its own restore read-back is recorded, and the monitor outside it SHALL page unless its own reads equal its pre-window read; no report clears the monitor's page. Each pages the owner, who restores by hand (on `ejm-ui` when the automation's restore failed, elsewhere always), and the security lead, as witness and for escalation.

#### Scenario: Service down through the window

- **WHEN** the script is killed after the lift and the service is down through the window
- **THEN** the monitor outside the service pages the owner and the security lead at 7 to 8 minutes, and on restart the service flags the unrestored lift first

### Requirement: The crash restore writes the saved checks or the lock

Where no automation restore applies or it fails, the owner SHALL restore from the owner's administrator account by writing the saved `checks` with their `app_id` and reading them back. Failing that, the same account SHALL `PUT` the saved JSON with `lock_branch: true`, read it back and page; an in-service pause MUST NOT count as the freeze.

#### Scenario: Merge and restore calls interrupted

- **WHEN** the merge call and then the restore call time out or return ambiguously
- **THEN** the deadline page fires and the owner restores by hand, or sets the branch lock on `main` from the saved JSON, reads it back, and pages the owner and the security lead

#### Scenario: Restore through the contexts-only call

- **WHEN** a restore would re-add the context without its `app_id`
- **THEN** the read-back fails on `app_id` and the lock path runs

### Requirement: The outside monitor is independent and cannot be silenced

The monitor outside the service SHALL run on a different hosting account from the service and the lab's automation, with its own administrators and pager route, and SHALL hold no GitHub, service or automation credential. Registration SHALL only add a window; no message from the service, the script or the automation SHALL cancel or delay its pages.

#### Scenario: Service tries to cancel the page

- **WHEN** the service, the script or the automation sends the monitor a cancel or delay for a registered window
- **THEN** the monitor ignores it and pages on its own timer

### Requirement: The outside monitor clears a window only on its own read

The monitor's baseline SHALL be its own last read before the window, never a value supplied at registration. It SHALL clear a window only when its own credential-free reads of `main` (the branch read's required status checks with every `app_id`, `strict` and the enforcement level, and the branch rules read) equal that baseline in full; a branch lock is not visible to it and SHALL leave the window paged.

#### Scenario: False restore report

- **WHEN** the service or the automation reports the restore done while `main` still lacks the context or its `app_id`
- **THEN** the monitor's own read at 7 and 8 minutes finds it lifted and pages the owner and the security lead, and an incident is opened

#### Scenario: Baseline offered at registration

- **WHEN** a registration carries an `app_id` or another protection value
- **THEN** the monitor ignores it and compares with its own pre-window read

### Requirement: The service compares the full protection after every window

After every window the service SHALL compare `main`'s full protection, read with the Governance App's administration read and never with the exception credential, with the saved JSON whose digest it recorded before the lift, and SHALL page on any difference.

#### Scenario: Another check changed inside the window

- **WHEN** inside a window another check, its `app_id` or `strict` changes and the lifted context is restored
- **THEN** the monitor's reads at 7 and 8 minutes differ from its pre-window read and it pages, and the service's post-window comparison pages

### Requirement: The outside monitor polls between windows

The monitor SHALL poll its credential-free reads for the life of the exception and page the owner on any difference from its last read outside a registered window.

#### Scenario: Change outside a window

- **WHEN** a required check, its `app_id`, `strict`, the enforcement level or a branch rule changes with no registered window
- **THEN** the monitor's next poll pages the owner at once

#### Scenario: Monitor cannot read protection without a credential

- **WHEN** preflight finds that the credential-free read does not return the required checks with their `app_id`
- **THEN** the switch exception cannot be used on that repository until the owner decides

### Requirement: Protection writes use the write shape

Every restore and lock SHALL build its write body from the saved protection read through a tested read-to-write transform that unwraps booleans, turns actor objects into logins and slugs, keeps every check's `app_id` (an unbound check written as explicitly unbound), refuses a contexts-only read and any unknown field at the top level or inside any block, and leaves out settings the full replace cannot carry. The read-back SHALL compare every field, those settings included.

#### Scenario: Read shape written back

- **WHEN** a restore would send the saved read body unchanged, or the saved read has no `checks` list or an unknown field
- **THEN** the transform refuses, and the field-by-field read-back reports any setting that differs from the saved read

#### Scenario: Unknown nested field

- **WHEN** a block of the saved read carries a field the transform does not know
- **THEN** the transform refuses it

### Requirement: A lift is read back with nothing excused

A lift SHALL be read back against the expected lifted read (the saved read less the one lifted context), with no field or block excused.

#### Scenario: Other change during a lift

- **WHEN** `strict`, another check's `app_id`, the enforcement level or the lock changes while one context is lifted
- **THEN** the lift read-back reports the change

### Requirement: A required-signatures difference is repaired or locked

A required-signatures difference SHALL be repaired through its own call and read back, or, by the automation's restore runner, answered with the lock and a page.

#### Scenario: Required signatures changed

- **WHEN** a restore's read-back finds required signatures different from the saved read
- **THEN** the owner's restore makes the signatures call and reads back, and the restore runner instead locks the branch and pages the owner

### Requirement: The crash residual is recorded

The design SHALL record that a crash after the lift leaves the automated-review requirement off on that repository until the restore (on `ejm-ui` the automation's deadline restore, else or on its failure the owner's manual restore), and that the 10-minute bound holds only on the script's own exit paths. It SHALL state that the security lead, who holds no administrator right, is paged as witness and for escalation, not to restore.

#### Scenario: Owner unreachable after a crash

- **WHEN** the automation's restore fails and the owner does not restore
- **THEN** the requirement stays off on that repository, the repository is recorded as frozen and the service merges nothing there, and the security lead escalates

### Requirement: Release validation uses governance evidence

`release.py` SHALL accept a release commit only if the Governance App merged exactly one PR into it, the evidence check on the merge commit and the service's evidence verify, release-affecting merges show security approval, and the release tree equals the validated merge tree. The service SHALL publish that evidence check after each merge, and a sweep SHALL publish it for any recorded merge that lacks it.

#### Scenario: Release of a non-strict merge

- **WHEN** a PR was merged after `main` moved and the release tree equals the validated merge tree
- **THEN** the release validator accepts it

#### Scenario: Release right after a crash

- **WHEN** the service crashed after merging and before publishing the merge-commit evidence check
- **THEN** the sweep publishes it, and until then `release.py` fails

### Requirement: Evidence format follows a durable cutover record

The evidence format SHALL be selected from a durable per-repository cutover record before verification: legacy evidence only for merges before that repository's cutover or within a recorded rollback epoch, new evidence otherwise. `release.py` MUST NOT fall back to legacy evidence when the service lookup fails.

#### Scenario: Service down with both evidence forms present

- **WHEN** a post-cutover merge also carries legacy statuses and the service is unreachable
- **THEN** `release.py` fails and does not accept the legacy evidence
