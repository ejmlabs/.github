## Context

The shared standards run from the pinned revision against the admitted tree, so the UI repository can only publish after a shared revision allows it. Publishing is irreversible, so the rule is an allowlist that names the packages, the registry settings, the shipped assets and the workflow file.

## Decisions

- **Name the public set.** `UI_PUBLIC` lists the four packages. A package is public only when it is in that set, has no `private` key, and its `publishConfig` equals `{"access": "public", "provenance": true}`. `"private": false` is refused, so intent is never implied by a false value. Everything else, including the root, must still be `private: true`.
- **Match what ships exactly.** Parsing `files`, `main`, `bin` and the other fields for forbidden paths was bypassed twice by npm spellings (re-including `!!` entries, `directories.bin`, case-folded targets). The rule is an exact allowlist instead. For each public package, the fields that decide what npm packs or what the package is called (`name`, `files`, `main`, `types`, `typings`, `exports`, `bin`, `browser`, `module`, `directories`, `man`, `bundleDependencies`, `bundledDependencies`, `workspaces`) are serialized, present ones only, in that order, as compact JSON, and their SHA-256 must equal the recorded digest of the reviewed manifest. A deviation in any field, a reordered or added `files` entry, a case variant, or a field that is present but not in the reviewed manifest changes the digest and is refused. The reviewed tokens `files` ship only `assets/fonts`, `assets/brand` and `assets/icons` from `assets`, so brand logos and artwork stay out of the tarball. Any change to what a public package ships needs a new shared revision. `provenance` must still be exactly `true`, because the digest does not cover `publishConfig`, which keeps its own exact check.
- **Pin the workflow by content.** `publish.yml` holds the OIDC publishing permission. It is accepted only in the `ejm-ui` profile, only as a regular file, and only when its SHA-256 equals `UI_PUBLISH_SHA256`, the hash of the reviewed file. Changing the workflow needs a new shared revision. A symlink is not accepted and fails as an unexpected workflow.
- **No new inputs.** The checks use data already in the tree and add no dependency or token.

## Risks

The hash blocks silent edits but not a weak reviewed workflow; review covers what it runs. Content copied into an allowed folder, or into a file the reviewed `files` list ships, is not a path matter; review and the UI repository's pack proof cover it.
