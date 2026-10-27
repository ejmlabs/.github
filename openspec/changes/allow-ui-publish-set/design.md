## Context

The shared standards run from the pinned revision against the admitted tree, so the UI repository can only publish after a shared revision allows it. Publishing is irreversible, so the rule is an allowlist that names the packages, the registry settings, the shipped assets and the workflow file.

## Decisions

- **Name the public set.** `UI_PUBLIC` lists the four packages. A package is public only when it is in that set, has no `private` key, and its `publishConfig` equals `{"access": "public", "provenance": true}`. `"private": false` is refused, so intent is never implied by a false value. Everything else, including the root, must still be `private: true`.
- **Bound the tokens tarball.** The owner excludes brand artwork. The tokens `files` list is required and normalized: a leading `./` and trailing `/` are removed, `..`, backslashes, `.` and empty entries are refused, `!` exclusions are ignored because they only narrow, and any entry whose first segment is `assets` must equal or sit under `assets/fonts`, `assets/brand` or `assets/icons` with no glob characters. An entry whose first segment is a glob is refused because it could match `assets`.
- **Pin the workflow by content.** `publish.yml` holds the OIDC publishing permission. It is accepted only in the `ejm-ui` profile, only as a regular file, and only when its SHA-256 equals `UI_PUBLISH_SHA256`, the hash of the reviewed file. Changing the workflow needs a new shared revision. A symlink is not accepted and fails as an unexpected workflow.
- **No new inputs.** The checks use data already in the tree and add no dependency or token.

## Risks

The hash blocks silent edits but not a weak reviewed workflow; review covers what it runs. `files` is only one npm inclusion mechanism; the UI repository's pack proof checks the real tarball.
