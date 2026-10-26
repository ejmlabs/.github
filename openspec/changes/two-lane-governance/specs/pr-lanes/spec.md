## ADDED Requirements

### Requirement: Every PR is classified into exactly one lane

The governance service SHALL classify every open PR targeting `main` as `trusted`, `inert` or `outside` on every relevant webhook, from metadata only. Classification MUST use the head repository, author identity, live roles, push-ledger senders, quarantine state, adoption records and changed files, and MUST NOT execute PR code.

#### Scenario: Maintainer branch PR

- **WHEN** a member of the `maintainers` team with live maintain or admin role opens a PR from a same-repository branch and is the only pusher
- **THEN** the lane is `trusted`

#### Scenario: Fork PR

- **WHEN** a PR's head repository differs from its base repository
- **THEN** the lane is `outside`, whoever the author is

### Requirement: Pusher identity comes from the push ledger

The service SHALL record the authenticated webhook sender of every head change in a push ledger. A PR SHALL be `outside` if any recorded sender is not trusted, except a Governance App adoption push or recorded branch-broker push (see "Permitted writers are a separate pinned allowlist"). Commit author and committer fields and co-author trailers MUST NOT grant or remove authority.

#### Scenario: Forged human author on an agent commit

- **WHEN** the Maintainer-agent App pushes a commit whose author field names a maintainer
- **THEN** the push ledger records the App as the pusher and the commit is treated as agent work

### Requirement: Trusted identities are pinned

The trusted set SHALL be exactly: the owner (by pinned account id); human (`type == User`) org members in the `maintainers` team with live maintain or admin role (both required); human org members in the `security` team; and the Maintainer-agent App (by pinned App id and bot account id). The Chief of Staff App is never trusted. Repository role alone MUST NOT make any principal trusted. Any other account, App or deploy key MUST be outside, whatever its login or role.

#### Scenario: Look-alike bot login

- **WHEN** a PR is opened by a bot whose login resembles the Maintainer-agent App but whose App id differs
- **THEN** the lane is `outside`

#### Scenario: Write collaborator outside the entire trusted set

- **WHEN** a collaborator with `write`, who is not the owner, not a `maintainers` member with live maintain or admin, and not in `security`, opens a PR from a same-repository branch
- **THEN** the lane is `outside`

#### Scenario: Security-team member with write

- **WHEN** a human org member in the `security` team with only `write` on the repository opens a PR from a same-repository branch and is the only pusher
- **THEN** the lane is `trusted`

#### Scenario: Outside collaborator with any role

- **WHEN** an outside collaborator added to the repository with any role, including `maintain` or `admin`, opens or pushes to a PR
- **THEN** the lane is `outside`, because outside collaborators cannot be in the trusted set

### Requirement: Permitted writers are a separate pinned allowlist

The permitted-writer allowlist SHALL be the trusted set plus the Governance App by pinned App id; only the access checks use it. The Governance App MUST NOT be a trusted author or pusher for lanes: its push-ledger entries SHALL count only as the adoption push of a recorded adoption for that exact `contrib/**` head, or as a recorded branch-broker push attributed to the Maintainer-agent App; any other Governance App push MUST make the PR `outside`.

#### Scenario: Intended installation passes preflight

- **WHEN** only the permitted writers hold write on every governed repository, including the Governance App's `contents: write`
- **THEN** the access checks report no finding and preflight passes that step

#### Scenario: Governance App push outside adoption

- **WHEN** the push ledger shows a Governance App push to a head with no matching adoption or branch-broker record
- **THEN** the lane is `outside`

### Requirement: Push credential provenance is established or fails closed

Product repositories SHALL have no deploy keys with write. While one exists, every PR in that repository MUST be `outside` and ship MUST be refused. The service SHALL trust a push-ledger sender only for push kinds whose real payloads were captured in preflight acceptance tests (user token; Governance App token for adoption and branch-broker pushes, with the broker's record naming the agent principal). Where the pushing credential cannot be established, the push MUST count as untrusted.

#### Scenario: Write deploy key present

- **WHEN** a deploy key with write exists on a product repository
- **THEN** preflight fails, and while the key exists every PR there is `outside` and ship is refused

#### Scenario: Deploy-key push attributed to a maintainer

- **WHEN** a push made with a deploy key arrives with a maintainer as its sender
- **THEN** the service does not treat the sender as proof of a trusted push, and the PR is `outside`

#### Scenario: Agent App token push

- **WHEN** an agent submits commits to the branch broker and the broker pushes them
- **THEN** the push ledger records the Maintainer-agent App as the pushing principal from the broker's record, and the push is recorded as agent work

### Requirement: Lane detection never relies on head location alone

The service MUST NOT treat a PR as trusted because its head is in the base repository. A same-repository head SHALL be classified by its principals (author, every push-ledger sender and their live trusted-set membership) exactly as any other PR; a head repository that differs from the base is an additional reason for `outside`, never the only check.

#### Scenario: Same-repository branch by an untrusted author

- **WHEN** an author outside the trusted set opens a PR from a branch pushed to the base repository
- **THEN** the lane is `outside`

#### Scenario: Trusted author, untrusted pusher on a same-repository branch

- **WHEN** a maintainer opens a PR from a same-repository branch and the push ledger records any sender outside the trusted set
- **THEN** the lane is `outside`

### Requirement: Write access outside the permitted writers is detected and alerted

Any principal not on the permitted-writer allowlist with write or higher on a governed repository SHALL be a finding, detected on `member`, `membership`, `team`, `team_add` and `deploy_key` webhooks and in the hourly reconciliation. Each finding SHALL write an audit record and notify the owner and the security lead. PRs whose author or push-ledger sender is a flagged principal MUST be `outside`.

#### Scenario: Collaborator granted write

- **WHEN** an org member outside the entire trusted set is given `write` on a governed repository
- **THEN** the service records an audit entry, notifies the owner and the security lead, leaves the access unchanged, and classifies that member's PRs as `outside`

#### Scenario: Missed webhook

- **WHEN** a deploy key with write is added and no webhook reaches the service
- **THEN** the hourly reconciliation detects it and alerts the same way

### Requirement: Other Apps with write are found by inventory

The hourly reconciliation SHALL read the organization's App installation inventory and each installation's repository coverage, and SHALL flag any App other than the two pinned Apps with contents write on a governed repository. An incomplete or forbidden inventory read MUST count as a finding. While an App finding is open, every PR in the affected repositories MUST be `outside`.

#### Scenario: A different App gains write

- **WHEN** another App is installed, or its permissions change to contents write, on a governed repository
- **THEN** the next reconciliation flags it, alerts the owner and the security lead, and classifies that repository's PRs as `outside`

#### Scenario: Inventory read forbidden

- **WHEN** the installation inventory read returns forbidden or a partial page set
- **THEN** the check fails as a finding instead of reporting no Apps

### Requirement: Access alerts never remove access

Detection SHALL alert only and MUST NOT remove access; removing access is an owner action. The settings tool SHALL run the same detection in preflight and at every cutover, and preflight MUST NOT pass while a finding is open.

#### Scenario: Preflight with an open finding

- **WHEN** the settings tool finds a `write` grant to a team other than `maintainers` or `security` during preflight
- **THEN** preflight fails until the owner removes the grant

### Requirement: Inert lane admits only strictly inert files

A trusted, non-adopted PR SHALL be `inert` only if every changed file is a regular `.md` or `.txt` file in a profile-approved location that no build or site consumes, and Markdown contains no raw HTML, front matter, include, directive or Liquid syntax, and no `javascript:` or `data:` link targets. Paths SHALL be normalized, case-folded and NFC-normalized first. The old and new path of a rename MUST both qualify. The checker MUST fail closed when it cannot parse a file.

#### Scenario: Docs-only change

- **WHEN** a trusted PR changes only `docs/guide.md` with plain Markdown
- **THEN** the lane is `inert`

#### Scenario: HTML hidden in Markdown

- **WHEN** a changed Markdown file contains a `<script>` tag or any raw HTML
- **THEN** the lane is `trusted`, not `inert`

#### Scenario: Symlink or config

- **WHEN** a PR adds a symlink, or changes a configuration file, under `docs/`
- **THEN** the lane is `trusted`, not `inert`

### Requirement: Active and instruction files are never inert

These MUST never be inert: active `.txt` files (`requirements*.txt`, `constraints.txt`, `robots.txt`, `CMakeLists.txt`, `llms.txt`), files that instruct agents (`AGENTS.md`, tool-specific agent instruction files listed by exact path or glob in the versioned policy file, `.github/instructions/**`, `*.prompt.md`), `.github/**/*.md`, README, install and release docs. A PR that adds or changes fenced code blocks, URLs or domains, or checksum-like hex strings MUST NOT be inert.

#### Scenario: Changed download URL in docs

- **WHEN** a docs-only PR changes a URL or a checksum in an install guide
- **THEN** the lane is `trusted` and the paid review runs

#### Scenario: Agent instruction file

- **WHEN** a PR changes only `AGENTS.md`
- **THEN** the lane is `trusted`, not `inert`

#### Scenario: Upper-case extension

- **WHEN** a PR adds `docs/NOTES.MD` containing raw HTML
- **THEN** the file is checked as Markdown and the lane is `trusted`

### Requirement: Quarantine revokes at once and is inherited

A downgrade SHALL quarantine the PR, and where specified also the principal, head SHA, tree SHA or adoption lineage. It SHALL revoke all authorizations in the current generation, fail `Governance` and cancel paid jobs immediately. PRs or adoptions that reuse a quarantined principal, head or tree MUST be outside.

#### Scenario: Manual downgrade

- **WHEN** the security lead posts `/downgrade suspicious push`
- **THEN** the PR becomes outside and its ship and paid jobs are revoked at once

#### Scenario: Same code reopened elsewhere

- **WHEN** a maintainer opens a new PR, or adopts an outside PR, with a quarantined head or tree
- **THEN** the new PR is outside and adoption is refused

### Requirement: Only owner or security lead can restore

A quarantine SHALL be lifted only by the owner or the security lead with `/restore-lane <reason>` naming the scope it lifts. Quarantine of a principal SHALL require the owner or security lead. A restore MUST NOT revive earlier authorizations.

#### Scenario: Restore needs a fresh ship

- **WHEN** the owner restores a quarantined PR
- **THEN** the PR is classified again and needs a new ship in the current generation

### Requirement: Loss of trust is detected and backstopped

The service SHALL quarantine affected PRs on membership, team or installation webhooks showing loss of a trusted role, SHALL run an hourly reconciliation of live roles, and SHALL re-check every authorizer's role just before each merge. Operations SHALL require revoking a maintainer's decisions before demoting them.

#### Scenario: Demotion without a PR event

- **WHEN** a maintainer who shipped an open PR is removed from the org and no PR event follows
- **THEN** the membership webhook, the reconciliation or the pre-merge re-check revokes the ship before any merge
