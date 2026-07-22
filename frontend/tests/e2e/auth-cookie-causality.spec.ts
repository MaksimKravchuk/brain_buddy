import { type Page, type Route, type TestInfo } from "@playwright/test";

import { test, expect } from "../allure.fixtures";
import { backendUrl, mintInvite, password, uniqueEmail } from "./gtdHelpers";

async function signup(page: Page, testInfo: TestInfo): Promise<{ email: string; predecessorToken: string }> {
  const email = uniqueEmail("auth-cookie-causality", testInfo);
  const response = await page.request.post(`${backendUrl}/api/auth/signup`, {
    data: { email, password, invite_code: await mintInvite() }
  });
  expect(response.status(), await response.text()).toBe(201);

  const cookie = (await page.context().cookies(backendUrl)).find((item) => item.name === "brainbuddy_session");
  expect(cookie?.value).toBeTruthy();
  return { email, predecessorToken: cookie!.value };
}

test("E2E-AUTH-03 delayed predecessor logout preserves the successor browser session", async ({ page }, testInfo) => {
  let heldLogout: Route | undefined;
  let logoutRequestCookie = "";
  let account!: { email: string; predecessorToken: string };
  let releaseLogout!: () => void;
  const logoutHeld = new Promise<void>((resolve) => {
    releaseLogout = resolve;
  });

  await test.step("create session A and load the authenticated browser", async () => {
    account = await signup(page, testInfo);
    await page.goto("/");
    await expect(page.getByText("Brain Buddy", { exact: true })).toBeVisible();
  });

  const predecessorToken = account.predecessorToken;

  await page.route("**/api/auth/logout", async (route) => {
    heldLogout = route;
    logoutRequestCookie = route.request().headers().cookie ?? "";
    releaseLogout();
  });

  const logoutCompletion = page.evaluate(async () => {
    const response = await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    return response.status;
  });

  await test.step("hold logout A before its response can affect the cookie jar", async () => {
    await logoutHeld;
    expect(logoutRequestCookie).toContain(`brainbuddy_session=${predecessorToken}`);
  });

  let successorToken = "";
  await test.step("complete successor login B while logout A is still held", async () => {
    const login = await page.evaluate(
      async ({ email, loginPassword }) => {
        const response = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password: loginPassword }),
          credentials: "include"
        });
        return { status: response.status, user: await response.json() };
      },
      { email: account.email, loginPassword: password }
    );
    expect(login.status).toBe(200);
    expect(login.user).toMatchObject({ email: expect.stringContaining("@example.com") });

    const successorCookie = (await page.context().cookies(backendUrl)).find(
      (item) => item.name === "brainbuddy_session"
    );
    expect(successorCookie?.value).toBeTruthy();
    expect(successorCookie?.value).not.toBe(predecessorToken);
    successorToken = successorCookie!.value;
  });

  await test.step("release logout A and prove its response cannot delete B", async () => {
    await heldLogout!.continue();
    await expect(logoutCompletion).resolves.toBe(204);

    const survivingCookie = (await page.context().cookies(backendUrl)).find(
      (item) => item.name === "brainbuddy_session"
    );
    expect(survivingCookie?.value).toBe(successorToken);

    const me = await page.evaluate(async () => {
      const response = await fetch("/api/auth/me", { credentials: "include" });
      return { status: response.status, user: await response.json() };
    });
    expect(me.status).toBe(200);
    expect(me.user).toMatchObject({ email: expect.stringContaining("@example.com") });
  });
});
