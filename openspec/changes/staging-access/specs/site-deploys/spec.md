## ADDED Requirements

### Requirement: The staging job verifies the served build through Access

After the staging deploy succeeds, the staging job SHALL request the deployed staging host with the Access service-token headers taken only from the job's environment secrets, and SHALL fail the job when the host answers with the Access login, a challenge or any non-200.

#### Scenario: Verify passes

- **WHEN** the deployed staging host answers the token-carrying GET with 200 and an HTML body within the cap
- **THEN** the staging job succeeds and the run is eligible for a production release

### Requirement: The staging smoke takes its host and token from reviewed sources

The staging host SHALL come from the reviewed Wrangler config's staging routes and SHALL be exactly one custom-domain entry whose pattern is one hostname. The token values SHALL come only from the job's environment secrets and SHALL fail the job when missing.

#### Scenario: Token secrets missing

- **WHEN** either Access service-token secret is unset in the `staging` environment
- **THEN** the staging job fails before the request and names the missing secret

#### Scenario: Verify passes

- **WHEN** the deployed staging host answers the token-carrying GET with 200 and an HTML body within the cap
- **THEN** the staging job succeeds and the run is eligible for a production release

#### Scenario: Access login instead of the page

- **WHEN** the token-carrying request is redirected to the Access login
- **THEN** the staging job fails, naming the failed verification, and production is not offered

#### Scenario: Over-cap response

- **WHEN** the response body exceeds the pipeline's byte cap
- **THEN** the staging job fails instead of trusting a truncated read

#### Scenario: Multi-route staging config

- **WHEN** a site's staging routes do not name exactly one custom-domain hostname
- **THEN** the staging job fails before the smoke and names the config field
