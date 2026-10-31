# Strict lint layer (draft for ejmlabs/.github templates/lint)

| File | Copied to | Used by |
|---|---|---|
| `eslint.strict.mjs` | beside each repository's `eslint.config.mjs` | ESLint flat config: `import strict from "./eslint.strict.mjs"; export default [...strict, /* repo globs */];` |
| `ruff.strict.toml` | repository root (or the Python project root) | `extend = "ruff.strict.toml"` in the repository ruff config |
| `.shellcheckrc` | repository root | picked up by shellcheck automatically |
| `cargo-lints.toml` | not copied; its tables are pasted into Cargo.toml | `scripts/sync_lint.py --check` compares the tables |

TypeScript needs no file here: every TypeScript project extends the published `@tsconfig/strictest@2.0.8` package and adds only its environment options (target, lib, module, jsx, types, paths).
mypy needs no file here: `[tool.mypy] strict = true` and `warn_unreachable = true`, inline per repository (mypy has no config inheritance).

Pinned tools (exact versions, all at least two weeks old on 2026-10-27):
eslint 10.13.0, @eslint/js 10.0.1, typescript-eslint 8.71.2, typescript 6.0.3 (typed lint needs < 6.1), @tsconfig/strictest 2.0.8, globals 17.13.0, @eslint-community/eslint-plugin-eslint-comments 4.8.1, eslint-plugin-react-hooks 7.1.1 (React repositories), ruff 0.17.0, mypy 2.4.0, shellcheck-py 0.11.0.1 (ShellCheck 0.11.0), Rust 1.99.1 clippy.
