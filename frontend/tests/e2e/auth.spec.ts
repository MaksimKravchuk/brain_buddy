import { expect, test } from "../allure.fixtures";

import {
  createUserViaApi,
  backendUrl,
  loginThroughUi,
  mintInvite,
  openCrtWorkspace,
  password,
  signOut,
  signupThroughUi,
  uniqueEmail
} from "./helpers";

test.describe("auth acceptance", () => {
  test("E2E-AUTH-01 invite signup creates a session and reaches protected workspace", async ({ page }, testInfo) => {
    const email = uniqueEmail("auth-signup", testInfo);
    const invite = await mintInvite();

    await signupThroughUi(page, email, invite);
    await openCrtWorkspace(page, email);

    await page.reload();
    await expect(page.getByText(email)).toBeVisible();
    await expect(page.getByLabel("Tree menu")).toBeVisible();
  });

  test("E2E-AUTH-02 used invite and invalid login fail without creating access", async ({ page }, testInfo) => {
    const email = uniqueEmail("auth-invalid", testInfo);
    const invite = await mintInvite();

    await signupThroughUi(page, email, invite);
    await signOut(page);

    await page.goto("/signup");
    await page.getByLabel("Email").fill(uniqueEmail("auth-reuse", testInfo));
    await page.getByLabel("Password").fill(password);
    await page.getByLabel("Invite code").fill(invite);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Invite code is invalid or already used.")).toBeVisible();
    await expect(page).toHaveURL(/\/signup$/);

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(`${password}-wrong`);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("Invalid email or password.")).toBeVisible();
    await expect(page.getByLabel("Tree menu")).toBeHidden();
  });

  test("E2E-AUTH-03 protected route redirects anonymous users and preserves intended destination", async ({ page }, testInfo) => {
    const email = await createUserViaApi(page.request, testInfo, "auth-redirect");
    await page.request.post(`${backendUrl}/api/auth/logout`);

    await page.goto("/crt");
    await expect(page).toHaveURL(/\/login$/);

    await loginThroughUi(page, email);
    await expect(page).toHaveURL(/\/crt$/);
    await expect(page.getByLabel("Tree menu")).toBeVisible();
  });
});
