## Context

The gate runs `python3 -m unittest discover -s tests -v` and `python3 scripts/build_workflows.py --check` for this repository; that command line lives in the generated `governance.yml` that every repository pins, so it stays as it is. The gate's check job installs uv 0.9.26. `release.py` and `attach.py` use names (`UI_PACKAGES`, `DOCS`, `GitHub`, `semver`) defined by scripts concatenated before them in the generated workflows (ruff F821: 16).

## Decisions

- **Enforce through a unit test.** `tests/test_strict.py` keeps the gate untouched; a missing `uv` is a failure, not a skip.
- **Resolve concatenated names for the checkers only.** Import them under `if TYPE_CHECKING:` from the sibling scripts, so the embedded code behaves exactly as before.
- **Write the lock with uv 0.9.26**, the gate's version (`uvx uv@0.9.26 lock`).
- **Keep the standard-library-only rule.** The privileged job runs no third-party code; the tools run only in the unprivileged check job and locally.
- **No loosening.** Escape hatches are line-scoped and reasoned. There is no explicit `any`, no `@ts-ignore`, `@ts-expect-error` or `@ts-nocheck`, no file-wide or unlimited disable, and no strict flag or rule turned off. A remaining `eslint-disable-next-line <rule> -- <reason>`, `# noqa: <code>` with a reason, `# type: ignore[<code>]` with a reason, `#[expect(<lint>, reason = "...")]` or `# shellcheck disable=<code>` with a reason names one rule and says why.

## Risks

Every embedded script changes, so the regenerated workflows need a full code and security review; consumers keep their pins and see no change until a later pin move. The 145+ unit tests and `build_workflows.py --check` cover behaviour.
