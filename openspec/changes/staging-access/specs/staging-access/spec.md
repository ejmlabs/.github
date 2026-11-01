## ADDED Requirements

### Requirement: Staging smoke requests carry only environment-stored token values

The staging smoke step SHALL read the Access service-token values only from the `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` environment secrets of the job's environment. No repository text, log line, error message or artifact output SHALL hold either value, and no other configuration source MAY supply them.

#### Scenario: Secrets absent

- **WHEN** either secret is unset in the `staging` environment
- **THEN** the smoke fails and names the missing secret without printing any value

#### Scenario: Failure reporting

- **WHEN** the smoke fails for any reason
- **THEN** the message names the failure kind, and no token value appears in the job log

#### Scenario: Token rotation

- **WHEN** the owner rotates the service token
- **THEN** the pipeline needs no code or repository change because the values live only in the environment secrets

### Requirement: The smoke proves the gate by Access's own rejection

The smoke and every live staging verification SHALL learn the gate's presence only from Access's own rejection of a probe GET carrying the smoke token's Client ID with an invalid secret; a challenge never records the gate as present, and the probe answered with the page fails the check.

#### Scenario: Denial probe answered

- **WHEN** the wrong-secret probe carries the smoke token's Client ID with an invalid Client Secret and a staging host answers it
- **THEN** only Access's own rejection, an Access-issued 403 or the Access login redirect, records the gate as present, because a challenge says nothing about the deploy and never stands in for it, and no rule is widened

#### Scenario: Unauthenticated access allowed

- **WHEN** the wrong-secret probe is answered with the site's own page instead of Access's rejection
- **THEN** the verification fails, names the missing gate, and no rule is widened

#### Scenario: Probe challenged

- **WHEN** the wrong-secret probe answers a challenge
- **THEN** the verification fails and names the missing or mis-scoped bot-phase skip, because the skip must match the probe's Client-ID header for Access to answer at all

### Requirement: Staging Access is never weakened to make a check pass

No workflow, script or instruction SHALL widen the Access boundary to make a check pass, and gerry's per-path signed-webhook bypass applications SHALL keep their current per-path scope. A bot-phase exception matching the smoke token's `CF-Access-Client-Id` header, its value or presence, on the staging hostnames MAY exist only as an owner decision recorded in `docs/operations.md`.

#### Scenario: Boundary stays at the owner and the token

- **WHEN** a change proposes an Access bypass, an allow-list entry besides the owner's email rule and the one smoke service token, a wider path scope, or a bot or WAF exception matching anything besides the smoke token's Client-ID header on the staging hostnames
- **THEN** it is refused as a widening of the boundary, and only the owner's recorded bot-phase exception exists

#### Scenario: Scoped bot exception

- **WHEN** the owner applies the bot-phase exception
- **THEN** it matches only the smoke token's `CF-Access-Client-Id` header, its value or presence, only on the staging hostnames, is recorded in `docs/operations.md` with its expression, and the denial probe relies on exactly this match

#### Scenario: Smoke cannot pass

- **WHEN** a site's staging host keeps failing its smoke after the Access setup is correct
- **THEN** the owner fixes the remaining setup as a recorded decision, and the smoke stays in the required path

### Requirement: The staging boundary stays recorded with each site

Every site repository that deploys a staging Worker SHALL name its staging Worker, staging hostname and the Access application that guards it in its own deploy documentation, and adding or renaming a staging hostname SHALL go through the site's configuration and a corresponding Access application before its next staging deploy.

#### Scenario: New staging hostname

- **WHEN** a site adds a staging hostname in its Wrangler config
- **THEN** its deploy documentation names the same hostname, the Access application planned for it, and what CI can reach on it

#### Scenario: Documentation drift

- **WHEN** a site's deploy docs name a staging hostname its Wrangler config does not declare
- **THEN** the mismatch is fixed in a reviewed change before that site's next staging deploy
