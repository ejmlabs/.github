# Design

## The profile carries `deploy=true`

The Repository standards check cannot pass for `ejm-agents` while its tree carries a credential-using local deploy workflow. The credential-free lint (safe triggers, read-only top-level permissions, no job permissions, no environments or secrets) rejects the local copy outright, and every profile fails closed on it: a minimal profile without `deploy` fails the lint, and there is no pass state in the shared standards for a local site deploy.

The only state the shared standards accept for a Cloudflare site is the canonical `deploy.yml` caller with `secrets: inherit`, which requires a profile with `deploy=true` and a `scripts/deploy.py` recipe. So this enrollment mirrors `ejm-calm` (commit `7b605ee`): profile with `deploy=true`, the deploy recipe, and the consumer swap from the local deploy copy to the canonical caller in its re-pin commit.

## Why no spec deltas

The admission list, the profile, the deploy recipe and the settings names are data for a repository that the existing `repository-standards`, `pr-gate` and `site-deploys` requirements already govern generically ("the profile's built-in commands", "the canonical `deploy.yml` caller", the quality table). Adding a repository adds no rule, so no spec text changes.

## PR 2 keeps no green path yet

`ejm-agents` PR 2 turns the site into a Worker with Durable Objects and container-based runs and carries a local, credential-using deploy workflow that builds a container image. The shared deploy has no shape for it: a `deploy.py` recipe cannot express Wrangler-assigned containers, and the Worker `main` (`src/worker/index.ts`) does not live inside a declared source path. No profile makes PR 2 green today: with `deploy=true` it fails the caller comparison; without it, the local deploy fails the credential-free lint. Resolving this needs either a shared deploy growth for containers or a reviewed policy opt-out for local product deploys, both of which are owner decisions above this enrollment, and neither belongs in the smallest admission change.

## The deploy is re-declared with the reviewed Access verification

The re-admission re-declares the deploy source as the reviewed version (the repository's deploy workflow at `540575729abbd8ff63113cd7cfa6f28118e64107`): each deploy job verifies its deployed host through Cloudflare Access with the environment's `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` service-token secrets and requires HTTP 200 with an HTML body, so any challenge or other answer fails the job. Right after deploy and before that check, the job sets the Worker's `ALLOWED_SERVICE_IDENTITIES`, derived at deploy time as the service-token Client-Id suffixed `.access` (the exact value the Worker's allowlist matches) and piped to `wrangler secret put` on standard input: never a preset value, never an argument, never echoed. `scripts/deploy.py` carries the verification for the sites that declare it (`ACCESS_VERIFY`), takes each environment's host from the reviewed Wrangler config routes, and the generated `deploy-site.yml` runs it for those sites only, so the reviewed checks survive the consumer's swap from the local deploy to the canonical caller. The canonical caller pins in this repository's own `pr.yml` and `release.yml` advance with this change to the branch head.
