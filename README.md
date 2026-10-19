# ejmlabs repository standards

## Overview

Shared repository policy and reusable GitHub workflows for ejm-cli, ejm-harness, ejm-ide, and the ejmlabs studio. Each consumer pins a reviewed full commit SHA. Versions remain independent.

## Status

This is the standards implementation. Activation and live run evidence are tracked in each adoption PR and [the operations guide](docs/operations.md). Installing these files does not publish a product or prove that every security surface has been tested.

Shared PR #14 was held after its AI jobs returned incomplete reviews that the older result validator accepted. Earlier studio PR #3 and harness PR #12 runs exposed the same defect. Fresh product reviews now include both pinned workflow sources. See [the completion guard and rollout limits](docs/readiness.md#review-completeness-guard). A successful job does not establish a complete review.

## Requirements

Python 3.11 or newer for policy tests and generation. GitHub Team supports protection of the current private repositories. Hosted checks use pinned Node 24, Rust 1.99.1, and tool versions. Consumers need OPENAI_API_KEY for AI review. IDE hosted Quality remains blocked until the harness is public under the owner's access policy. CLI dependency access and setup follow their separate reviewed rollout, including [PR #11](https://github.com/ejmlabs/.github/pull/11), whose shared changes remain pending.

CLI setup-hook validation is prepared for a separate execution change. See
[the staged adoption process](docs/operations.md#cli-setup-hook-adoption).

## Quick start

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_workflows.py --check
```

## Usage

Use the consumer PR and draft-release workflow templates described in [operations](docs/operations.md). A human maintainer posts `/ready FULL_HEAD_SHA`, then `/approve FULL_HEAD_SHA` after review. Both commands bind to the exact PR head. `/revoke FULL_HEAD_SHA` blocks merge and cancels active admitted work. New commits need new commands. Self approval is allowed.

## Development

Edit scripts in `scripts/`, prompts in `review/`, and then regenerate with `python3 scripts/build_workflows.py`. Review the generated workflows and validate them with actionlint. Tests cover identity, exact-head decisions, replay, stale results, SemVer, symlink policy, and model output. No third-party Python library is needed. Scripts are embedded into the reusable workflows so private consumers need no token to download shared code.

For every caller pin change, including this repository's own callers, export
the exact old and new shared implementations with
`scripts/export_review_context.py` before review. See
[static workflow review data](docs/operations.md#static-workflow-review-data).

## Documentation

- [Operations and bootstrap](docs/operations.md)
- [Rollout evidence and remaining acceptance](docs/readiness.md)
- [Contribution rules](CONTRIBUTING.md)
- [Release process](RELEASING.md)
- [Security policy](SECURITY.md)

## Contributing

See [Contributing](CONTRIBUTING.md). Keep the shared surface small and update consumers through reviewed pin changes.

## Security

Use [private reporting](SECURITY.md). A PR has no access to model credentials or a write token during its builds. AI works on static source in separate read-only jobs with trusted configuration. Result publication uses a separate job and validates live readiness again.

## Support

See [Support](SUPPORT.md).

## License

[MIT](LICENSE). Products and bundled assets keep their own notices; see [Third-party notices](THIRD_PARTY_NOTICES.md).
