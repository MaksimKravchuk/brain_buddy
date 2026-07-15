import { expect, test } from "@playwright/test";

test("local app serves the React root", async ({ page }) => {
  await page.goto("/login");
  await expect(page.locator("#root")).toBeAttached();
});
