# Repository operations

## Permissions and required settings

Main requires a PR, one native approval recorded from an explicit human maintainer comment, current Maintainer approval and Human readiness statuses, Quality, Repository standards, and AI review. Require strict status checks, resolved conversations, linear history, and stale approval dismissal. Enforce administrators. Disable force pushes and branch deletion. Use squash merges and delete merged branches.

Enable read-only default workflow tokens and bot review recording. Allow only pinned actions from actions/*, astral-sh/setup-uv, openai/codex-action, and this shared repository. Enable Actions sharing within the organization for this private shared repository. Never grant untrusted builds model keys, source-read secrets, deployment credentials, or write tokens. Do not reuse caches produced by PR code in a privileged job.

Every account with write access must be a human with maintain or admin permission. The settings tool rejects ordinary writers and bots before changing any repository. GitHub Actions app identity alone cannot prove which workflow created a status: a writer can add a branch workflow that uses the same identity. If ordinary writers become necessary, first migrate required result publication to a dedicated GitHub App whose credential is confined to a protected environment and unavailable to branch workflows.

After removing or demoting a maintainer, revoke their open PR decisions before completing the access change. Commands, finalization, and releases check current roles; GitHub does not send a continuous role-change event to this pipeline. Organization administrators can change repository policy and therefore remain trusted.

## Admission and budget controls

Only trusted main receives issue-comment events. Bot and unrelated comments are filtered before a runner starts. The script rechecks the current human's maintain/admin role, exact current head, non-draft main target, and the original command. Serialize admission per PR, reject repeated events and Actions reruns, and consume each comment once. A commit can be readmitted only after explicit revocation and a new human command.

Admission limits: 200 changed files, 12,000 added/deleted lines, 1 MB diff. Quality has a 45 minute limit, the separate registry gate 25 minutes, preparation 5 minutes, and each AI pass 9 minutes inside a 12 minute job. AI passes run independently and serially. There are no automatic model retries. Model output is capped at 64 KB and 50 findings. A failed or incomplete pass blocks merge. Critical, high, and medium findings block; low findings are advisory. Review artifacts are retained 7 days; source handoff artifacts 3 days.

These bounds limit each admitted run. Set a dedicated OpenAI project spending limit and GitHub Actions budget/alerts to bound total spending across admitted PRs. An organization member can still request workflows they are allowed to dispatch; restrict repository roles and revoke access when needed. GitHub administrators retain control over repository settings. No repository policy can stop an organization owner from changing the policy itself.

## Credentials

Store OPENAI_API_KEY as a selected organization secret or separately in the five repository secrets. Use a dedicated OpenAI project. Missing credentials fail closed. Rotate a leaked key at the provider, remove the secret, audit runs, and readmit only after the incident is contained.

While the harness is private, create a fine-grained GitHub token with **Contents: read** for **ejmlabs/ejm-harness only**, give it an expiry, and save it as EJM_HARNESS_TOKEN in ejm-cli and ejm-ide. The trusted preparation job archives the pinned harness revision; the untrusted build receives only source data. Once the dependency is public, remove this secret. Never copy a broad personal token into Actions.

## Bootstrap and rollout

1. Test and commit the shared implementation. Add the shared repository's own consumers pinned to that tested commit. Existing consumers pin the same immutable revision.
2. Review each adoption change, preserving earlier local commits and concurrent work. A trusted comment workflow must exist on main before GitHub can deliver PR comments to it. This is a one-time bootstrap requirement; installing only a branch copy cannot activate issue-comment admission.
3. During bootstrap, disable existing automatic PR/push workflows before opening adoption PRs. Do not authorize the old workflows to run unreviewed source. After explicit maintainer acceptance of the exact adoption changes, install the trusted callers on main, enable Actions, and verify the required checks using a fresh admitted PR. Do not silently weaken an active protection to merge a bootstrap PR.
4. Read back main protection, Actions policy, branch rules, dependency alerts, and security settings. Repos remain private until the public-readiness blockers are closed.
5. Test human readiness, stale pushes, self approval, revocation, missing secrets, failed checks, and a refused duplicate release tag in GitHub before claiming live enforcement. Local policy tests are not evidence of GitHub event delivery or bot review permission.

## Public visibility checklist

Before a visibility change, inspect all refs and release assets for private data and secrets; review licenses, copied brand material, and vulnerability findings. Enable GitHub secret scanning, push protection, private vulnerability reporting, dependency alerts/updates, dependency review and CodeQL where available without extra charges. Require approval for **all external contributors** in the public Actions settings, and keep write tokens/secrets disabled for fork workflows. Private fork approval and public private-reporting APIs are unavailable while these repositories are private. Do not enroll private repos in a billed security product by assumption.

Require two-factor authentication for organization members through the organization owner after checking member readiness and recovery access. This is an organization access change, separate from repository configuration. Review access, installed apps, scoped secrets, workflow pin updates, and supported release lines regularly.

## Recovery

Revoke the readiness comment for a suspect head, cancel its run, and inspect the isolated artifacts. A failed shared update is rolled back by an ordinary reviewed PR restoring the previous full workflow SHA. Do not move a shared revision or release tag. Keep GitHub Actions and OpenAI budget notifications enabled. Release setup makes drafts only and does not deploy or upload packages.
