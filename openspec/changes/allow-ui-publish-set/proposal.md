## Why

The owner decided to publish four UI packages (`@ejm/tokens`, `@ejm/core`, `@ejm/ui` and `@ejm/ssg`) to the public npm registry with provenance, and to keep brand artwork out of the published files. The repository standards require every UI npm package to be private and refuse any workflow other than the canonical consumers, so the UI release change cannot pass them.

## What Changes

- Let exactly `packages/core`, `packages/ssg`, `packages/tokens` and `packages/ui` omit `private`, only with `publishConfig` equal to `{"access": "public", "provenance": true}` and the scoped license unchanged.
- Require each public package's name and every field that decides what npm packs (`files`, `main`, `types`, `exports`, `bin`, `browser`, `directories`, the pack and install lifecycle scripts and the rest) to equal the reviewed values exactly, so any change to a public package's packing manifest needs a new shared revision and brand logos and artwork stay out of the tokens tarball.
- Keep the root package and every other UI package private.
- In `ejm-ui` only, allow one extra workflow, `publish.yml`, when its SHA-256 equals the reviewed file's recorded hash; any other content, a symlink, or another repository is refused.
- Regenerate the shared workflows that embed `scripts/standards.py`.

## Capabilities

### New Capabilities

- `ui-publish`: which UI packages may be public, what they may ship, and which publish workflow is accepted.

## Impact

`scripts/standards.py`, the generated shared workflows, `tests/test_ui_standards.py`, `tests/test_standards.py`, `CHANGELOG.md` and `docs/operations.md`. The UI repository adopts the rule through a pin update to the revision that carries this change.
