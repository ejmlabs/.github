# Tasks

## 1. Shared implementation (this repository)

- [ ] 1.1 `scripts/deploy.py`: the `verify staging` mode that takes the hostname from the reviewed config's one custom-domain staging route, sends the two Access header values from the environment, and fails closed on missing secrets, an Access login redirect, a challenge, a non-200 or an over-cap body, naming the failure kind and never printing a secret
- [ ] 1.2 `scripts/build_workflows.py`: the staging job gains the `Verify the staging build through Access` step after `Deploy the built site to staging`, with `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` from the `staging` environment; regenerate `.github/workflows/deploy-site.yml` in the same commit
- [ ] 1.3 `scripts/standards.py` and `scripts/deploy.py`: the `ejm-agents` profile (deploy paths, `SITES` entry), added only in the PR that follows its site landing
- [ ] 1.4 The owner-run script that stores the token: create or repair the `staging` environment in every site repository and hand `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` to `gh secret set --env staging` on standard input, following the `set_deploy_token.py` pattern, with a `--repository` limit and a dry run, and no value ever echoed
- [ ] 1.5 Tests: the smoke's URL derivation (exactly one custom-domain hostname route), each failure kind, the header-only environment projection, and the workflow step render through the generated workflow check
- [ ] 1.6 Docs: `docs/operations.md` gains the staging Access facts (one application per staging boundary, the owner email and service-token policy, the secret names and where they live, what stays unreachable without the token); `templates/agents/skills/ejmlabs-cloudflare/references/ci-deploys.md` (staging names, owner setup, failure table row for the smoke) and `verify.md` (how to check staging with the token or the signed-in browser) update in the same PR, as the standards rule requires
- [ ] 1.7 CHANGELOG entry when this change archives

## 2. Owner actions (Cloudflare, one by one; no agent runs these)

Listed in `/workspace/firstmate/data/staging-access/report.md` with the exact hostnames, policy lines and secret names. The owner creates the seven Access applications (six now plus `ejm-agents staging` when its site lands), adds the service-token rule to each, creates the one service token, runs the script from 1.4, and verifies in a browser that staging answers the login page when unauthenticated and the page when allowed.

## 3. Per-repo changes (each its own change and PR; nothing lands here)

- [ ] 3.1 `ejmlabs`: the studio-deploy skill's staging checks move from terminal asset bytes to the token headers or the signed-in browser; the security operations doc's staging row notes the Access gate
- [ ] 3.2 `ejm-ui`: the gallery deployment doc's staging note names the Access gate and the smoke step
- [ ] 3.3 `ejm-ide`: the distribution doc's staging row and the website skill note the Access gate; machine `/api/*` readers on staging need the token
- [ ] 3.4 `ejm-harness`: the harness-site skill adds the Access gate note; the registry services stay out (no staging)
- [ ] 3.5 `ejm-calm`: the calm-deploy skill and the AGENTS.md staging row note the Access gate
- [ ] 3.6 `ejm-cli`: the caller moves to the current pin with `secrets: inherit` (its staging deploy currently stops with an empty token); the site skill, contributing doc and developer guide staging facts note the Access gate and that terminal reads need the token
- [ ] 3.7 `ejm-agents`: after its site lands, adopt the shared caller and the `ejm-agents` profile, and keep the v0 plan's `ACCESS_AUD`/team-domain secrets split between its two environments
- [ ] 3.8 `ejm-chess` and the chess proof, capacity and drill Workers: no change (no staging boundary)
- [ ] 3.9 `gerry`: no change required; optionally add the smoke service token to the Gerry staging application if the shared workflow ever smokes it

## 4. Verification

- [ ] 4.1 Hosted: after the pins move, each site's staging job deploys and the smoke step passes on the live host; the report records the run URL and version id per site
- [ ] 4.2 Hosted: removing the service-token rule from one application fails that site's smoke with the login-redirect message, and restoring it passes again
- [ ] 4.3 Hosted: a site whose `staging` environment lacks the two secrets fails its smoke with the setup message, never deploying blindly
- [ ] 4.4 `python3 scripts/configure_repositories.py --check` passes for every site repository after the script from 1.4 runs
