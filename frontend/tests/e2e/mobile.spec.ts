import { expect, test } from "@playwright/test";

import {
  createTreeViaUi,
  loginThroughUi,
  mintInvite,
  openCrtWorkspace,
  signOut,
  signupThroughUi,
  uniqueEmail
} from "./helpers";

test.describe("mobile acceptance", () => {
  test("E2E-MOBILE-01 mobile auth and tree menu smoke", async ({ page }, testInfo) => {
    const email = uniqueEmail("mobile", testInfo);
    const treeName = `Mobile Tree ${testInfo.workerIndex}`;

    await signupThroughUi(page, email, await mintInvite());
    await openCrtWorkspace(page, email);
    await createTreeViaUi(page, treeName);
    await expect(page.locator("body")).toBeVisible();
    await expect(page.getByLabel("Tree menu")).toContainText(treeName);

    await signOut(page);
    await loginThroughUi(page, email);
    await openCrtWorkspace(page, email);
    await expect(page.getByLabel("Tree menu")).toContainText(treeName);
  });
});
