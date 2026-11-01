## ADDED Requirements

### Requirement: The staging job verifies the served build through Access

After the staging deploy succeeds, the staging job SHALL request the deployed staging host with the Access service-token headers taken only from the job's environment secrets, and SHALL fail the job when that request answers with the Access login, a challenge or any non-200. It SHALL also send a wrong-secret probe carrying the stored Client ID with an invalid secret, and SHALL fail the job unless Access itself rejects that probe; a challenge or the page's answer never counts as that rejection.

#### Scenario: Verify passes

- **WHEN** the token-carrying GET answers 200 with an HTML body within the cap and the wrong-secret probe is answered by Access's own rejection, an Access-issued 403 or the Access login redirect
- **THEN** the staging job succeeds and the run is eligible for a production release

#### Scenario: Gate absent

- **WHEN** the wrong-secret probe answers the page with 200 instead of Access's rejection, because the Access application is missing, deleted, or does not include the hostname
- **THEN** the staging job fails and names the gate it could not find

#### Scenario: Probe challenged

- **WHEN** the wrong-secret probe answers a challenge, because the owner's bot-phase skip is mis-scoped, absent, or does not match the probe's Client-ID header
- **THEN** the staging job fails and names the mis-scoped skip, and a challenge is never read as the gate being present

### Requirement: The staging smoke takes its host and token from reviewed sources

The staging host SHALL come from the reviewed Wrangler config's staging routes and SHALL be exactly one custom-domain entry whose pattern is one hostname. The token values SHALL come only from the job's environment secrets and SHALL fail the job when missing.

#### Scenario: Token secrets missing

- **WHEN** either Access service-token secret is unset in the `staging` environment
- **THEN** the staging job fails before the request and names the missing secret

#### Scenario: Access login instead of the page

- **WHEN** the token-carrying request is redirected to the Access login
- **THEN** the staging job fails, naming the failed verification, and production is not offered

#### Scenario: Over-cap response

- **WHEN** the response body exceeds the pipeline's byte cap
- **THEN** the staging job fails instead of trusting a truncated read

#### Scenario: Multi-route staging config

- **WHEN** a site's staging routes do not name exactly one custom-domain hostname
- **THEN** the staging job fails before the smoke and names the config field
