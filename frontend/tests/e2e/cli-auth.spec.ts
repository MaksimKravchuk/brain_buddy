import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "../allure.fixtures";
import { backendUrl, createUserViaApi, password } from "./gtdHelpers";

test.describe("024-FR-013 CLI browser approval", () => {
  test("024-SC-004 signed-out password return requires explicit approval and issues one session", async ({ page, request }, testInfo) => {
    const email = await createUserViaApi(request, testInfo, "cli-authorize");
    const started = await request.post(`${backendUrl}/api/auth/device/start`, { data: {} });
    expect(started.status()).toBe(200);
    const grant = await started.json();
    await test.step("capture the short code before shared sign in, with a clean return route", async () => {
      await page.goto(`/cli/authorize#user_code=${grant.user_code}`);
      await expect(page).toHaveURL(/\/login$/);
      expect(await page.evaluate(() => location.hash)).toBe("");
      await page.getByRole("button", { name: "Use your password" }).click();
      await page.getByLabel("Email address", { exact: true }).fill(email);
      await page.getByLabel("Password", { exact: true }).fill(password);
      await page.getByRole("button", { name: "Sign in", exact: true }).click();
      await expect(page).toHaveURL(/\/cli\/authorize$/);
      await expect(page.getByRole("heading", { name: "Confirm this CLI request" })).toBeFocused();
      await expect(page.getByText(email, { exact: true })).toBeVisible();
      await testInfo.attach("cli-desktop-approval", { body: await page.screenshot(), contentType: "image/png" });
    });
    await test.step("verify keyboard approval, accessibility and the announced result", async () => {
      const violations = (await new AxeBuilder({ page }).analyze()).violations.filter(item => ["serious", "critical"].includes(item.impact ?? ""));
      expect(violations).toEqual([]);
      await page.keyboard.press("Tab");
      await expect(page.getByRole("button", { name: "Approve access" })).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("status")).toContainText("Access approved");
      await testInfo.attach("cli-desktop-approved", { body: await page.screenshot(), contentType: "image/png" });
      expect(await page.evaluate(() => sessionStorage.getItem("brainbuddy.cli.authorization"))).toBeNull();
    });
    await test.step("exchange the private CLI proof once, then reject response-loss replay", async () => {
      // Respect the advertised interval even if the browser completed quickly.
      await new Promise(resolve => setTimeout(resolve, 5000));
      const issued = await request.post(`${backendUrl}/api/auth/device/token`, { data: { device_code: grant.device_code } });
      expect(issued.status()).toBe(200);
      expect((await issued.json()).account.email).toBe(email);
      expect(issued.headers()["set-cookie"]).toContain("HttpOnly");
      const repeated = await request.post(`${backendUrl}/api/auth/device/token`, { data: { device_code: grant.device_code } });
      expect(repeated.status()).toBe(409);
      expect((await repeated.json()).detail.code).toBe("authorization_consumed");
      await request.post(`${backendUrl}/api/auth/logout`);
    });
    await test.step("recover from an unavailable code with the real server reference", async () => {
      await page.goto("/cli/authorize");
      const unavailable = grant.user_code === "ABCD-EFGH" ? "JKLM-NPQR" : "ABCD-EFGH";
      await page.getByLabel("Code from your CLI").fill(unavailable);
      const response = page.waitForResponse(value => new URL(value.url()).pathname === "/api/auth/device/request");
      await page.getByRole("button", { name: "Check code", exact: true }).click();
      const rejected = await response;
      expect(rejected.status()).toBe(404);
      const reference = rejected.headers()["x-correlation-id"];
      expect(reference).toMatch(/^[0-9a-f]{8}-[0-9a-f-]{27}$/i);
      await expect(page.getByRole("alert")).toContainText(`Reference: ${reference}`);
      await expect(page.getByRole("button", { name: "Check code again" })).toBeEnabled();
    });
  });
});
