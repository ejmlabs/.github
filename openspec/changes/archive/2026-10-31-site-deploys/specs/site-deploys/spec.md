## ADDED Requirements

### Requirement: Merges deploy to staging automatically
A push to main in an adopting site repository SHALL build the site without credentials and deploy it to its staging Worker.

#### Scenario: Staging config missing
- **WHEN** the Wrangler config has no `env.staging` with its own name and routes
- **THEN** the staging deploy fails and production is not offered

### Requirement: Production waits for a human
Production SHALL deploy the files staging deployed, only after the `production` environment's required reviewer approves.

#### Scenario: Unprotected environment
- **WHEN** the `production` environment requires no reviewer
- **THEN** the production deploy fails before calling Wrangler

#### Scenario: Newer merge
- **WHEN** a newer main commit reaches production while an older one waits for approval
- **THEN** the older production deploy is cancelled
