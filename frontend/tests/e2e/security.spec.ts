import { expect, test } from "../allure.fixtures";

import { createTaskViaApi, loginThroughUi, logoutSession, mintInvite, signupThroughUi, uniqueEmail } from "./gtdHelpers";

test.describe("security acceptance", () => {
  test("E2E-SEC-01 cross-user tasks stay isolated in browser-visible projections", async ({ page }, testInfo) => {
    const userA = uniqueEmail("security-a", testInfo);
    const userB = uniqueEmail("security-b", testInfo);

    await test.step("create user A's private task", async () => {
      await signupThroughUi(page, userA, await mintInvite());
      await createTaskViaApi(page, "A private task", { state: "next" });
      await logoutSession(page);
    });
    await test.step("prove user B sees only user B data", async () => {
      await signupThroughUi(page, userB, await mintInvite());
      await createTaskViaApi(page, "B private task", { state: "next" });
      await page.goto("/tasks/next");
      await expect(page.getByText("B private task")).toBeVisible();
      await expect(page.getByText("A private task")).toHaveCount(0);
      await logoutSession(page);
    });
    await test.step("prove user A cannot see user B data after relogin", async () => {
      await loginThroughUi(page, userA);
      await page.goto("/tasks/next");
      await expect(page.getByText("A private task")).toBeVisible();
      await expect(page.getByText("B private task")).toHaveCount(0);
    });
  });
});