import { defineConfig, devices } from "@playwright/test";

const composeE2E = process.env.PLAYWRIGHT_COMPOSE === "1";
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? (composeE2E ? "http://127.0.0.1:8080" : "http://127.0.0.1:5173");

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: composeE2E
    ? [["list"], ["allure-playwright", { resultsDir: "allure-results/playwright", detail: true }]]
    : process.env.CI
      ? "github"
      : "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    trace: "on-first-retry"
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: composeE2E
    ? undefined
    : {
        command: "npm run dev -- --host 127.0.0.1",
        url: "http://127.0.0.1:5173/login",
        reuseExistingServer: !process.env.CI,
        timeout: 120_000
      }
});
