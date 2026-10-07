import { defineConfig, devices } from "@playwright/test";

// A separate real-app TLS fixture is required: optional auth is deliberately
// disabled in the legacy Compose stack, which continues to run unchanged.
export default defineConfig({
  testDir: "./tests",
  testMatch: "modern-auth.spec.ts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: [
    [process.env.CI ? "github" : "list"],
    ["html", { outputFolder: "playwright-report/modern-auth", open: "never" }],
    ["allure-playwright", { resultsDir: "allure-results/playwright", detail: false }]
  ],
  outputDir: "test-results/playwright-modern-auth",
  use: {
    ...devices["Desktop Chrome"],
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure"
  }
});
