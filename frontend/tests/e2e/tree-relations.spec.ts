import { expect, test } from "../allure.fixtures";

import { createProjectViaApi, createTagViaApi, createTaskViaApi, createUserViaApi } from "./gtdHelpers";

test.describe("task organization acceptance", () => {
  test("E2E-TASK-02 project and tag assignments survive filtered reloads", async ({ page }, testInfo) => {
    await createUserViaApi(page.request, testInfo, "task-relations");
    const project = await createProjectViaApi(page, "Launch Plan");
    const tag = await createTagViaApi(page, "deep-work");
    await createTaskViaApi(page, "Draft launch note", { state: "next", project_id: project.id, tag_ids: [tag.id] });

    await test.step("render the API-backed project projection", async () => {
      await page.goto(`/projects/${project.id}`);
      await expect(page.getByRole("heading", { name: "Launch Plan" })).toBeVisible();
      await expect(page.getByText("Draft launch note")).toBeVisible();
    });
    await test.step("render the same task through its persisted tag projection after reload", async () => {
      await page.goto(`/tags/${tag.id}`);
      await page.reload();
      await expect(page.getByRole("heading", { name: "#deep-work" })).toBeVisible();
      await expect(page.getByText("Draft launch note")).toBeVisible();
    });
  });
});