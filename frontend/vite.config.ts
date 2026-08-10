import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";

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
    reporters: [
      "default",
      [
        "allure-vitest/reporter",
        { resultsDir: "allure-results/vitest", reportMatchers: false }
      ]
    ],
    css: true,
    setupFiles: [
      "allure-vitest/setup",
      "./src/setupTests.ts",
      "./src/test/allureTaxonomy.ts"
    ],
    include: ["src/**/*.test.{ts,tsx}", "src/**/*.spec.{ts,tsx}"],
    exclude: ["tests/**"],
    coverage: {
      provider: "istanbul",
      // json-summary feeds scripts/validate_coverage_floor.py.
      reporter: ["text", "lcov", "json-summary"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/test/allureTaxonomy.ts"],
      thresholds: {
        statements: 95,
        branches: 95,
        functions: 95,
        lines: 95
      }
    }
  }
});
