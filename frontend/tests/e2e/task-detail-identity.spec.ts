import type { Page } from "@playwright/test";

import { expect, test } from "../allure.fixtures";

import {
  apiGet,
  createTaskViaApi,
  mintInvite,
  signupThroughUi,
  uniqueEmail,
  type TaskRecord
} from "./gtdHelpers";

function assertCondition(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

// Polls manually instead of `expect.poll(...).toBe(...)`: the Allure reporter
// wraps each poll attempt's matcher in its own "Expect toBe" step, and a fast
// attempt that resolves in under 1ms is recorded with equal start/stop
// timestamps and no attachments -- a zero-duration, evidence-less step the
// taxonomy validator correctly rejects as a no-op. Each GET below already
// carries real request/response evidence and duration, and the final
// `assertCondition` doesn't emit a synthetic Allure step at all.
async function waitForPersistedTitle(page: Page, taskId: string, expectedTitle: string): Promise<TaskRecord> {
  const deadline = Date.now() + 15_000;
  let task: TaskRecord;
  do {
    task = await apiGet<TaskRecord>(page, `/api/tasks/${taskId}`);
    if (task.title === expectedTitle) break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  } while (Date.now() < deadline);
  return task;
}

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
      const persisted = await waitForPersistedTitle(page, taskA.id, taskA.title);
      assertCondition(
        persisted.title === taskA.title,
        `task A title must remain ${JSON.stringify(taskA.title)} after Back+Save, but persisted as ${JSON.stringify(persisted.title)}`
      );
    });
  });
});
