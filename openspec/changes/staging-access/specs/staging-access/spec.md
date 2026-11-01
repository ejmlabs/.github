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

### Requirement: Staging Access is never weakened to make a check pass

The smoke and every live staging verification SHALL accept only an authenticated 200 response. No workflow, script or instruction SHALL add an Access bypass, an allow-list entry besides the one smoke service token, a WAF skip or a bot-protection exception to satisfy a staging check, and gerry's exact-path webhook bypass applications SHALL keep their exact-path scope.

#### Scenario: Access login redirect

- **WHEN** an unauthenticated request to a staging host answers with the Access login redirect or challenge
- **THEN** the check records that staging is private and fails, and no rule is widened

#### Scenario: Smoke cannot pass

- **WHEN** a site's staging host keeps failing its smoke
- **THEN** the Access setup is fixed by the owner, and the smoke stays in the required path

### Requirement: The staging boundary stays recorded with each site

Every site repository that deploys a staging Worker SHALL name its staging Worker, staging hostname and the Access application that guards it in its own deploy documentation, and adding or renaming a staging hostname SHALL go through the site's configuration and a corresponding Access application before its next staging deploy.

#### Scenario: New staging hostname

- **WHEN** a site adds a staging hostname in its Wrangler config
- **THEN** its deploy documentation names the same hostname, the Access application planned for it, and what CI can reach on it

#### Scenario: Documentation drift

- **WHEN** a site's deploy docs name a staging hostname its Wrangler config does not declare
- **THEN** the mismatch is fixed in a reviewed change before that site's next staging deploy
