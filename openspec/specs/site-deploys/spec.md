# site-deploys Specification

## Purpose

Continuous staging deploys and maintainer-released production deploys for the ejmlabs sites.

## Requirements

### Requirement: Merges deploy to staging automatically

A push to main in an adopting site repository SHALL build the site without credentials and deploy it to its staging Worker. The build SHALL run the product's executable `.github/site-build` when it exists, else the profile's built-in commands.

#### Scenario: Staging config missing

- **WHEN** the Wrangler config has no `env.staging` with its own name and routes
- **THEN** the staging deploy fails and production is not offered

### Requirement: Production waits for a maintainer

Production SHALL deploy the files staging deployed only after a required reviewer of the `production` environment approves the job, and only while the job's commit is still main's head. The merge releases a change to staging and the approval releases it to production. A deploy that has started SHALL never be cancelled; the build, staging and production jobs SHALL queue per repository in push order, and a newer main commit SHALL replace only an older run that has not started.

#### Scenario: Unprotected environment

- **WHEN** staging or production lacks a custom deployment branch policy of exactly `main`, or production requires no reviewer
- **THEN** the deploy fails before calling Wrangler

#### Scenario: An older run approved late

- **WHEN** a maintainer approves a production job after a newer commit reached main
- **THEN** that job fails before calling Wrangler, and the newer commit's job deploys once it is approved

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
