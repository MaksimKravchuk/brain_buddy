import { expect, test } from "../allure.fixtures";

import { createProjectViaApi, createTagViaApi, createTaskViaApi, createUserViaApi } from "./gtdHelpers";

const projectTaskCount = 62;
const tagTaskCount = 53;

test.describe("flat pagination subtitle truthfulness acceptance", () => {
  test("E2E-TASK-04 flat Project and Tag views report the true non-terminal total instead of the first loaded page, and Group by project keeps the same total", async ({ page }, testInfo) => {
    await createUserViaApi(page.request, testInfo, "pagination-count");
    const project = await createProjectViaApi(page, "Pagination Total Project");
    const tag = await createTagViaApi(page, "pagination-total");

    await test.step(`create ${projectTaskCount} persisted Next tasks in one project via the real API`, async () => {
      for (let index = 0; index < projectTaskCount; index += 1) {
        await createTaskViaApi(page, `Project pagination task ${String(index).padStart(2, "0")}`, {
          state: "next",
          project_id: project.id
        });
      }
    });

    await test.step(`create ${tagTaskCount} persisted Next tasks under one tag via the real API`, async () => {
      for (let index = 0; index < tagTaskCount; index += 1) {
        await createTaskViaApi(page, `Tag pagination task ${String(index).padStart(2, "0")}`, {
          state: "next",
          tag_ids: [tag.id]
        });
      }
    });

    await test.step(`flat Project route shows the true ${projectTaskCount}-task total although only the first page is rendered`, async () => {
      await page.goto(`/projects/${project.id}`);
      await expect(page.getByRole("heading", { name: "Pagination Total Project" })).toBeVisible();
      await expect(page.getByText(`${projectTaskCount} tasks`)).toBeVisible();
      await expect(page.getByText("50 tasks")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Load more tasks" })).toBeVisible();
      await expect(page.getByRole("list", { name: "Tasks" }).getByRole("listitem")).toHaveCount(50);
    });

    await test.step(`flat Tag route shows the true ${tagTaskCount}-task total although only the first page is rendered`, async () => {
      await page.goto(`/tags/${tag.id}`);
      await expect(page.getByRole("heading", { name: "#pagination-total" })).toBeVisible();
      await expect(page.getByText(`${tagTaskCount} tasks`)).toBeVisible();
      await expect(page.getByText("50 tasks")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Load more tasks" })).toBeVisible();
      await expect(page.getByRole("list", { name: "Tasks" }).getByRole("listitem")).toHaveCount(50);
    });

    await test.step("Group by project on the Tag route drains every cursor page and keeps the same truthful total", async () => {
      await page.getByRole("button", { name: "Group by project" }).click();
      await expect(page.getByTestId("grouped-task-list")).toBeVisible();
      await expect(page.getByText(`${tagTaskCount} tasks`)).toBeVisible();
      await expect(page.getByRole("button", { name: "Load more tasks" })).toHaveCount(0);
      await expect(page.getByTestId("grouped-task-list").getByRole("listitem")).toHaveCount(tagTaskCount);
    });
  });
});
