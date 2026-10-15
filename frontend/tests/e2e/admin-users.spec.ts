import { expect, test } from "../allure.fixtures";
import { password } from "./gtdHelpers";
import { readOwnerTasks } from "./testControl";

const operatorEmail = process.env.BRAIN_BUDDY_ADMIN_EMAIL;
const operatorPassword = process.env.BRAIN_BUDDY_ADMIN_PASSWORD ?? password;

test("013-FR-002 013-FR-003 013-FR-004 013-FR-009 013-FR-010 013-FR-012 013-FR-015 013-FR-016 013-FR-017 013-SC-001 013-SC-005 013-SC-007 013-SC-008 013-SC-009 admin operator completes the Users journey and opens Feature flags", async ({ page }, testInfo) => {
  test.skip(!operatorEmail, "BRAIN_BUDDY_ADMIN_EMAIL is required for the synthetic Compose operator journey");
  if (!operatorEmail) return;

  const suffix = `${testInfo.project.name}-${Date.now()}`.replace(/[^a-zA-Z0-9-]/g, "-");
  const memberEmail = `admin-crud-${suffix}@example.com`;
  const memberPassword = "E2E-safe-password-123";
  const browser = page.context().browser();
  if (!browser) throw new Error("Chromium browser is required for the isolated target session");
  const targetContext = await browser.newContext({
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5173"
  });
  const targetPage = await targetContext.newPage();
  let targetTaskId = "";

  await test.step("authenticate the configured synthetic operator", async () => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Use your password", exact: true }).click();
    await page.getByLabel("Email").fill(operatorEmail);
    await page.getByLabel("Password").fill(operatorPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).not.toHaveURL(/\/login$/);
  });

  await test.step("create and list a synthetic member in canonical Users", async () => {
    await page.goto("/admin");
    await expect(page.getByRole("tab", { name: "Users" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("columnheader", { name: "Email" })).toBeVisible();
    await page.getByRole("button", { name: "Create user" }).click();
    await page.getByLabel("Email").fill(memberEmail);
    await page.getByLabel("Display name (optional)").fill("Synthetic Admin Member");
    await page.getByLabel("Initial password").fill(memberPassword);
    await page.getByRole("button", { name: "Create user" }).click();
    await expect(page.getByText(memberEmail)).toBeVisible();
  });

  await test.step("edit, reload, and authenticate as the created target", async () => {
    const row = page.locator("tr", { hasText: memberEmail });
    await row.getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Display name", { exact: true }).fill("Synthetic Admin Member Renamed");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Synthetic Admin Member Renamed")).toBeVisible();
    await page.reload();
    await expect(page.getByText("Synthetic Admin Member Renamed")).toBeVisible();

    await targetPage.goto("/login");
    await targetPage.getByRole("button", { name: "Use your password", exact: true }).click();
    await targetPage.getByLabel("Email").fill(memberEmail);
    await targetPage.getByLabel("Password").fill(memberPassword);
    await targetPage.getByRole("button", { name: "Sign in" }).click();
    await expect(targetPage).not.toHaveURL(/\/login$/);
    const targetAccount = await targetPage.request.get("/api/auth/me");
    if (targetAccount.status() !== 200) throw new Error(`target account read failed: ${targetAccount.status()}`);
    const taskResponse = await targetPage.request.post("/api/tasks", {
      data: { title: `Synthetic owned task ${suffix}`, state: "inbox" },
      headers: { "Idempotency-Key": `admin-owned-${suffix}` }
    });
    if (taskResponse.status() !== 201) throw new Error(`target task creation failed: ${taskResponse.status()}`);
    targetTaskId = ((await taskResponse.json()) as { id: string }).id;
    const ownedTask = await targetPage.request.get(`/api/tasks/${targetTaskId}`);
    if (ownedTask.status() !== 200) throw new Error(`target-owned task was not readable before delete: ${ownedTask.status()}`);
    const ownerTasksBeforeDelete = await readOwnerTasks(memberEmail);
    if (ownerTasksBeforeDelete === "absent" || !ownerTasksBeforeDelete.some((task) => task.id === targetTaskId)) {
      throw new Error("target-owned task was absent from the owner-scoped repository before delete");
    }
  });

  await test.step("revoke sessions only after target-bound confirmation", async () => {
    const row = page.locator("tr", { hasText: memberEmail });
    await row.getByRole("button", { name: "Revoke sessions" }).click();
    const dialog = page.getByRole("dialog", { name: new RegExp(`^Revoke sessions for .+ \\(${memberEmail}\\)$`) });
    await expect(dialog).toContainText(memberEmail);
    await dialog.getByRole("button", { name: "Revoke sessions" }).click();
    await expect(page.getByText(/Revoked \d+ sessions?\./)).toBeVisible();
    const revokedSession = await targetPage.request.get("/api/auth/me");
    if (revokedSession.status() !== 401) throw new Error(`revoke did not invalidate target session: ${revokedSession.status()}`);
  });

  await test.step("delete only after explicit confirmation and verify absence", async () => {
    const row = page.locator("tr", { hasText: memberEmail });
    await row.getByRole("button", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog", { name: new RegExp(`^Delete account .+ \\(${memberEmail}\\)$`) });
    await expect(dialog).toContainText(memberEmail);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByText(memberEmail)).toBeVisible();
    await row.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete permanently" }).click();
    await expect(page.getByText(memberEmail)).toHaveCount(0);
    // The revoked target session can only prove access containment (401). The
    // test control owner read answers 404 once the account is gone. That proves
    // the account is absent, not that its task row was purged, so the Users
    // list is checked as well.
    if ((await readOwnerTasks(memberEmail)) !== "absent") {
      throw new Error("target account still resolves after account deletion");
    }
    const accounts = await page.request.get("/api/admin/accounts");
    expect(accounts.ok(), await accounts.text()).toBe(true);
    const { accounts: listedAccounts } = (await accounts.json()) as { accounts: Array<{ email: string }> };
    expect(listedAccounts.map((account) => account.email)).not.toContain(memberEmail);
    await targetPage.goto("/login");
    await targetPage.getByRole("button", { name: "Use your password", exact: true }).click();
    await targetPage.getByLabel("Email").fill(memberEmail);
    await targetPage.getByLabel("Password").fill(memberPassword);
    await targetPage.getByRole("button", { name: "Sign in" }).click();
    await expect(targetPage.getByText("Invalid email or password.")).toBeVisible();
  });

  await test.step("capture Users at desktop and mobile widths without table overflow", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const desktopGeometry = await page.evaluate(() => {
      const main = document.querySelector("main");
      const table = document.querySelector('[role="tabpanel"] table');
      if (!main || !table) throw new Error("Users table geometry targets were not found");
      return {
        mainWidth: main.getBoundingClientRect().width,
        tableWidth: table.getBoundingClientRect().width,
      };
    });
    if (desktopGeometry.tableWidth <= desktopGeometry.mainWidth * 0.85) {
      throw new Error(
        `Users table did not fill the desktop workspace: ${desktopGeometry.tableWidth}px of ${desktopGeometry.mainWidth}px`
      );
    }
    await page.screenshot({ path: "test-results/admin-users-desktop.png", fullPage: true });
    await page.setViewportSize({ width: 390, height: 851 });
    await expect(page.locator("table")).toBeVisible();
    const documentOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    );
    if (documentOverflow > 0) throw new Error(`Users document horizontally overflowed by ${documentOverflow}px`);
    await page.screenshot({ path: "test-results/admin-users-390x851.png", fullPage: true });
  });

  await test.step("switch exclusively to Feature flags", async () => {
    await page.getByRole("tab", { name: "Feature flags" }).click();
    await expect(page.getByRole("tab", { name: "Feature flags" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tabpanel", { name: "Feature flags" })).toBeVisible();
    await expect(page.getByRole("tabpanel", { name: "Users" })).toHaveCount(0);
  });
  await targetContext.close();
});
