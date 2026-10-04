import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["coverage", "dist", "allure-results", "playwright-report", "test-results"]
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.strict],
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // React Compiler diagnostic ("Compilation Skipped: existing memoization could not be
      // preserved"); this app does not run the compiler, so revisit only if it is adopted.
      "react-hooks/preserve-manual-memoization": "off",
      "@typescript-eslint/no-invalid-void-type": "off",
      "react-refresh/only-export-components": ["error", { allowConstantExport: true }]
    }
  }
);
