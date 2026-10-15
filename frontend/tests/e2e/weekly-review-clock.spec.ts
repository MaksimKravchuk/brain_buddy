import AxeBuilder from "@axe-core/playwright";
import { request as playwrightRequest, type Page, type TestInfo } from "@playwright/test";
import { expect, test } from "../allure.fixtures";
import { backendUrl, createTaskViaApi, mintInvite, password, signupThroughUi, uniqueEmail } from "./gtdHelpers";
import { advanceClock, resetClock, seedAgedTask } from "./testControl";

/*
 * The one journey that moves server time. The clock is process-wide, so this
 * file runs in its own Playwright project after every other browser project
 * has finished (playwright.config.ts), and each test returns the clock to the
 * wall clock in afterEach.
 */

test.describe.configure({ mode: "serial" });

const operatorEmail = process.env.BRAIN_BUDDY_ADMIN_EMAIL;
const operatorPassword = process.env.BRAIN_BUDDY_ADMIN_PASSWORD ?? password;
const NARROW = { width: 390, height: 851 };
const FIFTEEN_DAYS_SECONDS = 15 * 24 * 60 * 60;

test.beforeEach(async () => {
  test.skip(!operatorEmail, "BRAIN_BUDDY_ADMIN_EMAIL is required to turn weekly_review on for one synthetic account");
  await resetClock();
});

test.afterEach(async () => {
  await resetClock();
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
  const { violations } = await new AxeBuilder({ page }).disableRules(["aria-allowed-role"]).analyze();
  expect(violations.map((violation) => ({ id: violation.id, impact: violation.impact, html: violation.nodes.map((node) => node.html) }))).toEqual([]);
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
}

test("020-FR-032 020-FR-033 020-FR-040 the Waiting step and the summary fit 390 px, and the drawer carries the review link", async ({ page }, testInfo) => {
  const email = await newReviewer(page, testInfo);
  await createTaskViaApi(page, "Pick up the drill from Sam", { state: "waiting", waiting_for: "Sam" });
  // The task has waited since now; moving the clock 15 days makes it older than the 7-day Waiting threshold.
  await advanceClock(FIFTEEN_DAYS_SECONDS);
  await seedAgedTask(email, 15, "Renovate the bathroom");
  await page.setViewportSize(NARROW);

  await test.step("the drawer shows a working Weekly review link with its recap", async () => {
    await page.goto("/tasks/next");
    await expectNoHorizontalOverflow(page);
    await page.getByRole("button", { name: "Open task navigation" }).click();
    const drawer = page.getByRole("dialog", { name: "Task navigation" });
    await expect(drawer.getByRole("link", { name: /Weekly review/ })).toHaveAttribute("href", "/review");
    await expect(drawer.getByText("Set up in a minute")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.getByRole("button", { name: "Close task navigation" }).last().click();
  });

  await test.step("a Full review reaches the Waiting step with its decisions stacked and no overflow", async () => {
    await page.goto("/review");
    await page.getByRole("dialog", { name: "A weekly reset" }).getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: /^Full/ }).click();
    await expect(page.getByText("Step 1 of 10")).toBeVisible();
    for (const step of ["Mind sweep", "Inbox", "Tasks that ask for a decision", "The rest of Next", "Waiting for, older than 7 days"]) {
      await page.getByRole("button", { name: "Next", exact: true }).click();
      await expect(page.getByRole("heading", { name: step })).toBeVisible();
    }
    await expect(page.getByRole("heading", { name: "Pick up the drill from Sam" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
  });

  await test.step("the summary at 390 px has a two-column grid and no overflow", async () => {
    for (const step of ["Projects without a next action", "Someday / maybe", "The next 14 days", "Review done"]) {
      await page.getByRole("button", { name: "Next", exact: true }).click();
      await expect(page.getByRole("heading", { name: step })).toBeVisible();
    }
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
  });

  await test.step("/settings/account keeps one column at 390 px", async () => {
    await page.goto("/settings/account");
    await expect(page.getByRole("heading", { name: /Account/ }).first()).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
  });
});
