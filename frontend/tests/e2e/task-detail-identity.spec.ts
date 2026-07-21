import { expect, test } from "../allure.fixtures";

import {
  apiGet,
  createTaskViaApi,
  mintInvite,
  signupThroughUi,
  uniqueEmail,
  type TaskRecord
} from "./gtdHelpers";

test.describe("task detail identity acceptance", () => {
  test("E2E-TASK-05 browser Back never saves terminal task B values into terminal task A", async ({ page }, testInfo) => {
    const email = uniqueEmail("task-detail-identity", testInfo);
    await signupThroughUi(page, email, await mintInvite());

    const taskA = await createTaskViaApi(page, "Task A must stay A", { state: "next" });
    const taskB = await createTaskViaApi(page, "Task B must stay B", { state: "next" });

    await test.step("complete task A, then open and complete task B through the real browser UI", async () => {
      await page.goto(`/tasks/next/${taskA.id}`);
      await expect(page.getByRole("textbox", { name: "Title", exact: true })).toHaveValue(taskA.title);
      await page.getByRole("button", { name: "Complete", exact: true }).click();
      await expect(page.getByRole("button", { name: "Reopen to Inbox" })).toBeVisible();

      await page.goto(`/tasks/next/${taskB.id}`);
      await expect(page.getByRole("textbox", { name: "Title", exact: true })).toHaveValue(taskB.title);
      await page.getByRole("button", { name: "Complete", exact: true }).click();
      await expect(page.getByRole("button", { name: "Reopen to Inbox" })).toBeVisible();
    });

    await test.step("browser Back restores A's own form values before Save", async () => {
      await page.goBack();
      await expect(page).toHaveURL(new RegExp(`/tasks/next/${taskA.id}$`));
      await expect(page.getByRole("textbox", { name: "Title", exact: true })).toHaveValue(taskA.title);

      await page.getByRole("button", { name: "Save task detail" }).click();
      await expect.poll(async () => (await apiGet<TaskRecord>(page, `/api/tasks/${taskA.id}`)).title).toBe(taskA.title);
    });
  });
});
