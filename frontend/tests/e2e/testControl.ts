import { request as playwrightRequest } from "@playwright/test";

/**
 * Client for the test control API (spec 027, contracts/test-control.md).
 *
 * Black-box suites seed data, move the clock and run sweeps only through
 * `/api/__test__/`. The backend mounts that prefix solely with
 * BRAIN_BUDDY_ENV=test and BRAIN_BUDDY_TEST_CONTROL_TOKEN set, and the Compose
 * E2E runner sets both. No spec shells into a container or runs Python.
 */

const backendUrl = process.env.BRAIN_BUDDY_E2E_BACKEND_URL ?? "http://127.0.0.1:8000";

export type OwnerTask = { id: string; title: string; state: string; revision: number };
export type ReviewSweepCounts = {
  owners: number;
  parked: number;
  repaired: number;
  closed: number;
  gap_floors: number;
  snapshots_nulled: number;
};

type Method = "GET" | "POST" | "PUT" | "DELETE";
type ControlReply = { status: number; ok: boolean; text: string };

function controlToken(): string {
  const token = process.env.BRAIN_BUDDY_TEST_CONTROL_TOKEN;
  if (!token) throw new Error("BRAIN_BUDDY_TEST_CONTROL_TOKEN is required for the test control API");
  return token;
}

/**
 * One request with its own context, so no cookie or session leaks between
 * calls. The body is read before the context is disposed.
 */
async function control(method: Method, pathName: string, data?: Record<string, unknown>): Promise<ControlReply> {
  const api = await playwrightRequest.newContext();
  try {
    const response = await api.fetch(`${backendUrl}/api/__test__${pathName}`, {
      method,
      data,
      headers: { "X-Test-Control-Token": controlToken() },
      failOnStatusCode: false
    });
    return { status: response.status(), ok: response.ok(), text: await response.text() };
  } finally {
    await api.dispose();
  }
}

function parseOk<T>(reply: ControlReply, label: string): T {
  if (!reply.ok) throw new Error(`test control ${label} failed with ${reply.status} ${reply.text}`);
  return JSON.parse(reply.text) as T;
}

/** Mints one signup invite code for a new account. */
export async function mintTestInvite(): Promise<string> {
  const { codes } = parseOk<{ codes: string[] }>(
    await control("POST", "/invites", { count: 1 }),
    "POST /invites"
  );
  const [code] = codes;
  if (!code) throw new Error("test control minted no invite code");
  return code;
}

/** A Next task whose formulation started `days` ago; returns its id. */
export async function seedAgedTask(ownerEmail: string, days: number, title: string): Promise<string> {
  const { task_id } = parseOk<{ task_id: string }>(
    await control("POST", "/review/aged-task", { owner_email: ownerEmail, days, title }),
    "POST /review/aged-task"
  );
  return task_id;
}

/** One weekly-review maintenance sweep; the counts are the ones the CLI used to print. */
export async function runReviewSweep(): Promise<ReviewSweepCounts> {
  return parseOk<ReviewSweepCounts>(await control("POST", "/sweeps/review"), "POST /sweeps/review");
}

/** Moves server time forward. Clock-moving specs must call resetClock in afterEach. */
export async function advanceClock(seconds: number): Promise<void> {
  parseOk<Record<string, string>>(await control("POST", "/clock", { advance_seconds: seconds }), "POST /clock");
}

/** Returns server time to the wall clock. */
export async function resetClock(): Promise<void> {
  parseOk<Record<string, string>>(await control("DELETE", "/clock"), "DELETE /clock");
}

/**
 * The owner's stored tasks, read through the owner-scoped repository. Resolves
 * to "absent" when the account no longer exists (the control API answers 404).
 */
export async function readOwnerTasks(ownerEmail: string): Promise<OwnerTask[] | "absent"> {
  const reply = await control("GET", `/owners/${encodeURIComponent(ownerEmail)}/tasks`);
  if (reply.status === 404) return "absent";
  return parseOk<{ tasks: OwnerTask[] }>(reply, "GET /owners/tasks").tasks;
}
