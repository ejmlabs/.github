# ejmlabs repository standards

## Overview

Shared repository policy and reusable GitHub workflows for ejm-cli, ejm-harness, ejm-ide, and the ejmlabs studio. Each consumer pins a reviewed full commit SHA. Versions remain independent.

## Status

This is the standards implementation. Activation and live run evidence are tracked in each adoption PR and [the operations guide](docs/operations.md). Installing these files does not publish a product or prove that every security surface has been tested.

## Requirements

Python 3.11 or newer for policy tests and generation. GitHub Team supports protection of the current private repositories. Hosted checks use pinned Node 24, Rust 1.99.1, and tool versions. Consumers need OPENAI_API_KEY for AI review. IDE hosted Quality remains blocked until the harness is public under the owner's access policy.

CLI private harness review and checkout are authorized. The owner attested that EJM_HARNESS_TOKEN is an expiring fine-grained token with Contents read for ejmlabs/ejm-harness only, and hosted CLI source preparation succeeded. That attestation is not independent metadata verification. Reviewed harness API adoption, the immutable source pin and the complete consumer gate remain separate requirements. See [Credentials](docs/operations.md#credentials).

The prepared CLI quality hook calls the product setup action for relay build
and browser-test prerequisites. Keep it in draft until the trusted CLI baseline
contains the reviewed setup action, retaining its current working harness pin.
Adopt the new harness APIs after the setup hook can run. See
[CLI setup and adoption](docs/operations.md#cli-quality-prerequisites).

## Quick start

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_workflows.py --check
```

## Usage

Use the consumer PR and draft-release workflow templates described in [operations](docs/operations.md). A human maintainer posts `/ready FULL_HEAD_SHA`, then `/approve FULL_HEAD_SHA` after review. Both commands bind to the exact PR head. `/revoke FULL_HEAD_SHA` blocks merge and cancels active admitted work. New commits need new commands. Self approval is allowed.

## Development

Edit scripts in `scripts/`, prompts in `review/`, and then regenerate with `python3 scripts/build_workflows.py`. Review the generated workflows and validate them with actionlint. Tests cover identity, exact-head decisions, replay, stale results, SemVer, symlink policy, and model output. No third-party Python library is needed. Scripts are embedded into the reusable workflows so private consumers need no token to download shared code.

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
