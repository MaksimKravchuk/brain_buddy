import { expect, test } from "../allure.fixtures";

import {
  createNodeViaApi,
  createTreeViaApi,
  createUserViaApi,
  openCrtWorkspace
} from "./helpers";

test.describe("versioning acceptance", () => {
  test("E2E-VERSION-01 create snapshot, modify tree, restore snapshot", async ({ page }, testInfo) => {
    const email = await createUserViaApi(page.request, testInfo, "versioning");
    const tree = await createTreeViaApi(page.request, `E2E Version Tree ${testInfo.workerIndex}`);
    await createNodeViaApi(page.request, tree.id, "Baseline Cause", "parent", { x: 0, y: 0 });

    await openCrtWorkspace(page, email);
    await page.getByRole("button", { name: "Versions" }).click();
    await page.getByLabel("Snapshot label").fill("baseline");
    await page.getByLabel("Notes").fill("before edit");
    await page.getByRole("button", { name: "Capture snapshot" }).click();
    await expect(page.getByText("Snapshot captured")).toBeVisible();
    await expect(page.getByText("baseline", { exact: true })).toBeVisible();

    await page.getByText("Baseline Cause").click();
    await page.getByRole("button", { name: "Node", exact: true }).click();
    await page.getByLabel("Node label").fill("Edited Cause");
    await page.getByLabel("Node label").press("Enter");
    await expect(page.getByText("Edited Cause")).toBeVisible();

    await page.getByRole("button", { name: "Versions" }).click();
    await page.getByLabel("Snapshot label").fill("edited");
    await page.getByRole("button", { name: "Capture snapshot" }).click();
    await expect(page.getByText("edited", { exact: true })).toBeVisible();

    const baselineRow = page.locator("li", { hasText: "baseline" }).first();
    await baselineRow.getByRole("button", { name: "Restore" }).click();
    await expect(page.getByRole("heading", { name: "Restore snapshot" })).toBeVisible();
    await page.getByRole("button", { name: "Restore" }).last().click();
    await expect(page.getByText("Version restored")).toBeVisible();
    await expect(page.getByText("Baseline Cause")).toBeVisible();
    await expect(page.getByText("Edited Cause")).toBeHidden();

    await page.reload();
    await expect(page.getByText("Baseline Cause")).toBeVisible();
    await expect(page.getByText("Edited Cause")).toBeHidden();
  });
});
