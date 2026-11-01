## Why

The shared standards repository needs static security analysis and a reusable workflow for later consumer adoption.

## What changes

- Generate a reusable CodeQL workflow with pinned actions and security-extended queries.
- Generate a local caller that scans Python and Actions on main and weekly.
- Accept that exact caller in this repository's standards and preserve the scoped CodeQL action allowlist in repository configuration.

## Impact

The workflow generator, action pin manifest, standards, repository configuration, tests, changelog and operations guide change. Consumer callers are a separate task.
