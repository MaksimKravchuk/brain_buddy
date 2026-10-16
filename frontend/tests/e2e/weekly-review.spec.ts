/// <reference types="node" />

import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { request as playwrightRequest, type Page, type TestInfo } from "@playwright/test";
import { expect, test } from "../allure.fixtures";
import { apiGet, apiPatch, apiPost, backendUrl, createTaskViaApi, mintInvite, password, signupThroughUi, uniqueEmail } from "./gtdHelpers";
import { runReviewSweep, seedAgedTask } from "./testControl";

const operatorEmail = process.env.BRAIN_BUDDY_ADMIN_EMAIL;
const operatorPassword = process.env.BRAIN_BUDDY_ADMIN_PASSWORD ?? password;
const NARROW = { width: 390, height: 851 };
const DESKTOP = { width: 1280, height: 800 };

test.beforeEach(() => {
  test.skip(!operatorEmail, "BRAIN_BUDDY_ADMIN_EMAIL is required to turn weekly_review on for one synthetic account");
});

/** Exposure of the review is per account: only the one synthetic account gets the flag. */
async function enableWeeklyReview(email: string): Promise<void> {
  const operator = await playwrightRequest.newContext();
  try {
    const login = await operator.post(`${backendUrl}/api/auth/login`, { data: { email: operatorEmail, password: operatorPassword } });
    expect(login.ok(), await login.text()).toBe(true);
    const mode = await operator.put(`${backendUrl}/api/admin/feature-flags/weekly_review/mode`, { data: { mode: "selected_users" } });
    expect(mode.ok(), await mode.text()).toBe(true);
    const selected = await operator.post(`${backendUrl}/api/admin/feature-flags/weekly_review/selected-users`, { data: { email } });
    expect(selected.ok(), await selected.text()).toBe(true);
  } finally {
    await operator.dispose();
  }
}

async function newReviewer(page: Page, testInfo: TestInfo): Promise<string> {
  const email = uniqueEmail("review", testInfo);
  await signupThroughUi(page, email, await mintInvite());
  await enableWeeklyReview(email);
  await page.reload();
  return email;
}

/**
 * No axe violation of any impact. The task list's own rows (`article` with `role="listitem"`, feature 017)
 * carry one older minor finding, `aria-allowed-role`, that is not this feature's markup.
 */
async function expectAccessible(page: Page): Promise<void> {
  // Colours come from the Carry On design system by product decision, so text colour contrast is not gated by tests.
  const { violations } = await new AxeBuilder({ page }).disableRules(["aria-allowed-role", "color-contrast"]).analyze();
  expect(violations.map((violation) => ({ id: violation.id, impact: violation.impact, html: violation.nodes.map((node) => node.html) }))).toEqual([]);
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
}

/** Press Tab until the named button has focus: the keyboard-only way to reach it. */
async function tabTo(page: Page, name: string | RegExp, exact = false): Promise<void> {
  const target = page.getByRole("button", { name, exact }).first();
  for (let presses = 0; presses < 40; presses += 1) {
    if (await target.evaluate((element) => element === document.activeElement).catch(() => false)) {
      return;
    }
    await page.keyboard.press("Tab");
  }
  throw new Error(`Tab never reached the button ${String(name)}`);
}

test("020-FR-004 020-FR-040 020-FR-048 020-FR-051 020-SC-006 a stalled task: the explainer, the marker, a decision and its Undo", async ({ page }, testInfo) => {
  await page.setViewportSize(DESKTOP);
  const email = await newReviewer(page, testInfo);

  await test.step("D-05 asks first, once, and passes the axe scan at desktop and 390 px", async () => {
    const dialog = page.getByRole("dialog", { name: "How Next stays fresh" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "How Next stays fresh" })).toBeFocused();
    await expectAccessible(page);
    await page.setViewportSize(NARROW);
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
    await page.setViewportSize(DESKTOP);
    await dialog.getByRole("button", { name: "Got it" }).click();
    await expect(dialog).toBeHidden();
  });

  await test.step("a task 15 days in Next asks for a decision; the marker opens the dialog", async () => {
    await seedAgedTask(email, 15, "Renovate the bathroom");
    await page.goto("/tasks/next");
    await expect(page.getByRole("button", { name: /Open decision for Renovate the bathroom/ })).toBeVisible();
    await expectAccessible(page);
    await page.getByRole("button", { name: /Open decision for Renovate the bathroom/ }).click();
    const dialog = page.getByRole("dialog", { name: "Renovate the bathroom" });
    await expect(dialog).toBeVisible();
    await expectAccessible(page);
    await page.setViewportSize(NARROW);
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
    await page.setViewportSize(DESKTOP);
  });

  await test.step("Release to Someday, then Undo with the keyboard: the task is back in Next", async () => {
    await page.getByRole("button", { name: /^Release to Someday/ }).click();
    await expect(page.getByRole("button", { name: /^Undo: Released to Someday Renovate the bathroom/ })).toBeVisible();
    await expect(page.getByRole("link", { name: "Renovate the bathroom" })).toHaveCount(0);
    await page.keyboard.press("Control+z");
    // The seed sets a start older than the activation; the server's restore clamps it, so the marker is not asserted.
    await expect(page.getByRole("link", { name: "Renovate the bathroom" })).toBeVisible();
  });
});

test("020-FR-015 020-FR-004 auto-park moves an undecided task to Someday; While you were away lists it and Return brings it back", async ({ page }, testInfo) => {
  await page.setViewportSize(DESKTOP);
  const email = await newReviewer(page, testInfo);

  await test.step("a task undecided for 22 days is parked by the sweep", async () => {
    await seedAgedTask(email, 22, "Learn basic Portuguese");
    expect((await runReviewSweep()).parked).toBe(1);
    const someday = await apiGet<{ items: Array<{ title: string }> }>(page, "/api/tasks?state=someday");
    expect(someday.items.map((task) => task.title)).toEqual(["Learn basic Portuguese"]);
  });

  await test.step("the web opens on While you were away, accessible at desktop and 390 px", async () => {
    await page.goto("/tasks/next");
    const dialog = page.getByRole("dialog", { name: "While you were away" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "While you were away" })).toBeFocused();
    await expect(dialog.getByText("Learn basic Portuguese")).toBeVisible();
    await expectAccessible(page);
    await page.setViewportSize(NARROW);
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
    await page.setViewportSize(DESKTOP);
  });

  await test.step("Return brings it back with a fresh start, and Continue records that it was seen", async () => {
    const dialog = page.getByRole("dialog", { name: "While you were away" });
    await dialog.getByRole("button", { name: "Return Learn basic Portuguese to Next" }).click();
    await expect(dialog.getByText("Back in Next with a fresh start")).toBeVisible();
    await dialog.getByRole("button", { name: "Continue" }).click();
    await expect(dialog).toBeHidden();
    await page.reload();
    await expect(page.getByRole("dialog", { name: "While you were away" })).toHaveCount(0);
    await expect(page.getByText("Learn basic Portuguese")).toBeVisible();
  });
});

test("020-FR-002 020-FR-015 020-FR-052 020-SC-006 020-SC-007 a quick review end to end, then its summary on the entry", async ({ page }, testInfo) => {
  await page.setViewportSize(DESKTOP);
  const email = await newReviewer(page, testInfo);
  await seedAgedTask(email, 15, "Renovate the bathroom");
  await createTaskViaApi(page, "Buy printer paper", { state: "inbox" });
  await createTaskViaApi(page, "Call the dentist", { state: "inbox" });

  await test.step("onboarding opens first, accessible, and Continue saves it", async () => {
    await page.goto("/review");
    const dialog = page.getByRole("dialog", { name: "A weekly reset" });
    await expect(dialog.getByRole("heading", { name: "A weekly reset" })).toBeFocused();
    await expect(dialog.getByText("The web doesn't send reminders; the sidebar shows when your last review was.", { exact: false })).toBeVisible();
    await expectAccessible(page);
    await dialog.getByRole("button", { name: "Continue" }).click();
    await expect(dialog).toBeHidden();
  });

  await test.step("the entry offers Quick and Full without horizontal overflow at 390 px", async () => {
    await expect(page.getByRole("heading", { name: "How much time do you have?" })).toBeVisible();
    await expectAccessible(page);
    await page.setViewportSize(NARROW);
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
    await page.setViewportSize(DESKTOP);
  });

  await test.step("Wins first, then the Inbox one item at a time", async () => {
    await page.getByRole("button", { name: /^Quick/ }).click();
    await expect(page.getByRole("heading", { name: "Wins of the week" })).toBeFocused();
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Inbox" })).toBeFocused();
    await expect(page.getByText("Item 1 of 2")).toBeVisible();
    await expectAccessible(page);
    await page.getByRole("group", { name: "Choices" }).getByRole("button", { name: "Next actions" }).click();
    await expect(page.getByText("Item 2 of 2")).toBeVisible();
    await page.getByRole("group", { name: "Choices" }).getByRole("button", { name: "Someday / maybe" }).click();
    await expect(page.getByText("2 items processed")).toBeVisible();
    await page.getByRole("button", { name: "Next", exact: true }).click();
  });

  await test.step("the decision step shows the card inline; one decision finishes it", async () => {
    await expect(page.getByRole("heading", { name: "Tasks that ask for a decision" })).toBeVisible();
    const card = page.getByRole("region", { name: "Renovate the bathroom" });
    await expect(card).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expectAccessible(page);
    await card.getByRole("button", { name: /^Release to Someday/ }).click();
    await expect(page.getByText("All 1 decided")).toBeVisible();
    await page.getByRole("button", { name: "Next", exact: true }).click();
  });

  await test.step("the summary counts the decisions and Done returns to the entry with the last review", async () => {
    await expect(page.getByRole("heading", { name: "Review done" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Decisions in this review" })).toBeVisible();
    await expect(page.getByText(/^Next review: /)).toBeVisible();
    await expectAccessible(page);
    await page.setViewportSize(NARROW);
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
    await page.setViewportSize(DESKTOP);
    await page.getByRole("button", { name: "Yes" }).click();
    await page.getByRole("button", { name: "Done" }).click();
    await expect(page.getByText(/^Last review · .* · on the web$/)).toBeVisible();
    await expect(page.getByText("Clear start: Yes")).toBeVisible();
  });
});

test("020-SC-007 020-FR-027 a run finished through the API as an iOS client would shows its summary on the /review entry", async ({ page }, testInfo) => {
  await page.setViewportSize(DESKTOP);
  const email = await newReviewer(page, testInfo);
  await seedAgedTask(email, 3, "Fresh enough");
  const sessionId = `review_${randomUUID()}`;

  await test.step("start, finish a step and press Done as the iPhone would", async () => {
    await apiPost(page, "/api/review/sessions", { id: sessionId, mode: "quick", entry: "list", origin: "ios", replace_open: true });
    const progress = await apiPatch(page, `/api/review/sessions/${sessionId}`, {
      progress_id: `progress_${randomUUID()}`,
      step: { code: "wins", status: "finished" },
      current_step: "inbox"
    });
    expect(progress.ok(), await progress.text()).toBe(true);
    await apiPost(page, `/api/review/sessions/${sessionId}/finish`, { clear_start: "yes" });
    const state = await apiGet<{ last_counted_review: { origin: string } | null }>(page, "/api/review/state");
    expect(state.last_counted_review?.origin).toBe("ios");
  });

  await test.step("the web entry shows that review, with its answer", async () => {
    await page.goto("/review");
    await page.getByRole("dialog", { name: "A weekly reset" }).getByRole("button", { name: "Close" }).click();
    await expect(page.getByText(/^Last review · .* · on iPhone$/)).toBeVisible();
    await expect(page.getByText("Clear start: Yes")).toBeVisible();
    await expectAccessible(page);
  });
});

test("E2E-A11Y-01 020-FR-048 020-FR-052 a whole quick review with the keyboard alone", async ({ page }, testInfo) => {
  await page.setViewportSize(DESKTOP);
  const email = await newReviewer(page, testInfo);
  await seedAgedTask(email, 15, "Renovate the bathroom");

  await test.step("onboarding: focus starts on its heading and Continue is one Shift+Tab away", async () => {
    await page.goto("/review");
    await expect(page.getByRole("heading", { name: "A weekly reset" })).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByRole("button", { name: "Continue" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  await test.step("start a Quick review and move through Wins and the Inbox", async () => {
    await tabTo(page, /^Quick/);
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Wins of the week" })).toBeFocused();
    // Next waits for the step's queue (D-03) and Tab skips it while disabled, so wait for it first.
    await expect(page.getByRole("button", { name: "Next", exact: true })).toBeEnabled();
    await tabTo(page, "Next", true);
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Inbox" })).toBeFocused();
    await expect(page.getByRole("button", { name: "Next", exact: true })).toBeEnabled();
    await tabTo(page, "Next", true);
    await page.keyboard.press("Enter");
    await expect(page.getByRole("region", { name: "Renovate the bathroom" })).toBeVisible();
  });

  await test.step("Leave asks first; Escape keeps going and focus returns to Leave", async () => {
    await tabTo(page, "Leave");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Keep going" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Leave" })).toBeFocused();
  });

  await test.step("Escape never closes the review; the card takes number keys and Ctrl+Z undoes", async () => {
    await page.keyboard.press("Escape");
    await expect(page.getByRole("navigation", { name: "Review steps" })).toBeVisible();
    const card = page.getByRole("region", { name: "Renovate the bathroom" });
    await card.getByRole("heading", { name: "Renovate the bathroom" }).focus();
    await page.keyboard.press("5");
    await expect(page.getByText("All 1 decided")).toBeVisible();
    await page.keyboard.press("Control+z");
    await expect(card.getByRole("heading", { name: "Renovate the bathroom" })).toBeFocused();
    // The seed's start is older than the activation, so the restored clock no longer asks.
    await expect(card.getByText("This task no longer asks for a decision.")).toBeVisible();
    await tabTo(page, "Not now");
    await page.keyboard.press("Enter");
    await expect(page.getByText("0 of 1 decided")).toBeVisible();
  });

  await test.step("finish: Next, the question and Done, all from the keyboard", async () => {
    await tabTo(page, "Next", true);
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Review done" })).toBeFocused();
    await tabTo(page, "Not really");
    await page.keyboard.press("Enter");
    await tabTo(page, "Done");
    await page.keyboard.press("Enter");
    await expect(page.getByText("Clear start: Not really")).toBeVisible();
  });
});
