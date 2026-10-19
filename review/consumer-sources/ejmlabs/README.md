# Studio checker review context

These are exact source copies from public, protected Studio `main` at
[`d943a119ebcce92931d1b3d46c85d287b6cac408`](https://github.com/ejmlabs/ejmlabs/commit/d943a119ebcce92931d1b3d46c85d287b6cac408).
The [manifest](manifest.json) records the source repository, commit, tree,
path, Git mode, blob, byte count and SHA-256 for each copy. The six copied files
total 36,954 bytes. They retain Studio's
[rights notice](d943a119ebcce92931d1b3d46c85d287b6cac408/LICENSE);
this repository's MIT license does not relicense these snapshots.

## Scope

The shared Studio recipe changes only its first command:

```text
node design-kit/scripts/check-kit.mjs
```

becomes:

```text
node scripts/check.mjs
```

The copied [entry](d943a119ebcce92931d1b3d46c85d287b6cac408/scripts/check.mjs)
imports the same unchanged
[checker](d943a119ebcce92931d1b3d46c85d287b6cac408/design-kit/scripts/check-kit.mjs).
The checker resolves its paths from its own `import.meta.url`, uses Node's
standard library, and invokes these unchanged child commands with `--check`:

- [build-ui.mjs](d943a119ebcce92931d1b3d46c85d287b6cac408/design-kit/scripts/build-ui.mjs)
- [build-web.mjs](d943a119ebcce92931d1b3d46c85d287b6cac408/design-kit/scripts/build-web.mjs)
- [build-motifs.mjs](d943a119ebcce92931d1b3d46c85d287b6cac408/design-kit/scripts/build-motifs.mjs)

The entry neither changes the working directory nor catches errors. The
following site test and build commands stay unchanged in the shared recipe.

## Use and limits

Treat these ordinary, nonexecutable files as read-only review data. Do not
import, execute or package them as an implementation. Studio owns the active
checker and its migration to shared UI contracts. No workflow loads this
directory as code, and the canonical `.github/review-context` remains separate.

The checker also reads Studio's catalogs, pages and generated styles. The
generators read theme data, CSS parts and existing output files. Those data and
output files remain in the owning repository at the pinned commit; they are
outside this bounded source fixture. These copies support static assessment
of the entry and call path. They do not form a runnable Studio checkout or
establish hosted Quality, asset consistency or site publication.

For a later entry change, replace this snapshot with the smallest relevant
public source set from the reviewed owner revision. Preserve its rights
notice, compare each byte and Git mode with the owning Git objects, update the
manifest and remove the old snapshot. Human decisions and complete reviews
still apply to the new shared PR head.
