# Remove the AI review from the PR gate

## Why
The owner asked to turn off the AI PR reviewer: it adds too much friction and not enough value. In the last 14 days it was red in 86 gate runs; 43 were real findings and 43 were the reviewer failing to finish (provider credits, capacity, a second pass timing out). It is a required status in all six gate repositories, so every failure blocks a merge.

## What changes
- The six gate repositories stop requiring the "AI review" status. This happens first, so no repository ever requires a status the gate has stopped publishing.
- The shared gate stops running the AI review job and stops publishing the "AI review" status.
- The security-concern label and its maintainer override are removed, because they exist only to gate the AI review.
- Callers stop passing the model key; the model key secret and the prepaid provider account are retired.
- The repository settings script and the standards check stop listing "AI review".
- The four remaining statuses stay enforced for administrators, and re-enabling any model review goes to the security review first.

## Impact
- Required statuses go from five to four: Human readiness, Maintainer approval, Quality, Repository standards.
- Affected: `.github` (scripts/governance.py, scripts/configure_repositories.py, scripts/standards.py, scripts/build_workflows.py, .github/workflows/governance.yml, docs/operations.md, tests), and the callers in ejm-ui, ejm-cli, ejm-ide, ejm-harness and ejmlabs.
- The open label-trigger plan (tighten-label-override) becomes moot and is dropped.
