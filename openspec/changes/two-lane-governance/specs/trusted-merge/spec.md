## ADDED Requirements

### Requirement: One required Governance check gates main

`main` in each governed repository SHALL be protected by two rulesets. Ruleset A SHALL require a pull request and the `Governance` check from the Governance App, with squash only, linear history, resolved conversations, and no force pushes or deletion, and MUST have no bypass actors. Ruleset B SHALL restrict updates to `main`, with the Governance App as its only bypass actor. There MUST be no emergency or owner bypass. Informational checks MUST NOT be required.

#### Scenario: Forged status from a branch workflow

- **WHEN** a branch workflow publishes a `Governance` status as the GitHub Actions app
- **THEN** the ruleset does not count it and the PR cannot merge

#### Scenario: Maintainer merges a green SHA

- **WHEN** a maintainer or the Maintainer-agent App calls the merge endpoint while `Governance` is green on the head
- **THEN** ruleset B refuses the update

### Requirement: Checks and review start automatically and once per head

For a non-draft trusted PR, the service SHALL dispatch Quality and Repository standards after a 2-minute push debounce, and then the paid review only if both passed. Work SHALL be deduplicated by repository, PR, head, base, policy version and pass. Metadata-only events MUST NOT start paid work.

#### Scenario: Push to a trusted PR

- **WHEN** a maintainer pushes to a non-draft trusted PR
- **THEN** checks and then the review run on that head with no command

#### Scenario: Title edited three times

- **WHEN** the PR title is edited three times on an unchanged head
- **THEN** no new paid review is started

#### Scenario: Failing tests skip the paid review

- **WHEN** Quality fails on a head
- **THEN** no paid pass runs for that head

### Requirement: Inert lane review follows the effective tier

For an `inert` PR, the service SHALL run Repository standards and a Markdown render and link check, and SHALL review it at its effective tier's cap and pass count; lane membership MUST NOT lower the tier. The review MAY be skipped (G12, under re-review) only when the effective tier is T0, the 50-PR shadow is complete and clean, and the owner recorded approval. A ship MUST still be required.

#### Scenario: Docs PR before skipping is approved

- **WHEN** a T0 inert PR passes its checks and is shipped while skipping is not enabled
- **THEN** one review pass at the T0 cap ran, and the service merges it

#### Scenario: 301-line inert PR

- **WHEN** an inert PR changes 301 lines
- **THEN** it is T2, reviewed at the T2 cap with two passes, and never skipped

#### Scenario: Classifier absent

- **WHEN** the classifier is absent or fails for an inert PR
- **THEN** it is T3 and reviewed at the T3 cap

#### Scenario: Skip flag with a higher tier

- **WHEN** skipping is enabled but an inert PR's effective tier is T3
- **THEN** the review runs at the T3 cap

#### Scenario: Skip enabled for a T0 PR

- **WHEN** the owner has recorded the skip decision after a clean 50-PR shadow and the effective tier is T0
- **THEN** the PR marks `Automated review` as not required without calling the reviewer

### Requirement: Ship binds to an exact head without typing a SHA

A trusted human SHALL be able to ship by clicking the `Ship` check-run action, which binds to that check run's head SHA. They SHALL also be able to ship with a native Approve review whose commit is the current head, from a `type == User` reviewer with a live trusted role at decision time who is not the author and pushed nothing to the PR. A ship SHALL count only for the current generation. A click from anyone else, or on a check run not created by the Governance App, MUST be refused and audited.

#### Scenario: Owner ships own PR with one click

- **WHEN** the owner clicks Ship on the current head of their own PR
- **THEN** the ship is recorded for that head and generation, and the service merges once all gates pass

#### Scenario: Click on an old head

- **WHEN** someone clicks Ship on a check run for a head or generation that is no longer current
- **THEN** nothing is recorded and the reply points to the current head (binding rules in governance-control-plane)

### Requirement: Ship comments are accepted only when ordering is certain

A `/ship` comment SHALL count only when typed by a trusted human, and never on a PR that any App pushed to or that is release-affecting. It SHALL be accepted only if the push ledger shows the current head was received at least 60 seconds before the comment was created, and no later head event exists. An optional hex prefix of 7 or more characters MUST match if given. Otherwise the command SHALL be rejected and nothing recorded.

#### Scenario: Push races the ship comment

- **WHEN** a head event is received within 60 seconds before, or after, the `/ship` comment's creation time
- **THEN** the command is rejected with a reply offering the Ship button

#### Scenario: Comment ship on an agent-pushed PR

- **WHEN** a maintainer posts `/ship` on a PR the Maintainer-agent App pushed to
- **THEN** the command is refused and the reply offers the Ship button or a native review

### Requirement: Comment commands come only from accounts no automation holds

A `/ship` or `/security-ok` comment SHALL count only from an account for which no automation holds a token. A quarterly review of the org's credential authorizations (personal tokens, OAuth grants and App user tokens) SHALL verify this; an account found with an automation token SHALL have its comment commands refused until the token is revoked.

#### Scenario: Automation token found on a maintainer account

- **WHEN** the credential review finds a token used by automation on a maintainer's account
- **THEN** that account's comment commands are refused until the token is revoked, and the button and native review remain

### Requirement: Only humans ship, approve, adopt, waive or restore

A ship, security approval, adoption, waiver or restore MUST come from a human identity. Any command, click or review made by an App or agent identity, including the Maintainer-agent App and the Chief of Staff App, MUST NOT count and SHALL be audited. No agent SHALL hold or use the owner's or a maintainer's user credential, except under the named exception to decision 11 below. The `Governance` check output SHALL show the ship actor's `actor_type` and any waiver.

#### Scenario: Chief of Staff posts a ship

- **WHEN** the Chief of Staff App posts `/ship`, `/security-ok`, `/adopt` or a waiver request
- **THEN** nothing is recorded and an audit record is written

### Requirement: The decision-11 exception confers no authority

The owner credential the lab's automation holds for the `ejm-ui` switch-exception lift and restore, until that exception ends, MUST NOT be used for a ship, approval, adoption, waiver or quarantine restore, and while it is held the owner's comment commands and native reviews MUST NOT count.

#### Scenario: Owner comment while the exception credential exists

- **WHEN** a `/ship` comment or native approval from the owner account arrives while the lab's automation holds the owner credential under the decision-11 exception
- **THEN** it does not count, and the reply offers the Ship button

### Requirement: Revocations take effect at once

`/unship`, a dismissed approving review, an edited or deleted `/ship` or `/security-ok` comment, a new generation, an outside lane and quarantine SHALL each void the affected authorizations immediately. The Maintainer-agent App MUST NOT ship, in any lane.

#### Scenario: Native approval dismissed

- **WHEN** the approving review that served as ship is dismissed
- **THEN** the ship is void and the PR is not merged

#### Scenario: Agent tries to ship

- **WHEN** the Maintainer-agent App posts `/ship`
- **THEN** nothing is recorded and an audit record is written

### Requirement: Release-affecting PRs need independent security approval

The release-affecting set SHALL be defined in a versioned policy file that fails closed; its minimum contents are listed in the design (release files, workflows, `CODEOWNERS`, community templates, governance and release scripts, profiles, lockfiles, manifests, rulesets, the policy file, service and runner repositories). A release-affecting PR SHALL need a security pass and `security_ok` from a `security` team member who MUST NOT have pushed to the PR and MUST NOT be the ship actor.

#### Scenario: Unreadable policy file

- **WHEN** the service cannot evaluate the release-affecting policy file for a PR
- **THEN** the PR is treated as release-affecting

#### Scenario: Version bump

- **WHEN** a trusted PR changes `VERSION`
- **THEN** it is not merged until a security team member who pushed no commit gives security approval on the current generation

#### Scenario: Security lead approves own push

- **WHEN** the security lead pushed a commit to the PR and then posts `/security-ok`
- **THEN** the approval is refused

#### Scenario: Owner ships and approves

- **WHEN** the owner both ships and gives `security_ok` on a release-affecting PR
- **THEN** the security approval is refused; a different `security` member must give it

### Requirement: The pipeline has no separate model-session security gate

A PR in this pipeline SHALL need tests, the automated review on the chosen provider and a human ship, plus human security approval when release-affecting. A separate model-session security review, used only for the owner's own direct work, MUST NOT be a gate, cost or capacity limit in this pipeline.

#### Scenario: PR without a model-session review

- **WHEN** a trusted PR has passing tests, a passing automated review and a ship, and no separate model-session review
- **THEN** it merges

### Requirement: Agent pushes need an independent human ship on sensitive PRs

If the Maintainer-agent App pushed to a release-affecting PR, the ship SHALL come from a human who pushed nothing to it, through the button or a native review.

#### Scenario: Agent edits governance

- **WHEN** the agent App pushed changes to `scripts/governance.py` and a human who did not push clicks Ship
- **THEN** the ship counts, subject to security approval

### Requirement: Merged history carries clean org authorship

The squash message SHALL be the PR title and body, and SHALL carry each contributor's `Signed-off-by` and `Co-authored-by` trailers. Repository standards SHALL fail if either contains agent, tool, model or vendor names, personal names outside `Co-authored-by` and `Signed-off-by` trailers, or secret-like values. Every commit in every lane SHALL carry a DCO `Signed-off-by` matching its author. Maintainer agent commits SHALL be pushed by the Maintainer-agent App with the same disclosure as any PR.

#### Scenario: Tool name in PR title

- **WHEN** a PR title names a code generation tool
- **THEN** Repository standards fails, pointing to the public-history rule

#### Scenario: Sign-off trailer in the squash message

- **WHEN** the squash message carries a contributor's `Signed-off-by` trailer with their name
- **THEN** Repository standards accepts it

#### Scenario: Maintainer commit without sign-off

- **WHEN** a maintainer's PR has a commit with no matching `Signed-off-by`
- **THEN** Repository standards fails and explains how to add it

### Requirement: The shipping human certifies agent-authored work

An agent cannot make the DCO certification, so for a PR the Maintainer-agent App pushed to, the shipping human's `Signed-off-by` SHALL be added to the squash message, and the ship action SHALL state that it certifies the change.

#### Scenario: Agent-authored PR merged

- **WHEN** the owner ships a PR pushed only by the Maintainer-agent App
- **THEN** the squash message carries the owner's `Signed-off-by`

### Requirement: Public text never names the reviewer

Public docs, the PR template, bot comments, labels and check names SHALL describe the reviewer only as "automated review". Repository standards SHALL fail on vendor, model or tool names in `templates/community/**`, public docs, workflows and scripts. The versioned policy file, which lists agent instruction files by exact path or glob, is configuration and SHALL be exempt.

#### Scenario: Template names a model

- **WHEN** a change to `templates/community/CONTRIBUTING.md` names a model or vendor
- **THEN** Repository standards fails

#### Scenario: Policy file lists instruction files

- **WHEN** the release-affecting policy file lists a tool-specific agent instruction file by path
- **THEN** Repository standards accepts it

### Requirement: Centrally owned documents change through templates

Community documents generated from `templates/community/`, including `GOVERNANCE.md` and `MAINTAINERS`, SHALL be changed only in the shared templates. After a template change merges, the service SHALL open one sync PR per governed repository from the Maintainer-agent App. Each sync PR SHALL need a human ship; a bulk owner ship SHALL be allowed only after the service confirms each diff exactly matches the merged template.

#### Scenario: Local CONTRIBUTING edit

- **WHEN** a PR edits `CONTRIBUTING.md` directly in a product repository
- **THEN** Repository standards fails with a pointer to the template path
