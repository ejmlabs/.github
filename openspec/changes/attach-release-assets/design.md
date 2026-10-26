## Context

Build jobs run project code (`cargo` build scripts, package installs), so they hold `contents: read` and no secrets. The job that writes to the release must not run that code. The tag is immutable, so a build or smoke failure found after the tag exists burns the version.

## Decisions

- **Two reusable workflows, one script.** `verify-build.yml` needs only `actions: read` and runs before the draft step. `attach-assets.yml` needs `contents: write` and `actions: read`, plus `id-token` and `attestations: write` for the optional attestation step only. GitHub validates nested-job permissions statically against the caller, so the gate cannot share a file with the write job without forcing write permission on the gate call. Both embed `scripts/attach.py`, as the existing shared workflows embed their scripts.
- **Order by composition.** A product `release.yml` runs `verify-build`, then Draft release (`needs`), then `attach-assets` (`needs`). The build runs as its own workflow on `workflow_dispatch` or a push on main; its run id is passed in. Draft release already requires the commit to be the current main head, so the tag lands on the verified commit.
- **Run binding.** A run is accepted only when its workflow file is the named build workflow, its event is `workflow_dispatch` or `push`, its branch is `main` in this repository, its `head_sha` equals the release commit, and it completed with success. Attach also requires the `v<version>` tag to be a lightweight ref to that commit and exactly one draft release for the tag, so a published release is never modified.
- **Digests.** The build uploads its files plus `build-sha256.txt` (`sha256sum` format). Attach downloads the run's artifacts with the pinned download action only after the run checks pass, requires the file set to equal the manifest set, rejects links and unsafe names, recomputes every SHA-256, and fails on any difference. A built file may not replace an existing release asset. The release's `SHA256SUMS` is read from the draft, the new lines are appended, and it is uploaded last.
- **Attestations are optional** and described as build provenance, not code signing.

## Risks

A build workflow that signs its own manifest proves nothing beyond transit integrity; the commit, workflow and trigger bindings are the substantive checks. The workflow run id is caller input, so attach re-verifies everything the gate checked.
