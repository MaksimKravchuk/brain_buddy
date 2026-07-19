import { expect, test } from "./allure.fixtures";
import { ContentType, attachment } from "allure-js-commons";

const taskResponse = {
  items: [
    {
      id: "task-1",
      title: "Take car in for the flat tire",
      details: null,
      state: "next",
      project_id: "project-personal",
      tag_ids: ["tag-errands"],
      due_date: "2026-07-18",
      priority: "none",
      waiting_for: null,
      waiting_since: null,
      order_key: 1,
      source_capture_ids: [],
      created_at: "2026-07-15T10:00:00Z",
      updated_at: "2026-07-15T10:00:00Z",
      completed_at: null,
      cancelled_at: null,
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
      tag_ids: ["tag-deep-work"],
      due_date: null,
      priority: "none",
      waiting_for: null,
      waiting_since: null,
      order_key: 2,
      source_capture_ids: [],
      created_at: "2026-07-15T10:00:00Z",
      updated_at: "2026-07-15T10:00:00Z",
      completed_at: null,
      cancelled_at: null,
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
  { id: "project-launch", name: "Launch v2", color: "#0ea5e9", state: "active", revision: 1, open_task_count: 2 },
  { id: "project-onboarding", name: "Onboarding drop-off", color: "#6366f1", state: "active", revision: 1, open_task_count: 1 },
  { id: "project-personal", name: "Personal admin", color: "#94a3b8", state: "active", revision: 1, open_task_count: 1 }
];

const tagsResponse = [
  { id: "tag-context-calls", name: "@calls", state: "active", revision: 1, open_task_count: 1 },
  { id: "tag-calls", name: "calls", state: "active", revision: 1, open_task_count: 2 },
  { id: "tag-errands", name: "errands", state: "active", revision: 1, open_task_count: 1 },
  { id: "tag-deep-work", name: "deep-work", state: "active", revision: 1, open_task_count: 1 },
  { id: "tag-laptop", name: "laptop", state: "active", revision: 1, open_task_count: 0 }
];

const brainDumpProposals = Array.from({ length: 9 }, (_, index) => ({
  id: `proposal-${index + 1}`,
  ordinal: index + 1,
  title: [
    "Renew car insurance",
    "Reply to Anna about the offsite",
    "Book flights to Lisbon",
    "Update pricing page copy",
    "Prepare interview questions for Vlad",
    "Call dentist to move Monday's appointment",
    "Take car in for the flat tire",
    "Draft launch announcement post",
    "Cancel unused SaaS subscriptions"
  ][index],
  status: index === 0 ? "ready_to_review" : index === 1 ? "wording_changing" : "provisional",
  source_segment_ids: ["segment-1"],
  deleted: false,
  user_edited: false,
  revision: 1
}));

const brainDumpRecordingResponse = {
  id: "brain_dump_1",
  owner_id: "user-1",
  kind: "voice_brain_dump",
  status: "recording",
  consent: { microphone: true, external_processing_allowed: false, provider: null, recorded_at: "2026-07-15T10:00:00Z" },
  segments: [],
  proposals: [],
  committed_task_ids: [],
  created_at: "2026-07-15T10:00:00Z",
  updated_at: "2026-07-15T10:00:00Z",
  revision: 1
};

const brainDumpReviewResponse = {
  ...brainDumpRecordingResponse,
  status: "awaiting_confirmation",
  proposals: brainDumpProposals,
  revision: 2
};

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
    const taskDetailMatch = url.pathname.match(/\/tasks\/(task-\d+)$/);
    if (taskDetailMatch) {
      const task = taskResponse.items.find((item) => item.id === taskDetailMatch[1]);
      await route.fulfill({ json: task ?? { detail: "Not found" }, status: task ? 200 : 404 });
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
    if (url.pathname.includes("/tags")) {
      await route.fulfill({ json: tagsResponse });
      return;
    }
    if (url.pathname === "/api/brain-dump-operations" && route.request().method() === "POST") {
      await route.fulfill({ json: brainDumpRecordingResponse });
      return;
    }
    if (url.pathname === "/api/brain-dump-operations/brain_dump_1/seal") {
      await route.fulfill({ json: brainDumpReviewResponse });
      return;
    }
    if (url.pathname === "/api/brain-dump-operations/brain_dump_1") {
      await route.fulfill({ json: brainDumpReviewResponse });
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
  await expect(page.getByText("Tags", { exact: true })).toBeVisible();
  await expect(page.getByText("Contexts", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "@calls" })).toBeVisible();
  await expect(page.locator("body")).toHaveScreenshot("claude-design-shell-1280x780.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.08
  });
});

test("clicking a task expands inline task detail in place", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 780 });
  await page.goto("/tasks/next");

  await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Task detail" })).toHaveCount(0);

  await page.getByRole("link", { name: "Fix onboarding drop-off" }).click();
  await expect(page.getByRole("heading", { name: "Task detail" })).toBeVisible();
  await expect(page.getByLabel("New subtask title")).toBeVisible();
  await expect(page.getByLabel("New comment")).toBeVisible();

  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("heading", { name: "Task detail" })).toHaveCount(0);
});

test("mobile task shell uses the labelled drawer and avoids horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 402, height: 874 });
  await page.goto("/tasks/next");

  await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
  await page.getByRole("button", { name: "Open task navigation" }).click();
  await expect(page.getByRole("dialog", { name: "Task navigation" })).toBeVisible();
  await test.step("Verify the mobile task drawer fits inside the viewport", async () => {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    await attachment("Viewport overflow", `Horizontal overflow: ${overflow}px`, ContentType.TEXT);
    if (overflow > 0) {
      throw new Error(`Expected no horizontal overflow, received ${overflow}px`);
    }
  });
  await expect(page.locator("body")).toHaveScreenshot("claude-design-shell-mobile-402x874.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.08
  });
});

test("Brain Dump recording and review surfaces use source-derived mobile geometry", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: async () => ({ getTracks: () => [{ stop: () => undefined }] }) }
    });
    class FakeSpeechRecognition {
      continuous = false;
      interimResults = false;
      lang = "";
      onresult: (() => void) | null = null;
      onerror: (() => void) | null = null;
      start() {
        return undefined;
      }
      stop() {
        return undefined;
      }
    }
    const writableWindow = window as typeof window & {
      SpeechRecognition?: typeof FakeSpeechRecognition;
      webkitSpeechRecognition?: typeof FakeSpeechRecognition;
    };
    writableWindow.SpeechRecognition = FakeSpeechRecognition;
    writableWindow.webkitSpeechRecognition = FakeSpeechRecognition;
  });
  await page.setViewportSize({ width: 402, height: 874 });
  await page.goto("/brain-dump/new");

  await expect(page.getByRole("dialog", { name: "Brain dump" })).toBeVisible();
  await page.getByRole("button", { name: "Record" }).click();
  await expect(page.getByText("Recording")).toBeVisible();
  await expect(page.getByText("Nothing is saved until review")).toBeVisible();
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
