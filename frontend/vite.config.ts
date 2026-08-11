import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";

// Stryker runs the suite thousands of times, once per mutant, inside a sandbox
// copy of the project. Allure evidence is dropped for those runs, exactly as
// ADR-0004 does for the backend campaign: a mutant run is not a product test,
// so its results must never reach the Allure report, and the reporter's setup
// module resolves through an absolute path that does not exist under the
// sandbox root anyway.
const underMutationTesting = process.env.STRYKER_MUTATOR_WORKER !== undefined;

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true
      }
    }
  },
  preview: {
    port: 4173,
    strictPort: true
  },
  test: {
    environment: "jsdom",
    globals: true,
    reporters: underMutationTesting
      ? ["default"]
      : [
          "default",
          [
            "allure-vitest/reporter",
            { resultsDir: "allure-results/vitest", reportMatchers: false }
          ]
        ],
    css: true,
    setupFiles: underMutationTesting
      ? ["./src/setupTests.ts"]
      : ["allure-vitest/setup", "./src/setupTests.ts", "./src/test/allureTaxonomy.ts"],
    include: ["src/**/*.test.{ts,tsx}", "src/**/*.spec.{ts,tsx}"],
    exclude: ["tests/**"],
    coverage: {
      provider: "istanbul",
      // json-summary feeds scripts/validate_coverage_floor.py.
      reporter: ["text", "lcov", "json-summary"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/test/allureTaxonomy.ts"],
      // Kept just under frontend/coverage-floor.json, which is the gate CI
      // enforces: a local `npm run test:coverage` should fail on the same
      // regression rather than passing and leaving CI to find it.
      thresholds: {
        statements: 98,
        branches: 97,
        functions: 98,
        lines: 98
      }
    }
  }
});
