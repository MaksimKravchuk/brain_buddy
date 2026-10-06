import { expect, test } from "../allure.fixtures";

import { backendUrl, createTaskViaApi, loginThroughUi, logoutSession, mintInvite, signupThroughUi, uniqueEmail } from "./gtdHelpers";

test.describe("mobile acceptance", () => {
  test("024-FR-013 CLI approval stays usable at 390px and denial is explicit", async ({ page, request }, testInfo) => {
    await signupThroughUi(page, uniqueEmail("cli-mobile", testInfo), await mintInvite());
    const started = await request.post(`${backendUrl}/api/auth/device/start`, { data: {} });
    expect(started.status()).toBe(200);
    const grant = await started.json();
    await test.step("open the code on mobile, verify layout and touch target sizes", async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`/cli/authorize#user_code=${grant.user_code}`);
      const approve = page.getByRole("button", { name: "Approve access" });
      await expect(approve).toBeEnabled();
      const size = await approve.boundingBox();
      expect(size?.height).toBeGreaterThanOrEqual(44);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
      await testInfo.attach("cli-mobile-approval-390", { body: await page.screenshot(), contentType: "image/png" });
    });
    await test.step("deny without issuing any CLI session and announce recovery", async () => {
      await page.getByRole("button", { name: "Deny access" }).click();
      await expect(page.getByRole("status")).toContainText("Access denied");
      await testInfo.attach("cli-mobile-denied-390", { body: await page.screenshot(), contentType: "image/png" });
      const denied = await request.post(`${backendUrl}/api/auth/device/token`, { data: { device_code: grant.device_code } });
      expect(denied.status()).toBe(403);
      expect((await denied.json()).detail.code).toBe("authorization_denied");
    });
  });
  test("E2E-MOBILE-02 planned workflows remain visible and honestly gated at 390px", async ({ page }, testInfo) => {
    await signupThroughUi(page, uniqueEmail("mobile-planned", testInfo), await mintInvite());
    await page.setViewportSize({ width: 390, height: 844 });

    await test.step("open the real GTD navigation drawer", async () => {
      await page.goto("/");
      await page.getByRole("button", { name: "Open task navigation" }).click();
      await expect(page.getByRole("dialog", { name: "Task navigation" })).toBeVisible();
    });
    await test.step("verify planned workflows are honestly marked Soon and the legacy CRT link is absent", async () => {
      const navigation = page.getByRole("navigation", { name: "Task navigation" });
      await expect(navigation.getByRole("button", { name: "Weekly review — Coming soon" })).toBeDisabled();
      await expect(navigation.getByRole("button", { name: "Thinking Mode — Coming soon" })).toBeDisabled();
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
