# site-deploys Specification

## Purpose

Continuous staging and production deploys for the ejmlabs sites, decided by the merge.

## Requirements

### Requirement: Merges deploy to staging automatically

A push to main in an adopting site repository SHALL build the site without credentials and deploy it to its staging Worker. The build SHALL run the product's executable `.github/site-build` when it exists, else the profile's built-in commands.

#### Scenario: Staging config missing

- **WHEN** the Wrangler config has no `env.staging` with its own name and routes
- **THEN** the staging deploy fails and production is not offered

### Requirement: Production follows staging after the merge

Production SHALL deploy the files staging deployed as soon as staging succeeds, with no approval in GitHub: the human decision is the merge. A required reviewer on the `production` environment SHALL be allowed and SHALL NOT be required. A deploy that has started SHALL never be cancelled; the build, staging and production jobs SHALL queue per repository in push order, and a newer main commit SHALL replace only an older run that has not started.

#### Scenario: Unprotected environment

- **WHEN** staging or production lacks a custom deployment branch policy of exactly `main`
- **THEN** the deploy fails before calling Wrangler

#### Scenario: A newer push while a deploy runs

- **WHEN** a newer commit reaches main while a deploy job is running Wrangler
- **THEN** that job finishes, and the newer commit's job waits behind it

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
