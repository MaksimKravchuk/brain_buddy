import { defineConfig, devices } from "@playwright/test";

const isCI = Boolean(process.env.CI);
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5173";
const usesExternalComposeStack = Boolean(process.env.BRAIN_BUDDY_E2E_COMPOSE_PROJECT);

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: 1,
  reporter: [
    [isCI ? "github" : "list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["allure-playwright", { resultsDir: "allure-results/playwright" }]
  ],
  outputDir: "test-results/playwright",
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    trace: isCI ? "retain-on-failure" : "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure"
  },
  projects: [
    {
      name: "chromium",
      testMatch: /(?:e2e\/(?!mobile).*|native-tasks-voice-brain-dump\.compose|claude-design-shell)\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] }
    },
    {
      name: "mobile-chromium",
      testMatch: /e2e\/mobile\.spec\.ts/,
      use: { ...devices["Pixel 5"] }
    }
  ],
  webServer: usesExternalComposeStack
    ? undefined
    : {
        command: "npm run dev -- --host 127.0.0.1",
        url: `${baseURL}/login`,
        reuseExistingServer: !isCI,
        timeout: 120_000
      }
});
