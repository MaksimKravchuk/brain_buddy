import { expect, test } from "@playwright/test";

const taskResponse = {
  items: [
    {
      id: "task-1",
      title: "Take car in for the flat tire",
      details: null,
      state: "next",
      project_id: "project-personal",
      context_ids: ["tag-errands"],
      due_date: "2026-07-18",
      waiting_for: null,
      waiting_since: null,
      order_key: 1,
      source_capture_ids: [],
      created_at: "2026-07-15T10:00:00Z",
      updated_at: "2026-07-15T10:00:00Z",
      completed_at: null,
      revision: 1,
      subtasks: [],
      comments: []
    },
    {
      id: "task-2",
      title: "Fix onboarding drop-off",
      details: null,
      state: "next",
      project_id: "project-onboarding",
      context_ids: ["tag-deep-work"],
      due_date: null,
      waiting_for: null,
      waiting_since: null,
      order_key: 2,
      source_capture_ids: [],
      created_at: "2026-07-15T10:00:00Z",
      updated_at: "2026-07-15T10:00:00Z",
      completed_at: null,
      revision: 1,
      subtasks: [],
      comments: []
    }
  ],
  next_cursor: null,
  has_more: false,
  counts_by_state: { inbox: 17, next: 6, waiting: 3, someday: 0 }
};

const projectsResponse = [
  { id: "project-launch", name: "Launch v2", color: "#0ea5e9", state: "active", revision: 1 },
  { id: "project-onboarding", name: "Onboarding drop-off", color: "#6366f1", state: "active", revision: 1 },
  { id: "project-personal", name: "Personal admin", color: "#94a3b8", state: "active", revision: 1 }
];

const tagsResponse = [
  { id: "tag-calls", name: "calls", state: "active", revision: 1 },
  { id: "tag-errands", name: "errands", state: "active", revision: 1 },
  { id: "tag-deep-work", name: "deep-work", state: "active", revision: 1 },
  { id: "tag-laptop", name: "laptop", state: "active", revision: 1 }
];

test.beforeEach(async ({ page }) => {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }
    if (url.pathname.includes("/auth/me")) {
      await route.fulfill({ json: { id: "user-1", email: "max@example.test" } });
      return;
    }
    if (url.pathname.includes("/tasks")) {
      await route.fulfill({ json: taskResponse });
      return;
    }
    if (url.pathname.includes("/projects")) {
      await route.fulfill({ json: projectsResponse });
      return;
    }
    if (url.pathname.includes("/contexts")) {
      await route.fulfill({ json: tagsResponse });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
});

test("desktop task shell matches the Claude Design 1280x780 source surface", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 780 });
  await page.goto("/tasks/next");

  await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
  await expect(page.getByText("Brain Buddy")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Task navigation" })).toBeVisible();
  await expect(page.getByText("Tags")).toBeVisible();
  await expect(page.getByText("Contexts")).toHaveCount(0);
  await expect(page.locator("body")).toHaveScreenshot("claude-design-shell-1280x780.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.08
  });
});

test("mobile task shell uses the labelled drawer and avoids horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 402, height: 874 });
  await page.goto("/tasks/next");

  await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
  await page.getByRole("button", { name: "Open task navigation" }).click();
  await expect(page.getByRole("dialog", { name: "Task navigation" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await expect(page.locator("body")).toHaveScreenshot("claude-design-shell-mobile-402x874.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.08
  });
});

test("Brain Dump recording and review surfaces use source-derived mobile geometry", async ({ page }) => {
  await page.setViewportSize({ width: 402, height: 874 });
  await page.goto("/brain-dump/new");

  await expect(page.getByRole("dialog", { name: "Brain dump" })).toBeVisible();
  await expect(page.getByText("Nothing is saved until you stop")).toBeVisible();
  await expect(page.locator("body")).toHaveScreenshot("claude-design-brain-dump-recording-402x874.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.08
  });

  await page.getByRole("button", { name: "Stop & review" }).click();
  await expect(page.getByRole("heading", { name: "Review 9 tasks" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save 9 to inbox" })).toBeVisible();
  await expect(page.locator("body")).toHaveScreenshot("claude-design-brain-dump-review-402x874.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.08
  });
});
