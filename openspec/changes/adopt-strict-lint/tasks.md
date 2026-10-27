## 1. Tooling
- [x] 1.1 Root `pyproject.toml`, `uv.lock` (uv 0.9.26), `ruff.toml` extending the shared layer, `[tool.mypy]` strict.
- [x] 1.2 `tests/test_strict.py` runs `uv run --locked --group dev ruff check .` and `uv run --locked --group dev mypy`.

## 2. Fixes
- [x] 2.1 ruff: 709 (ANN 526, E701 45, F821 16, quotes 20, imports 11); apply safe fixes first.
- [x] 2.2 mypy: 949 (no-untyped-call 485, no-untyped-def 310, attr-defined 58, union-attr 19); annotate the scripts first, the tests follow.
- [x] 2.3 `TYPE_CHECKING` imports for names supplied by concatenation.
- [x] 2.4 `python3 scripts/build_workflows.py` to regenerate.

## 3. Verification
- [x] 3.1 `python3 -m unittest discover -s tests -v`, `python3 scripts/build_workflows.py --check`, and the standards check of this tree at the current pin pass.
- [x] 3.2 `git diff` of the generated workflows shows only the embedded script bytes changing.
