import AxeBuilder from "@axe-core/playwright";
import { epic, feature, story } from "allure-js-commons";
import { expect, test } from "../allure.fixtures";
import { createTagViaApi, createTaskViaApi, createUserViaApi } from "./gtdHelpers";

test.use({ video: "on" });

async function identifyFeature(): Promise<void> {
  await epic("Task management");
  await feature("Compact Task rows");
  await story("017 dense desktop list and inline Task detail");
}

test("017-FR-001 017-FR-004 017-FR-006 017-SC-001 017-SC-004 017-SC-005 shows ten 44px rows and opens detail inline", async ({ page }, testInfo) => {
  await identifyFeature();
  await page.setViewportSize({ width: 1440, height: 900 });

  await test.step("Create ten synthetic next actions", async () => {
    await createUserViaApi(page.request, testInfo, "compact-rows");
    for (let index = 1; index <= 10; index += 1) {
      await createTaskViaApi(page, `Compact row ${String(index).padStart(2, "0")}`, { state: "next" });
    }
  });

  await test.step("Measure the collapsed list", async () => {
    await page.goto("/tasks/next?group=off");
    const headers = page.getByTestId("task-row-header");
    await expect(headers).toHaveCount(10);
    const boxes = await headers.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect()));
    expect(boxes.every((box) => box.height === 44)).toBe(true);
    expect(boxes.at(-1)?.bottom).toBeLessThanOrEqual(900);
    expect(await page.locator("body").evaluate((body) => body.scrollWidth <= body.clientWidth)).toBe(true);
  });

  await test.step("Open and close the real inline detail with the keyboard", async () => {
    const title = page.getByRole("link", { name: "Compact row 01", exact: true });
    await title.focus();
    await page.keyboard.press("Enter");
    const row = page.getByRole("listitem").filter({ has: page.getByRole("link", { name: "Compact row 01", exact: true }) });
    await expect(row.getByRole("complementary", { name: "Task detail" })).toBeVisible();
    await expect(page.getByRole("dialog", { name: "Task detail" })).toHaveCount(0);
    await expect(page.locator(".task-side-sheet")).toHaveCount(0);
    await page.getByRole("button", { name: "Close task" }).click();
    await expect(title).toBeFocused();
  });

  await test.step("Check the affected main surface for serious accessibility violations", async () => {
    const result = await new AxeBuilder({ page }).include("main").analyze();
    expect(result.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical")).toEqual([]);
    await testInfo.attach("compact-task-rows-1440.png", { body: await page.screenshot(), contentType: "image/png" });
  });
});

test("017-FR-002 017-FR-003 017-FR-010 017-FR-012 017-FR-016 017-SC-002 017-SC-003 keeps aligned controls without horizontal overflow", async ({ page }, testInfo) => {
  await identifyFeature();
  await createUserViaApi(page.request, testInfo, "compact-statuses");
  const tag = await createTagViaApi(page, "aaa");
  const labels = ["Queued", "Running", "Needs you", "Agent reported complete", "Failed"];
  const tasks = [];
  for (const [index, label] of labels.entries()) {
    tasks.push(await createTaskViaApi(page, `${label}: a deliberately long task title that must remain on one line ${index}`, {
      state: "next",
      tag_ids: [tag.id]
    }));
  }
  const summaries = Object.fromEntries(tasks.map((task, index) => [task.id, {
    id: `run-${index}`,
    task_id: task.id,
    agent_name: "Hermes",
    primary_state_label: labels[index],
    needs_user: labels[index] === "Needs you",
    stopped_reporting: false,
    last_contact_at: "2026-09-11T10:00:00Z",
    guarantee_tier: index % 2 ? "best_effort" : "guaranteed",
    cancel_outcome: index === 4 ? "not_cancelable" : "none",
    agent_task_missing: false
  }]));
  await page.route("**/api/agent-run-summaries?**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(summaries) }));

  for (const viewport of [{ width: 768, height: 900 }, { width: 390, height: 851 }]) {
    await test.step(`Measure ${viewport.width}px responsive layout`, async () => {
      await page.setViewportSize(viewport);
      await page.goto("/tasks/next?group=off");
      const headers = page.getByTestId("task-row-header");
      await expect(headers).toHaveCount(5);
      expect(await headers.evaluateAll((elements) => elements.every((element) => element.getBoundingClientRect().height === 44))).toBe(true);

      const controls = page.locator("[data-agent-assigned-control]");
      await expect(controls).toHaveCount(5);
      const geometry = await controls.evaluateAll((elements) => elements.map((element) => {
        const box = element.getBoundingClientRect();
        const children = Array.from(element.children).map((child) => child.getBoundingClientRect().x - box.x);
        return { width: box.width, height: box.height, children };
      }));
      expect(geometry.every((item) => item.width === 184 && item.height === 28)).toBe(true);
      expect(geometry.every((item) => JSON.stringify(item.children) === JSON.stringify(geometry[0].children))).toBe(true);
      await expect(page.getByText("Reported", { exact: true })).toBeVisible();
      await expect(page.getByText("Done", { exact: true })).toHaveCount(0);
      await expect(page.getByText("#aaa", { exact: true }).first()).toBeAttached();
      for (const row of await page.getByRole("listitem").all()) {
        await expect(row.getByText("Inbox", { exact: true })).toHaveCount(0);
      }
      expect(await page.locator("body").evaluate((body) => body.scrollWidth <= body.clientWidth)).toBe(true);
      await testInfo.attach(`compact-task-rows-${viewport.width}.png`, { body: await page.screenshot(), contentType: "image/png" });
    });
  }
});
