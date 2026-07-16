import { expect, test } from "@playwright/test";

test("Playwright local harness is wired", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveTitle(/Brain Buddy/i);
});
