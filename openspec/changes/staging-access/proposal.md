# Proposal

## Why

The owner asked on 2026-11-01 that every ejmlabs staging domain sit behind Cloudflare Access. Today five site staging hosts are public and serve the latest main to anyone who asks: `staging.ejmlabs.com`, `staging.ui.ejmlabs.com`, `staging.ide.ejmlabs.com`, `staging.harness.ejmlabs.com` and `staging.calm.ejmlabs.com` (each returned 200 to an unauthenticated GET on 2026-11-01). `gerry`'s staging is already behind Access, `ejm-cli`'s staging cannot deploy because its caller predates `secrets: inherit`, and `ejm-agents`' staging lands with its site. The shared deploy pipeline has no smoke check: once Access fronts these hosts, a post-deploy verify that hits them needs the Access service-token headers, and the repository holds no place to keep those headers except GitHub environment secrets. The owner decided the open calls on 2026-11-01 (relay card `7d5ac842232dd313`): the plan is approved, the bot-phase remedy is the token-scoped Client-ID-header skip, `media.staging.meetgerry.ai` goes behind Access, and the allowlist and lifetimes keep the recorded defaults (the v0 pattern; a long-lived token and 24-hour sessions). He also ordered, the same hour, that `ejm-agents` sits behind Access always, production `agents.ejmlabs.com` and staging alike, and created that application himself, so this change plans the token path and the verify checks for both agents hosts.

## What Changes

- Access apps: one Access application per staging hostname. The policy, decided 2026-11-01, allows the owner's email (`everett@ejmlabs.com`) with One-time PIN and the one smoke service token; nobody else. The owner has already created the agents application covering `agents.ejmlabs.com` and `staging.agents.ejmlabs.com`, and remains to create the five live-host staging applications, the `ejm-cli` one, and a gerry-employee application for `media.staging.meetgerry.ai`, decided behind Access. The existing `Gerry staging` application keeps its Google login with device MFA and its per-path webhook bypasses.
- One CI service token: its Client ID and Client Secret live only as the GitHub environment secrets `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` in each site repository's `staging` environment, written by a new owner-run script and never printed, logged or committed. The owner created the token (`ejm-agents-deploy-checks`) and set both secrets in the ejm-agents `staging` and `production` environments himself; the same token's values reach the other site repositories through the script, and a gated production host's job reads them from its own environment.
- Smoke check: after a staging deploy, the staging job requests the deployed hostname twice: with the service-token headers, which must answer 200 with an HTML body, and with a deliberately wrong secret (the stored Client ID, an invalid Client Secret), which Access itself must reject on a gated host, so a staging host with no Access application (the page answering instead) fails the job instead of passing it. The URL is read from the reviewed Wrangler config's staging route. The zone's bot phase challenges automated clients on HTML routes, and the owner's decided remedy, recorded when applied, is a bot-management skip matching the smoke token's Client-ID header, value or presence, on the staging hostnames only; until then a challenge fails the smoke. The agents deploy workflow's post-deploy checks carry the same headers on both hosts, and no bot-phase skip covers the production host: a challenge on a production check fails the check.
- Staging stays public-to-all no longer: **BREAKING**, staging serves only the owner and the smoke service token, and the agents production host joins it behind the owner's application. Players, testers and outside machines stop seeing staging updates.
- Profiles: `ejm-agents` joins the shared deploy when its site lands, with its config path and paths declared like the other sites.
- Per-repo changes: each site repository updates its deploy skill and docs so live staging checks either use the owner's signed-in browser or carry the service-token headers; `ejm-cli` also moves its pins and adopts `secrets: inherit`; `ejm-agents` pins the same requirement on both agents hosts for its deploy workflow's smoke checks.

## Capabilities

### New Capabilities

- `staging-access`: the Access applications, the smoke service token and its secret storage, the always-gated agents hosts, and the rule that Access on the gated hosts is never weakened to make a check pass.

### Modified Capabilities

- `site-deploys`: the staging job verifies the served staging build through Access after the deploy and refuses to run without the service token, and a deploy job whose production host is gated verifies the same way from its own environment.

## Impact

`scripts/deploy.py` (smoke mode), `scripts/build_workflows.py` (the staging smoke step), `scripts/standards.py` (the `ejm-agents` when it lands), `scripts/set_deploy_token.py` unchanged, one new owner script for the service token, `.github/workflows/deploy-site.yml` regenerated, `docs/operations.md`, `templates/agents/skills/ejmlabs-cloudflare/references/ci-deploys.md` and `verify.md`. Per-repo changes are listed in `tasks.md` and each lands in its own repository. Cloudflare Access setup is an owner action and is never performed by an agent or the pipeline.

Anything that reaches staging only by its hostname keeps working after a human Access login. Anything that expects anonymous machine reads of staging (the terminal asset-bytes checks in the per-repo deploy skills) needs the service-token headers or the owner's browser, and this change names that for each repository.
