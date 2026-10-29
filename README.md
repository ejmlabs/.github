# ejmlabs repository standards

## Overview

Shared repository policy and reusable GitHub workflows for ejm-cli,
ejm-harness, ejm-ide and the ejmlabs studio. Consumers pin reviewed full
commit SHAs. Each repository keeps its own semantic version.

The source also supports an explicit `ejm-ui` owner profile. Its gate and
metadata rules are described in [UI owner support](docs/operations.md#ui-owner-profile).
This support does not install callers, change settings, or activate UI checks.

## Status

This repository contains the shared implementation and caller templates.
Each consumer adopts a revision through its own protected PR. Review the
consumer's installed caller and checks to establish what is active.

Source publication, source releases, package releases, native installers and
website deployments are separate steps. A passing source check establishes
neither a published artifact nor a deployed site. See the
[acceptance limits](docs/operations.md#acceptance-limits).

## Requirements

- Python 3.11 or newer for policy checks and workflow generation.
- GitHub Actions and a plan that supports the required repository protections.
- The review model key secret named in the trusted workflow for the automated review.
- The pinned tools required by the selected product's Quality gate.

Public dependencies need no private repository token. Keep dependency source
pinned and pass it through the trusted source-preparation job. See
[credentials](docs/operations.md#credentials) and the product contributor guide.

The CLI selector can test a reviewed harness pin and matching lockfile in one
change after checking the pin against protected harness history. Consumers must
adopt that selector through a reviewed workflow revision. See
[CLI dependency selection](docs/operations.md#cli-harness-pin-updates).

## Quick start

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_workflows.py --check
```

## Usage

Install the consumer PR and draft-release templates described in
[operations](docs/operations.md). After inspecting the exact PR commit, a human
maintainer posts these as separate, unedited comments:

```text
/ready FULL_HEAD_SHA
/approve FULL_HEAD_SHA
```

Readiness admits bounded CI and one automated review. Approval records human review;
maintainers may approve their own changes. `/revoke FULL_HEAD_SHA` blocks merge
and cancels active admitted work. New commits require new decisions.

## Development

Edit `scripts/` and `review/`, then regenerate workflows with
`python3 scripts/build_workflows.py`. Review generated changes and validate them
with actionlint. The policy checks use the Python standard library.

## Documentation

- [Repository operations](docs/operations.md)
- [Agent instructions](AGENTS.md)
- [Contribution rules](CONTRIBUTING.md)
- [Release process](RELEASING.md)
- [Security policy](SECURITY.md)

## Contributing

See [Contributing](CONTRIBUTING.md). Keep the shared surface small and adopt
changes in consumers through reviewed pin updates.

## Security

Use [private reporting](SECURITY.md). Product builds receive no model key or
write token. The automated review reads the PR through the API with trusted
configuration and never runs PR code. Its security label blocks merge until a
maintainer removes it. Result publication rechecks live human readiness.

## Support

See [Support](SUPPORT.md).

## License

[MIT](LICENSE). Products and bundled assets retain their own notices; see
[Third-party notices](THIRD_PARTY_NOTICES.md).
