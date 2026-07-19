import { expect, test } from "../allure.fixtures";

import {
  backendUrl,
  createUserViaApi,
  loginThroughUi,
  logoutSession,
  mintInvite,
  openTaskWorkspace,
  password,
  signupThroughUi,
  uniqueEmail
} from "./gtdHelpers";

test.describe("auth acceptance", () => {
  test("E2E-AUTH-01 invite signup creates a session and reaches the canonical GTD workspace", async ({ page }, testInfo) => {
    const email = uniqueEmail("auth-signup", testInfo);
    await test.step("sign up through the real invite-gated UI", async () => {
      await signupThroughUi(page, email, await mintInvite());
      await openTaskWorkspace(page, email);
    });
    await test.step("reload preserves the authenticated GTD session", async () => {
      await page.reload();
      await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
      await expect(page.getByLabel(email)).toBeVisible();
    });
  });

  test("E2E-AUTH-02 used invite and invalid login fail without creating access", async ({ page }, testInfo) => {
    const email = uniqueEmail("auth-invalid", testInfo);
    const invite = await mintInvite();
    await signupThroughUi(page, email, invite);
    await logoutSession(page);

    await test.step("reject reuse of a consumed invite", async () => {
      await page.goto("/signup");
      await page.getByLabel("Email").fill(uniqueEmail("auth-reuse", testInfo));
      await page.getByLabel("Password").fill(password);
      await page.getByLabel("Invite code").fill(invite);
      await page.getByRole("button", { name: "Create account" }).click();
      await expect(page.getByText("Invite code is invalid or already used.")).toBeVisible();
    });

    await test.step("reject an invalid password without exposing the workspace", async () => {
      await page.goto("/login");
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(`${password}-wrong`);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByText("Invalid email or password.")).toBeVisible();
      await expect(page.getByRole("heading", { name: "Next actions" })).toHaveCount(0);
    });
  });

  test("E2E-AUTH-03 protected route redirects anonymous users and preserves intended destination", async ({ page }, testInfo) => {
    const email = await createUserViaApi(page.request, testInfo, "auth-redirect");
    await logoutSession(page);
    await test.step("redirect an anonymous deep link to login", async () => {
      await page.goto("/tasks/inbox");
      await expect(page).toHaveURL(/\/login$/);
    });
    await test.step("return to the intended GTD projection after login", async () => {
      await loginThroughUi(page, email);
      await expect(page).toHaveURL(/\/tasks\/inbox$/);
      await expect(page.getByRole("heading", { name: "Inbox" })).toBeVisible();
      const session = await page.request.get(`${backendUrl}/api/auth/me`);
      if (!session.ok()) {
        throw new Error(`authenticated session check failed with ${session.status()} ${await session.text()}`);
      }
    });
  });
});