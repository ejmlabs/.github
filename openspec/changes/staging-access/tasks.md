# Tasks

## 1. Shared implementation (this repository)

- [ ] 1.1 `scripts/deploy.py`: the `verify staging` mode that takes the hostname from the reviewed config's one custom-domain staging route, sends the token GET with the two Access header values from the environment and the wrong-secret denial probe (the stored Client ID with a fixed invalid secret), and fails closed on missing secrets, an Access login redirect or challenge on the token request, a non-200, the denial probe answered with the page or a challenge instead of Access's rejection, or an over-cap body, naming the failure kind and never printing a secret
- [ ] 1.2 `scripts/build_workflows.py`: the staging job gains the `Verify the staging build through Access` step after `Deploy the built site to staging`, with `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` from the `staging` environment; regenerate `.github/workflows/deploy-site.yml` in the same commit
- [ ] 1.3 `scripts/standards.py` and `scripts/deploy.py`: the `ejm-agents` profile (deploy paths, `SITES` entry), added only in the PR that follows its site landing
- [ ] 1.4 The owner-run script that stores the token: create or repair the `staging` environment in every site repository and hand `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` to `gh secret set --env staging` on standard input, following the `set_deploy_token.py` pattern, with a `--repository` limit and a dry run, and no value ever echoed
- [ ] 1.5 Tests: the smoke's URL derivation (exactly one custom-domain hostname route), each failure kind of both reads including the gate-absent and probe-challenge kinds, the header-only environment projection, and the workflow step render through the generated workflow check
- [ ] 1.6 Docs: `docs/operations.md` gains the staging Access facts (one application per staging hostname, the owner email and service-token policy, the secret names and where they live, what stays unreachable without the token) and becomes the durable record of the owner decisions (the bot-phase remedy and its pinned Client-ID-header match form, the token lifetime, the allowlist shape, the `media.staging.meetgerry.ai` posture, and the change's remaining open questions); `templates/agents/skills/ejmlabs-cloudflare/references/ci-deploys.md` (staging names, owner setup, failure table row for the smoke) and `verify.md` (how to check staging with the token, the signed-in browser and the denial probe, and its never-add-a-skip-rule line aligned with the same scoping: Access-boundary widening stays forbidden and the one token-scoped bot exception may exist only as the owner's recorded decision) update in the same PR, as the standards rule requires
- [ ] 1.7 CHANGELOG entry when this change archives

## 2. Owner actions (Cloudflare, one by one; no agent runs these)

This change's own files are the durable record: the seven applications and their policies in `design.md`, the service token and its storage in task 1.4, and the owner decisions in `docs/operations.md` once 1.6 lands (the bot-phase remedy and its pinned match form, the token lifetime, the allowlist shape, and the `media.staging.meetgerry.ai` posture). The owner creates the seven Access applications (six now plus `ejm-agents staging` when its site lands), adds the service-token rule to each, creates the one service token, runs the script from 1.4, and verifies in a browser that staging answers the login page when unauthenticated and the page when allowed.

## 3. Per-repo changes (each its own change and PR; nothing lands here)

- [ ] 3.1 `ejmlabs`: the studio-deploy skill's staging checks move from terminal asset bytes to the token headers or the signed-in browser; the security operations doc's staging row notes the Access gate
- [ ] 3.2 `ejm-ui`: the gallery deployment doc's staging note names the Access gate and the smoke step
- [ ] 3.3 `ejm-ide`: the distribution doc's staging row and the website skill note the Access gate; machine `/api/*` readers on staging need the token
- [ ] 3.4 `ejm-harness`: the harness-site skill adds the Access gate note; the registry services stay out (no staging)
- [ ] 3.5 `ejm-calm`: the calm-deploy skill and the AGENTS.md staging row note the Access gate
- [ ] 3.6 `ejm-cli`: the caller moves to the current pin with `secrets: inherit` (its staging deploy currently stops with an empty token); the site skill, contributing doc and developer guide staging facts note the Access gate and that terminal reads need the token
- [ ] 3.7 `ejm-agents`: after its site lands, adopt the shared caller and the `ejm-agents` profile, and keep the v0 plan's `ACCESS_AUD`/team-domain secrets split between its two environments
- [ ] 3.8 `ejm-chess` and the chess proof, capacity and drill Workers: no change (no staging boundary)
- [ ] 3.9 `gerry`: no change; the shared workflow does not smoke its host, and if that ever changes, the least-privilege form is a gerry-scoped token admitted only to the Gerry staging application, not the shared one

## 4. Verification

- [ ] 4.1 Hosted: after the pins move, each site's staging job deploys and the smoke step passes on the live host, the token GET answering 200 and the wrong-secret probe answered by Access's own rejection; the report records the run URL and version id per site
- [ ] 4.2 Hosted: removing the service-token rule from one application fails that site's smoke with the login-redirect message, and restoring it passes again
- [ ] 4.3 Hosted: a site whose `staging` environment lacks the two secrets fails its smoke with the setup message, never deploying blindly
- [ ] 4.4 Hosted: with the owner, remove or mis-scope one application so no Access application serves its hostname; with the skip matching the probe's Client-ID header, the smoke's wrong-secret probe then answers the page instead of Access's rejection and the job fails naming the gate absent, and it passes again when the application is restored
- [ ] 4.5 `python3 scripts/configure_repositories.py --check` proves the `staging` environments' branch policy and reviewers after the script from 1.4 runs; it reads neither secret, so each token's presence is proved instead by the storing script's name-only read-back and the first green smoke in 4.1
