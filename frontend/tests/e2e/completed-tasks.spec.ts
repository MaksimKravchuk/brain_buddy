import { type Page } from "@playwright/test";
import { epic, feature, story } from "allure-js-commons";
import { expect, test } from "../allure.fixtures";
import { apiGet, createProjectViaApi, createTagViaApi, createTaskViaApi, createUserViaApi, type TaskRecord } from "./gtdHelpers";

test.use({ video: "on" });

type MotionSample = {
  title: string;
  duration: number | string;
  minY: number;
  maxY: number;
  finished: boolean;
  displacedControlHit: boolean;
};

declare global {
  interface Window { completionMotionSamples: MotionSample[] }
}

function row(page: Page, title: string) {
  return page.getByRole("listitem").filter({ has: page.getByRole("link", { name: title, exact: true }) });
}

async function observeMotion(page: Page) {
  await page.evaluate(() => {
    window.completionMotionSamples = [];
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (keyframes, options) {
      const animation = animate.call(this, keyframes, options);
      const article = this.closest("article");
      if (!article) return animation;
      const initial = article.getBoundingClientRect().y;
      const duration = animation.effect?.getTiming().duration ?? 0;
      const sample: MotionSample = {
        title: article.querySelector("a")?.textContent ?? "",
        duration: typeof duration === "number" ? duration : String(duration),
        minY: initial, maxY: initial, finished: false, displacedControlHit: false
      };
      window.completionMotionSamples.push(sample);
      const measure = () => {
        const y = article.getBoundingClientRect().y;
        sample.minY = Math.min(sample.minY, y);
        sample.maxY = Math.max(sample.maxY, y);
        const control = article.querySelector<HTMLButtonElement>("button[aria-label^='Complete ']");
        if (control && sample.maxY - sample.minY > 1) {
          const box = control.getBoundingClientRect();
          const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
          sample.displacedControlHit ||= Boolean(hit && control.contains(hit));
        }
        if (!sample.finished) requestAnimationFrame(measure);
      };
      requestAnimationFrame(measure);
      void animation.finished.then(() => { sample.finished = true; measure(); }, () => { sample.finished = true; });
      return animation;
    };
  });
}

async function expectCompleted(page: Page, task: TaskRecord, openTitles: string[] = []) {
  const title = page.getByRole("link", { name: task.title, exact: true });
  await expect(title).toHaveCount(1);
  await expect(title).toHaveCSS("text-decoration-line", "line-through");
  await expect(title).toHaveCSS("color", "rgb(100, 116, 139)");
  const completed = page.getByRole("heading", { name: "Completed", exact: true });
  await expect(completed).toBeVisible();
  const headingBox = await completed.boundingBox();
  const taskBox = await row(page, task.title).boundingBox();
  expect(headingBox).not.toBeNull();
  expect(taskBox).not.toBeNull();
  expect(taskBox!.y).toBeGreaterThanOrEqual(headingBox!.y + headingBox!.height);
  for (const openTitle of openTitles) {
    const openBox = await row(page, openTitle).boundingBox();
    expect(openBox).not.toBeNull();
    expect(headingBox!.y).toBeGreaterThanOrEqual(openBox!.y + openBox!.height);
  }
  expect(await row(page, task.title).ariaSnapshot()).toMatch(/completed/i);
  const opacity = await title.evaluate((element) => {
    let result = 1;
    for (let node: Element | null = element; node; node = node.parentElement) result *= Number(getComputedStyle(node).opacity);
    return result;
  });
  expect(opacity).toBe(1);
}

for (const width of [1240, 390]) {
  test(`016-FR-001 016-FR-002 016-FR-003 016-SC-001 016-SC-002 016-SC-004 completion moves after save with usable controls at ${width}px`, async ({ page }, testInfo) => {
    await epic("End-to-end journeys");
    await feature("Visible completed tasks");
    await story("016-SC-002 Canonical completion motion and recovery");
    await page.setViewportSize({ width, height: 900 });
    let target: TaskRecord;
    let remaining: TaskRecord[];

    await test.step("Create an isolated account and open tasks in two project groups", async () => {
      await createUserViaApi(page.request, testInfo, `completion-${width}`);
      const alpha = await createProjectViaApi(page, "Completion Alpha");
      const beta = await createProjectViaApi(page, "Completion Beta");
      target = await createTaskViaApi(page, "A completion motion sample", { state: "next", project_id: alpha.id });
      remaining = [
        await createTaskViaApi(page, "B remaining alpha sample", { state: "next", project_id: alpha.id }),
        await createTaskViaApi(page, "C remaining beta sample", { state: "next", project_id: beta.id })
      ];
      await page.goto("/tasks/next?sort=title");
      await expect(page.getByRole("button", { name: `Complete ${target.title}` })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Completed", exact: true })).toHaveCount(0);
      await observeMotion(page);
    });

    await test.step("Keep a pending keyboard completion open and send one transition despite repeated activation", async () => {
      const button = page.getByRole("button", { name: `Complete ${target.title}` });
      const before = await row(page, target.title).boundingBox();
      let release!: () => void;
      const held = new Promise<void>((resolve) => { release = resolve; });
      let requests = 0;
      const endpoint = `**/api/tasks/${target.id}/transitions`;
      await page.route(endpoint, async (route) => { requests += 1; await held; await route.continue(); });
      try {
        const request = page.waitForRequest((request) => request.url().endsWith(`/tasks/${target.id}/transitions`));
        await button.focus();
        await page.keyboard.press("Space");
        await request;
        await expect(button).toBeDisabled();
        await button.evaluate((element) => { (element as HTMLButtonElement).click(); (element as HTMLButtonElement).click(); });
        expect(requests).toBe(1);
        expect(await page.evaluate(() => window.completionMotionSamples.length)).toBe(0);
        expect((await row(page, target.title).boundingBox())!.y).toBe(before!.y);
        await expect(page.getByRole("link", { name: target.title, exact: true })).toHaveCSS("text-decoration-line", "none");
      } finally { release(); }
      await expect.poll(async () => (await apiGet<TaskRecord>(page, `/api/tasks/${target.id}`)).state).toBe("completed");
      await expect.poll(async () => page.evaluate(() => window.completionMotionSamples.length)).toBeGreaterThan(0);
      await expect.poll(async () => page.evaluate(() => window.completionMotionSamples.every((sample) => sample.finished))).toBe(true);
      await expectCompleted(page, target, remaining.map((task) => task.title));
      await expect(page.getByRole("link", { name: target.title, exact: true })).toBeFocused();
      const samples = await page.evaluate(() => window.completionMotionSamples);
      const moved = samples.find((sample) => sample.title === target.title);
      expect(moved).toBeDefined();
      expect(moved!.duration).toBeGreaterThan(0);
      expect(moved!.duration).toBeLessThanOrEqual(600);
      expect(moved!.maxY - moved!.minY).toBeGreaterThan(1);
      expect(samples.some((sample) => sample.displacedControlHit)).toBe(true);
      expect(requests).toBe(1);
      await page.unroute(endpoint);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
      await testInfo.attach(`completion-motion-${width}`, { body: JSON.stringify(samples), contentType: "application/json" });
      await testInfo.attach(`completed-list-${width}`, { body: await page.screenshot(), contentType: "image/png" });
    });

    await test.step("A failed completion stays open, reports the failure and can be retried", async () => {
      const failed = remaining[0];
      const endpoint = `**/api/tasks/${failed.id}/transitions`;
      const motionCount = await page.evaluate(() => window.completionMotionSamples.length);
      await page.route(endpoint, (route) => route.fulfill({ status: 503, headers: { "X-Correlation-ID": "completion-e2e-failure" }, json: { detail: "Completion temporarily unavailable" } }));
      const button = page.getByRole("button", { name: `Complete ${failed.title}` });
      await button.click();
      await expect(page.getByRole("alert")).toContainText("Completion temporarily unavailable");
      await expect(button).toBeEnabled();
      await expect(page.getByRole("link", { name: failed.title, exact: true })).toHaveCSS("text-decoration-line", "none");
      expect((await row(page, failed.title).boundingBox())!.y).toBeLessThan((await page.getByRole("heading", { name: "Completed", exact: true }).boundingBox())!.y);
      expect(await page.evaluate(() => window.completionMotionSamples.length)).toBe(motionCount);
      expect((await apiGet<TaskRecord>(page, `/api/tasks/${failed.id}`)).state).toBe("next");
      await page.unroute(endpoint);
      await button.click();
      await expect.poll(async () => (await apiGet<TaskRecord>(page, `/api/tasks/${failed.id}`)).state).toBe("completed");
      await expect.poll(async () => page.evaluate(() => window.completionMotionSamples.length)).toBeGreaterThan(motionCount);
      await expect.poll(async () => page.evaluate(() => window.completionMotionSamples.every((sample) => sample.finished))).toBe(true);
      await expectCompleted(page, failed, [remaining[1].title]);
      await page.reload();
      await expectCompleted(page, target, [remaining[1].title]);
      await expectCompleted(page, failed, [remaining[1].title]);
    });
  });
}

test("016-FR-002 016-FR-003 016-SC-002 reduced motion places a saved task immediately without row animation", async ({ page }, testInfo) => {
  await epic("End-to-end journeys");
  await feature("Visible completed tasks");
  await story("016-SC-002 Reduced motion");
  await test.step("Complete a task with reduced motion and retain its saved visible state", async () => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await createUserViaApi(page.request, testInfo, "completion-reduced");
    const target = await createTaskViaApi(page, "Reduced motion sample", { state: "next" });
    await page.goto("/tasks/next?group=off");
    const button = page.getByRole("button", { name: `Complete ${target.title}` });
    await expect(button).toBeVisible();
    await observeMotion(page);
    await button.click();
    await expect.poll(async () => (await apiGet<TaskRecord>(page, `/api/tasks/${target.id}`)).state).toBe("completed");
    await expectCompleted(page, target);
    expect(await page.evaluate(() => window.completionMotionSamples)).toEqual([]);
    await page.reload();
    await expectCompleted(page, target);
  });
});

test("016-FR-001 016-FR-002 016-FR-003 016-SC-001 016-SC-003 016-SC-004 one task shares completion and reopening across project tag and search views", async ({ page }, testInfo) => {
  await epic("End-to-end journeys");
  await feature("Visible completed tasks");
  await story("016-SC-003 One canonical status across overlapping views");
  await test.step("Complete through task detail, visit each matching view and reopen the same task", async () => {
    await createUserViaApi(page.request, testInfo, "completion-shared");
    const project = await createProjectViaApi(page, "Completion shared project");
    const tag = await createTagViaApi(page, "completion-shared");
    const target = await createTaskViaApi(page, "Shared completion sample", { state: "next", project_id: project.id, tag_ids: [tag.id] });
    const views = [`/projects/${project.id}`, `/tags/${tag.id}`, "/tasks/next?q=Shared"];
    for (const view of views) {
      await page.goto(view);
      await expect(page.getByRole("button", { name: `Complete ${target.title}` })).toBeVisible();
    }
    await page.getByRole("link", { name: target.title, exact: true }).click();
    await page.getByRole("button", { name: "Complete task", exact: true }).click();
    await expect(page.getByRole("button", { name: "Reopen task", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Close task", exact: true }).click();
    await expectCompleted(page, target);
    for (const view of views) {
      await page.goto(view);
      await expectCompleted(page, target);
      await page.reload();
      await expectCompleted(page, target);
    }
    await page.goto("/tasks/next?q=Unrelated");
    await expect(page.getByRole("link", { name: target.title, exact: true })).toHaveCount(0);
    await page.goto(views[0]);
    await page.getByRole("link", { name: target.title, exact: true }).click();
    await page.getByLabel("List", { exact: true }).selectOption("next");
    await expect(page.getByRole("button", { name: "Complete task", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Close task", exact: true }).click();
    for (const view of views) {
      await page.goto(view);
      await expect(page.getByRole("button", { name: `Complete ${target.title}` })).toBeVisible();
      await expect(page.getByRole("link", { name: target.title, exact: true })).toHaveCSS("text-decoration-line", "none");
    }
    expect((await apiGet<TaskRecord>(page, `/api/tasks/${target.id}`)).state).toBe("next");
  });
});
