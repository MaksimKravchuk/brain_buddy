import { attachment, ContentType, epic, feature, story } from "allure-js-commons";
import { expect, test } from "../allure.fixtures";
import { apiGet, createTaskViaApi, createUserViaApi, loginThroughUi } from "./gtdHelpers";

test("task edits stay saved after independently revised subtasks and comments", async ({ page }, testInfo) => {
  await epic("BrainBuddy MVP loop");
  await feature("Native task editing");
  await story("Reliable autosave with task children");

  const email = await createUserViaApi(page.request, testInfo, "child-autosave");
  await page.context().clearCookies();
  await loginThroughUi(page, email);
  const task = await createTaskViaApi(page, "Review the homepage navigation");
  await page.goto(`/tasks/inbox/${task.id}`);
  const panel = page.getByRole("complementary", { name: "Task detail" });
  await expect(panel.getByLabel("Title", { exact: true })).toHaveValue(task.title);

  await test.step("create a subtask and comment through the real task detail UI", async () => {
    await panel.getByLabel("New subtask title").fill("Check navigation labels");
    await panel.getByLabel("New subtask title").press("Enter");
    await expect(panel.getByRole("button", { name: "Complete Check navigation labels" })).toBeVisible();
    await panel.getByLabel("New comment").fill("Check the mobile drawer too.");
    await panel.getByLabel("New comment").press("Enter");
    await expect(panel.getByText("Check the mobile drawer too.")).toBeVisible();
  });

  await expect(panel.getByText("Not saved", { exact: true })).toHaveCount(0);
  await expect(panel.getByRole("alert")).toHaveCount(0);

  await test.step("save a parent field without mistaking the child projection for a conflict", async () => {
    const saved = page.waitForResponse((response) => response.request().method() === "PATCH" && response.url().endsWith(`/api/tasks/${task.id}`));
    await panel.getByLabel("Priority", { exact: true }).selectOption("high");
    const response = await saved;
    if (!response.ok()) throw new Error(`Priority save failed with ${response.status()}`);
    await expect(panel.getByText("Not saved", { exact: true })).toHaveCount(0);
    await expect(panel.getByRole("alert")).toHaveCount(0);
    await expect(panel.getByRole("button", { name: "Complete Check navigation labels" })).toBeVisible();
    await expect(panel.getByText("Check the mobile drawer too.")).toBeVisible();
    await page.waitForFunction(() => !Object.keys(sessionStorage).some((key) => key.startsWith("bb.taskDetailDraft.v1.")));
  });

  await test.step("reload the canonical task and verify durable edits without false recovery", async () => {
    await page.reload();
    await expect(panel.getByLabel("Priority", { exact: true })).toHaveValue("high");
    await expect(panel.getByRole("button", { name: "Complete Check navigation labels" })).toBeVisible();
    await expect(panel.getByText("Check the mobile drawer too.")).toBeVisible();
    await expect(panel.getByText("Not saved", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Unsaved task change recovered. Retry or Discard.", { exact: true })).toHaveCount(0);
    const canonical = await apiGet<{ priority: string; subtasks: Array<{ title: string }>; comments: Array<{ body: string }> }>(page, `/api/tasks/${task.id}`);
    await attachment("Persisted synthetic task", JSON.stringify(canonical), ContentType.JSON);
    if (canonical.priority !== "high" || canonical.subtasks.length !== 1 || canonical.subtasks[0].title !== "Check navigation labels" ||
      canonical.comments.length !== 1 || canonical.comments[0].body !== "Check the mobile drawer too.") {
      throw new Error("Expected the priority, subtask and comment to remain durable after reload");
    }
  });
});
