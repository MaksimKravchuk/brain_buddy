import { expect, test } from "../allure.fixtures";

import {
  createTreeViaUi,
  deleteCurrentTreeViaUi,
  openCrtWorkspace,
  renameCurrentTreeViaUi,
  signOut,
  signupThroughUi,
  switchTreeViaUi,
  mintInvite,
  uniqueEmail
} from "./helpers";

test.describe("tree CRUD acceptance", () => {
  test("E2E-TREE-01 create, rename, switch, delete, and persist tree list", async ({ page }, testInfo) => {
    const email = uniqueEmail("tree-crud", testInfo);
    await signupThroughUi(page, email, await mintInvite());
    await openCrtWorkspace(page, email);

    const primaryName = `E2E Primary Tree ${testInfo.workerIndex}`;
    const renamedName = `E2E Renamed Tree ${testInfo.workerIndex}`;
    const secondaryName = `E2E Secondary Tree ${testInfo.workerIndex}`;

    await createTreeViaUi(page, primaryName);
    await expect(page.getByTestId("tree-canvas")).toBeVisible();

    await renameCurrentTreeViaUi(page, renamedName);
    await createTreeViaUi(page, secondaryName);
    await switchTreeViaUi(page, renamedName);
    await switchTreeViaUi(page, secondaryName);
    await deleteCurrentTreeViaUi(page, secondaryName);

    await page.reload();
    await expect(page.getByLabel("Tree menu")).toContainText(renamedName);
    await page.getByLabel("Tree menu").click();
    await expect(page.getByRole("menu")).not.toContainText(secondaryName);
    await page.keyboard.press("Escape");

    await signOut(page);
  });
});
