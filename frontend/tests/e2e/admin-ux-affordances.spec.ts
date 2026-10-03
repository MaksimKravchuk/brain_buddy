import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "../allure.fixtures";

async function openSyntheticAdmin(page: import("@playwright/test").Page): Promise<void> {
  page.on("pageerror", (error) => console.error(`pageerror: ${error.message}`));
  page.on("console", (message) => { if (message.type() === "error") console.error(`console: ${message.text()}`); });
  await page.route("**/*", async (route) => {
    const { pathname } = new URL(route.request().url());
    if (!pathname.startsWith("/api/")) return route.continue();
    const replies: Record<string, unknown> = {
      "/api/auth/me": { id: "operator", email: "operator@example.test" },
      "/api/admin/status": { is_operator: true },
      "/api/admin/accounts": {
        accounts: [
          { id: "operator", email: "operator@example.test", display_name: "Operator", deletion_requested: false },
          { id: "member", email: "member.long-email-address@example.test", display_name: "Member", deletion_requested: false }
        ]
      },
      "/api/admin/feature-flags": { degraded: false, flags: [
        { name: "voice_brain_dump", mode: "off", selected_users: [] },
        { name: "mobile_task_classification", mode: "selected_users", selected_users: [{ account_id: "member", email: "member.long-email-address@example.test" }] },
        { name: "external_agent_relay", mode: "on", selected_users: [] }
      ] },
      "/api/tasks": { items: [], next_cursor: null, has_more: false, counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 } },
      "/api/projects": [],
      "/api/tags": []
    };
    if (route.request().method() !== "GET") throw new Error(`Unexpected write ${pathname}`);
    await route.fulfill({ json: replies[pathname] ?? {} });
  });
  await page.goto("/admin");
  await expect(page.getByRole("tabpanel", { name: "Users" })).toBeVisible();
  await expect(page.getByText("member.long-email-address@example.test")).toBeVisible();
}

test("013-SC-007 visually marks the active Admin tab and preserves keyboard switching", async ({ page }, testInfo) => {
  await test.step("open the operator Users tab at desktop width", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await openSyntheticAdmin(page);
  });
  const users = page.getByRole("tab", { name: "Users" });
  const flags = page.getByRole("tab", { name: "Feature flags" });
  await test.step("verify selected appearance and keyboard focus in both directions", async () => {
    await expect(users).toHaveAttribute("aria-selected", "true");
    await expect(users).toHaveCSS("border-bottom-color", "rgb(3, 105, 161)");
    await expect(flags).toHaveCSS("border-bottom-color", "rgba(0, 0, 0, 0)");
    const desktopTable = page.getByTestId("admin-users-table-scroll");
    expect(await desktopTable.evaluate((el) => el.scrollWidth - el.clientWidth)).toBe(0);
    await expect(page.getByText("More columns and actions")).toHaveCount(0);
    await expect(desktopTable).not.toHaveAttribute("tabindex", "0");
    await page.screenshot({ path: testInfo.outputPath("admin-users-desktop.png") });
    await users.focus();
    await users.press("ArrowRight");
    await expect(flags).toBeFocused();
    await expect(flags).toHaveAttribute("aria-selected", "true");
    await expect(flags).toHaveCSS("border-bottom-color", "rgb(3, 105, 161)");
    await expect(users).toHaveCSS("border-bottom-color", "rgba(0, 0, 0, 0)");
    await expect(page.getByRole("tabpanel", { name: "Feature flags" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "voice_brain_dump" })).toBeVisible();
    const flagsA11y = await new AxeBuilder({ page }).include("main").analyze();
    expect(flagsA11y.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("admin-flags-desktop.png") });
    await flags.press("ArrowLeft");
    await expect(users).toBeFocused();
    await expect(users).toHaveCSS("border-bottom-color", "rgb(3, 105, 161)");
  });
});

test("013-SC-007 makes the narrow Users table scroll discoverable and keyboard reachable", async ({ page }, testInfo) => {
  await test.step("open the Users tab at a narrow width", async () => {
    await page.setViewportSize({ width: 390, height: 851 });
    await openSyntheticAdmin(page);
  });
  const table = page.getByTestId("admin-users-table-scroll");
  const goToActions = page.getByRole("button", { name: "Show table actions" });
  await test.step("switch tabs on a narrow screen without losing the active indicator", async () => {
    const users = page.getByRole("tab", { name: "Users" });
    const flags = page.getByRole("tab", { name: "Feature flags" });
    await users.focus();
    await users.press("ArrowRight");
    await expect(flags).toBeFocused();
    await expect(flags).toHaveCSS("border-bottom-color", "rgb(3, 105, 161)");
    await expect(page.getByRole("heading", { name: "voice_brain_dump" })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("admin-flags-390.png") });
    await flags.press("ArrowLeft");
    await expect(users).toBeFocused();
    await expect(users).toHaveCSS("border-bottom-color", "rgb(3, 105, 161)");
  });
  await test.step("see a visible hint only while table content is hidden", async () => {
    await expect(goToActions).toBeVisible();
    const usersA11y = await new AxeBuilder({ page }).include("main").analyze();
    expect(usersA11y.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
    const range = await table.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(range).toBeGreaterThan(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0);
    await page.screenshot({ path: testInfo.outputPath("admin-users-390-before.png") });
  });
  await test.step("reach actions with an explicit control and return to email", async () => {
    await goToActions.click();
    await expect.poll(() => table.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
    const action = page.getByRole("button", { name: "Delete member (member.long-email-address@example.test)" });
    await expect(action).toBeVisible();
    const inView = await action.evaluate((el) => {
      const rect = el.getBoundingClientRect();
      const parent = el.closest("[data-testid='admin-users-table-scroll']")!.getBoundingClientRect();
      return rect.left >= parent.left - 1 && rect.right <= parent.right + 1;
    });
    expect(inView).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("admin-users-390-actions.png") });
    await page.getByRole("button", { name: "Back to table start" }).click();
    await expect.poll(() => table.evaluate((el) => el.scrollLeft)).toBe(0);
  });
  await test.step("support a keyboard focus path to the horizontal scroller", async () => {
    await goToActions.focus();
    await goToActions.press("Tab");
    await expect(table).toBeFocused();
    await table.press("ArrowRight");
    await expect.poll(() => table.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
  });
  await test.step("recalculate the cue and keyboard tab stop when the viewport changes", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(goToActions).toHaveCount(0);
    await expect(table).not.toHaveAttribute("tabindex", "0");
    await page.setViewportSize({ width: 390, height: 851 });
    await expect(goToActions).toBeVisible();
    await expect(table).toHaveAttribute("tabindex", "0");
  });
});
