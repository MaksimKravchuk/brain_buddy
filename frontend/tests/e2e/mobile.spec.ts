import { expect, test } from "../allure.fixtures";

import {
  createTreeViaUi,
  loginThroughUi,
  mintInvite,
  openCrtWorkspace,
  signOut,
  signupThroughUi,
  uniqueEmail
} from "./helpers";

const treeListResponse = [
  { id: "tree-1", name: "Current tree", updated_at: "2026-07-15T10:00:00Z", owner_id: "user-1" }
];

const treeResponse = {
  id: "tree-1",
  name: "Current tree",
  metadata: {
    version: 1,
    created_at: "2026-07-15T10:00:00Z",
    updated_at: "2026-07-15T10:00:00Z",
    owner_id: "user-1",
    layout: null
  },
  nodes: [],
  relations: [],
  owner_id: "user-1"
};

test.describe("mobile acceptance", () => {
  test("E2E-MOBILE-02 CRT header shows planned workflow placeholders at 390px", async ({ page }) => {
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/api/")) {
        await route.continue();
        return;
      }
      if (url.pathname === "/api/auth/me") {
        await route.fulfill({ json: { id: "user-1", email: "max@example.test" } });
        return;
      }
      if (url.pathname === "/api/trees") {
        await route.fulfill({ json: treeListResponse });
        return;
      }
      if (url.pathname === "/api/trees/tree-1") {
        await route.fulfill({ json: treeResponse });
        return;
      }
      await route.fulfill({ status: 404, json: { detail: "Not found" } });
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/crt");

    const plannedWorkflows = page.getByRole("navigation", { name: "Planned workflows" });
    const crt = plannedWorkflows.getByRole("button", { name: "CRT — Coming Later" });
    const weeklyReview = plannedWorkflows.getByRole("button", { name: "Weekly Review — Coming Later" });

    await expect(page.getByLabel("Tree menu")).toContainText("Current tree");
    await expect(crt).toBeVisible();
    await expect(weeklyReview).toBeVisible();
    await expect(crt).toBeDisabled();
    await expect(weeklyReview).toBeDisabled();
    await expect(plannedWorkflows.getByRole("link")).toHaveCount(0);

    await test.step("Verify both planned placeholders are not clipped in the 390px viewport", async () => {
      for (const item of [crt, weeklyReview]) {
        const box = await item.boundingBox();
        expect(box?.width ?? 0).toBeGreaterThan(40);
        expect(box?.x ?? -1).toBeGreaterThanOrEqual(0);
        expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(390);
      }
    });
  });

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
