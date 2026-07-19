import { expect, test } from "../allure.fixtures";

import { createTaskViaApi, loginThroughUi, logoutSession, mintInvite, signupThroughUi, uniqueEmail } from "./gtdHelpers";

test.describe("mobile acceptance", () => {
  test("E2E-MOBILE-02 planned workflows remain visible, disabled, and non-navigable at 390px", async ({ page }, testInfo) => {
    await signupThroughUi(page, uniqueEmail("mobile-planned", testInfo), await mintInvite());
    await page.setViewportSize({ width: 390, height: 844 });

    await test.step("open the real GTD navigation drawer", async () => {
      await page.goto("/");
      await page.getByRole("button", { name: "Open task navigation" }).click();
      await expect(page.getByRole("dialog", { name: "Task navigation" })).toBeVisible();
    });
    await test.step("verify planned workflows are disabled and the legacy CRT link is absent", async () => {
      const navigation = page.getByRole("navigation", { name: "Task navigation" });
      await expect(navigation.getByRole("button", { name: "Weekly review — Coming later" })).toBeDisabled();
      await expect(navigation.getByRole("button", { name: "Think with CRT — Coming later" })).toBeDisabled();
      await expect(navigation.getByRole("link", { name: /CRT.*legacy/i })).toHaveCount(0);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (overflow > 0) throw new Error(`390px planned-workflow drawer overflowed by ${overflow}px`);
    });
  });

  test("E2E-MOBILE-01 mobile auth, navigation, and task persistence smoke", async ({ page }, testInfo) => {
    const email = uniqueEmail("mobile", testInfo);
    await signupThroughUi(page, email, await mintInvite());
    await createTaskViaApi(page, "Mobile persisted task", { state: "next" });
    await page.setViewportSize({ width: 390, height: 844 });

    await test.step("render the persisted task and accessible drawer without horizontal overflow", async () => {
      await page.goto("/");
      await expect(page.getByText("Mobile persisted task")).toBeVisible();
      await page.getByRole("button", { name: "Open task navigation" }).click();
      await expect(page.getByRole("dialog", { name: "Task navigation" })).toContainText("Inbox");
      await page.getByRole("button", { name: "Close task navigation" }).last().click();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (overflow > 0) throw new Error(`390px task workspace overflowed by ${overflow}px`);
    });
    await test.step("relogin and recover the same API-backed task", async () => {
      await logoutSession(page);
      await loginThroughUi(page, email);
      await page.goto("/tasks/next");
      await expect(page.getByText("Mobile persisted task")).toBeVisible();
    });
  });
});