import { execFile } from "node:child_process";
import * as path from "node:path";
import { promisify } from "node:util";

import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

const execFileAsync = promisify(execFile);

export const password = "E2E-safe-password-123";
export const backendUrl = process.env.BRAIN_BUDDY_E2E_BACKEND_URL ?? "http://127.0.0.1:8000";
const composeProject = process.env.BRAIN_BUDDY_E2E_COMPOSE_PROJECT ?? process.env.COMPOSE_PROJECT_NAME;
const repoRoot = path.resolve(process.cwd(), "..");

export function uniqueEmail(prefix: string, testInfo: TestInfo): string {
  const slug = `${testInfo.project.name}-${testInfo.workerIndex}-${Date.now()}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-");
  return `${prefix}-${slug}@example.com`;
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
  const chunks = stdout.trim().split(/\s+/);
  const code = chunks[chunks.length - 1];
  if (!code) {
    throw new Error(`Invite command returned no code: ${stdout}`);
  }
  return code;
}

export async function signupThroughUi(page: Page, email: string, inviteCode: string): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByLabel("Invite code").fill(inviteCode);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).not.toHaveURL(/\/signup$/);
  await expect(page.getByRole("link", { name: "Brain Buddy" })).toBeVisible();
}

export async function createUserViaApi(request: APIRequestContext, testInfo: TestInfo, prefix = "user"): Promise<string> {
  const email = uniqueEmail(prefix, testInfo);
  const invite = await mintInvite();
  const response = await request.post(`${backendUrl}/api/auth/signup`, {
    data: { email, password, invite_code: invite }
  });
  expect(response.status(), await response.text()).toBe(201);
  return email;
}

export async function loginThroughUi(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login$/);
}

export async function openCrtWorkspace(page: Page, email?: string): Promise<void> {
  await page.goto("/crt");
  await expect(page.getByLabel("Tree menu")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  if (email) {
    await expect(page.locator(`[title="${email}"]`)).toHaveCount(1);
  }
}

export async function signOut(page: Page): Promise<void> {
  if (!(await page.getByRole("button", { name: "Sign out" }).isVisible().catch(() => false))) {
    await page.goto("/crt");
  }
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

export async function createTreeViaUi(page: Page, name: string): Promise<void> {
  await page.getByLabel("Tree menu").click();
  await page.getByRole("menuitem", { name: "New tree" }).click();
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Name").press("Enter");
  await expect(page.getByLabel("Tree menu")).toContainText(name);
}

export async function renameCurrentTreeViaUi(page: Page, nextName: string): Promise<void> {
  await page.getByLabel("Tree menu").click();
  await page.getByRole("menuitem", { name: "Rename tree" }).click();
  await page.getByLabel("Name").fill(nextName);
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByLabel("Tree menu")).toContainText(nextName);
}

export async function switchTreeViaUi(page: Page, name: string): Promise<void> {
  await page.getByLabel("Tree menu").click();
  await page.getByRole("menuitem", { name }).click();
  await expect(page.getByLabel("Tree menu")).toContainText(name);
}

export async function deleteCurrentTreeViaUi(page: Page, name: string): Promise<void> {
  await page.getByLabel("Tree menu").click();
  await page.getByRole("menuitem", { name: "Delete tree" }).click();
  await expect(page.getByRole("heading", { name: "Delete tree" })).toBeVisible();
  await expect(
    page.getByText(`This will permanently delete “${name}” including its nodes, relations, and versions.`)
  ).toBeVisible();
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("Tree deleted")).toBeVisible();
}

export async function createTreeViaApi(request: APIRequestContext, name: string): Promise<{ id: string }> {
  const response = await request.post(`${backendUrl}/api/trees`, { data: { name } });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()) as { id: string };
}

export async function createNodeViaApi(
  request: APIRequestContext,
  treeId: string,
  label: string,
  type: "parent" | "child",
  position: { x: number; y: number }
): Promise<{ id: string }> {
  const response = await request.post(`${backendUrl}/api/trees/${treeId}/nodes`, {
    data: { label, type, position, highlight_state: "none" }
  });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()) as { id: string };
}

export async function createRelationViaApi(
  request: APIRequestContext,
  treeId: string,
  sourceNodeId: string,
  targetNodeId: string
): Promise<void> {
  const response = await request.post(`${backendUrl}/api/trees/${treeId}/relations`, {
    data: { source_node_id: sourceNodeId, target_node_id: targetNodeId, kind: "why" }
  });
  expect(response.status(), await response.text()).toBe(201);
}
