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
  source_segment_ids: [`segment-${index + 1}`],
  deleted: false,
  user_edited: false,
  revision: 1
}));

const brainDumpSegments = [
  "I really need to renew the car insurance before it lapses",
  "oh and reply to Anna about the offsite she pinged me yesterday",
  "book the flights to Lisbon while they're still cheap",
  "the pricing page copy needs an update after the plan change",
  "prepare interview questions for Vlad on Thursday",
  "call the dentist to move Monday's appointment",
  "take the car in for the flat tire",
  "draft the launch announcement post for v2",
  "cancel the SaaS subscriptions we don't use anymore"
].map((text, index) => ({
  id: `segment-${index + 1}`,
  sequence: index + 1,
  text,
  stability: "stable",
  provider_role: "accurate"
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
  segments: brainDumpSegments,
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
      await route.fulfill({
        json: { id: "user-1", email: "max@example.test", feature_flags: { voice_brain_dump: true } }
      });
      return;
    }
    if (url.pathname === "/api/brain-dump-providers") {
      await route.fulfill({ json: { accurate_stt: "openai", reconciler: "openai" } });
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
    await expect(page.getByText("BrainBuddy")).toBeVisible();
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
      await expect(page.getByRole("button", { name: "Thinking Mode — Coming soon" })).toBeDisabled();
    });

    await test.step("keep enabled primary and secondary actions readable at rest, on hover, and while pressed", async () => {
      for (const name of ["Brain dump", "New project", "New tag"]) {
        const button = page.getByRole("button", { name, exact: true });
        for (const state of ["rest", "hover", "pressed"]) {
          if (state === "hover") await button.hover();
          if (state === "pressed") await page.mouse.down();
          await button.evaluate((element) => Promise.all(element.getAnimations().map((animation) => animation.finished)));
          const contrast = await button.evaluate((element) => {
            const style = getComputedStyle(element);
            const background = style.backgroundColor === "rgba(0, 0, 0, 0)"
              ? getComputedStyle(element.closest(".bg-surface-base")!).backgroundColor
              : style.backgroundColor;
            const luminance = (color: string) => {
              const channels = color.match(/[\d.]+/g)!.slice(0, 3).map((value) => {
                const channel = Number(value) / 255;
                return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
              });
              return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
            };
            const values = [luminance(style.color), luminance(background)].sort((a, b) => a - b);
            return (values[1] + 0.05) / (values[0] + 0.05);
          });
          await attachment(`${name}: ${state} contrast`, `${contrast.toFixed(2)}:1`, ContentType.TEXT);
          if (contrast < 4.5) throw new Error(`${name} contrast in ${state} was ${contrast}:1; expected at least 4.5:1`);
        }
        await page.locator("header").first().hover();
        await page.mouse.up();
      }
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
      maxDiffPixelRatio: 0.08
    });
  });
});

test("clicking a task opens the docked right-side detail panel", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 780 });
  await page.goto("/tasks/next");

  await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
  // Unselected lists keep the workspace width instead of reserving an empty column.
  await expect(page.getByRole("complementary", { name: "Task detail" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Task detail" })).toHaveCount(0);

  await page.getByRole("link", { name: "Fix onboarding drop-off" }).click();
  await expect(page.getByRole("heading", { name: "Task detail" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Title", exact: true })).toHaveValue("Fix onboarding drop-off");
  await expect(page.getByLabel("New subtask title")).toBeVisible();
  await expect(page.getByLabel("New comment")).toBeVisible();

  await test.step("keep the canonical task-row link addressable while the panel is open", async () => {
    await expect(page.getByRole("link", { name: "Fix onboarding drop-off" })).toBeVisible();
  });

  await test.step("give task content room before secondary properties without overflowing the workspace", async () => {
    const panel = await page.getByRole("complementary", { name: "Task detail" }).boundingBox();
    const details = await page.getByRole("textbox", { name: "Details", exact: true }).boundingBox();
    const properties = await page.getByRole("region", { name: "Task properties" }).boundingBox();
    expect(panel?.width).toBeGreaterThanOrEqual(380);
    expect(details).not.toBeNull();
    expect(properties).not.toBeNull();
    expect(details!.y + details!.height).toBeLessThanOrEqual(properties!.y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0);
  });

  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("heading", { name: "Task detail" })).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "Task detail" })).toHaveCount(0);
});

test("task detail preserves the filtered route, focus, and Back history after detail whitespace clicks", async ({ page }) => {
  await page.setViewportSize({ width: 1240, height: 800 });
  await page.goto("/tasks/next?sort=priority&q=Persisted");

  const originLink = page.getByRole("link", { name: "Fix onboarding drop-off" });
  await originLink.click();
  await expect(page).toHaveURL(/\/tasks\/next\/task-2\?sort=priority&q=Persisted$/);

  const detailHeading = page.getByRole("heading", { name: "Task detail" });
  await expect(detailHeading).toBeFocused();

  await test.step("ignore noninteractive panel whitespace without adding a same-URL history entry", async () => {
    await page.getByRole("heading", { name: "Comments" }).click();
    await expect(page).toHaveURL(/\/tasks\/next\/task-2\?sort=priority&q=Persisted$/);
  });

  await page.goBack();
  await expect(page).toHaveURL(/\/tasks\/next\?sort=priority&q=Persisted$/);
  await expect(detailHeading).toHaveCount(0);
  await expect(originLink).toBeFocused();
});

test("mobile task detail slides over the list and browser back restores it", async ({ page }) => {
  await page.setViewportSize({ width: 402, height: 874 });
  await page.goto("/tasks/next");

  await page.getByRole("link", { name: "Fix onboarding drop-off" }).click();
  await expect(page.getByRole("heading", { name: "Task detail" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Title", exact: true })).toHaveValue("Fix onboarding drop-off");
  await expect(page.getByRole("heading", { name: "Comments" })).toBeVisible();
  await expect(page.locator("body")).toHaveScreenshot("claude-design-task-detail-mobile-402x874.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.08
  });

  await page.goBack();
  await expect(page.getByRole("heading", { name: "Task detail" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
});

test("mobile task detail wraps a long task title without horizontal overflow", async ({ page }) => {
  const longTitle = "Prepare a comprehensive accessibility and route-history regression evidence package for the task-detail workflow";
  await page.route("**/api/tasks/task-2", async (route) => {
    await route.fulfill({ json: { ...taskResponse.items[1], title: longTitle } });
  });
  await page.setViewportSize({ width: 402, height: 874 });
  await page.goto("/tasks/next");
  await page.getByRole("link", { name: "Fix onboarding drop-off" }).click();

  const mobileTitle = page.getByRole("textbox", { name: "Title", exact: true });
  await expect(mobileTitle).toHaveValue(longTitle);
  await test.step("keep the full mobile detail title readable inside the viewport", async () => {
    // The title textarea auto-grows to its content, so the full title must fit
    // without horizontal or vertical clipping.
    const titleMetrics = await mobileTitle.evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight
    }));
    if (titleMetrics.scrollWidth > titleMetrics.clientWidth || titleMetrics.scrollHeight > titleMetrics.clientHeight + 1) {
      throw new Error(`Expected a fully visible wrapped mobile title, received ${JSON.stringify(titleMetrics)}`);
    }
    const completionTarget = await page.getByRole("button", { name: "Complete task", exact: true }).boundingBox();
    expect(completionTarget?.width).toBeGreaterThanOrEqual(44);
    expect(completionTarget?.height).toBeGreaterThanOrEqual(44);
  });
});

test.describe("mobile task shell at the canonical 375x812 viewport", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("mobile task shell uses the labelled drawer and avoids horizontal overflow", async ({ page }) => {
    await page.goto("/tasks/next");

    await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
    await test.step("make completion touchable and keep capture guidance within the field", async () => {
      const complete = page.getByRole("button", { name: "Complete Fix onboarding drop-off" });
      const box = await complete.boundingBox();
      await attachment("Completion target", JSON.stringify(box), ContentType.JSON);
      if (!box || box.width < 44 || box.height < 44) throw new Error("Expected a completion target of at least 44×44 CSS pixels");
      const capture = page.getByRole("combobox", { name: "New task title" });
      const fits = await capture.evaluate((element: HTMLInputElement) => {
        const canvas = document.createElement("canvas");
        const context = canvas.getContext("2d")!;
        context.font = getComputedStyle(element).font;
        return context.measureText(element.placeholder).width <= element.clientWidth;
      });
      await attachment("Capture placeholder fits", String(fits), ContentType.TEXT);
      if (!fits) throw new Error("The capture placeholder exceeds the visible input width");
    });
    await test.step("search from the mobile drawer and return to the filtered list", async () => {
      await page.goto("/tasks/next?sort=due");
      await page.getByRole("button", { name: "Open task navigation" }).click();
      const drawer = page.getByRole("dialog", { name: "Task navigation" });
      const search = drawer.getByRole("searchbox", { name: "Search tasks" });
      await search.pressSequentially("review homepage");
      await search.press("Enter");
      await expect(drawer).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Open task navigation" })).toBeFocused();
      await expect(page).toHaveURL(/\/tasks\/next\?sort=due&q=review\+homepage$/);
      await page.getByRole("button", { name: "Open task navigation" }).click();
      await drawer.getByRole("searchbox", { name: "Search tasks" }).fill("");
      await drawer.getByRole("button", { name: "Search", exact: true }).click();
      await expect(page).toHaveURL(/\/tasks\/next\?sort=due$/);
      await page.goto("/tasks/next");
    });
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
      maxDiffPixelRatio: 0.08
    });
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Task navigation" })).toHaveCount(0);
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
  await expect(page.getByText("Nothing is saved until you stop")).toBeVisible();
  await expect(page.locator("body")).toHaveScreenshot("claude-design-brain-dump-recording-402x874.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.08
  });

  await page.getByRole("button", { name: "Stop & review" }).click();
  await expect(page.getByRole("heading", { name: "Review 9 tasks" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Send 9 to inbox" })).toBeVisible();
  await expect(page.locator("body")).toHaveScreenshot("claude-design-brain-dump-review-402x874.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.08
  });
});
});
