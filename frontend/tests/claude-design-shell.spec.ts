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
  { id: "tag-laptop", name: "laptop", state: "active", revision: 1, open_task_count: 0 },
  { id: "tag-long-context", name: "waiting-for-quarterly-budget-approval", state: "active", revision: 1, open_task_count: 0 }
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
  consent: { microphone: true, external_processing_allowed: true, provider: "openai", recorded_at: "2026-07-15T10:00:00Z" },
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
  committable: true,
  reconciliation_quality: "accurate",
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

test.describe("desktop task shell at the canonical 1240x800 viewport", () => {
  test.use({ viewport: { width: 1240, height: 800 } });

  test("desktop task shell matches the Claude Design 1240x800 source surface", async ({ page }) => {
    await page.goto("/tasks/next");

    await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
    await expect(page.getByText("Brain Buddy")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Task navigation" })).toBeVisible();
    await expect(page.getByText("Tags", { exact: true })).toBeVisible();
    await expect(page.getByText("Contexts", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "@calls" })).toBeVisible();

    await test.step("verify canonical shell geometry and honest gating", async () => {
      const banner = page.locator("header").first();
      const bannerBox = await banner.boundingBox();
      if (Math.round(bannerBox?.height ?? 0) !== 56) {
        throw new Error(`Expected a 56px topbar, received ${bannerBox?.height}px`);
      }
      const sidebar = page.locator("aside").first();
      const sidebarBox = await sidebar.boundingBox();
      if (Math.round(sidebarBox?.width ?? 0) !== 248) {
        throw new Error(`Expected a 248px sidebar, received ${sidebarBox?.width}px`);
      }
      // Zero secondary counts stay visible (Someday / maybe has 0 open tasks).
      await expect(page.getByRole("link", { name: "Someday / maybe 0" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Weekly review" })).toBeEnabled();
      await expect(page.getByRole("button", { name: "Think with CRT — Coming soon" })).toBeDisabled();
    });

    await test.step("keep wrapped desktop tag actions inside the sidebar", async () => {
      const sidebar = page.locator("aside").first();
      const tagName = "waiting-for-quarterly-budget-approval";
      await page.getByRole("link", { name: `#${tagName}` }).hover();
      await page.getByRole("button", { name: `Tag options ${tagName}` }).click();
      const dialog = page.getByRole("dialog", { name: `Edit tag ${tagName}` });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Rename" })).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Delete" })).toBeVisible();

      const [sidebarBox, dialogBox, overflow] = await Promise.all([
        sidebar.boundingBox(),
        dialog.boundingBox(),
        sidebar.evaluate((element) => element.scrollWidth - element.clientWidth)
      ]);
      if (!sidebarBox || !dialogBox) {
        throw new Error("Expected desktop sidebar and tag dialog geometry");
      }
      if (dialogBox.x < sidebarBox.x || dialogBox.x + dialogBox.width > sidebarBox.x + sidebarBox.width) {
        throw new Error(`Expected desktop tag dialog inside sidebar bounds: ${JSON.stringify({ sidebarBox, dialogBox })}`);
      }
      if (dialogBox.y < sidebarBox.y || dialogBox.y + dialogBox.height > sidebarBox.y + sidebarBox.height) {
        throw new Error(`Expected desktop tag dialog inside sidebar vertical bounds: ${JSON.stringify({ sidebarBox, dialogBox })}`);
      }
      if (overflow !== 0) {
        throw new Error(`Expected no desktop sidebar overflow, received ${overflow}px`);
      }

      await page.getByRole("button", { name: `Tag options ${tagName}` }).click();
      await expect(dialog).toHaveCount(0);
    });

    await expect(page.locator("body")).toHaveScreenshot("claude-design-shell-1240x800.png", {
      animations: "disabled",
      maxDiffPixelRatio: 0.02
    });
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

  await test.step("keep the canonical task-row link addressable while the mobile-only title stays hidden", async () => {
    await expect(page.getByRole("link", { name: "Fix onboarding drop-off" })).toBeVisible();
    await expect(page.locator("p", { hasText: "Fix onboarding drop-off" })).toBeHidden();
  });

  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("heading", { name: "Task detail" })).toHaveCount(0);
});

test("task detail preserves the filtered route, focus, and Back history after detail whitespace clicks", async ({ page }) => {
  await page.setViewportSize({ width: 1240, height: 800 });
  await page.goto("/tasks/next?sort=priority&q=Persisted");

  const originLink = page.getByRole("link", { name: "Fix onboarding drop-off" });
  await originLink.click();
  await expect(page).toHaveURL(/\/tasks\/next\/task-2\?sort=priority&q=Persisted$/);

  const detailHeading = page.getByRole("heading", { name: "Task detail" });
  await expect(detailHeading).toBeFocused();

  await test.step("ignore noninteractive Agent whitespace without adding a same-URL history entry", async () => {
    await page.getByTestId("task-detail-agent").click();
    await expect(page).toHaveURL(/\/tasks\/next\/task-2\?sort=priority&q=Persisted$/);
  });

  await page.goBack();
  await expect(page).toHaveURL(/\/tasks\/next\?sort=priority&q=Persisted$/);
  await expect(detailHeading).toHaveCount(0);
  await expect(originLink).toBeFocused();
});

test("mobile task detail pushes the list pane and browser back restores it", async ({ page }) => {
  await page.setViewportSize({ width: 402, height: 874 });
  await page.goto("/tasks/next");

  await page.getByRole("link", { name: "Fix onboarding drop-off" }).click();
  await expect(page.getByRole("button", { name: "Back to list" })).toBeVisible();
  await expect(page.getByText("Fix onboarding drop-off", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Next actions" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Agent" })).toBeVisible();
  await expect(page.getByText("Coming soon")).toBeVisible();
  await expect(page.locator("body")).toHaveScreenshot("claude-design-task-detail-mobile-402x874.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.02
  });

  await page.goBack();
  await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Back to list" })).toHaveCount(0);
});

test("mobile task detail focuses the announced heading on open, restores origin link focus via Back to list, and avoids a Back/Close history ping-pong", async ({ page }) => {
  await page.setViewportSize({ width: 402, height: 874 });
  await page.goto("/tasks/waiting");
  await expect(page.getByRole("heading", { name: "Waiting for" })).toBeVisible();

  await test.step("navigate to Next actions via the drawer, establishing the list history entry detail is opened from", async () => {
    await page.getByRole("button", { name: "Open task navigation" }).click();
    await page.getByRole("dialog", { name: "Task navigation" }).getByRole("link", { name: "Next actions" }).click();
    await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
  });

  const originLink = page.getByRole("link", { name: "Fix onboarding drop-off" });
  await originLink.click();

  const detailHeading = page.getByRole("heading", { name: "Task detail" });
  await test.step("opening task detail at a narrow width focuses the announced (visually hidden) heading", async () => {
    await expect(detailHeading).toBeFocused();
    await expect(page.getByRole("heading", { name: "Next actions" })).toHaveCount(0);
  });

  await test.step("visible Back to list returns to the prior list history entry and restores focus to the origin link", async () => {
    await page.getByRole("button", { name: "Back to list" }).click();
    await expect(page).toHaveURL(/\/tasks\/next$/);
    await expect(detailHeading).toHaveCount(0);
    await expect(originLink).toBeFocused();
  });

  await test.step("the next browser Back reaches the pre-list history entry, not a resurrected detail", async () => {
    await page.goBack();
    await expect(page.getByRole("heading", { name: "Waiting for" })).toBeVisible();
    await expect(detailHeading).toHaveCount(0);
  });
});

test.describe("desktop deep-linked task detail at 1240x800", () => {
  test.use({ viewport: { width: 1240, height: 800 } });

  test("a direct deep link to task detail focuses the heading and Close falls back to a history replace, preserving query/group state and not reviving detail on Back", async ({ page }) => {
    await page.goto("/tasks/next/task-2?sort=priority&q=Persisted&group=project");

    const detailHeading = page.getByRole("heading", { name: "Task detail" });
    await expect(detailHeading).toBeFocused();

    await page.getByRole("button", { name: "Close" }).click();
    await expect(page).toHaveURL(/\/tasks\/next\?sort=priority&q=Persisted&group=project$/);
    await expect(detailHeading).toHaveCount(0);

    await page.goBack();
    await expect(detailHeading).toHaveCount(0);
  });
});

test("mobile task detail wraps a long task title without horizontal overflow", async ({ page }) => {
  const longTitle = "Prepare a comprehensive accessibility and route-history regression evidence package for the task-detail workflow";
  await page.route("**/api/tasks/task-2", async (route) => {
    await route.fulfill({ json: { ...taskResponse.items[1], title: longTitle } });
  });
  await page.setViewportSize({ width: 402, height: 874 });
  await page.goto("/tasks/next");
  await page.getByRole("link", { name: "Fix onboarding drop-off" }).click();

  const mobileTitle = page.getByText(longTitle, { exact: true });
  await expect(mobileTitle).toBeVisible();
  await test.step("keep the full mobile detail title readable inside the viewport", async () => {
    const titleMetrics = await mobileTitle.evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      whiteSpace: getComputedStyle(element).whiteSpace
    }));
    if (titleMetrics.scrollWidth > titleMetrics.clientWidth || titleMetrics.whiteSpace === "nowrap") {
      throw new Error(`Expected a wrapped mobile title, received ${JSON.stringify(titleMetrics)}`);
    }
  });
});

test("mobile pushed task detail uses its own summary-first topbar and exposes 44px task controls", async ({ page }) => {
  await page.route("**/api/tasks/task-2", async (route) => {
    await route.fulfill({
      json: {
        ...taskResponse.items[1],
        subtasks: [{ id: "subtask-1", title: "Confirm the reproduction", state: "open", revision: 1 }]
      }
    });
  });
  await page.setViewportSize({ width: 402, height: 874 });
  await page.goto("/tasks/next/task-2");

  await test.step("show the detail topbar and concise summary before the editable form without the global shell topbar", async () => {
    await expect(page.locator("header")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Back to list" })).toHaveCount(1);
    await expect(page.getByText("Fix onboarding drop-off", { exact: true })).toBeVisible();
    const summary = page.getByTestId("task-detail-summary");
    const form = page.locator("form").first();
    await expect(summary).toContainText("Next actions");
    const [summaryBox, formBox] = await Promise.all([summary.boundingBox(), form.boundingBox()]);
    if (!summaryBox || !formBox || summaryBox.y >= formBox.y) {
      throw new Error(`Expected a summary before the detail form, received ${JSON.stringify({ summaryBox, formBox })}`);
    }
  });

  await test.step("keep subtask completion at or above the 44px mobile target", async () => {
    const button = page.getByRole("button", { name: "Complete Confirm the reproduction" });
    const box = await button.boundingBox();
    if (!box || box.width < 44 || box.height < 44) {
      throw new Error(`Expected a >=44px mobile subtask target, received ${JSON.stringify(box)}`);
    }
  });
});

test.describe("mobile task shell at the canonical 375x812 viewport", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("mobile task shell uses the labelled drawer and avoids horizontal overflow", async ({ page }) => {
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
    await test.step("Verify drawer CRUD stays reachable and Escape closes the drawer", async () => {
      const drawer = page.getByRole("dialog", { name: "Task navigation" });
      await expect(drawer.getByRole("button", { name: "New project" })).toBeVisible();
      await expect(drawer.getByRole("button", { name: "New tag" })).toBeVisible();
      await expect(drawer.getByRole("button", { name: "Project options Launch v2" })).toBeVisible();
    });
    await test.step("Keep project and tag options at or above the 44px mobile target", async () => {
      const drawer = page.getByRole("dialog", { name: "Task navigation" });
      const targets = await Promise.all([
        drawer.getByRole("button", { name: "Project options Launch v2" }).boundingBox(),
        drawer.getByRole("button", { name: "Tag options deep-work" }).boundingBox()
      ]);
      if (targets.some((box) => !box || box.width < 44 || box.height < 44)) {
        throw new Error(`Expected >=44px drawer option targets, received ${JSON.stringify(targets)}`);
      }
    });
    await test.step("Keep wrapped mobile tag actions inside the drawer", async () => {
      const drawer = page.getByRole("dialog", { name: "Task navigation" });
      const scroller = drawer.locator(".overflow-y-auto");
      const tagName = "waiting-for-quarterly-budget-approval";
      await drawer.getByRole("button", { name: `Tag options ${tagName}` }).click();
      const dialog = drawer.getByRole("dialog", { name: `Edit tag ${tagName}` });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Rename" })).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Delete" })).toBeVisible();

      const [scrollerBox, dialogBox, overflow] = await Promise.all([
        scroller.boundingBox(),
        dialog.boundingBox(),
        scroller.evaluate((element) => element.scrollWidth - element.clientWidth)
      ]);
      if (!scrollerBox || !dialogBox) {
        throw new Error("Expected mobile drawer scroller and tag dialog geometry");
      }
      if (dialogBox.x < scrollerBox.x || dialogBox.x + dialogBox.width > scrollerBox.x + scrollerBox.width) {
        throw new Error(`Expected mobile tag dialog inside drawer bounds: ${JSON.stringify({ scrollerBox, dialogBox })}`);
      }
      if (dialogBox.y < scrollerBox.y || dialogBox.y + dialogBox.height > scrollerBox.y + scrollerBox.height) {
        throw new Error(`Expected mobile tag dialog inside drawer vertical bounds: ${JSON.stringify({ scrollerBox, dialogBox })}`);
      }
      if (overflow !== 0) {
        throw new Error(`Expected no mobile drawer overflow, received ${overflow}px`);
      }

      await drawer.getByRole("button", { name: `Tag options ${tagName}` }).click();
      await expect(dialog).toHaveCount(0);
    });
    await expect(page.locator("body")).toHaveScreenshot("claude-design-shell-mobile-375x812.png", {
      animations: "disabled",
      maxDiffPixelRatio: 0.02
    });
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Task navigation" })).toHaveCount(0);
  });

  test("mobile tag options hit target does not overlap the tag navigation link, which stays tappable", async ({ page }) => {
    await page.goto("/tasks/next");
    await page.getByRole("button", { name: "Open task navigation" }).click();
    const drawer = page.getByRole("dialog", { name: "Task navigation" });
    const tagLink = drawer.getByRole("link", { name: "#deep-work" });
    const tagOptions = drawer.getByRole("button", { name: "Tag options deep-work" });
    await expect(tagLink).toBeVisible();
    await expect(tagOptions).toBeVisible();

    await test.step("keep the options hit target from covering the tag link's own hit target", async () => {
      const [linkBox, optionsBox] = await Promise.all([tagLink.boundingBox(), tagOptions.boundingBox()]);
      if (!linkBox || !optionsBox) {
        throw new Error("Expected geometry for both the tag link and its options target");
      }
      const overlaps =
        linkBox.x < optionsBox.x + optionsBox.width &&
        linkBox.x + linkBox.width > optionsBox.x &&
        linkBox.y < optionsBox.y + optionsBox.height &&
        linkBox.y + linkBox.height > optionsBox.y;
      if (overlaps) {
        throw new Error(`Expected the tag options target not to overlap the tag link, received ${JSON.stringify({ linkBox, optionsBox })}`);
      }
    });

    await test.step("tapping the tag navigation row still navigates instead of being intercepted", async () => {
      await tagLink.click();
      await expect(page).toHaveURL(/\/tags\/tag-deep-work/);
    });
  });
});

test.describe("Brain Dump mobile design surface", () => {
  test.use({ viewport: { width: 402, height: 874 } });

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
  await page.goto("/brain-dump/new");

  await test.step("Verify the Brain Dump mobile viewport", async () => {
    const viewport = page.viewportSize();
    await attachment("Brain Dump viewport", JSON.stringify(viewport), ContentType.JSON);
    if (viewport?.width !== 402 || viewport.height !== 874) {
      throw new Error(`Expected 402x874 viewport, received ${viewport?.width ?? "unknown"}x${viewport?.height ?? "unknown"}`);
    }
  });

  await expect(page.getByRole("dialog", { name: "Brain dump" })).toBeVisible();
  await page.getByRole("checkbox", { name: "Allow secure cloud transcription" }).check();
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
});

test.describe("desktop at-rest pane header and row anatomy at 1240x800", () => {
  test.use({ viewport: { width: 1240, height: 800 } });

  test("pane header stacks title over count with ghost Group by project and Sort actions", async ({ page }) => {
    await page.goto("/tasks/next");

    const heading = page.getByRole("heading", { name: "Next actions" });
    await expect(heading).toBeVisible();
    const count = page.getByText("6 tasks", { exact: true });
    await expect(count).toBeVisible();

    await test.step("title sits above the count, not inline with it", async () => {
      const [headingBox, countBox] = await Promise.all([heading.boundingBox(), count.boundingBox()]);
      if (!headingBox || !countBox) {
        throw new Error("Expected header title and count geometry");
      }
      if (countBox.y <= headingBox.y + headingBox.height / 2) {
        throw new Error(`Expected the count to sit below the title, received ${JSON.stringify({ headingBox, countBox })}`);
      }
      if (Math.round(headingBox.height) < 20) {
        throw new Error(`Expected a >=20px title line, received ${headingBox.height}px`);
      }
    });

    const groupButton = page.getByRole("button", { name: "Group by project" });
    const sortControl = page.getByLabel("Sort tasks");
    await expect(groupButton).toBeVisible();
    await expect(groupButton).toHaveAttribute("aria-pressed", "false");
    await expect(sortControl).toBeVisible();

    await test.step("ghost actions sit to the right of the stacked title/count", async () => {
      const [headingBox, groupBox] = await Promise.all([heading.boundingBox(), groupButton.boundingBox()]);
      if (!headingBox || !groupBox) {
        throw new Error("Expected title and Group by project geometry");
      }
      if (groupBox.x <= headingBox.x) {
        throw new Error(`Expected Group by project to sit right of the title, received ${JSON.stringify({ headingBox, groupBox })}`);
      }
    });
  });

  test("rows keep a readable title and a fixed right project column, wrapping metadata instead of truncating", async ({ page }) => {
    const longTitle = "Reconcile the Q3 quarterly budget approval workflow across finance, legal and the vendor onboarding pipeline";
    await page.route("**/api/tasks?**", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("state") !== "next") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        json: {
          items: [
            {
              ...taskResponse.items[0],
              id: "task-many-tags",
              title: longTitle,
              tag_ids: ["tag-context-calls", "tag-calls", "tag-errands", "tag-deep-work", "tag-laptop", "tag-long-context"],
              project_id: "project-onboarding"
            }
          ],
          next_cursor: null,
          has_more: false,
          counts_by_state: taskResponse.counts_by_state
        }
      });
    });

    await page.goto("/tasks/next");
    const titleLink = page.getByRole("link", { name: longTitle });
    await expect(titleLink).toBeVisible();

    await test.step("the full title renders on more than one line instead of truncating", async () => {
      const metrics = await titleLink.evaluate((element) => ({
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
        clientHeight: element.clientHeight,
        lineHeight: parseFloat(getComputedStyle(element).lineHeight || "0"),
        textOverflow: getComputedStyle(element).textOverflow
      }));
      if (metrics.textOverflow === "ellipsis") {
        throw new Error("Expected the row title to wrap, not truncate with an ellipsis");
      }
      if (!metrics.lineHeight || metrics.clientHeight < metrics.lineHeight * 1.5) {
        throw new Error(`Expected the title to span multiple lines, received ${JSON.stringify(metrics)}`);
      }
      if (metrics.scrollWidth > metrics.clientWidth + 1) {
        throw new Error(`Expected the wrapped title to fit its column without horizontal overflow, received ${JSON.stringify(metrics)}`);
      }
    });

    await test.step("the project name renders in a fixed right-hand column near the row's top edge", async () => {
      const row = page.locator('[role="listitem"]').first();
      const [rowBox, projectBox] = await Promise.all([
        row.boundingBox(),
        row.getByText("Onboarding drop-off", { exact: true }).first().boundingBox()
      ]);
      if (!rowBox || !projectBox) {
        throw new Error("Expected row and project column geometry");
      }
      if (projectBox.x + projectBox.width < rowBox.x + rowBox.width * 0.6) {
        throw new Error(`Expected the project label near the row's right edge, received ${JSON.stringify({ rowBox, projectBox })}`);
      }
    });
  });
});

test.describe("mobile at-rest topbar and card density at 402x874", () => {
  test.use({ viewport: { width: 402, height: 874 } });

  test("topbar stays compact: 44px hamburger, icon-only Brain dump, 32px avatar, no crowding wordmark", async ({ page }) => {
    await page.goto("/tasks/next");
    await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();

    const hamburger = page.getByRole("button", { name: "Open task navigation" });
    const brainDump = page.getByRole("button", { name: "Brain dump" });
    const avatar = page.getByLabel("max@example.test");

    const [hamburgerBox, brainDumpBox, avatarBox] = await Promise.all([
      hamburger.boundingBox(),
      brainDump.boundingBox(),
      avatar.boundingBox()
    ]);
    if (!hamburgerBox || !brainDumpBox || !avatarBox) {
      throw new Error("Expected compact mobile topbar geometry");
    }
    if (Math.round(hamburgerBox.height) < 44 || Math.round(hamburgerBox.width) < 44) {
      throw new Error(`Expected a >=44px hamburger target, received ${JSON.stringify(hamburgerBox)}`);
    }
    if (Math.round(avatarBox.height) !== 32 || Math.round(avatarBox.width) !== 32) {
      throw new Error(`Expected a 32px avatar, received ${JSON.stringify(avatarBox)}`);
    }

    await test.step("Brain dump is icon-only with an accessible name, not a wide labelled button", async () => {
      await expect(brainDump.getByText("Brain dump", { exact: true })).toBeHidden();
      if (brainDumpBox.width > 60) {
        throw new Error(`Expected an icon-only Brain dump control, received ${brainDumpBox.width}px wide`);
      }
    });

    await test.step("the wordmark text does not crowd the compact topbar", async () => {
      await expect(page.getByText("Brain Buddy", { exact: true })).toBeHidden();
    });

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (overflow > 0) {
      throw new Error(`Expected no horizontal overflow, received ${overflow}px`);
    }
  });

  test("task cards use compact ~14px padding/radius, a >=44px check target, a wrapping title, and inline-wrapping chips instead of full-width strips", async ({ page }) => {
    await page.goto("/tasks/next");
    const row = page.locator('[role="listitem"]', { hasText: "Fix onboarding drop-off" });
    await expect(row).toBeVisible();

    await test.step("card padding and radius are compact", async () => {
      const styles = await row.evaluate((element) => {
        const computed = getComputedStyle(element);
        return { paddingLeft: parseFloat(computed.paddingLeft), borderRadius: parseFloat(computed.borderTopLeftRadius) };
      });
      if (styles.paddingLeft < 12 || styles.paddingLeft > 16) {
        throw new Error(`Expected ~14px card padding, received ${styles.paddingLeft}px`);
      }
      if (styles.borderRadius < 12 || styles.borderRadius > 16) {
        throw new Error(`Expected ~14px card radius, received ${styles.borderRadius}px`);
      }
    });

    await test.step("the complete checkbox exposes a >=44px hit target", async () => {
      const checkButton = row.getByRole("button", { name: "Complete Fix onboarding drop-off" });
      const box = await checkButton.boundingBox();
      if (!box || box.width < 44 || box.height < 44) {
        throw new Error(`Expected a >=44px mobile check target, received ${JSON.stringify(box)}`);
      }
    });

    await test.step("tag chips wrap inline below the title instead of rendering as full-width strips", async () => {
      const chip = row.getByText("#deep-work", { exact: true });
      const [rowBox, chipBox] = await Promise.all([row.boundingBox(), chip.boundingBox()]);
      if (!rowBox || !chipBox) {
        throw new Error("Expected row and chip geometry");
      }
      if (chipBox.width > rowBox.width * 0.6) {
        throw new Error(`Expected a compact inline chip, received ${chipBox.width}px wide inside a ${rowBox.width}px row`);
      }
    });

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (overflow > 0) {
      throw new Error(`Expected no horizontal overflow, received ${overflow}px`);
    }

    await expect(page.locator("body")).toHaveScreenshot("claude-design-task-cards-mobile-402x874.png", {
      animations: "disabled",
      maxDiffPixelRatio: 0.02
    });
  });

  test("Waiting rows render real waiting metadata, never a fabricated status", async ({ page }) => {
    await page.route("**/api/tasks?**", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("state") !== "waiting") {
        await route.fallback();
        return;
      }
      await route.fulfill({
        json: {
          items: [
            {
              ...taskResponse.items[1],
              id: "task-waiting",
              title: "Get sign-off from finance",
              state: "waiting",
              waiting_for: "Finance approval from Priya",
              waiting_since: "2026-07-14T09:00:00Z",
              project_id: null,
              tag_ids: []
            }
          ],
          next_cursor: null,
          has_more: false,
          counts_by_state: taskResponse.counts_by_state
        }
      });
    });

    await page.goto("/tasks/waiting");
    await expect(page.getByText("Get sign-off from finance")).toBeVisible();
    await expect(page.getByText(/Waiting on Finance approval from Priya/)).toBeVisible();
    await expect(page.getByText(/since Jul 14/)).toBeVisible();
    await expect(page.getByText("sent Tue", { exact: false })).toHaveCount(0);
  });
});

test.describe("Group by project at 1240x800", () => {
  test.use({ viewport: { width: 1240, height: 800 } });

  test("Group by project is URL-backed, drains every cursor page, orders No project last, and hides duplicate row labels", async ({ page }) => {
    const pageOne = {
      items: [
        { ...taskResponse.items[0], id: "grp-1", title: "Grouped launch task", project_id: "project-launch", tag_ids: [] },
        { ...taskResponse.items[1], id: "grp-2", title: "Grouped onboarding task", project_id: "project-onboarding", tag_ids: [] },
        { ...taskResponse.items[0], id: "grp-3", title: "Grouped unassigned task", project_id: null, tag_ids: [] }
      ],
      next_cursor: "group-page-2",
      has_more: true,
      counts_by_state: taskResponse.counts_by_state
    };
    const pageTwo = {
      items: [{ ...taskResponse.items[0], id: "grp-4", title: "Second page launch task", project_id: "project-launch", tag_ids: [] }],
      next_cursor: null,
      has_more: false,
      counts_by_state: taskResponse.counts_by_state
    };

    await page.route("**/api/tasks?**", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("state") !== "next") {
        await route.fallback();
        return;
      }
      if (url.searchParams.get("cursor") === "group-page-2") {
        await route.fulfill({ json: pageTwo });
        return;
      }
      await route.fulfill({ json: pageOne });
    });

    await page.goto("/tasks/next");
    await expect(page.getByText("Grouped launch task")).toBeVisible();

    await page.getByRole("button", { name: "Group by project" }).click();
    await expect(page).toHaveURL(/[?&]group=project/);

    const groupedList = page.getByTestId("grouped-task-list");
    await expect(groupedList).toBeVisible();
    await expect(groupedList.getByText("Second page launch task")).toBeVisible({ timeout: 10_000 });

    await test.step("groups are ordered with No project last", async () => {
      const headingTexts = await groupedList.getByRole("heading", { level: 2 }).allTextContents();
      const noProjectIndex = headingTexts.findIndex((text) => text.includes("No project"));
      if (noProjectIndex !== headingTexts.length - 1) {
        throw new Error(`Expected No project last, received ${JSON.stringify(headingTexts)}`);
      }
    });

    await test.step("a row inside a group does not repeat the project label already shown in the group heading", async () => {
      const launchHeading = groupedList.getByRole("heading", { name: /Launch v2/ });
      const launchSection = page.locator("section", { has: launchHeading });
      await expect(launchSection.getByText("Launch v2", { exact: true })).toHaveCount(1);
    });

    await page.reload();
    await expect(page.getByTestId("grouped-task-list")).toBeVisible();
    await expect(page.getByRole("button", { name: "Group by project" })).toHaveAttribute("aria-pressed", "true");
  });
});
