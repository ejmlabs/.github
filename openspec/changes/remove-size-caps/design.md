## Context

The shared gate runs each profile's own commands. Only the `ejm-ui` profile ran size steps; the `ejmlabs` profile runs `scripts/check.mjs` and the site tests, whose content belongs to that repository. The standards check holds no bundle-byte or dependency-count rule.

## Decisions

- **Delete the steps, add no replacement.** The two `ejm-ui` size commands are removed and the synthetic gate test expects the shorter sequence.
- **Load time is measured in each product repository.** Each product carries its own `npm run perf`, which needs a browser and so does not belong in the credential-free shared gate. Anything that adds whole seconds to first paint on a normal connection is flagged there, by measurement rather than a byte cap. This repository adds no load-time step.
- **Keep safety bounds.** Admission budgets, review-context byte limits, PR size bounds, the standards file-read limit (8,000,000 bytes) and the owned-manifest count protect the gate and reviewer from hostile or runaway input. They are not download-size or dependency-count caps and stay.

- **The commands belong to each product.** The shared gate only runs the commands each profile names; what `npm run check` or `scripts/check.mjs` covers is owned by that product. `ejm-ui` and `ejmlabs` remove their own budgets and size scripts in their own changes.
- **Refresh the reviewed `@ejm/ssg` digest.** `UI_PACKING_SHA256['packages/ssg']` and its test fixture move to the cap-free manifest (no `./budget` export) at `ejm-ui` revision b0602a06266e24dd927ba47b136a55e9f264d23b, so the standard does not lock in the removed export once `@ejm/ssg` is public. `ejm-ui` pins this revision in the same PR as its cap removal; the digest is unchanged from the previously reviewed value because the packing fields it covers did not change, and `ejm-ui` main before its cap removal (1caee5894fc0e37e455d599457864b588b1791bf) still fails on it through the `./budget` export.

## Risks

A product repository can now ship a large bundle without a shared check failing. That is intended; review and each product's perf measurement cover load time.
