import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { arch, cpus, platform, release } from "node:os";
import { promisify } from "node:util";

import AxeBuilder from "@axe-core/playwright";
import type { Browser, Locator, Page, Route, TestInfo } from "@playwright/test";
import { attachment, epic, feature, story } from "allure-js-commons";

import { expect, test } from "./allure.fixtures";

const origin = process.env.BRAIN_BUDDY_MODERN_E2E_ORIGIN ?? "https://brainbuddy-e2e.example.com:9443";
const captureFile = process.env.BRAIN_BUDDY_MODERN_E2E_CAPTURE_FILE;
const password = "E2E-modern-safe-password-123";
const legacyEmail = "legacy-modern-e2e@gmail.com";
const recoveryEmail = "recovery-modern-e2e@example.com";
const staleEmail = "stale-modern-e2e@example.com";
const otherEmail = "other-modern-e2e@example.com";
const execFileAsync = promisify(execFile);

test.use({
  baseURL: origin,
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 1000 },
  contextOptions: { reducedMotion: "no-preference" },
  launchOptions: {
    ...(process.env.BRAIN_BUDDY_MODERN_E2E_CHROMIUM ? { executablePath: process.env.BRAIN_BUDDY_MODERN_E2E_CHROMIUM } : {}),
    args: [`--host-resolver-rules=MAP ${new URL(origin).hostname} 127.0.0.1`]
  }
});

for (const provider of ["google", "apple"] as const) {
  const label = provider === "google" ? "Google" : "Apple";
  test(`023-FR-007 023-FR-018 023-SC-003 Remove ${label} ends public provider authority until the same owner explicitly reconnects`, async ({ page }) => {
    test.setTimeout(60_000);
    const email = provider === "google" ? "removed-google-modern-e2e@gmail.com" : "removed-apple-modern-e2e@privaterelay.appleid.com";
    const subject = `removed-${provider}-subject`;
    const finish = () => provider === "google" ? finishGoogle(page) : finishApple(page);
    if (provider === "google") await fakeGoogle(page, email, subject);
    else await fakeApple(page, email, subject);
    await test.step("create one provider owner and establish its remaining password through fresh provider confirmation", async () => {
      await page.goto("/login");
      await page.getByRole("button", { name: `Sign in with ${label}`, exact: true }).click();
      await finish();
      await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
      await prepareProviderPassword(page, provider, password);
      await page.getByRole("button", { name: "Confirm and save", exact: true }).click();
      await expect(page.getByRole("status")).toContainText("Password saved");
    });
    const owner = (await api<Me>(page, "/auth/me")).body;
    const task = await api<{ id: string }>(page, "/tasks", { title: `Preserve removed ${label} owner's task`, state: "inbox" });
    expect(task.status).toBe(201);
    await test.step("Remove commits, revokes the originating session, and prevents public restoration", async () => {
      await page.goto("/settings/account");
      await page.getByRole("button", { name: `Remove ${label}`, exact: true }).click();
      await page.getByRole("button", { name: "Confirm removal", exact: true }).click();
      await page.getByLabel("Current password").fill(password);
      const unlinked = page.waitForResponse(response => new URL(response.url()).pathname === `/api/account/auth-methods/${provider}/unlink`);
      await page.getByRole("button", { name: "Confirm", exact: true }).click();
      expect((await unlinked).status()).toBe(200);
      await expect(page).toHaveURL(/\/login$/);
      expect((await api(page, "/auth/me")).status).toBe(401);
      const completed = page.waitForResponse(response => new URL(response.url()).pathname === "/api/auth/providers/complete");
      await page.getByRole("button", { name: `Sign in with ${label}`, exact: true }).click();
      await finish();
      expect((await completed).status()).toBe(200);
      expect((await api(page, "/auth/me")).status).toBe(401);
      await expect(page.getByRole("alert")).toContainText("Connect to your existing account");
    });
    await test.step("remaining password access retains the owner and permits an explicit fresh provider link", async () => {
      await passwordLogin(page, email);
      expect((await api<Me>(page, "/auth/me")).body.id).toBe(owner.id);
      await page.goto("/settings/account");
      await page.getByRole("button", { name: new RegExp(`^(Connect|Reconnect) ${label}$`) }).click();
      await page.getByLabel("Current password").fill(password);
      await page.getByRole("button", { name: "Confirm", exact: true }).click();
      await finish();
      await expect(page.getByRole("button", { name: `Remove ${label}`, exact: true })).toBeVisible();
      expect((await api<Me>(page, "/auth/me")).body.id).toBe(owner.id);
      expect((await api<{ title: string }>(page, `/tasks/${task.body.id}`)).body.title).toBe(`Preserve removed ${label} owner's task`);
      expect((await api<AccountMethods>(page, "/account/auth-methods")).body.methods.some(method => method.method === provider && method.usable)).toBe(true);
    });
  });
}

interface Me { id: string; email: string }
interface AccountMethods { account_id: string; has_password: boolean; email_verified: boolean; methods: Array<{ method: string; usable: boolean }> }
interface Challenge { challenge_id: string; expires_at: string; resend_at: string }
interface ProviderStarted { attempt_id: string; state: string; authorization_url: string }
interface RecentProof { recent_proof: string }
interface CapturedMail { recipient: string; code: string; purpose: string }
interface ClientProof { verifier: string; challenge: string }

async function realResponse(route: Route) {
  // Route.fetch uses Node's resolver rather than Chromium's host mapping.
  // Forward the original browser headers to loopback without a DNS request.
  const target = new URL(route.request().url());
  const host = target.host;
  target.hostname = "127.0.0.1";
  return route.fetch({ url: target.href, headers: { ...await route.request().allHeaders(), host } });
}

async function api<T = Record<string, unknown>>(page: Page, path: string, body?: unknown): Promise<{ status: number; body: T }> {
  return page.evaluate(async ({ path, body }) => {
    const response = await fetch(`/api${path}`, {
      method: body === undefined ? "GET" : "POST", credentials: "include",
      headers: body === undefined ? { Accept: "application/json" } : {
        "Content-Type": "application/json",
        ...(path.startsWith("/tasks") ? { "Idempotency-Key": crypto.randomUUID() } : {})
      },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    return { status: response.status, body: response.status === 204 ? null : await response.json() };
  }, { path, body }) as Promise<{ status: number; body: T }>;
}

async function clientProof(page: Page): Promise<ClientProof> {
  return page.evaluate(async () => {
    const encode = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const verifier = encode(crypto.getRandomValues(new Uint8Array(32)));
    return { verifier, challenge: encode(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)))) };
  });
}

async function readCode(email: string, purpose: string): Promise<string> {
  let code: string | undefined;
  await expect.poll(async () => {
    const lines = (await readFile(captureFile!, "utf8")).trim().split("\n").filter(Boolean);
    const messages = lines.map(line => JSON.parse(line) as CapturedMail);
    code = messages.filter(message => message.recipient === email && message.purpose === purpose).at(-1)?.code;
    return code;
  }, { message: "the synthetic SMTP boundary acknowledged a fresh code", timeout: 15_000 }).toMatch(/^\d{6}$/);
  return code!;
}

async function enterCode(page: Page, email: string, purpose: string): Promise<void> {
  await expect(page.getByLabel("Email code")).toBeVisible();
  await page.getByLabel("Email code").fill(await readCode(email, purpose));
  await page.getByRole("button", { name: "Verify and continue", exact: true }).click();
}

async function passwordLogin(page: Page, email: string, value = password): Promise<void> {
  await page.goto("/login");
  await page.getByRole("button", { name: "Use your password", exact: true }).click();
  await page.getByLabel("Email address", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(value);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
}

async function emailSignup(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email address", { exact: true }).fill(email);
  const requested = page.waitForResponse(response => new URL(response.url()).pathname === "/api/auth/email/request");
  await page.getByRole("button", { name: "Continue with email", exact: true }).click();
  const response = await requested;
  expect(response.status()).toBe(202);
  const challenge = await response.json() as Challenge;
  expect(challenge.challenge_id).toMatch(/^[A-Za-z0-9_-]{43}$/);
  expect(Object.keys(challenge)).not.toContain("code");
  await enterCode(page, email, "login");
  await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function fakeGoogle(page: Page, email: string, subject: string): Promise<void> {
  await page.route("https://accounts.google.com/o/oauth2/v2/auth?**", async route => {
    const authorization = new URL(route.request().url());
    expect(authorization.searchParams.get("scope")).toBe("openid email");
    expect(authorization.searchParams.get("redirect_uri")).toBe(`${origin}/api/auth/providers/google/callback`);
    expect(authorization.searchParams.get("code_challenge_method")).toBe("S256");
    const code = Buffer.from(JSON.stringify({
      email, subject, nonce: authorization.searchParams.get("nonce"), pkce: authorization.searchParams.get("code_challenge")
    })).toString("base64url");
    await route.fulfill({
      contentType: "text/html",
      body: `<html><body><h1>Synthetic Google sign-in</h1><form action="${escapeHtml(authorization.searchParams.get("redirect_uri")!)}" method="get"><input type="hidden" name="state" value="${escapeHtml(authorization.searchParams.get("state")!)}"><input type="hidden" name="code" value="${code}"><button type="submit">Continue as synthetic identity</button></form></body></html>`
    });
  });
}

async function finishGoogle(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Synthetic Google sign-in" })).toBeVisible();
  await page.getByRole("button", { name: "Continue as synthetic identity" }).click();
}

for (const provider of ["google", "apple"] as const) {
  test(`023-FR-004 024-FR-013 ${provider} cancellation returns to recoverable sign-in without a session`, async ({ page }, testInfo) => {
    const upstream = provider === "google" ? "https://accounts.google.com/o/oauth2/v2/auth?**" : "https://appleid.apple.com/auth/authorize?**";
    await page.route(upstream, async route => {
      const authorization = new URL(route.request().url());
      await route.fulfill({ contentType: "text/html", body: `<html><body><h1>Cancel synthetic sign-in</h1><form action="${escapeHtml(authorization.searchParams.get("redirect_uri")!)}" method="${provider === "google" ? "get" : "post"}"><input type="hidden" name="state" value="${escapeHtml(authorization.searchParams.get("state")!)}"><input type="hidden" name="error" value="access_denied"><button type="submit">Cancel authorization</button></form></body></html>` });
    });
    await test.step("cancel a real bound provider attempt without returning any code", async () => {
      await page.goto("/login");
      await page.getByRole("button", { name: provider === "google" ? "Sign in with Google" : "Sign in with Apple", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Cancel synthetic sign-in" })).toBeVisible();
      const callback = page.waitForResponse(response => new URL(response.url()).pathname === `/api/auth/providers/${provider}/callback`);
      await page.getByRole("button", { name: "Cancel authorization" }).click();
      expect((await callback).status()).toBe(303);
      await expect(page.getByRole("alert")).toHaveText(/Sign-in cancelled/);
      expect(new URL(page.url()).hash).toBe("");
      expect(await page.evaluate(() => sessionStorage.length)).toBe(0);
      expect((await page.context().cookies()).some(cookie => cookie.name === "brainbuddy_auth_binder")).toBe(false);
      expect((await api(page, "/auth/me")).status).toBe(401);
      await accessible(page);
      await page.screenshot({ path: testInfo.outputPath(`${provider}-cancel.png`) });
    });
    await test.step("return to enabled sign-in choices for a fresh attempt", async () => {
      await page.getByRole("link", { name: "Back to sign in" }).click();
      await expect(page.getByRole("button", { name: "Sign in with Google", exact: true })).toBeEnabled();
      await expect(page.getByRole("button", { name: "Sign in with Apple", exact: true })).toBeEnabled();
      await expect(page.getByRole("button", { name: "Continue with email", exact: true })).toBeEnabled();
    });
  });
}

async function fakeApple(page: Page, email: string | null, subject: string): Promise<void> {
  await page.route("https://appleid.apple.com/auth/authorize?**", async route => {
    const authorization = new URL(route.request().url());
    expect(authorization.searchParams.get("client_id")).toBe("com.example.modern-e2e.web");
    expect(authorization.searchParams.get("scope")).toBe("email");
    expect(authorization.searchParams.get("response_mode")).toBe("form_post");
    expect(authorization.searchParams.get("response_type")).toBe("code");
    expect(authorization.searchParams.get("redirect_uri")).toBe(`${origin}/api/auth/providers/apple/callback`);
    expect(authorization.searchParams.has("code_challenge")).toBe(false);
    const code = Buffer.from(JSON.stringify({ email, subject, nonce: authorization.searchParams.get("nonce") })).toString("base64url");
    await route.fulfill({
      contentType: "text/html",
      body: `<html><body><h1>Synthetic Apple sign-in</h1><form action="${escapeHtml(authorization.searchParams.get("redirect_uri")!)}" method="post"><input type="hidden" name="state" value="${escapeHtml(authorization.searchParams.get("state")!)}"><input type="hidden" name="code" value="${code}"><button type="submit">Continue as synthetic Apple identity</button></form></body></html>`
    });
  });
}

async function finishApple(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Synthetic Apple sign-in" })).toBeVisible();
  const callback = page.waitForResponse(response => new URL(response.url()).pathname === "/api/auth/providers/apple/callback");
  await page.getByRole("button", { name: "Continue as synthetic Apple identity" }).click();
  const response = await callback;
  const request = response.request();
  expect(request.method()).toBe("POST");
  const headers = await request.allHeaders();
  expect(headers["origin"]).toBe("https://appleid.apple.com");
  expect(headers["content-type"]).toContain("application/x-www-form-urlencoded");
  expect(headers["cookie"]).toContain("brainbuddy_auth_binder=");
  expect(new URLSearchParams(request.postData()!).get("state")).toMatch(/^[A-Za-z0-9_-]{43}$/);
  expect(response.status()).toBe(303);
}

async function signOut(page: Page, email: string): Promise<void> {
  await page.getByRole("button", { name: `Account menu for ${email}`, exact: true }).click();
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
  await page.getByRole("alertdialog", { name: "Sign out?" }).getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continue with email", exact: true })).toBeVisible();
  expect((await api(page, "/auth/me")).status).toBe(401);
}

async function prepareProviderPassword(page: Page, provider: "google" | "apple", value: string): Promise<void> {
  await page.goto("/settings/account");
  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("New password", { exact: true }).fill(value);
  await page.getByLabel("Repeat password", { exact: true }).fill(value);
  await page.getByRole("button", { name: "Confirm and save", exact: true }).click();
  await page.getByRole("button", { name: `Confirm with ${provider === "google" ? "Google" : "Apple"}`, exact: true }).click();
  if (provider === "google") await finishGoogle(page);
  else await finishApple(page);
  await expect(page.getByRole("button", { name: "Add password", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add password", exact: true }).click();
  await page.getByLabel("New password", { exact: true }).fill(value);
  await page.getByLabel("Repeat password", { exact: true }).fill(value);
}

async function accessible(page: Page, surface = "Authentication"): Promise<void> {
  const result = await new AxeBuilder({ page }).analyze();
  await attachment("Accessibility scan summary", JSON.stringify({
    pathname: new URL(page.url()).pathname,
    surface,
    engine: result.testEngine,
    violations: result.violations.map(({ id, impact }) => ({ id, impact })),
    passed_rules: result.passes.length,
    incomplete_rules: result.incomplete.length,
    inapplicable_rules: result.inapplicable.length
  }), "application/json");
  await attachment(`${surface} screen (inputs masked)`, await page.screenshot({
    fullPage: true, mask: [page.locator("input")]
  }), "image/png");
  expect(result.violations.filter(violation => violation.impact === "serious" || violation.impact === "critical")).toEqual([]);
}

interface FeedbackFrame { elapsed_ms: number; busy: boolean; disabled: boolean; visible: boolean; width: number; height: number }

async function pendingFeedback(page: Page, browser: Browser, testInfo: TestInfo, action: string, path: string, trigger: Locator, submit: Locator, status: number): Promise<void> {
  const marker = action.replace(/[^a-zA-Z0-9]/g, "-");
  const pattern = `**/api${path}`;
  let dispatches = 0;
  let realStatus: number | undefined;
  let releaseResponse: () => void = () => undefined;
  const pending = new Promise<void>(resolve => { releaseResponse = resolve; });
  const handler = async (route: Route) => {
    dispatches += 1;
    const response = await realResponse(route);
    realStatus = response.status();
    await pending;
    await route.fulfill({ response });
  };
  await expect(submit).toBeEnabled();
  await submit.scrollIntoViewIfNeeded();
  await submit.evaluate((element, marker) => element.setAttribute("data-modern-e2e-submit", marker), marker);
  await trigger.evaluate((element, marker) => element.setAttribute("data-modern-e2e-trigger", marker), marker);
  const markedTrigger = page.locator(`[data-modern-e2e-trigger="${marker}"]`);
  await trigger.focus();
  await page.route(pattern, handler);
  const completed = page.waitForResponse(response => new URL(response.url()).pathname === `/api${path}`, { timeout: 90_000 });
  // Observe an early rejection while held; awaiting the original in finally
  // still enforces response completion and preserves the failing assertion.
  void completed.catch(() => undefined);
  try {
    await page.evaluate(marker => {
      const state = window as Window & { modernPendingFeedback?: FeedbackFrame };
      delete state.modernPendingFeedback;
      document.addEventListener("keydown", event => {
        if (event.key !== "Enter") return;
        const started = performance.now();
        const frame = () => {
          const button = document.querySelector<HTMLButtonElement>(`[data-modern-e2e-submit="${marker}"]`);
          if (!button) return;
          const bounds = button.getBoundingClientRect();
          const style = getComputedStyle(button);
          const visible = bounds.width > 0 && bounds.height > 0 && bounds.x >= 0 && bounds.y >= 0 && bounds.right <= innerWidth && bounds.bottom <= innerHeight && style.visibility === "visible" && style.display !== "none";
          const busy = button.closest("[aria-busy]")?.getAttribute("aria-busy") === "true" || /Please wait|Checking/.test(button.textContent ?? "");
          if (visible && busy && button.disabled) state.modernPendingFeedback = { elapsed_ms: performance.now() - started, busy, disabled: button.disabled, visible, width: bounds.width, height: bounds.height };
          else if (performance.now() - started < 2000) requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
      }, { once: true, capture: true });
    }, marker);
    await page.keyboard.press("Enter");
    await expect.poll(() => page.evaluate(() => (window as Window & { modernPendingFeedback?: FeedbackFrame }).modernPendingFeedback)).toBeDefined();
    const measured = await page.evaluate(() => (window as Window & { modernPendingFeedback?: FeedbackFrame }).modernPendingFeedback!);
    expect(measured.elapsed_ms).toBeLessThanOrEqual(200);
    expect(measured.busy && measured.disabled && measured.visible).toBe(true);
    expect(measured.height).toBeGreaterThanOrEqual(44);
    expect(measured.width).toBeGreaterThanOrEqual(44);
    await expect.poll(() => realStatus).toBe(status);
    await expect.poll(() => dispatches).toBe(1);
    await page.keyboard.press("Enter");
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
    expect(dispatches).toBe(1);
    if (await markedTrigger.evaluate(element => element instanceof HTMLInputElement)) await expect(markedTrigger).toBeFocused();
    await page.keyboard.press("Tab");
    const preferences = await page.evaluate(() => {
      const active = document.activeElement as HTMLElement | null;
      const bounds = active?.getBoundingClientRect();
      return {
        headless: /HeadlessChrome/.test(navigator.userAgent),
        reduced_motion: matchMedia("(prefers-reduced-motion: reduce)").matches,
        visibility: document.visibilityState,
        focus_reachable: Boolean(active && active !== document.body && !active.matches(":disabled") && bounds && bounds.width > 0 && bounds.height > 0),
        focus_outline_px: active ? Number.parseFloat(getComputedStyle(active).outlineWidth) : 0,
        focus_visible: Boolean(active?.matches(":focus-visible") && (Number.parseFloat(getComputedStyle(active).outlineWidth) > 0 || getComputedStyle(active).boxShadow !== "none")),
        device_pixel_ratio: devicePixelRatio,
        horizontal_overflow: document.documentElement.scrollWidth > innerWidth,
        viewport: { width: innerWidth, height: innerHeight }
      };
    });
    expect(preferences.focus_reachable).toBe(true);
    expect(preferences.focus_visible).toBe(true);
    expect(preferences.horizontal_overflow).toBe(false);
    expect(preferences.visibility).toBe("visible");
    if (process.env.BRAIN_BUDDY_MODERN_E2E_HEADED === "1") expect(preferences.headless).toBe(false);
    const candidate = (await execFileAsync("git", ["rev-parse", "HEAD"])).stdout.trim();
    await attachment(`${action} feedback measurement`, JSON.stringify({
      candidate_sha: candidate, browser: browser.version(), os: `${platform()} ${release()} ${arch()}`,
      cpu: cpus()[0]?.model ?? "unavailable", cpu_throttle: "none", action,
      completion: "held real API response", real_status: realStatus, dispatches,
      ...measured, ...preferences, reference: "1440x1000 and 390x851; physical iOS evidence remains separate"
    }), "application/json");
    await accessible(page, `${action} pending ${testInfo.title}`);
  } finally {
    releaseResponse();
    await completed;
    await page.unroute(pattern, handler);
  }
}

test.beforeAll(() => {
  expect(captureFile, "an explicit task-specific /tmp SMTP capture file is required").toMatch(/^\/tmp\/modern-auth-e2e[^]*\/[^/]+$/);
});

test.beforeEach(async ({ page }, testInfo) => {
  await epic("Authentication & Access");
  await feature("Modern authentication browser journeys");
  await story(testInfo.title);
  // Every provider call is intercepted. Unexpected outbound browser traffic
  // fails closed instead of reaching a real provider, font host, or account.
  await page.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort("blockedbyclient"));
});

for (const method of ["email", "google", "email-code"] as const) {
  test(`023-FR-013 023-FR-018 ${method} owner management recovers from another browser account`, async ({ page, context }) => {
    const email = `linked-switch-${method}-modern-e2e@gmail.com`;
    await page.setViewportSize({ width: 390, height: 844 });
    await fakeGoogle(page, email, `linked-switch-${method}-subject`);
    let owner: Me;
    let previousCookies: Awaited<ReturnType<typeof context.cookies>>;
    await test.step("establish a passwordless linked owner and a different current browser account", async () => {
      // A verified provider creates the passwordless owner without spending
      // the mailbox login quota needed by the email recovery path below.
      await page.goto("/login");
      await page.getByRole("button", { name: "Sign in with Google", exact: true }).click();
      await finishGoogle(page);
      await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
      owner = (await api<Me>(page, "/auth/me")).body;
      expect((await api<AccountMethods>(page, "/account/auth-methods")).body.has_password).toBe(false);
      expect((await api(page, "/auth/logout", {})).status).toBe(204);
      await passwordLogin(page, otherEmail);
      previousCookies = await context.cookies();
      expect((await api<Me>(page, "/auth/me")).body.id).not.toBe(owner.id);
    });
    await test.step("withhold sign-in until explicit server-confirmed sign-out, including offline retry", async () => {
      const pathname = method === "google" ? "/settings/account" : "/settings/account/delete";
      await page.goto(`${pathname}?expected_owner=${encodeURIComponent(owner.id)}`);
      const switchButton = page.getByRole("button", { name: "Sign out and use linked account", exact: true });
      await expect(switchButton).toBeVisible();
      await expect(page.getByRole("button", { name: "Sign in with Google", exact: true })).toHaveCount(0);
      await expect(page.getByLabel("Email address", { exact: true })).toHaveCount(0);
      await accessible(page);
      await page.route("**/api/auth/logout", route => route.abort("failed"), { times: 1 });
      await switchButton.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("alert")).toContainText("Couldn't confirm sign-out");
      expect((await api<Me>(page, "/auth/me")).body.email).toBe(otherEmail);
      await expect(page.getByLabel("Email address", { exact: true })).toHaveCount(0);
      await accessible(page);
      await switchButton.click();
      await expect(page.getByRole("button", { name: "Continue with email", exact: true })).toBeVisible();
      expect((await api(page, "/auth/me")).status).toBe(401);
      const sibling = await context.newPage();
      await sibling.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort("blockedbyclient"));
      let signInPosts = 0;
      page.on("request", request => {
        if (request.method() === "POST" && ["/api/auth/email/request", "/api/auth/providers/google/start", "/api/auth/email/verify"].includes(new URL(request.url()).pathname)) signInPosts += 1;
      });
      try {
        await passwordLogin(sibling, otherEmail);
        if (method !== "google") {
          await page.getByLabel("Email address", { exact: true }).fill(email);
          await page.getByRole("button", { name: "Continue with email", exact: true }).click();
        } else await page.getByRole("button", { name: "Sign in with Google", exact: true }).click();
        await expect(switchButton).toBeVisible();
        expect(signInPosts).toBe(0);
        expect((await api<Me>(page, "/auth/me")).body.email).toBe(otherEmail);
        await accessible(page);
        await switchButton.click();
        await expect(page.getByRole("button", { name: "Continue with email", exact: true })).toBeVisible();
        expect((await api(page, "/auth/me")).status).toBe(401);
        if (method === "email-code") {
          await page.getByLabel("Email address", { exact: true }).fill(email);
          await page.getByRole("button", { name: "Continue with email", exact: true }).click();
          await expect(page.getByLabel("Email code", { exact: true })).toBeVisible();
          await passwordLogin(sibling, otherEmail);
          await page.getByLabel("Email code", { exact: true }).fill("123456");
          await page.getByRole("button", { name: "Verify and continue", exact: true }).click();
          await expect(switchButton).toBeVisible();
          expect(signInPosts).toBe(1);
          expect((await api<Me>(page, "/auth/me")).body.email).toBe(otherEmail);
          await switchButton.click();
          await expect(page.getByRole("button", { name: "Continue with email", exact: true })).toBeVisible();
        }
      } finally { await sibling.close(); }
      if (method === "email") {
        await page.getByLabel("Email address", { exact: true }).fill(email);
        await page.getByRole("button", { name: "Continue with email", exact: true }).click();
        await enterCode(page, email, "login");
      } else {
        if (method === "email-code") {
          // Abandoning a proof must not bypass the real mailbox cooldown.
          // A fresh connected provider remains a usable recovery method.
          await page.getByLabel("Email address", { exact: true }).fill(email);
          const limited = page.waitForResponse(response => new URL(response.url()).pathname === "/api/auth/email/request");
          await page.getByRole("button", { name: "Continue with email", exact: true }).click();
          expect((await limited).status()).toBe(429);
          await expect(page.getByRole("alert")).toContainText("Too many attempts");
          await accessible(page);
        }
        await page.getByRole("button", { name: "Sign in with Google", exact: true }).click();
        await finishGoogle(page);
      }
      await expect(page.getByRole("heading", { name: "Account settings", exact: true })).toBeVisible();
      expect(new URL(page.url()).pathname).toBe(pathname);
      expect(new URL(page.url()).searchParams.get("expected_owner")).toBe(owner.id);
      expect((await api<Me>(page, "/auth/me")).body.id).toBe(owner.id);
    });
    await test.step("read back revocation of the previous browser session while retaining the linked owner", async () => {
      const currentCookies = await context.cookies();
      await context.clearCookies();
      await context.addCookies(previousCookies);
      expect((await api(page, "/auth/me")).status).toBe(401);
      await context.clearCookies();
      await context.addCookies(currentCookies);
      expect((await api<Me>(page, "/auth/me")).body.id).toBe(owner.id);
    });
  });
}

test("023-FR-001 023-FR-008 023-SC-001 email signup commits one session and survives reload", async ({ page }) => {
  const email = "signup-modern-e2e@example.com";
  await test.step("request a neutral code and finish through the real browser form", async () => {
    const verifying = page.waitForRequest(request => new URL(request.url()).pathname === "/api/auth/email/verify");
    await emailSignup(page, email);
    const spent = (await verifying).postDataJSON() as Record<string, unknown>;
    expect((await api(page, "/auth/email/verify", spent)).status).toBe(400);
    const current = await api<Me>(page, "/auth/me");
    expect(current.status).toBe(200);
    expect(current.body.email).toBe(email);
    const methods = await api<AccountMethods>(page, "/account/auth-methods");
    expect(methods.body.has_password).toBe(false);
    expect(methods.body.email_verified).toBe(true);
  });
  await test.step("reload retains the server-backed session", async () => {
    await page.reload();
    await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
    expect((await api<Me>(page, "/auth/me")).body.email).toBe(email);
  });
});

test("023-FR-004 023-FR-005 023-SC-001 Google signup verifies a signed assertion and clears callback material", async ({ page }) => {
  const email = "google-modern-e2e@gmail.com";
  await fakeGoogle(page, email, "google-signup-subject");
  await test.step("complete the fixed Google authorization and real callback exchange", async () => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Sign in with Google" }).click();
    await finishGoogle(page);
    await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
    expect((await api<Me>(page, "/auth/me")).body.email).toBe(email);
    const methods = await api<AccountMethods>(page, "/account/auth-methods");
    expect(methods.body.methods.some(method => method.method === "google" && method.usable)).toBe(true);
    expect(methods.body.has_password).toBe(false);
    expect(await page.evaluate(() => ({ hash: location.hash, pending: sessionStorage.getItem("brainbuddy.auth.provider-attempt") }))).toEqual({ hash: "", pending: null });
  });
});

test("023-FR-001 023-FR-004 023-FR-006 023-FR-013 023-SC-001 Apple form-post signup returns to the same subject and never merges a matching email", async ({ page }) => {
  const email = "apple-modern-e2e@privaterelay.appleid.com";
  const subject = "apple-signup-subject";
  let owner: Me;
  let taskId: string;
  await test.step("a signed Apple relay assertion creates one passwordless account through the real callback", async () => {
    await fakeApple(page, email, subject);
    await page.goto("/login");
    await expect(page.getByRole("button", { name: "Sign in with Apple", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Sign in with Apple", exact: true }).click();
    await finishApple(page);
    await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
    owner = (await api<Me>(page, "/auth/me")).body;
    expect(owner.email).toBe(email);
    const methods = (await api<AccountMethods>(page, "/account/auth-methods")).body;
    expect(methods.has_password).toBe(false);
    expect(methods.email_verified).toBe(true);
    expect(methods.methods.some(method => method.method === "apple" && method.usable)).toBe(true);
    const task = await api<{ id: string }>(page, "/tasks", { title: "Preserve Apple subject ownership", state: "inbox" });
    expect(task.status).toBe(201);
    taskId = task.body.id;
    await signOut(page, email);
  });
  await test.step("a returning assertion without another email claim retains the stable subject owner and data", async () => {
    await fakeApple(page, null, subject);
    await page.getByRole("button", { name: "Sign in with Apple", exact: true }).click();
    await finishApple(page);
    await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
    expect((await api<Me>(page, "/auth/me")).body).toMatchObject({ id: owner.id, email });
    expect((await api<{ title: string }>(page, `/tasks/${taskId}`)).body.title).toBe("Preserve Apple subject ownership");
    await signOut(page, email);
  });
  await test.step("a different Apple subject with the matching relay address receives no account authority", async () => {
    await fakeApple(page, email, "apple-distinct-matching-email-subject");
    await page.getByRole("button", { name: "Sign in with Apple", exact: true }).click();
    await finishApple(page);
    await expect(page.getByRole("alert")).toContainText("Connect to your existing account");
    expect((await api(page, "/auth/me")).status).toBe(401);
    await fakeApple(page, null, subject);
    await page.goto("/login");
    await page.getByRole("button", { name: "Sign in with Apple", exact: true }).click();
    await finishApple(page);
    await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
    expect((await api<Me>(page, "/auth/me")).body.id).toBe(owner.id);
    expect((await api<{ title: string }>(page, `/tasks/${taskId}`)).body.title).toBe("Preserve Apple subject ownership");
    await page.goto("/settings/account");
    await accessible(page);
  });
});

test("023-FR-006 023-FR-010 external Google email requires mailbox completion before any session", async ({ page }) => {
  const email = "external-modern-e2e@example.com";
  await fakeGoogle(page, email, "external-mailbox-subject");
  await test.step("a verified third-party claim stages a mailbox challenge without account authority", async () => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Sign in with Google" }).click();
    await finishGoogle(page);
    await expect(page.getByLabel("Email code")).toBeVisible();
    expect((await api(page, "/auth/me")).status).toBe(401);
  });
  await test.step("mailbox proof finishes the original provider attempt exactly once", async () => {
    await enterCode(page, email, "provider_mailbox");
    await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
    const methods = await api<AccountMethods>(page, "/account/auth-methods");
    expect(methods.body.email_verified).toBe(true);
    expect(methods.body.methods.some(method => method.method === "google" && method.usable)).toBe(true);
  });
});

test("023-FR-013 023-FR-014 023-SC-003 legacy collision requires password ownership and interrupted linking refreshes that owner", async ({ page }) => {
  await fakeGoogle(page, legacyEmail, "legacy-link-subject");
  await test.step("matching an unverified legacy address never signs into or merges its account", async () => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Sign in with Google" }).click();
    await finishGoogle(page);
    await expect(page.getByRole("alert")).toContainText("Connect to your existing account");
    expect((await api(page, "/auth/me")).status).toBe(401);
  });
  await test.step("confirm the existing owner and commit a real link despite a lost completion response", async () => {
    await passwordLogin(page, legacyEmail);
    const owner = (await api<Me>(page, "/auth/me")).body;
    const task = await api<{ id: string }>(page, "/tasks", { title: "Preserve legacy account task", state: "inbox" });
    expect(task.status).toBe(201);
    await page.goto("/settings/account");
    await page.getByRole("button", { name: "Connect Google", exact: true }).click();
    await page.getByLabel("Current password").fill(password);
    await page.route("**/api/auth/providers/complete", async route => {
      const completed = await realResponse(route);
      expect(completed.status()).toBe(200);
      expect((await completed.json()).status).toBe("linked");
      await route.abort("failed");
    });
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await finishGoogle(page);
    await expect(page.getByRole("alert")).toContainText("couldn't confirm whether linking finished");
    await page.getByRole("link", { name: "Check your sign-in methods" }).click();
    await expect(page.getByRole("button", { name: "Remove Google", exact: true })).toBeVisible();
    expect((await api<Me>(page, "/auth/me")).body.id).toBe(owner.id);
    expect((await api<{ title: string }>(page, `/tasks/${task.body.id}`)).body.title).toBe("Preserve legacy account task");
  });
});

test("023-FR-011 023-SC-004 verified password recovery revokes existing sessions and requires a fresh login", async ({ page, context }) => {
  await test.step("establish an existing password session before requesting recovery", async () => {
    await passwordLogin(page, recoveryEmail);
    const oldCookies = await context.cookies();
    // Discard only this browser's cookie; keep the existing server session
    // live so the later read-back proves reset, rather than logout, revoked it.
    await context.clearCookies();
    await page.goto("/login");
    await page.getByRole("button", { name: "Use your password", exact: true }).click();
    await page.getByRole("button", { name: "Forgot password?", exact: true }).click();
    await page.getByLabel("Email address", { exact: true }).fill(recoveryEmail);
    await page.getByRole("button", { name: "Send a recovery code", exact: true }).click();
    await enterCode(page, recoveryEmail, "recover");
    const nextPassword = `${password}-reset`;
    await page.getByLabel("New password", { exact: true }).fill(nextPassword);
    await page.getByLabel("Repeat password", { exact: true }).fill(nextPassword);
    await page.getByRole("button", { name: "Save password", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Password reset. Sign in with your new password.");
    expect((await api(page, "/auth/me")).status).toBe(401);
    await context.addCookies(oldCookies);
    expect((await api(page, "/auth/me")).status).toBe(401);
    await context.clearCookies();
    await passwordLogin(page, recoveryEmail, nextPassword);
  });
});

test("023-FR-004 023-FR-008 023-SC-003 a stolen callback handoff without its initiating verifier grants no session", async ({ page, browser }) => {
  await fakeGoogle(page, "stolen-modern-e2e@gmail.com", "stolen-handoff-subject");
  await test.step("obtain only the callback handoff from a real signed provider exchange", async () => {
    await page.goto("/login");
    const proof = await clientProof(page);
    const started = await api<ProviderStarted>(page, "/auth/providers/google/start", { purpose: "login", client: "web", client_challenge: proof.challenge });
    expect(started.status).toBe(200);
    await page.goto(started.body.authorization_url);
    const callback = page.waitForResponse(response => new URL(response.url()).pathname === "/api/auth/providers/google/callback");
    await finishGoogle(page);
    const location = (await (await callback).allHeaders()).location;
    const fragment = new URLSearchParams(new URL(location).hash.slice(1));
    const stolen = { attempt_id: fragment.get("attempt"), state: fragment.get("state"), handoff_code: fragment.get("grant"), client_verifier: "w".repeat(43) };
    await expect(page.getByRole("alert")).toBeVisible();
    expect((await api(page, "/auth/providers/complete", stolen)).status).toBe(404);
    expect((await api(page, "/auth/me")).status).toBe(401);
    const attacker = await browser.newContext({ baseURL: origin, ignoreHTTPSErrors: true });
    try {
      const stranger = await attacker.newPage();
      await stranger.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
      await stranger.goto("/login");
      expect((await api(stranger, "/auth/providers/complete", stolen)).status).toBe(404);
      expect((await api(stranger, "/auth/me")).status).toBe(401);
    } finally { await attacker.close(); }
  });
});

test("023-FR-018 023-FR-020 023-SC-005 a passwordless account confirms export and deletion with its connected Google identity", async ({ page }) => {
  const email = "rights-modern-e2e@gmail.com";
  await fakeGoogle(page, email, "passwordless-rights-subject");
  await test.step("create the account and confirm export using the connected provider", async () => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Sign in with Google" }).click();
    await finishGoogle(page);
    await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
    await page.goto("/settings/account");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await expect(page.getByLabel("Current password")).toHaveCount(0);
    await page.getByRole("button", { name: "Confirm with Google" }).click();
    await finishGoogle(page);
    await expect(page.getByRole("button", { name: "Export", exact: true })).toBeVisible();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const archive = await download;
    expect(archive.suggestedFilename()).toMatch(/\.zip$/);
    const archivePath = await archive.path();
    expect(archivePath).toBeTruthy();
    await execFileAsync(process.env.BRAIN_BUDDY_MODERN_E2E_PYTHON ?? "python", ["-c", `
import json, sys, zipfile
forbidden = {"password_hash", "session_token", "token_hash", "code", "code_hmac", "recent_proof", "reset_grant", "client_verifier", "nonce", "sealed_payload", "key_id", "access_token", "refresh_token", "provider_credentials"}
def inspect(value):
    if isinstance(value, dict):
        assert not forbidden.intersection(value), "An authority-bearing field reached export"
        for child in value.values(): inspect(child)
    elif isinstance(value, list):
        for child in value: inspect(child)
with zipfile.ZipFile(sys.argv[1]) as archive:
    documents = [json.loads(archive.read(name)) for name in archive.namelist() if name.endswith(".json")]
    for document in documents: inspect(document)
    assert any("passwordless-rights-subject" in json.dumps(document) for document in documents), "Safe provider subject metadata is absent"
`, archivePath!]);
    await expect(page.getByRole("status")).toContainText("Auth secrets are excluded");
    await accessible(page);
  });
  await test.step("confirm deletion with fresh action-bound proof and end the session", async () => {
    await page.getByRole("button", { name: "Delete account…", exact: true }).click();
    await expect(page.getByRole("button", { name: "Keep account", exact: true })).toBeFocused();
    await page.getByRole("button", { name: "Confirm and delete", exact: true }).click();
    await page.getByRole("button", { name: "Confirm with Google" }).click();
    await finishGoogle(page);
    await expect(page.getByRole("button", { name: "Delete account…", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Delete account…", exact: true }).click();
    const deletion = page.waitForResponse(response => new URL(response.url()).pathname === "/api/account/auth-delete");
    await page.getByRole("button", { name: "Confirm and delete", exact: true }).click();
    const response = await deletion;
    expect(response.status()).toBe(202);
    const scheduled = await response.json() as { deletion_requested_at: string; purge_at: string };
    expect(Date.parse(scheduled.purge_at) - Date.parse(scheduled.deletion_requested_at)).toBe(14 * 24 * 60 * 60 * 1000);
    await expect(page).toHaveURL(/\/login$/);
    expect((await api(page, "/auth/me")).status).toBe(401);
    const displayedDate = await page.evaluate(purgeAt => new Date(purgeAt).toLocaleDateString(), scheduled.purge_at);
    await expect(page.getByRole("status")).toContainText(`permanently deleted on ${displayedDate}`);
  });
});

test("023-FR-018 023-SC-003 a browser account switch cannot spend the previous owner's export proof", async ({ page }) => {
  await test.step("obtain a legitimate action-specific proof for the first owner", async () => {
    await passwordLogin(page, staleEmail);
    const owner = (await api<Me>(page, "/auth/me")).body;
    const confirmed = await api<RecentProof>(page, "/auth/confirm/password", { current_password: password, action: "export", expected_account_id: owner.id });
    expect(confirmed.status).toBe(200);
    await page.goto("/settings/account");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const switched = await api<Me>(page, "/auth/login", { email: otherEmail, password });
    expect(switched.status).toBe(200);
    expect(switched.body.id).not.toBe(owner.id);
    const stale = await api(page, "/account/auth-export", { recent_proof: confirmed.body.recent_proof, expected_account_id: owner.id });
    expect(stale.status).toBe(404);
    await page.getByLabel("Current password").fill(password);
    const rejected = page.waitForResponse(response => new URL(response.url()).pathname === "/api/auth/confirm/password");
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    expect((await rejected).status()).toBe(404);
    await expect(page.getByRole("alert")).toBeVisible();
    expect((await api<Me>(page, "/auth/me")).body.id).toBe(switched.body.id);
  });
});

test("023-SC-007 023-FR-016 023-FR-022 keyboard submission paints disabled busy feedback within 200ms and dispatches once", async ({ page, browser }, testInfo) => {
  const email = "feedback-modern-e2e@example.com";
  let dispatches = 0;
  let release: () => void = () => undefined;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/auth/email/request", async route => {
    dispatches += 1;
    const response = await realResponse(route);
    await held;
    await route.fulfill({ response });
  });
  try {
    await test.step("hold real completion while measuring the first busy frame from keyboard action", async () => {
      await page.goto("/login");
      await accessible(page);
      await page.getByLabel("Email address", { exact: true }).fill(email);
      await page.getByLabel("Email address", { exact: true }).focus();
      await page.evaluate(() => {
        const state = window as Window & { modernAuthFeedback?: { elapsed: number; busy: boolean; disabled: boolean } };
        document.addEventListener("keydown", event => {
          if (event.key !== "Enter") return;
          const form = (event.target as HTMLElement).closest("form")!;
          const started = performance.now();
          const frame = () => {
            const button = form.querySelector<HTMLButtonElement>("button[type=submit]")!;
            const busy = form.getAttribute("aria-busy") === "true";
            if (busy && button.disabled) state.modernAuthFeedback = { elapsed: performance.now() - started, busy, disabled: button.disabled };
            else if (performance.now() - started < 2000) requestAnimationFrame(frame);
          };
          requestAnimationFrame(frame);
        }, { once: true, capture: true });
      });
      await page.keyboard.press("Enter");
      const emailForm = page.locator("form").filter({ has: page.getByLabel("Email address", { exact: true }) });
      await expect(emailForm).toHaveAttribute("aria-busy", "true");
      await expect(emailForm.locator('button[type="submit"]')).toBeDisabled();
      await expect.poll(() => page.evaluate(() => (window as Window & { modernAuthFeedback?: unknown }).modernAuthFeedback)).toBeDefined();
      const measured = await page.evaluate(() => (window as Window & { modernAuthFeedback?: { elapsed: number; busy: boolean; disabled: boolean } }).modernAuthFeedback!);
      expect(measured.elapsed).toBeLessThanOrEqual(200);
      expect(measured.busy && measured.disabled).toBe(true);
      await page.keyboard.press("Enter");
      expect(dispatches).toBe(1);
      await expect(page.getByLabel("Email address", { exact: true })).toBeFocused();
      await attachment("Browser feedback measurement", JSON.stringify({
        browser: browser.version(), headless: process.env.BRAIN_BUDDY_MODERN_E2E_HEADED !== "1" && (testInfo.project.use.headless ?? true),
        viewport: page.viewportSize(), action: "keyboard Enter", completion: "held real API response",
        elapsed_ms: measured.elapsed, busy: measured.busy, disabled: measured.disabled, dispatches,
        reference_limit: "200ms; headed reference and physical iOS evidence remain separate acceptance requirements"
      }), "application/json");
    });
    await test.step("release the real response, retain focus, and complete the captured email proof", async () => {
      release();
      await expect(page.getByLabel("Email code")).toBeFocused();
      await accessible(page);
      await enterCode(page, email, "login");
      await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
    });
  } finally { release(); }
});

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 851 }]) {
  test.describe(`documented feedback reference ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });
    test("023-SC-007 023-FR-022 023-FR-008 023-FR-011 real pending auth actions retain visible feedback and keyboard access", async ({ page, browser }, testInfo) => {
      test.setTimeout(120_000);
      const email = `timing-mail-${viewport.width}@example.com`;
      const googleEmail = `timing-mutation-${viewport.width}@gmail.com`;
      const nextPassword = "Timing-safe-password-123";
      const recoveredPassword = "Timing-recovered-password-456";
      await test.step("email request and verification show first-frame feedback while their real responses are held", async () => {
        await page.goto("/login");
        await page.getByLabel("Email address", { exact: true }).fill(email);
        await pendingFeedback(page, browser, testInfo, "Email request", "/auth/email/request",
          page.getByLabel("Email address", { exact: true }), page.getByRole("button", { name: "Continue with email", exact: true }), 202);
        await expect(page.getByLabel("Email code")).toBeFocused();
        await page.getByLabel("Email code").fill(await readCode(email, "login"));
        await pendingFeedback(page, browser, testInfo, "Email verification", "/auth/email/verify",
          page.getByLabel("Email code"), page.getByRole("button", { name: "Verify and continue", exact: true }), 200);
        await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
        await signOut(page, email);
      });
      await test.step("provider start paints disabled feedback before navigating to its actual synthetic provider boundary", async () => {
        await fakeGoogle(page, googleEmail, `timing-subject-${viewport.width}`);
        const start = page.getByRole("button", { name: "Sign in with Google", exact: true });
        await pendingFeedback(page, browser, testInfo, "Provider start", "/auth/providers/google/start", start, start, 200);
        await finishGoogle(page);
        await expect(page.getByRole("heading", { name: "Next actions", exact: true })).toBeVisible();
      });
      const owner = (await api<Me>(page, "/auth/me")).body;
      await test.step("a fresh provider confirmation authorizes a separately measured account mutation", async () => {
        await prepareProviderPassword(page, "google", nextPassword);
        await pendingFeedback(page, browser, testInfo, "Account password mutation", "/account/auth-password",
          page.getByLabel("Repeat password", { exact: true }), page.getByRole("button", { name: "Confirm and save", exact: true }), 204);
        await expect(page.getByRole("status")).toContainText("Password saved");
        expect((await api<Me>(page, "/auth/me")).body.id).toBe(owner.id);
        expect((await api<AccountMethods>(page, "/account/auth-methods")).body.has_password).toBe(true);
        await signOut(page, googleEmail);
      });
      await test.step("recovery save holds the actual reset response without auto-login and preserves reachable focus", async () => {
        await page.getByRole("button", { name: "Use your password", exact: true }).click();
        await page.getByRole("button", { name: "Forgot password?", exact: true }).click();
        await page.getByLabel("Email address", { exact: true }).fill(googleEmail);
        await page.getByRole("button", { name: "Send a recovery code", exact: true }).click();
        await enterCode(page, googleEmail, "recover");
        await page.getByLabel("New password", { exact: true }).fill(recoveredPassword);
        await page.getByLabel("Repeat password", { exact: true }).fill(recoveredPassword);
        await pendingFeedback(page, browser, testInfo, "Recovery password save", "/auth/recovery/reset",
          page.getByLabel("Repeat password", { exact: true }), page.getByRole("button", { name: "Save password", exact: true }), 204);
        await expect(page.getByRole("status")).toContainText("Password reset");
        expect((await api(page, "/auth/me")).status).toBe(401);
        await passwordLogin(page, googleEmail, recoveredPassword);
        expect((await api<Me>(page, "/auth/me")).body.id).toBe(owner.id);
      });
    });
  });
}
