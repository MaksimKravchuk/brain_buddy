import type { Page } from "@playwright/test";

import { expect, test } from "../allure.fixtures";

import {
  apiGet,
  apiPatch,
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

  test("E2E-TASK-06 browser Save 409 conflict preserves the draft and a retry persists it on the refreshed revision", async ({ page }, testInfo) => {
    const email = uniqueEmail("task-detail-conflict", testInfo);
    await signupThroughUi(page, email, await mintInvite());

    const task = await createTaskViaApi(page, "Task detail Save must retry after a real conflict", { state: "next" });
    const draftTitle = "Browser draft after conflicting revision";
    const authoritativeTitle = "Authoritative concurrent edit while browser drafts";

    const titleInput = page.getByRole("textbox", { name: "Title", exact: true });

    await test.step("owner opens the real detail page and enters an unsaved draft title", async () => {
      await page.goto(`/tasks/next/${task.id}`);
      await expect(titleInput).toHaveValue(task.title);
      await titleInput.fill(draftTitle);
    });

    await test.step("a separate real API PATCH advances the task to revision 2 behind the browser's back", async () => {
      const authoritative = await apiPatch<TaskRecord>(page, `/api/tasks/${task.id}`, {
        title: authoritativeTitle,
        expected_revision: task.revision
      });
      if (authoritative.status() !== 200) {
        throw new Error(`authoritative revision bump failed with ${authoritative.status()} ${await authoritative.text()}`);
      }
    });

    await test.step("first browser Save collides with the stale revision, gets a real 409, and the resulting refetch does not overwrite the visible draft", async () => {
      const conflictPatchResponse = page.waitForResponse(
        (response) => response.request().method() === "PATCH" && response.url().endsWith(`/api/tasks/${task.id}`)
      );
      const conflictRefetchResponse = page.waitForResponse(
        (response) => response.request().method() === "GET" && response.url().endsWith(`/api/tasks/${task.id}`)
      );
      await page.getByRole("button", { name: "Save task detail" }).click();

      const patchResponse = await conflictPatchResponse;
      assertCondition(patchResponse.status() === 409, `expected first Save to be rejected with 409, got ${patchResponse.status()}`);

      const refetchResponse = await conflictRefetchResponse;
      assertCondition(refetchResponse.status() === 200, `expected the owner-scoped conflict refetch to succeed, got ${refetchResponse.status()}`);
      const refetched = (await refetchResponse.json()) as TaskRecord;
      assertCondition(
        refetched.title === authoritativeTitle && refetched.revision === 2,
        `conflict refetch must surface the authoritative title/revision, got ${JSON.stringify(refetched)}`
      );

      await expect(page.getByRole("alert")).toContainText("has newer changes; reload before saving.");
      await expect(titleInput).toHaveValue(draftTitle);
    });

    await test.step("explicit retry Save succeeds on the refreshed baseline and persists the draft title", async () => {
      const retryPatchResponse = page.waitForResponse(
        (response) => response.request().method() === "PATCH" && response.url().endsWith(`/api/tasks/${task.id}`)
      );
      await page.getByRole("button", { name: "Save task detail" }).click();

      const retryResponse = await retryPatchResponse;
      assertCondition(retryResponse.status() === 200, `expected the retried Save to succeed once rebased on the refreshed revision, got ${retryResponse.status()}`);
      const saved = (await retryResponse.json()) as TaskRecord;
      assertCondition(
        saved.title === draftTitle && saved.revision === 3,
        `retried Save must persist the draft title on revision 3, got ${JSON.stringify(saved)}`
      );

      const persisted = await apiGet<TaskRecord>(page, `/api/tasks/${task.id}`);
      assertCondition(
        persisted.title === draftTitle,
        `task must remain persisted with the draft title ${JSON.stringify(draftTitle)}, but found ${JSON.stringify(persisted.title)}`
      );
    });
  });
});
