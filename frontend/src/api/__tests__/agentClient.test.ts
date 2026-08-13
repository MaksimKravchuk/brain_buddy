import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentManifestResponse } from "../agentTypes";
import { apiClient } from "../client";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

const reportingContract = {
  callback_url: "https://brain.example.test/api/agent-runs/run-1/reports",
  connection_id: "conn-1",
  connection_header: "X-BrainBuddy-Connection",
  timestamp_header: "X-BrainBuddy-Timestamp",
  signature_header: "X-BrainBuddy-Signature",
  timestamp_format: "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero",
  signature_algorithm: "hmac-sha256",
  signing_bytes: "timestamp_bytes + b'.' + raw_body",
  signature_format: "v1=<lowercase hex>",
  body_envelope_version: "1"
} satisfies AgentManifestResponse["reporting"];

function response(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Request failed" : "OK",
    headers: { "Content-Type": "application/json", ...headers }
  });
}

describe("apiClient external agent relay contract", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads connections without an idempotency key because reads change nothing", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response([])));

    await apiClient.listAgentConnections();
    await apiClient.getAgentConnection("conn-1");

    expect(fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method])).toEqual([
      [`${API_BASE_URL}/agent-connections`, "GET"],
      [`${API_BASE_URL}/agent-connections/conn-1`, "GET"]
    ]);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Idempotency-Key")).toBeNull();
  });

  it("creates a connection with the caller's idempotency key and the re-authentication password", async () => {
    fetchMock.mockResolvedValue(response({ id: "conn-1", inbound_signing_secret: "secret" }, 201));

    await apiClient.createAgentConnection(
      {
        name: "Hermes",
        endpoint_url: "https://agent.example.com/hooks",
        auth_header_name: "Authorization",
        credential: "token-abc",
        current_password: "hunter2hunter2"
      },
      "create-connection-key"
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/agent-connections`);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("create-connection-key");
    expect(JSON.parse(String(init.body))).toEqual({
      name: "Hermes",
      endpoint_url: "https://agent.example.com/hooks",
      auth_header_name: "Authorization",
      credential: "token-abc",
      current_password: "hunter2hunter2"
    });
  });

  it("updates a connection with the backend PUT contract and caller idempotency key", async () => {
    fetchMock.mockResolvedValue(response({ id: "conn-1", name: "Hermes prod", revision: 3 }));

    const payload = {
      name: "Hermes prod",
      endpoint_url: "https://agent.example.com/v2/hooks",
      expected_revision: 2,
      current_password: "hunter2hunter2"
    };
    await apiClient.updateAgentConnection("conn-1", payload, "update-connection-key");

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/agent-connections/conn-1`);
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("update-connection-key");
    expect(JSON.parse(String(init.body))).toEqual(payload);
  });

  it("posts a connection test without a body so a retry is always safe", async () => {
    fetchMock.mockResolvedValue(response({ id: "conn-1", status: "ready" }));

    await apiClient.testAgentConnection("conn-1");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/agent-connections/conn-1/test`);
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });

  it("rotates and disconnects a connection against the revision the user saw", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "conn-1", revision: 3 })));

    await apiClient.rotateAgentCredential(
      "conn-1",
      { credential: "token-def", current_password: "hunter2hunter2", expected_revision: 2 },
      "rotate-key"
    );
    await apiClient.disconnectAgentConnection(
      "conn-1",
      { current_password: "hunter2hunter2", expected_revision: 3 },
      "disconnect-key"
    );

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `${API_BASE_URL}/agent-connections/conn-1/credential`,
      `${API_BASE_URL}/agent-connections/conn-1/disconnect`
    ]);
    const inits = fetchMock.mock.calls.map(([, init]) => init as RequestInit);
    expect(inits.map((init) => new Headers(init.headers).get("Idempotency-Key"))).toEqual([
      "rotate-key",
      "disconnect-key"
    ]);
    expect(JSON.parse(String(inits[1].body))).toEqual({
      current_password: "hunter2hunter2",
      expected_revision: 3
    });
  });

  it("replaces the signing secret at its own endpoint, never the credential one", async () => {
    fetchMock.mockResolvedValue(
      response({ id: "conn-1", revision: 3, inbound_signing_secret: "sk-inbound-new" })
    );

    const replaced = await apiClient.rotateAgentSigningSecret(
      "conn-1",
      { current_password: "hunter2hunter2", expected_revision: 2 },
      "signing-secret-key"
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/agent-connections/conn-1/signing-secret`);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("signing-secret-key");
    // No credential field: this route replaces what the agent signs *with*, not
    // what BrainBuddy authenticates *to* it with.
    expect(JSON.parse(String(init.body))).toEqual({
      current_password: "hunter2hunter2",
      expected_revision: 2
    });
    expect(replaced.inbound_signing_secret).toBe("sk-inbound-new");
  });

  it("surfaces a superseded signing-secret replay as a conflict rather than a secret", async () => {
    fetchMock.mockResolvedValue(
      response(
        { message: "This agent's signing secret has been replaced since that request." },
        409,
        { "X-Correlation-ID": "corr-signing-9" }
      )
    );

    await expect(
      apiClient.rotateAgentSigningSecret(
        "conn-1",
        { current_password: "hunter2hunter2", expected_revision: 2 },
        "signing-secret-key"
      )
    ).rejects.toMatchObject({ status: 409, correlationId: "corr-signing-9" });
  });

  it("previews a hand-off without an idempotency key and confirms it with one", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(response({ token: "manifest-token", reporting: reportingContract }))
    );

    const preview = await apiClient.previewAgentHandoff("task-1", {
      connection_id: "conn-1",
      include_details: false,
      context_items: [{ label: "Spec", body: "Read the spec" }]
    });
    await apiClient.confirmAgentHandoff(
      "task-1",
      {
        connection_id: "conn-1",
        include_details: false,
        context_items: [{ label: "Spec", body: "Read the spec" }],
        manifest_token: "manifest-token",
        current_password: null
      },
      "handoff-key"
    );

    expect(preview.reporting).toEqual(reportingContract);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `${API_BASE_URL}/tasks/task-1/agent-runs/preview`,
      `${API_BASE_URL}/tasks/task-1/agent-runs`
    ]);
    const inits = fetchMock.mock.calls.map(([, init]) => init as RequestInit);
    expect(new Headers(inits[0].headers).get("Idempotency-Key")).toBeNull();
    expect(new Headers(inits[1].headers).get("Idempotency-Key")).toBe("handoff-key");
    expect(JSON.parse(String(inits[1].body))).toMatchObject({ manifest_token: "manifest-token" });
  });

  it("lists, reads, replies to, and requests cancellation of runs", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "run-1" })));

    await apiClient.listAgentRuns("task-1");
    await apiClient.getAgentRun("run-1");
    await apiClient.replyToAgentRun(
      "run-1",
      { message: "Use the staging key", expected_revision: 7 },
      "reply-key"
    );
    await apiClient.cancelAgentRun("run-1", "cancel-key");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `${API_BASE_URL}/tasks/task-1/agent-runs`,
      `${API_BASE_URL}/agent-runs/run-1`,
      `${API_BASE_URL}/agent-runs/run-1/reply`,
      `${API_BASE_URL}/agent-runs/run-1/cancel`
    ]);
    const inits = fetchMock.mock.calls.map(([, init]) => init as RequestInit);
    expect(inits.map((init) => init.method)).toEqual(["GET", "GET", "POST", "POST"]);
    expect(new Headers(inits[2].headers).get("Idempotency-Key")).toBe("reply-key");
    expect(new Headers(inits[3].headers).get("Idempotency-Key")).toBe("cancel-key");
    expect(JSON.parse(String(inits[2].body))).toEqual({
      message: "Use the staging key",
      expected_revision: 7
    });
    expect(inits[3].body).toBeUndefined();
  });

  it("batches compact run summaries for every requested task without losing task identity", async () => {
    fetchMock.mockResolvedValue(
      response({
        "task-1": { task_id: "task-1", latest_run_id: "run-1" },
        "task-2": { task_id: "task-2", latest_run_id: "run-2" }
      })
    );

    const summaries = await apiClient.listAgentRunSummaries(["task-1", "task-2"]);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `${API_BASE_URL}/agent-run-summaries?task_id=task-1&task_id=task-2`
    );
    expect(summaries).toMatchObject({
      "task-1": { latest_run_id: "run-1" },
      "task-2": { latest_run_id: "run-2" }
    });
  });

  it("preserves the correlation ID when a hand-off confirmation is rejected", async () => {
    fetchMock.mockResolvedValue(
      response(
        { message: "Review it again before confirming.", detail: { reason: "manifest_token_mismatch" } },
        400,
        { "X-Correlation-ID": "corr-agent-1" }
      )
    );

    await expect(
      apiClient.confirmAgentHandoff(
        "task-1",
        { connection_id: "conn-1", manifest_token: "stale-token" },
        "handoff-key"
      )
    ).rejects.toMatchObject({
      status: 400,
      correlationId: "corr-agent-1",
      payload: { detail: { reason: "manifest_token_mismatch" } }
    });
  });
});
