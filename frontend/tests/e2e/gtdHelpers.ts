import { execFile } from "node:child_process";
import * as path from "node:path";
import { promisify } from "node:util";

import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

const execFileAsync = promisify(execFile);

export const password = "E2E-safe-password-123";
export const backendUrl = process.env.BRAIN_BUDDY_E2E_BACKEND_URL ?? "http://127.0.0.1:8000";
const composeProject = process.env.BRAIN_BUDDY_E2E_COMPOSE_PROJECT ?? process.env.COMPOSE_PROJECT_NAME;
const repoRoot = path.resolve(process.cwd(), "..");

export type TaskRecord = { id: string; title: string; state: string; revision: number };
export type ProjectRecord = { id: string; name: string; revision: number };
export type TagRecord = { id: string; name: string; revision: number };

export function uniqueEmail(prefix: string, testInfo: TestInfo): string {
  const slug = `${testInfo.project.name}-${testInfo.workerIndex}-${Date.now()}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-");
  return `${prefix}-${slug}@example.com`;
}

export function uniqueKey(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function requireOk(response: Awaited<ReturnType<APIRequestContext["get"]>>, label: string): Promise<void> {
  if (!response.ok()) {
    throw new Error(`${label} failed with ${response.status()} ${await response.text()}`);
  }
}

export async function mintInvite(): Promise<string> {
  if (!composeProject) {
    throw new Error("BRAIN_BUDDY_E2E_COMPOSE_PROJECT is required to mint invites for Compose E2E");
  }
  const { stdout } = await execFileAsync(
    "docker",
    ["compose", "-p", composeProject, "exec", "-T", "backend", "python", "-m", "app.cli", "create-invite"],
    { cwd: repoRoot, timeout: 30_000 }
  );
  const code = stdout.trim().split(/\s+/).at(-1);
  if (!code) throw new Error(`Invite command returned no code: ${stdout}`);
  return code;
}

export async function signupThroughUi(page: Page, email: string, inviteCode: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByLabel("Invite code").fill(inviteCode);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Next actions" })).toBeVisible();
}

export async function createUserViaApi(request: APIRequestContext, testInfo: TestInfo, prefix = "user"): Promise<string> {
  const email = uniqueEmail(prefix, testInfo);
  const response = await request.post(`${backendUrl}/api/auth/signup`, {
    data: { email, password, invite_code: await mintInvite() }
  });
  expect(response.status(), await response.text()).toBe(201);
  return email;
}

export async function loginThroughUi(page: Page, email: string, loginPassword = password): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(loginPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login$/);
}

export async function logoutSession(page: Page): Promise<void> {
  const response = await page.request.post(`${backendUrl}/api/auth/logout`);
  await requireOk(response, "logout");
  await page.context().clearCookies();
}

export async function openTaskWorkspace(page: Page, email?: string, pathName = "/"): Promise<void> {
  await page.goto(pathName);
  await expect(page.getByText("BrainBuddy", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading")).toBeVisible();
  if (email) await expect(page.getByLabel(email)).toBeVisible();
}

export async function apiPost<T>(page: Page, pathName: string, data: Record<string, unknown>): Promise<T> {
  const response = await page.request.post(`${backendUrl}${pathName}`, {
    data,
    headers: { "Idempotency-Key": uniqueKey("post") }
  });
  await requireOk(response, `POST ${pathName}`);
  return (await response.json()) as T;
}

export async function apiPatch<T>(page: Page, pathName: string, data: Record<string, unknown>) {
  const response = await page.request.patch(`${backendUrl}${pathName}`, {
    data,
    headers: { "Idempotency-Key": uniqueKey("patch") }
  });
  return response;
}

export async function apiGet<T>(page: Page, pathName: string): Promise<T> {
  const response = await page.request.get(`${backendUrl}${pathName}`);
  await requireOk(response, `GET ${pathName}`);
  return (await response.json()) as T;
}

export async function createTaskViaApi(page: Page, title: string, overrides: Record<string, unknown> = {}): Promise<TaskRecord> {
  return apiPost<TaskRecord>(page, "/api/tasks", { title, state: "inbox", ...overrides });
}

export async function createProjectViaApi(page: Page, name: string): Promise<ProjectRecord> {
  return apiPost<ProjectRecord>(page, "/api/projects", { name, color: "#0ea5e9" });
}

export async function createTagViaApi(page: Page, name: string): Promise<TagRecord> {
  return apiPost<TagRecord>(page, "/api/tags", { name });
}
