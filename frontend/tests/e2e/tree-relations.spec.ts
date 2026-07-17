import { expect, test } from "@playwright/test";

import {
  createNodeViaApi,
  createRelationViaApi,
  createTreeViaApi,
  createUserViaApi,
  openCrtWorkspace
} from "./helpers";

test.describe("tree canvas acceptance", () => {
  test("E2E-TREE-02 node and relation canvas state survives reload", async ({ page }, testInfo) => {
    const email = await createUserViaApi(page.request, testInfo, "tree-relations");
    const tree = await createTreeViaApi(page.request, `E2E Relation Tree ${testInfo.workerIndex}`);
    const cause = await createNodeViaApi(page.request, tree.id, "Root Cause", "parent", { x: -120, y: 0 });
    const effect = await createNodeViaApi(page.request, tree.id, "Observed Effect", "child", { x: 160, y: 160 });
    await createRelationViaApi(page.request, tree.id, cause.id, effect.id);

    await openCrtWorkspace(page, email);

    await expect(page.getByText("Root Cause")).toBeVisible();
    await expect(page.getByText("Observed Effect")).toBeVisible();
    await expect(page.getByTestId("relation-edge")).toHaveCount(1);

    await page.reload();
    await expect(page.getByText("Root Cause")).toBeVisible();
    await expect(page.getByText("Observed Effect")).toBeVisible();
    await expect(page.getByTestId("relation-edge")).toHaveCount(1);
  });
});
