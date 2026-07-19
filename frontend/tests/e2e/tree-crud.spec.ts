import { expect, test } from "../allure.fixtures";

import { loginThroughUi, logoutSession, mintInvite, signupThroughUi, uniqueEmail } from "./gtdHelpers";

test.describe("native task CRUD acceptance", () => {
  test("E2E-TASK-01 create, edit, move, complete, and persist tasks", async ({ page }, testInfo) => {
    const email = uniqueEmail("task-crud", testInfo);
    await signupThroughUi(page, email, await mintInvite());

    await test.step("create and edit a real Inbox task", async () => {
      await page.goto("/tasks/inbox");
      await page.getByLabel("New task title").fill("Plan quarterly review");
      await page.getByRole("button", { name: "Add task" }).click();
      await expect(page.getByText("Plan quarterly review")).toBeVisible();
      await page.getByRole("button", { name: "Edit Plan quarterly review" }).click();
      await page.getByRole("textbox", { name: "Task title", exact: true }).fill("Prepare quarterly review");
      await page.getByRole("button", { name: "Save task title" }).click();
      await expect(page.getByText("Prepare quarterly review")).toBeVisible();
    });

    await test.step("move the task to Next and persist across reload and relogin", async () => {
      await page.getByRole("button", { name: "Move Prepare quarterly review to Next" }).click();
      await page.goto("/tasks/next");
      await expect(page.getByText("Prepare quarterly review")).toBeVisible();
      await page.reload();
      await expect(page.getByText("Prepare quarterly review")).toBeVisible();
      await logoutSession(page);
      await loginThroughUi(page, email);
      await page.goto("/tasks/next");
      await expect(page.getByText("Prepare quarterly review")).toBeVisible();
    });

    await test.step("complete without leaving a stale open row", async () => {
      await page.getByRole("button", { name: "Complete Prepare quarterly review" }).click();
      await expect(page.getByText("Prepare quarterly review")).toHaveCount(0);
    });
  });
});