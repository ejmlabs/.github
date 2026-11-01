# ejmlabs repository standards

## Overview

Shared repository policy and reusable GitHub workflows for ejm-chess, ejm-cli,
ejm-harness, ejm-ide, ejm-ui and the ejmlabs studio. Consumers pin reviewed
full commit SHAs. Each repository keeps its own semantic version.

The `ejm-ui` owner profile adds its package and publish rules to the same gate.
They are described in [UI owner profile](docs/operations.md#ui-owner-profile).

## Status

This repository contains the shared implementation and caller templates.
Each consumer adopts a revision through its own protected PR. Review the
consumer's installed caller and checks to establish what is active.

Source publication, source releases, package releases, native installers and
website deployments are separate steps. See the
[acceptance limits](docs/operations.md#acceptance-limits).

## Requirements

- Python 3.12 or newer for policy checks and workflow generation, and
  [uv](https://docs.astral.sh/uv/) for the locked ruff and mypy tests.
- GitHub Actions and a plan that supports the required repository protections.
- The pinned tools required by the selected product's Quality gate.

Public dependencies need no private repository token. See
[credentials](docs/operations.md#credentials) and
[quality profiles](docs/operations.md#quality-profiles) for the harness pin and
the product-owned gate commands.

## Quick start

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_workflows.py --check
python3 scripts/sync_agents.py . --check
```

## Usage

Install the consumer PR and draft-release templates described in
[operations](docs/operations.md). A maintainer's same-repo non-draft PR admits
itself. Any other PR waits for a maintainer to mark it Ready or add
`gate:approve`, and fork PRs are not admitted. See
[admission, approval and reruns](docs/operations.md#admission-approval-and-reruns).
Required merge checks are Quality and Repository standards plus one approving
GitHub review.

## Development

Edit `scripts/`, then regenerate workflows with
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
write token. There is no automated model review; maintainers review every
change. Result publication writes a status only for the run that owns it, after
rechecking the live PR head.

## Support

See [Support](SUPPORT.md).

## License

[MIT](LICENSE). Products and bundled assets retain their own notices; see
[Third-party notices](THIRD_PARTY_NOTICES.md).
