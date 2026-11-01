# Design

## Inventory: every staging hostname the repositories name

Sources: each repository's Wrangler config and deploy caller at its `main` head, read on 2026-11-01 (base `d7d7f03` here). Live values were checked with unauthenticated GETs from this box on 2026-11-01.

| Staging Worker | Staging hostname | Production Worker | Production host | Repository and config | Deployed by | Access today |
| --- | --- | --- | --- | --- | --- | --- |
| `ejmlabs-staging` | `staging.ejmlabs.com` | `ejmlabs` | `ejmlabs.com` | `ejmlabs`, `site/wrangler.jsonc` `env.staging` | shared `deploy-site.yml` staging job | public (200) |
| `ejmlabs-ui-staging` | `staging.ui.ejmlabs.com` | `ejmlabs-ui` | `ui.ejmlabs.com` | `ejm-ui`, `apps/gallery/wrangler.jsonc` `env.staging` | shared `deploy-site.yml` staging job | public (200) |
| `ejmlabs-ide-staging` | `staging.ide.ejmlabs.com` | `ejmlabs-ide` | `ide.ejmlabs.com` | `ejm-ide`, `distribution/wrangler.jsonc` `env.staging` | shared `deploy-site.yml` staging job | public (200) |
| `ejmlabs-harness-staging` | `staging.harness.ejmlabs.com` | `ejmlabs-harness` | `harness.ejmlabs.com` | `ejm-harness`, `site/wrangler.jsonc` `env.staging` | shared `deploy-site.yml` staging job | public (200) |
| `calm-staging` | `staging.calm.ejmlabs.com` | `calm` | `calm.ejmlabs.com` | `ejm-calm`, `wrangler.jsonc` `env.staging` | shared `deploy-site.yml` staging job | public (200) |
| `ejmlabs-cli-staging` | `cli-staging.ejmlabs.com` | `ejmlabs-cli` | `cli.ejmlabs.com` | `ejm-cli`, `site/wrangler.jsonc` `env.staging` | shared `deploy-site.yml` staging job, caller predates `secrets: inherit` so the token stays empty and the deploy stops | none yet, host not reachable (no TLS endpoint) |
| `agents-staging` | `staging.agents.ejmlabs.com` | `agents` | `agents.ejmlabs.com` | `ejm-agents` (site lands through its open PR), `wrangler.jsonc` `env.staging` | its local `deploy.yml` until the `ejm-agents` profile exists | none yet, site not deployed; the v0 approvals already plan both hostnames |
| `gerry-marketing-staging` | `staging.meetgerry.ai` (Worker routes marketing paths with `zone_name`; `staging.gerry.ejmlabs.com` is a retiring alias, not a route) | `gerry-coming-soon` | `meetgerry.ai` and `www.meetgerry.ai` | `gerry`, `marketing/wrangler.staging.jsonc` | `gerry` staging.yml (Google Cloud Run behind the tunnel), Worker runs marketing paths only | behind Access today (application `Gerry staging`: named employee, Google login, device MFA) |

Surfaces that never serve staging and stay out of scope: `ejmlabs-preview` (an env of `ejmlabs` with no routes, held unpublished until its own Access policy exists), the `ejm-registry` and `ejm-registry-auth` Worker services (no staging), the chess proof, capacity and recovery drill Workers (transient, no custom domains, `workers.dev` off), `gerry-workspace-hosting` (wildcard `*.apps.meetgerry.ai` Worker for the workspace origin), the retiring `staging.gerry.ejmlabs.com` alias (a leftover proxied record plus the zone's redirect rule; it 301s to `staging.meetgerry.ai`, whose `Gerry staging` application answers), `media.staging.gerry.ejmlabs.com` (a leftover DNS-only record; open question), and `media.staging.meetgerry.ai`, the staging LiveKit host gerry's terraform declares, DNS-only by necessity because media and TURN cannot use the proxy, live and public today with LiveKit's own auth in front, whose boundary posture (behind Cloudflare, or public by design) is an owner decision recorded in the report. The ten signed-webhook Access bypass applications on gerry's staging paths keep their current per-path scope (ten, three of them path prefixes). Every config sets `workers_dev` and `preview_urls` false, so no `*.workers.dev` staging name is real.

Who hits staging: the pipeline's staging job (deploy through the Cloudflare API, no host requests today); the maintainer who checks staging before releasing production (headed browser, per the deploy skills); agents doing pre-release verify (headed browser, plus terminal asset-byte comparisons that curl works only while the host answers unauthenticated); the smoke check this change adds (service-token headers); and, on gerry, provider webhooks through the existing per-path bypasses plus a GCP-side readiness job that never touches Access.

## One application per staging hostname

Every staging boundary this inventory names is exactly one live hostname: gerry's staging Worker routes marketing paths of one hostname, and its retired `staging.gerry.ejmlabs.com` is a leftover alias, not a second boundary. Cloudflare permits one application to name several destinations and leading wildcards such as `*.example.com` can appear in them, but a wildcard in the middle (`staging.*.ejmlabs.com`) is not a supported form and no site needs a whole-zone match, so the rule collapses to one application per staging hostname. One application per hostname preserves per-worker revocation and keeps each application's audience tag separate, which the agents site verifies against from its Worker (`ACCESS_AUD` in the v0 plan).

Applications to create (owner action, listed in the report):

- `ejmlabs staging` for `staging.ejmlabs.com`
- `ejm-ui staging` for `staging.ui.ejmlabs.com`
- `ejm-ide staging` for `staging.ide.ejmlabs.com`
- `ejm-harness staging` for `staging.harness.ejmlabs.com`
- `ejm-calm staging` for `staging.calm.ejmlabs.com`
- `ejm-cli staging` for `cli-staging.ejmlabs.com`
- `ejm-agents staging` for `staging.agents.ejmlabs.com`, when that site lands (the v0 plan already names it and needs its audience tag as a Worker secret)
- `ejm-chess` has no staging host and `ejm-chess` production is already behind the whole-host application the owner set up.

Policy for every new application: action **Allow**, **Include** the owner's email `everett@ejmlabs.com` and the one smoke service token; **everyone else denied** by the absence of any other rule. Login method: One-time PIN, which is the pattern the agents v0 approvals recorded (no identity provider needed). The gerry staging application keeps its Google login, device MFA and named employee list unchanged; no repository change proposes touching it, and if a shared-workflow smoke of its host was ever wanted, its least-privilege form is a gerry-scoped token admitted only to that application, not the shared one.

## One service token for CI, held only as environment secrets

One Access service token serves every staging smoke check; per-token-per-application duplication buys nothing and doubles the rotation work. The owner creates it (Zero Trust, Access, Service Tokens), keeps the Client ID and the one-time Client Secret, and no repository text ever records either value.

- Name it for the job it holds, for example `ejm-ci-staging-smoke`. The owner picks the session or credential lifetime; the report asks for that choice.
- Each new staging application's policy carries an Include rule for this service token, alongside the owner's email.
- Storage: the Owner-run script (task 1.4) creates or repairs the `staging` environment in every site repository with the existing main-only branch policy and hands both values to `gh secret set --env staging` on standard input, the same pattern `set_deploy_token.py` already uses. That script stays separate rather than gaining a service-token mode because its flow verifies the deploy token against Cloudflare, a step with no service-token equivalent, and its production-safe defaults should stay untouched. Secrets are GitHub environment secrets named `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`, never repository or organization variables or Actions-level secrets. They are written to `staging` and not to `production`, because production hosts keep their public posture.
- The headers the pipeline then sends are `CF-Access-Client-Id` and `CF-Access-Client-Secret`. The projection never falls back to reading the values from anywhere else, and no log line, error message, artifact or test prints them. The value never enters a prompt; the script's error output names a field, never a value.

What stays unreachable to CI without the token: every path on a staging host, hashed assets included, answers the Access login instead of the page, and unauthenticated CI reads of staging are impossible by design. The deploy itself needs no host reach; Wrangler talks to the Cloudflare API. The per-repo terminal checks that compare staging asset bytes with `dist/` stop working and move to the headed browser or the token headers (task 3 items).

## Smoke check in the shared staging job

`scripts/deploy.py` gains a `verify staging` mode for the staging job, after `wrangler deploy` succeeds and inside the same job so the job fails rather than leaving an unverified deploy.

- The mode re-reads the reviewed Wrangler config (already checked out and byte-compared) and takes the staging hostname from `env.staging.routes`: it accepts exactly one custom-domain entry whose pattern is one hostname with no scheme, no path and no wildcard. Anything else fails with a message that names the config field, so gerry's path-pattern routes and future multi-route configs are caught rather than silently skipped.
- It sends GET `https://<staging-host>/` twice (fixed 15 second timeout, no redirect following, body cap bounded like the other reads in this script, `MAX_API_BYTES`): one request with the two headers taken only from `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`, which must answer 200 with an HTML content type, and one request with no credentials, which must be denied by Access. The two together, not the 200 alone, are what a green smoke means: a host with no Access application answers both requests the same way and fails the unauthenticated assertion, and the token 200 alone would say nothing about the gate.
- Fail, telling the operator which of these happened, with no environment values printed: the two secrets missing (message points at the owner setup in `docs/operations.md`), a redirect to the Access login on the token request (the token was absent, wrong, or its policy rule is missing from this application), a Cloudflare challenge on the token request (`cf-mitigated` present; see the bot phase section below), a non-200 on the token request, the unauthenticated request answered with the page instead of a denial (the application is missing, deleted, or does not cover the hostname), or a response body over the cap.
- Fail closed everywhere: there is no flag that skips the check, no environment variable that switches it off, and no widening of the Access boundary to make it green: no bypass application, no allow-list entry besides the owner's email rule and the one smoke service token, no wider path scope, and no exception that matches requests without the smoke token's credentials. If a site's staging cannot pass, the owner fixes the Access or bot-phase setup and records the decision; the pipeline never self-silences.
- The production job gains nothing: production hosts stay public and their checks remain the headed-browser live checks the deploy skills already describe.

## The zone's bot phase is a design input

The zone's Super Bot Fight Mode challenges automated clients on HTML routes: the 2026-10-26 account snapshot records `sbfm_definitely_automated: managed_challenge`, [verify.md](../../../templates/agents/skills/ejmlabs-cloudflare/references/verify.md) documents curl and headless reads of the ejmlabs HTML routes answering the 403 "Just a moment..." page and says not to count that as a pass or a deploy failure, and a 2026-11-01 re-probe reproduced it (default curl answered 403 `cf-mitigated: challenge` on every staging root where a browser User-Agent answers 200; `relay.ejmlabs.com` answers its own 401 because the zone's existing "Skip SBFM for machine clients" rule exempts it). A GitHub runner's Python GET is exactly the class that phase challenges. The remedy the plan adopts is owner-only and Access-boundary scoped: a bot-management skip matching requests that present the smoke service token's credentials, mirroring the zone's existing machine-client skip, decided and recorded in `docs/operations.md` when applied (owner actions in the report). Until it is applied, a challenge on the token request fails the smoke and the deploy stays blocked; a challenge is never a pass and never a skip. If the owner decides against the exception, or it does not clear the challenge, the follow-up change moves the smoke target to a per-site path the zone serves machine clients without a challenge (the verify.md precedent of `robots.txt` and hashed `/assets/*`), trading page verification for build-served verification.

Config parsing reuses the existing `site_config` reader; the smoke adds no new dependency and no second URL source. The `ejm-agents` staging Worker sits behind the same gate, and the v0 plan's server-side JWT audience check continues to run after Access at the edge, so a green smoke says the build is served through the gate and the gate is present.

## Profile wiring for `ejm-agents`

The v0 approvals order the profile after the site lands. `scripts/standards.py` adds an `ejm-agents` profile with `deploy=True` (which adds it to `SITE_DEPLOY`), and `scripts/deploy.py` adds its `SITES` entry: commands from the product's own build, `wrangler.jsonc`, and the paths the deploy needs, including the Worker source and `container/` because Wrangler builds its image from that source during deploy. `standards.py` accepts the caller only in the canonical form, so `ejm-agents`' local workflow is replaced by the shared caller in the same PR that moves its pins. Nothing in this change hides the containers permission the deploy token needs for that site; the v0 approvals already ask the owner to widen the token for containers and verify the dashboard label, and the smoke step changes nothing about the token.

## What this change deliberately does not do

- No Cloudflare action by the pipeline or an agent. Every Access application, rule, service token and secret add is an owner action listed one by one in the report.
- No production Access. Production hosts stay public; chess's existing whole-host application and gerry's staging boundary stay as they are.
- No per-repo implementation here. Each repository's docs and caller fixes list in `tasks.md` and land one PR per repository.
- No bypass for webhooks or unauthenticated traffic. gerry's per-path webhook bypasses keep their current per-path scope; nothing admits an unauthenticated request to a staging host; the one bot-phase exception is the owner's recorded, token-scoped decision in the bot phase section above.

## Limits recorded

- The Cloudflare state in this design comes from repository files at the listed commits, the account snapshot of 2026-10-26 (`/workspace/cloudflare-review/applied-2026-10-26/`), gerry's Access documentation, and unauthenticated GET probes on 2026-11-01. No Access or API listing was read with credentials in this task, so application IDs stay the historical record's names and the owner confirms live IDs in the dashboard.
- The zone's bot phase is recorded above as a design input: it challenges automated GETs of HTML routes today, the owner's token-scoped skip decision remediates it inside the Access boundary, and whether a token-carrying GET answers 200 under it is unverified until the owner's first token-carrying check or the first live smoke.
