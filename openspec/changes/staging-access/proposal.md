# Proposal

## Why

The owner asked on 2026-11-01 that every ejmlabs staging domain sit behind Cloudflare Access. Today five site staging hosts are public and serve the latest main to anyone who asks: `staging.ejmlabs.com`, `staging.ui.ejmlabs.com`, `staging.ide.ejmlabs.com`, `staging.harness.ejmlabs.com` and `staging.calm.ejmlabs.com` (each returned 200 to an unauthenticated GET on 2026-11-01). `gerry`'s staging is already behind Access, `ejm-cli`'s staging cannot deploy because its caller predates `secrets: inherit`, and `ejm-agents`' staging lands with its site. The shared deploy pipeline has no smoke check: once Access fronts these hosts, a post-deploy verify that hits them needs the Access service-token headers, and the repository holds no place to keep those headers except GitHub environment secrets.

## What Changes

- Access apps: one Access application per staging hostname. The policy allows the owner's email (`everett@ejmlabs.com`) with One-time PIN and the one smoke service token; nobody else. The existing `Gerry staging` application keeps its Google login with device MFA and its per-path webhook bypasses.
- One CI service token: its Client ID and Client Secret live only as the GitHub environment secrets `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` in each site repository's `staging` environment, written by a new owner-run script and never printed, logged or committed.
- Smoke check: after a staging deploy, the staging job requests the deployed hostname twice: with the service-token headers, which must answer 200 with an HTML body, and unauthenticated, which must be denied, so a missing Access application fails the job instead of passing it. The URL is read from the reviewed Wrangler config's staging route. The zone's bot phase challenges automated clients on HTML routes, and the plan's one remedy is an owner decision recorded when applied: a bot-management skip scoped to the smoke token's requests, mirroring the zone's existing machine-client skip; until then a challenge fails the smoke.
- Staging stays public-to-all no longer: **BREAKING**, staging serves only the owner and the smoke service token. Players, testers and outside machines stop seeing staging updates.
- Profiles: `ejm-agents` joins the shared deploy when its site lands, with its config path and paths declared like the other sites.
- Per-repo changes: each site repository updates its deploy skill and docs so live staging checks either use the owner's signed-in browser or carry the service-token headers; `ejm-cli` also moves its pins and adopts `secrets: inherit`.

## Capabilities

### New Capabilities

- `staging-access`: the Access applications, the smoke service token and its secret storage, and the rule that staging Access is never weakened to make a check pass.

### Modified Capabilities

- `site-deploys`: the staging job verifies the served staging build through Access after the deploy and refuses to run without the service token.

## Impact

`scripts/deploy.py` (smoke mode), `scripts/build_workflows.py` (the staging smoke step), `scripts/standards.py` (the `ejm-agents` when it lands), `scripts/set_deploy_token.py` unchanged, one new owner script for the service token, `.github/workflows/deploy-site.yml` regenerated, `docs/operations.md`, `templates/agents/skills/ejmlabs-cloudflare/references/ci-deploys.md` and `verify.md`. Per-repo changes are listed in `tasks.md` and each lands in its own repository. Cloudflare Access setup is an owner action and is never performed by an agent or the pipeline.

Anything that reaches staging only by its hostname keeps working after a human Access login. Anything that expects anonymous machine reads of staging (the terminal asset-bytes checks in the per-repo deploy skills) needs the service-token headers or the owner's browser, and this change names that for each repository.
