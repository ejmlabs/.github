## Context

The shared gate runs each profile's own commands. Only the `ejm-ui` profile ran size steps; the `ejmlabs` profile runs `scripts/check.mjs` and the site tests, whose content belongs to that repository. The standards check holds no bundle-byte or dependency-count rule.

## Decisions

- **Delete the steps, add no replacement.** The two `ejm-ui` size commands are removed and the synthetic gate test expects the shorter sequence.
- **Load time is measured in each product repository.** Each product carries its own `npm run perf`, which needs a browser and so does not belong in the credential-free shared gate. Anything that adds whole seconds to first paint on a normal connection is flagged there, by measurement rather than a byte cap. This repository adds no load-time step.
- **Keep safety bounds.** Admission budgets, review-context byte limits, PR size bounds, the standards file-read limit (8,000,000 bytes) and the owned-manifest count protect the gate and reviewer from hostile or runaway input. They are not download-size or dependency-count caps and stay.

## Risks

A product repository can now ship a large bundle without a shared check failing. That is intended; review and each product's perf measurement cover load time.
