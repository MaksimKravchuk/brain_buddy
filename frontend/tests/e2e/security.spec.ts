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

test.describe("security acceptance", () => {
  test("E2E-SEC-01 cross-user tree isolation in browser-visible lists", async ({ page }, testInfo) => {
    const userA = uniqueEmail("security-a", testInfo);
    const userB = uniqueEmail("security-b", testInfo);
    const treeA = `A Secret Tree ${testInfo.workerIndex}`;
    const treeB = `B Public Tree ${testInfo.workerIndex}`;

    await signupThroughUi(page, userA, await mintInvite());
    await openCrtWorkspace(page, userA);
    await createTreeViaUi(page, treeA);
    await signOut(page);

    await signupThroughUi(page, userB, await mintInvite());
    await openCrtWorkspace(page, userB);
    await createTreeViaUi(page, treeB);
    await page.getByLabel("Tree menu").click();
    await expect(page.getByRole("menu")).not.toContainText(treeA);
    await page.keyboard.press("Escape");
    await signOut(page);

    await loginThroughUi(page, userA);
    await openCrtWorkspace(page, userA);
    await page.getByLabel("Tree menu").click();
    await expect(page.getByRole("menu")).not.toContainText(treeB);
  });
});
