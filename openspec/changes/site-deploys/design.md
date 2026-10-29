## Context

Building a site runs product code and its dependencies. The deploy token must never share a job with that code. Production is the owner's decision each time.

## Decisions

- **Build once, deploy twice.** The build job has `contents: read` and no secrets. Staging and production download the same artifact, so production serves exactly what staging served.
- **Trusted deployer.** Deploy jobs install Wrangler 4.151.3 from a lockfile embedded in the workflow, with `--ignore-scripts`, and run only `scripts/deploy.py`. Configs with a Wrangler `build` command are refused, because it would run product code beside the token.
- **Staging cannot reach production.** `--env staging` inherits top-level routes when the env omits them, so a staging deploy requires `env.staging` with its own name and routes.
- **Approval is checked, not assumed.** GitHub creates a missing environment without protection, so the production step reads the environment and refuses to deploy without a required reviewer.
- **Latest wins in production.** The production job's concurrency cancels an older run still waiting for approval; staging deploys queue in order.

## Risks

Staging hosts are public unless the owner adds Cloudflare Access. The build job runs dependency code that could tamper with the artifact, so it can only change what the reviewed main commit already controls. A token scoped wider than the documented permissions widens the blast radius of a deployer compromise.
