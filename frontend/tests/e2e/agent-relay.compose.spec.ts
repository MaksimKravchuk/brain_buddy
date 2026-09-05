/**
 * The A2A wire, driven through the product surfaces against real agents.
 *
 * Two reference runtimes run beside the stack under the Compose `agents`
 * profile: the unmodified a2a-sdk `helloworld` sample in the backend's network
 * namespace, and the unmodified Hermes A2A plugin at `http://hermes-a2a:9900/`.
 * Nothing here mocks a response — what these stories prove is that the wire
 * works against servers nobody adapted for BrainBuddy (014-FR-017).
 *
 * 014-SC-001, 014-SC-002, 014-SC-003, 014-SC-004, 014-SC-005.
 *
 * Selectors are accessible roles and labels rather than `data-testid`, matching
 * every other spec in this suite and the component tests that prove those names
 * exist. A test id would be a second, unverified name for the same control.
 *
 * Two scoping rules follow from what the product deliberately renders twice.
 * A run states itself as a headline *and* as a timeline row, so a state label
 * and the agent's own text each appear more than once on the task page; those
 * assertions are made against the run card as a whole rather than against a
 * bare `getByText`, which Playwright would refuse as ambiguous. And a connection
 * card echoes its new status into a "Test finished: …" confirmation, so the
 * status assertions are `exact` — otherwise the case-insensitive substring
 * would match the confirmation sentence too.
 *
 * `expect` here is only ever applied to a **locator**. Every other spec in this
 * suite does the same, and the reason is mechanical: Playwright records each
 * `expect` as its own Allure step, and a comparison of two values already in
 * memory finishes inside the same millisecond, which
 * `scripts/validate_allure_taxonomy.py` indexes as a zero-duration no-op with
 * no evidence and rejects. A locator assertion auto-waits, so it carries
 * duration. `expect.poll` is *not* an escape: it nests that same instantaneous
 * matcher inside its wrapper, and the inner step measured 0 ms in 5 of 12 local
 * runs — a coin flip per assertion. So the facts these stories read back from
 * the API are compared and thrown, the way `gtdHelpers.requireOk` already
 * reports a bad status; the awaited read is what gives the surrounding step its
 * duration and its evidence.
 */
import { expect, test } from "../allure.fixtures";

import {
  apiGet,
  apiPost,
  backendUrl,
  createTaskViaApi,
  mintInvite,
  password,
  signupThroughUi,
  uniqueEmail,
  uniqueKey
} from "./gtdHelpers";

import type { APIRequestContext, Locator, Page } from "@playwright/test";

/** Where the helloworld sample listens, from inside the backend's namespace. */
const HELLOWORLD_URL = "http://127.0.0.1:9999";

/** Where the Hermes fixture listens, as a Compose service — the backend's view. */
const HERMES_URL = "http://hermes-a2a:9900/";

/**
 * Where the Hermes fixture listens for *this process*.
 *
 * Playwright runs on the host, outside the Compose network, so the service name
 * above does not resolve here. `scripts/run_playwright_e2e.sh` publishes the
 * fixture on a free host port and passes the address in. Only the direct
 * interrogation of the agent uses it; the connection BrainBuddy stores keeps the
 * service address, because that is the one the backend has to be able to reach.
 */
const HERMES_HOST_URL = process.env.BRAIN_BUDDY_E2E_HERMES_HOST_URL ?? "http://127.0.0.1:9900/";

const HERMES_TOKEN = process.env.BRAIN_BUDDY_E2E_HERMES_TOKEN ?? "hermes-e2e-bearer-token";

interface AgentConnection {
  id: string;
  status: string;
  revision: number;
}

interface AgentRun {
  id: string;
  dispatch_state: string;
  reported_state: string | null;
  primary_state_label: string;
  agent_task_id: string | null;
}

/** Comparison that does not care what order an object's keys were built in. */
function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, inner: unknown) =>
    inner !== null && typeof inner === "object" && !Array.isArray(inner)
      ? Object.fromEntries(
          Object.entries(inner as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b))
        )
      : inner
  );
}

function same(actual: unknown, expected: unknown): boolean {
  return canonical(actual) === canonical(expected);
}

/** State a mismatch the way `expect` would, without emitting an `expect` step. */
function refuse(what: string, actual: unknown, expected: unknown): never {
  throw new Error(`${what}: expected ${canonical(expected)}, got ${canonical(actual)}`);
}

const RETRY_MS = 500;

async function readUntil<T>(
  what: string,
  read: () => Promise<T>,
  holds: (value: T) => boolean,
  expected: unknown,
  timeout: number
): Promise<T> {
  const deadline = Date.now() + timeout;
  for (;;) {
    const actual = await read();
    if (holds(actual)) {
      return actual;
    }
    if (Date.now() >= deadline) {
      refuse(what, actual, expected);
    }
    await new Promise((resolve) => setTimeout(resolve, RETRY_MS));
  }
}

/**
 * Read the API until it says what the story claims.
 *
 * Waiting rather than reading once, because the relay settles a run out of
 * band: the exchange leaves on a worker and the observer is what learns the
 * agent's answer, so a read taken the instant a request returns is a race and
 * not a fact.
 */
async function settles<T>(
  what: string,
  read: () => Promise<T>,
  expected: T,
  timeout = 60_000
): Promise<T> {
  return readUntil(what, read, (value) => same(value, expected), expected, timeout);
}

/** Read the API until it produces a value at all, then hand that value back. */
async function settlesToValue<T>(
  what: string,
  read: () => Promise<T | null>,
  timeout = 60_000
): Promise<T> {
  const value = await readUntil(what, read, (candidate) => candidate !== null, "a value", timeout);
  return value as T;
}

async function connectAgent(
  page: Page,
  { name, address, credential }: { name: string; address: string; credential: string }
): Promise<AgentConnection> {
  const created = await apiPost<AgentConnection>(page, "/api/agent-connections", {
    name,
    agent_address: address,
    auth_scheme: "bearer",
    credential,
    current_password: password
  });
  return created;
}

async function openAgentSettings(page: Page): Promise<void> {
  await page.goto("/settings/agents");
  await expect(page.getByRole("heading", { name: "Connected agents" })).toBeVisible();
}

/**
 * Test one saved connection and wait for the status it earned.
 *
 * Clicking is the whole ceremony: readiness costs no password, because testing
 * sends no task content (`app/api/agents.py` `test_agent_connection`).
 */
async function testConnection(page: Page, agentName: string, expected: string): Promise<Locator> {
  const card = page.getByRole("article", { name: agentName });
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(card.getByText(expected, { exact: true })).toBeVisible({ timeout: 30_000 });
  return card;
}

async function openTask(page: Page, taskId: string): Promise<void> {
  // `/tasks/:state/:taskId` is the route (`app/AppRoutes.tsx`), and
  // `createTaskViaApi` files the task in `inbox`. The panel fetches the task by
  // id, so the deep link alone opens it.
  await page.goto(`/tasks/inbox/${taskId}`);
}

/**
 * Open the hand-off review and choose the agent it is for.
 *
 * The review opens with nothing selected and no manifest: the server builds
 * what-will-be-sent only once a connection is chosen, and the consent boundary
 * — every reviewable field, the acknowledgement, and **Send to agent** itself —
 * exists only while that manifest does. The reviewed manifest region is handed
 * back beside the dialog so assertions run against the disclosure rather than
 * against the dialog's header, which repeats the task title.
 */
async function openHandoffReview(
  page: Page,
  agentName: string
): Promise<{ review: Locator; manifest: Locator }> {
  await page.getByRole("button", { name: "Hand to agent" }).click();
  const review = page.getByRole("dialog");
  await review.getByRole("radio", { name: agentName }).check();
  const manifest = review.getByRole("region", { name: "What will be sent" });
  await expect(manifest).toBeVisible({ timeout: 30_000 });
  return { review, manifest };
}

/**
 * The one run card on the task, named by the agent it belongs to.
 *
 * Scoped rather than reached by bare text, because a run states itself twice on
 * purpose: the headline badge is what the run *is*, and the timeline row is when
 * it became that. Both are true, so the assertion is about the card.
 */
function runCard(page: Page, agentName: string): Locator {
  return page.getByRole("article").filter({ hasText: agentName });
}

async function runsForTask(page: Page, taskId: string): Promise<AgentRun[]> {
  return apiGet<AgentRun[]>(page, `/api/tasks/${taskId}/agent-runs`);
}

/**
 * One JSON-RPC call straight at an agent, bypassing BrainBuddy.
 *
 * Only ever used to ask the *agent* what it holds. A story that asked
 * BrainBuddy to confirm its own claim would prove nothing about the wire.
 */
async function agentRpc(
  request: APIRequestContext,
  url: string,
  method: string,
  params: Record<string, unknown>,
  bearer?: string
): Promise<Record<string, unknown>> {
  const response = await request.post(url, {
    headers: {
      "Content-Type": "application/json",
      "A2A-Version": "1.0",
      ...(bearer ? { Authorization: `Bearer ${bearer}` } : {})
    },
    data: { jsonrpc: "2.0", id: "e2e", method, params }
  });
  if (!response.ok()) {
    throw new Error(`${method} at ${url} answered ${response.status()}: ${await response.text()}`);
  }
  return (await response.json()) as Record<string, unknown>;
}

test.describe("external agent relay over the A2A wire", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    await signupThroughUi(page, uniqueEmail("relay", testInfo), await mintInvite());
  });

  test("014-SC-005 A2A hand-off to the helloworld sample", async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1440, height: 900 });

    const connection = await test.step("connect and test the sample", async () => {
      const created = await connectAgent(page, {
        name: "Hello World Agent",
        address: HELLOWORLD_URL,
        credential: "unused-by-the-sample"
      });
      await openAgentSettings(page);
      // D-01-S11: readiness is the agent's own card plus an authenticated call.
      const card = await testConnection(page, "Hello World Agent", "Tested ready");
      await expect(card.getByText("Echo Bot")).toBeVisible();
      return created;
    });

    const task = await createTaskViaApi(page, "Draft the relay migration plan");

    await test.step("review the hand-off at desktop width (D-02-S01/S02)", async () => {
      await openTask(page, task.id);
      const { review, manifest } = await openHandoffReview(page, "Hello World Agent");
      await expect(manifest.getByText("Draft the relay migration plan")).toBeVisible();
      await expect(manifest.getByText(HELLOWORLD_URL)).toBeVisible();
      // D-02-S13/S14: the send is gated on the one-time acknowledgement,
      // because this agent declares no single-start extension.
      const send = review.getByRole("button", { name: "Send to agent" });
      await expect(send).toBeDisabled();
      await review
        .getByRole("checkbox", { name: /duplicate task is possible with this agent/i })
        .check();
      await expect(send).toBeEnabled();
      await send.click();
    });

    await test.step("the sample answers inside the exchange (D-03-S11)", async () => {
      const card = runCard(page, "Hello World Agent");
      await expect(card).toContainText("Agent reported complete", { timeout: 60_000 });
      await expect(card).toContainText("Hello, World! I have received your request");
    });

    await test.step("the run is one task at the agent", async () => {
      await settles(
        "the runs BrainBuddy holds for this task",
        async () =>
          (await runsForTask(page, task.id)).map((run) => ({
            reported_state: run.reported_state,
            started_a_task_at_the_agent: run.agent_task_id !== null
          })),
        [{ reported_state: "completed", started_a_task_at_the_agent: true }]
      );
      // The 201 that registered this connection claimed nothing about it: only
      // a test can say an agent is reachable, and none had run yet.
      if (connection.status !== "untested") {
        refuse("the status a freshly registered connection reports", connection.status, "untested");
      }
    });
  });

  test("014-SC-004 A2A hand-off to the Hermes stub", async ({ page }) => {
    test.setTimeout(180_000);

    await test.step("connect and test the Hermes fixture", async () => {
      await connectAgent(page, {
        name: "Hermes",
        address: HERMES_URL,
        credential: HERMES_TOKEN
      });
      await openAgentSettings(page);
      await testConnection(page, "Hermes", "Tested ready");
    });

    const task = await createTaskViaApi(page, "Please ask me which environment to use");

    await test.step("hand off and reach Needs you (D-03-S08)", async () => {
      await openTask(page, task.id);
      const { review, manifest } = await openHandoffReview(page, "Hermes");
      await expect(manifest.getByText("Please ask me which environment to use")).toBeVisible();
      await review
        .getByRole("checkbox", { name: /duplicate task is possible with this agent/i })
        .check();
      await review.getByRole("button", { name: "Send to agent" }).click();
      // D-03-S07 then S08: the wire says **Sent**, and the agent's own
      // input-required state is what turns it into a question.
      await expect(runCard(page, "Hermes")).toContainText("Needs you", { timeout: 90_000 });
    });

    await test.step("answer the question and settle the run (D-03-S11)", async () => {
      const card = runCard(page, "Hermes");
      await card.getByRole("textbox", { name: "Your answer" }).fill("Use staging.");
      await card.getByRole("button", { name: "Send answer" }).click();
      await expect(card).toContainText("Agent reported complete", { timeout: 90_000 });
    });

    await test.step("the run kept one correlation ID across the succession (S27)", async () => {
      // One run, even though the reply started a second task at the agent: the
      // succession is recorded inside this run, never as another one.
      await settles(
        "how many runs answering the question left behind",
        async () => (await runsForTask(page, task.id)).length,
        1
      );
      const [run] = await runsForTask(page, task.id);
      await settles(
        "the correlation ID the run kept",
        async () =>
          (await apiGet<{ correlation_id: string | null }>(page, `/api/agent-runs/${run.id}`))
            .correlation_id,
        run.id
      );
    });
  });

  test("014-SC-002 A2A replay creates one task", async ({ page, request }) => {
    test.setTimeout(120_000);

    await connectAgent(page, {
      name: "Hermes",
      address: HERMES_URL,
      credential: HERMES_TOKEN
    });
    await openAgentSettings(page);
    await testConnection(page, "Hermes", "Tested ready");
    const connections = await apiGet<AgentConnection[]>(page, "/api/agent-connections");
    const connectionId = connections[0].id;

    const task = await createTaskViaApi(page, "Replay safety at the agent");

    const { token, runId } = await test.step("reserve one confirmation", async () => {
      const preview = await apiPost<{ token: string; run_id: string }>(
        page,
        `/api/tasks/${task.id}/agent-runs/preview`,
        { connection_id: connectionId }
      );
      return { token: preview.token, runId: preview.run_id };
    });

    await test.step("confirm it three times with one idempotency key", async () => {
      const key = uniqueKey("relay-replay");
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        const response = await page.request.post(`${backendUrl}/api/tasks/${task.id}/agent-runs`, {
          headers: { "Idempotency-Key": key },
          data: {
            connection_id: connectionId,
            manifest_token: token,
            acknowledge_duplicate_risk: true
          }
        });
        // Checked per attempt rather than polled: each confirmation is a single
        // answer to a single request, and retrying one would be a fourth
        // confirmation rather than a re-read of the third.
        if (response.status() !== 201) {
          refuse(`confirmation ${attempt} of 3`, response.status(), 201);
        }
      }
    });

    await test.step("BrainBuddy shows one run, and the agent holds one task", async () => {
      await settles(
        "the runs the three confirmations left behind",
        async () => (await runsForTask(page, task.id)).map((run) => run.id),
        [runId]
      );
      // The confirmation answers as soon as the run is durable; the message
      // itself leaves on an exchange worker, so the agent's task id is what has
      // to be waited for rather than the run row.
      const agentTaskId = await settlesToValue(
        "the id of the task this run started at the agent",
        async () => (await runsForTask(page, task.id))[0]?.agent_task_id ?? null
      );

      // The claim is about the *agent*, so the agent is what gets asked.
      const listed = await agentRpc(
        request,
        HERMES_HOST_URL,
        "ListTasks",
        { contextId: runId, pageSize: 20 },
        HERMES_TOKEN
      );
      const result = listed.result as { tasks?: Array<{ id: string }> };
      const heldByTheAgent = (result.tasks ?? []).map((agentTask) => agentTask.id);
      if (!same(heldByTheAgent, [agentTaskId])) {
        refuse("the tasks the agent holds in this conversation", heldByTheAgent, [agentTaskId]);
      }
    });
  });

  test("014-SC-003 A2A security rejections", async ({ page }) => {
    test.setTimeout(120_000);

    await test.step("an invalid credential is refused, and echoes nothing (D-01-S12)", async () => {
      await connectAgent(page, {
        name: "Wrong credential",
        address: HERMES_URL,
        credential: "not-the-fixture-token"
      });
      await openAgentSettings(page);
      const card = await testConnection(page, "Wrong credential", "Invalid credentials");
      await expect(card.getByText("not-the-fixture-token")).toHaveCount(0);
    });

    await test.step("a private destination is refused before a credential leaves (D-01-S18)", async () => {
      // The stack opts private destinations in for the fixtures, so the case
      // that must still be refused is one no policy admits: the cloud metadata
      // address, which is never a legitimate agent.
      const response = await page.request.post(`${backendUrl}/api/agent-connections`, {
        headers: { "Idempotency-Key": uniqueKey("relay-metadata") },
        data: {
          name: "Metadata",
          agent_address: "http://169.254.169.254/latest/meta-data/",
          auth_scheme: "bearer",
          credential: "must-not-leave",
          current_password: password
        }
      });
      // 400, not 422: the address is a well-formed URL, so it clears the
      // request schema and is refused by the destination check, which
      // `app/api/errors.py` maps to a domain-validation 400.
      const refusal = {
        status: response.status(),
        leaks_the_credential: (await response.text()).includes("must-not-leave")
      };
      const expected = { status: 400, leaks_the_credential: false };
      if (!same(refusal, expected)) {
        refuse("how the metadata address is refused", refusal, expected);
      }
    });

    await test.step("a forged push token changes nothing", async () => {
      const before = (await apiGet<AgentConnection[]>(page, "/api/agent-connections")).length;
      const forged = await page.request.post(
        `${backendUrl}/api/a2a/push/agentrun_does_not_exist/forged-token`,
        { data: {} }
      );
      if (forged.status() !== 403) {
        refuse("the answer to a forged push token", forged.status(), 403);
      }
      await settles(
        "how many connections the account has after the forged push",
        async () => (await apiGet<AgentConnection[]>(page, "/api/agent-connections")).length,
        before
      );
    });
  });
});
