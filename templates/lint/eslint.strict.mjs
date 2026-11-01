// Shared strict lint layer. Synced from ejmlabs/.github templates/lint; edit it there.
import js from "@eslint/js";
import comments from "@eslint-community/eslint-plugin-eslint-comments/configs";
import globals from "globals";
import tseslint from "typescript-eslint";

const HTML_SINKS = ["innerHTML", "outerHTML", "insertAdjacentHTML"].map((property) => ({
  property,
  message: "Render text, not HTML: use textContent or a framework binding.",
}));

export default tseslint.config(
  { ignores: ["**/node_modules/**", "**/dist/**", "**/build/**", "**/coverage/**", "**/target/**", "**/.wrangler/**", "**/*.d.ts"] },
  { linterOptions: { reportUnusedDisableDirectives: "error", reportUnusedInlineConfigs: "error" } },
  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  comments.recommended,
  {
    languageOptions: {
      globals: { ...globals.es2024 },
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      "@eslint-community/eslint-comments/require-description": ["error", { ignore: [] }],
      "@eslint-community/eslint-comments/no-unlimited-disable": "error",
      "@typescript-eslint/ban-ts-comment": ["error", { "ts-check": false, "ts-expect-error": true, "ts-ignore": true, "ts-nocheck": true }],
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/switch-exhaustiveness-check": "error",
      "no-eval": "error",
      "no-new-func": "error",
      "no-restricted-properties": ["error", ...HTML_SINKS],
    },
  },
  // Typed rules are off for plain JavaScript, so the untyped implied-eval rule takes over.
  { files: ["**/*.{js,mjs,cjs}"], extends: [tseslint.configs.disableTypeChecked], rules: { "no-implied-eval": "error" } },
  {
    files: ["**/*.{test,spec}.{ts,tsx,js,mjs,cjs}", "**/{test,tests,__tests__}/**"],
    rules: {
      "@typescript-eslint/unbound-method": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/no-non-null-asserted-optional-chain": "off",
    },
  },
);
