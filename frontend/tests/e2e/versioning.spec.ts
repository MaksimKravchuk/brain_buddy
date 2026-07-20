import { expect, test } from "../allure.fixtures";

import { apiGet, apiPatch, createTaskViaApi, createUserViaApi, type TaskRecord } from "./gtdHelpers";

test.describe("task revision acceptance", () => {
  test("E2E-REVISION-01 rejects a stale write and preserves the accepted task revision", async ({ page }, testInfo) => {
    await createUserViaApi(page.request, testInfo, "task-revision");
    const task = await createTaskViaApi(page, "Original title", { state: "next" });

    await test.step("accept a write against the current revision", async () => {
      const response = await apiPatch<TaskRecord>(page, `/api/tasks/${task.id}`, {
        title: "Accepted title",
        expected_revision: task.revision
      });
      if (response.status() !== 200) {
        throw new Error(`current revision update failed with ${response.status()} ${await response.text()}`);
      }
    });
    await test.step("reject a stale concurrent write without overwriting accepted data", async () => {
      const stale = await apiPatch<TaskRecord>(page, `/api/tasks/${task.id}`, {
        title: "Stale overwrite",
        expected_revision: task.revision
      });
      if (stale.status() !== 409) {
        throw new Error(`stale revision update returned ${stale.status()} instead of 409: ${await stale.text()}`);
      }
      const persisted = await apiGet<TaskRecord>(page, `/api/tasks/${task.id}`);
      if (persisted.title !== "Accepted title") {
        throw new Error(`stale update overwrote persisted title with ${JSON.stringify(persisted.title)}`);
      }
      await page.goto(`/tasks/next/${task.id}`);
      await expect(page.getByRole("link", { name: "Accepted title" })).toBeVisible();
      await expect(page.getByText("Stale overwrite")).toHaveCount(0);
    });
  });
});