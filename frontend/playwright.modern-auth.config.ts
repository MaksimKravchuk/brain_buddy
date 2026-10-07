import { defineConfig, devices } from "@playwright/test";

const fixtureHost = new URL(process.env.BRAIN_BUDDY_MODERN_E2E_ORIGIN ?? "https://brainbuddy-e2e.example.com:9443").hostname;
const runtimeProxy = process.env.HTTPS_PROXY ?? process.env.HTTP_PROXY;

// A separate real-app TLS fixture is required: optional auth is deliberately
// disabled in the legacy Compose stack, which continues to run unchanged.
export default defineConfig({
  testDir: "./tests",
  testMatch: /(?:modern-auth|e2e\/account)\.spec\.ts/,
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
    baseURL: process.env.BRAIN_BUDDY_MODERN_E2E_ORIGIN,
    // This generated certificate and hostname belong only to the TLS fixture.
    ignoreHTTPSErrors: true,
    // Preserve managed outbound routing; only this loopback fixture bypasses it.
    ...(runtimeProxy ? { proxy: { server: runtimeProxy, bypass: `${fixtureHost},127.0.0.1,localhost` } } : {}),
    launchOptions: {
      args: [`--host-resolver-rules=MAP ${fixtureHost} 127.0.0.1`]
    },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure"
  }
});
