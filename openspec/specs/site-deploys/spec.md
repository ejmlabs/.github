# site-deploys Specification

## Purpose

Continuous staging deploys and approved production deploys for the ejmlabs sites.

## Requirements

### Requirement: Merges deploy to staging automatically

A push to main in an adopting site repository SHALL build the site without credentials and deploy it to its staging Worker. The build SHALL run the product's executable `.github/site-build` when it exists, else the profile's built-in commands.

#### Scenario: Staging config missing

- **WHEN** the Wrangler config has no `env.staging` with its own name and routes
- **THEN** the staging deploy fails and production is not offered

### Requirement: Production waits for a human

Production SHALL deploy the files staging deployed, only after the `production` environment's required reviewer approves, and a newer main commit SHALL cancel an older production deploy still waiting.

#### Scenario: Unprotected environment

- **WHEN** an environment lacks a custom deployment branch policy of exactly `main`, or production requires no reviewer
- **THEN** the deploy fails before calling Wrangler

### Requirement: Deploy trusts only the reviewed commit

Each deploy job SHALL check out the reviewed `github.sha` without credentials and SHALL require the artifact's Wrangler config, and any Worker source, to be byte-identical to it. It SHALL validate tar members before extraction and run Wrangler with an environment that holds no GitHub token.

#### Scenario: Build changed the config

- **WHEN** the built artifact's Wrangler config differs from the reviewed commit's
- **THEN** the deploy fails before calling Wrangler

### Requirement: The deploy token reaches only the deploy step

The canonical `deploy.yml` SHALL pass `secrets: inherit` so the environment's `CLOUDFLARE_API_TOKEN` reaches the deploy jobs, and only their final deploy step SHALL read it. The build job SHALL receive no secret.

#### Scenario: Build job

- **WHEN** the build job runs
- **THEN** it holds `contents: read` and no secret
