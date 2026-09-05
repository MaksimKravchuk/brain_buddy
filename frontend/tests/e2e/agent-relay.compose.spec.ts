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

import type { APIRequestContext, Page } from "@playwright/test";

/** Where the helloworld sample listens, from inside the backend's namespace. */
const HELLOWORLD_URL = "http://127.0.0.1:9999";

/** Where the Hermes fixture listens, as a Compose service. */
const HERMES_URL = "http://hermes-a2a:9900/";

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

async function connectAgent(
  page: Page,
  { name, address, credential }: { name: string; address: string; credential: string }
): Promise<AgentConnection> {
  const created = await apiPost<AgentConnection>(page, "/agent-connections", {
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

async function openTask(page: Page, taskId: string): Promise<void> {
  await page.goto(`/tasks/${taskId}`);
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
  expect(response.ok()).toBeTruthy();
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
      const card = page.getByRole("article", { name: "Hello World Agent" });
      await card.getByRole("button", { name: "Test connection" }).click();
      // D-01-S11: readiness is the agent's own card plus an authenticated call.
      await expect(card.getByText("Tested ready")).toBeVisible({ timeout: 30_000 });
      await expect(card.getByText("Echo Bot")).toBeVisible();
      return created;
    });

    const task = await createTaskViaApi(page, "Draft the relay migration plan");

    await test.step("review the hand-off at desktop width (D-02-S01/S02)", async () => {
      await openTask(page, task.id);
      await page.getByRole("button", { name: "Hand to agent" }).click();
      const review = page.getByRole("dialog");
      await expect(review.getByText("Draft the relay migration plan")).toBeVisible();
      await expect(review.getByText(HELLOWORLD_URL)).toBeVisible();
      // D-02-S13/S14: the send is gated on the one-time acknowledgement,
      // because this agent declares no single-start extension.
      const send = review.getByRole("button", { name: "Send to agent" });
      await expect(send).toBeDisabled();
      await review
        .getByLabel(/duplicate task is possible with this agent/i)
        .check();
      await expect(send).toBeEnabled();
      await send.click();
    });

    await test.step("the sample answers inside the exchange (D-03-S11)", async () => {
      await expect(page.getByText("Agent reported complete")).toBeVisible({ timeout: 60_000 });
      await expect(page.getByText(/Hello, World! I have received your request/)).toBeVisible();
    });

    await test.step("the run is one task at the agent", async () => {
      const runs = await apiGet<AgentRun[]>(page, `/tasks/${task.id}/agent-runs`);
      expect(runs).toHaveLength(1);
      expect(runs[0].reported_state).toBe("completed");
      expect(runs[0].agent_task_id).toBeTruthy();
      expect(connection.status).toBe("untested");
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
      const card = page.getByRole("article", { name: "Hermes" });
      await card.getByRole("button", { name: "Test connection" }).click();
      await expect(card.getByText("Tested ready")).toBeVisible({ timeout: 30_000 });
    });

    const task = await createTaskViaApi(page, "Please ask me which environment to use");

    await test.step("hand off and reach Needs you (D-03-S08)", async () => {
      await openTask(page, task.id);
      await page.getByRole("button", { name: "Hand to agent" }).click();
      const review = page.getByRole("dialog");
      await review
        .getByLabel(/duplicate task is possible with this agent/i)
        .check();
      await review.getByRole("button", { name: "Send to agent" }).click();
      // D-03-S07 then S08: the wire says **Sent**, and the agent's own
      // input-required state is what turns it into a question.
      await expect(page.getByText("Needs you")).toBeVisible({ timeout: 90_000 });
    });

    await test.step("answer the question and settle the run (D-03-S11)", async () => {
      await page.getByRole("textbox", { name: /reply/i }).fill("Use staging.");
      await page.getByRole("button", { name: /send reply/i }).click();
      await expect(page.getByText("Agent reported complete")).toBeVisible({ timeout: 90_000 });
    });

    await test.step("the run kept one correlation ID across the succession (S27)", async () => {
      const runs = await apiGet<AgentRun[]>(page, `/tasks/${task.id}/agent-runs`);
      expect(runs).toHaveLength(1);
      const run = await apiGet<Record<string, unknown>>(page, `/agent-runs/${runs[0].id}`);
      expect(run.correlation_id).toBe(runs[0].id);
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
    const card = page.getByRole("article", { name: "Hermes" });
    await card.getByRole("button", { name: "Test connection" }).click();
    await expect(card.getByText("Tested ready")).toBeVisible({ timeout: 30_000 });
    const connections = await apiGet<AgentConnection[]>(page, "/agent-connections");
    const connectionId = connections[0].id;

    const task = await createTaskViaApi(page, "Replay safety at the agent");

    const { token, runId } = await test.step("reserve one confirmation", async () => {
      const preview = await apiPost<{ token: string; run_id: string }>(
        page,
        `/tasks/${task.id}/agent-runs/preview`,
        { connection_id: connectionId }
      );
      return { token: preview.token, runId: preview.run_id };
    });

    await test.step("confirm it three times with one idempotency key", async () => {
      const key = uniqueKey("relay-replay");
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const response = await page.request.post(`${backendUrl}/api/tasks/${task.id}/agent-runs`, {
          headers: { "Idempotency-Key": key },
          data: {
            connection_id: connectionId,
            manifest_token: token,
            acknowledge_duplicate_risk: true
          }
        });
        expect(response.status()).toBe(201);
      }
    });

    await test.step("BrainBuddy shows one run, and the agent holds one task", async () => {
      const runs = await apiGet<AgentRun[]>(page, `/tasks/${task.id}/agent-runs`);
      expect(runs).toHaveLength(1);
      expect(runs[0].id).toBe(runId);
      expect(runs[0].agent_task_id).toBeTruthy();

      // The claim is about the *agent*, so the agent is what gets asked.
      const listed = await agentRpc(
        request,
        HERMES_URL,
        "ListTasks",
        { contextId: runId, pageSize: 20 },
        HERMES_TOKEN
      );
      const result = listed.result as { tasks?: Array<{ id: string }> };
      expect(result.tasks ?? []).toHaveLength(1);
      expect((result.tasks ?? [])[0].id).toBe(runs[0].agent_task_id);
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
      const card = page.getByRole("article", { name: "Wrong credential" });
      await card.getByRole("button", { name: "Test connection" }).click();
      await expect(card.getByText("Invalid credentials")).toBeVisible({ timeout: 30_000 });
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
      expect([400, 422]).toContain(response.status());
      expect(await response.text()).not.toContain("must-not-leave");
    });

    await test.step("a forged push token changes nothing", async () => {
      const connections = await apiGet<AgentConnection[]>(page, "/agent-connections");
      const forged = await page.request.post(
        `${backendUrl}/api/a2a/push/agentrun_does_not_exist/forged-token`,
        { data: {} }
      );
      expect(forged.status()).toBe(403);
      const after = await apiGet<AgentConnection[]>(page, "/agent-connections");
      expect(after).toHaveLength(connections.length);
    });
  });
});
