import { epic, feature, story } from "allure-js-commons";
import { expect, test } from "../allure.fixtures";
import { apiGet, createProjectViaApi, createTagViaApi, createUserViaApi, loginThroughUi, openTaskWorkspace } from "./gtdHelpers";

type TaskList = { items: Array<{ title: string; project_id: string | null; tag_ids: string[] }> };

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`rapid capture at ${viewport.width}x${viewport.height} is one POST and durable`, async ({ browser }, testInfo) => {
    const context = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, viewport });
    const page = await context.newPage();
    await epic("BrainBuddy MVP loop");
    await feature("Native tasks and Voice Brain Dump");
    await story("Rapid task capture");
    await test.step("create an isolated synthetic account and sign in through the UI", async () => {
      const email = await createUserViaApi(page.request, testInfo, `rapid-${viewport.width}`);
      await page.context().clearCookies();
      await loginThroughUi(page, email);
    });
    await openTaskWorkspace(page, undefined, "/tasks/next");

    const title = `Rapid capture ${viewport.width}-${Date.now()}`;
    let posts = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && /\/api\/tasks$/.test(request.url())) posts += 1;
    });
    const field = page.getByLabel("New task title");
    await field.fill(title);
    await page.getByRole("button", { name: "Add task" }).dblclick();
    const deadline = Date.now() + 5000;
    while (posts < 1 && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 20));
    if (posts !== 1) throw new Error(`expected one POST, observed ${posts}`);
    await expect(field).toHaveValue("");

    const tasks = await apiGet<TaskList>(page, "/api/tasks?state=next");
    if (tasks.items.filter((task) => task.title === title).length !== 1) {
      throw new Error("expected exactly one durable task");
    }
    await page.reload();
    await expect(page.getByText(title, { exact: true })).toBeVisible();
    await context.close();
  });
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`Smart Add at ${viewport.width}x${viewport.height} persists one task and classification set`, async ({ browser }, testInfo) => {
    const context = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, viewport });
    const page = await context.newPage();
    await epic("BrainBuddy MVP loop");
    await feature("Native tasks and Voice Brain Dump");
    await story("Durable Smart Add classification");

    const email = await createUserViaApi(page.request, testInfo, `smart-add-${viewport.width}`);
    await page.context().clearCookies();
    await loginThroughUi(page, email);
    await openTaskWorkspace(page, undefined, "/tasks/next");
    const project = await createProjectViaApi(page, `Smart project ${viewport.width}`);
    const tag = await createTagViaApi(page, `smart-${viewport.width}`);
    await page.reload();
    await expect(page.getByText("Brain Buddy", { exact: true })).toBeVisible();

    const title = `Durable Smart Add ${viewport.width}`;
    const field = page.getByLabel("New task title");
    await field.fill(`${title} #smart-${viewport.width} @"Smart project ${viewport.width}" `);
    await page.getByRole("button", { name: "Add task" }).click();
    await expect(field).toHaveValue("");

    const tasks = await apiGet<TaskList>(page, "/api/tasks?state=next");
    const matches = tasks.items.filter((task) => task.title === title);
    if (matches.length !== 1) throw new Error(`expected exactly one durable Smart Add task, observed ${matches.length}`);
    if (matches[0]?.project_id !== project.id || matches[0].tag_ids.length !== 1 || matches[0].tag_ids[0] !== tag.id) {
      throw new Error("expected exactly one project and one tag classification");
    }
    await page.reload();
    await expect(page.getByText(title, { exact: true })).toBeVisible();
    await context.close();
  });
}

test("capture success preserves an external form control focus and restores BODY focus", async ({ browser }, testInfo) => {
  const context = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL });
  const page = await context.newPage();
  await epic("BrainBuddy MVP loop");
  await feature("Native tasks and Voice Brain Dump");
  await story("Rapid task capture focus continuity");
  const email = await createUserViaApi(page.request, testInfo, "focus-capture");
  await page.context().clearCookies();
  await loginThroughUi(page, email);
  await openTaskWorkspace(page, undefined, "/tasks/next");

  await page.locator("body").evaluate(() => {
    const form = document.createElement("form");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "External form control";
    form.append(button);
    document.body.append(form);
  });
  const externalButton = page.getByRole("button", { name: "External form control" });
  const field = page.getByLabel("New task title");
  await field.fill("External focus capture");
  await externalButton.focus();
  await page.locator("form").filter({ has: page.getByLabel("New task title") }).evaluate((form) => (form as HTMLFormElement).requestSubmit());
  await expect(field).toHaveValue("");
  await expect(externalButton).toBeFocused();

  await externalButton.evaluate((button) => button.remove());
  let releasePost!: () => void;
  const postHeld = new Promise<void>((resolve) => { releasePost = resolve; });
  await page.route("**/api/tasks", async (route) => {
    await postHeld;
    await route.continue();
  });
  await field.fill("Body focus capture");
  await field.focus();
  const submission = page.waitForRequest((request) => request.method() === "POST" && /\/api\/tasks$/.test(request.url()));
  await page.locator("form").filter({ has: page.getByLabel("New task title") }).evaluate((form) => (form as HTMLFormElement).requestSubmit());
  await submission;
  await field.blur();
  await expect(page.locator("body")).toBeFocused();
  releasePost();
  await expect(field).toHaveValue("");
  await expect(field).toBeFocused();
  await page.unroute("**/api/tasks");
  await context.close();
});
