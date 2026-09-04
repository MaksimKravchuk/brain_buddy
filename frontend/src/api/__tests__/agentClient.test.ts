import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../client";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

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

  it("014-FR-001 creates a connection by address and scheme, never a header name", async () => {
    fetchMock.mockResolvedValue(response({ id: "conn-1" }, 201));

    await apiClient.createAgentConnection(
      {
        name: "Hermes",
        agent_address: "https://agent.example.com",
        auth_scheme: "api_key",
        credential: "token-abc",
        current_password: "hunter2hunter2"
      },
      "create-connection-key"
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/agent-connections`);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("create-connection-key");
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body).toEqual({
      name: "Hermes",
      agent_address: "https://agent.example.com",
      auth_scheme: "api_key",
      credential: "token-abc",
      current_password: "hunter2hunter2"
    });
    // The header the credential travels in comes from the agent's card, so the
    // client has nothing to send and no field to send it in.
    expect(body).not.toHaveProperty("auth_header_name");
    expect(body).not.toHaveProperty("endpoint_url");
  });

  it("014-FR-001 updates a connection by address and scheme with the caller's key", async () => {
    fetchMock.mockResolvedValue(response({ id: "conn-1", name: "Hermes prod", revision: 3 }));

    const payload = {
      name: "Hermes prod",
      agent_address: "https://second.example.com",
      auth_scheme: "bearer" as const,
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

  it("014-FR-005 previews a hand-off without an idempotency key and confirms it with one", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(response({ token: "manifest-token", supporting_items: [] }))
    );

    const preview = await apiClient.previewAgentHandoff("task-1", {
      connection_id: "conn-1",
      include_details: false,
      supporting_items: [{ label: "Spec", body: "Read the spec" }]
    });
    await apiClient.confirmAgentHandoff(
      "task-1",
      {
        connection_id: "conn-1",
        include_details: false,
        supporting_items: [{ label: "Spec", body: "Read the spec" }],
        manifest_token: "manifest-token",
        current_password: null,
        acknowledge_duplicate_risk: true
      },
      "handoff-key"
    );

    expect(preview.supporting_items).toEqual([]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `${API_BASE_URL}/tasks/task-1/agent-runs/preview`,
      `${API_BASE_URL}/tasks/task-1/agent-runs`
    ]);
    const inits = fetchMock.mock.calls.map(([, init]) => init as RequestInit);
    expect(new Headers(inits[0].headers).get("Idempotency-Key")).toBeNull();
    expect(new Headers(inits[1].headers).get("Idempotency-Key")).toBe("handoff-key");
    // The acknowledgement travels in the body, so it is part of the canonical
    // request the Idempotency-Key is spent on (AC-026).
    expect(JSON.parse(String(inits[1].body))).toMatchObject({
      manifest_token: "manifest-token",
      supporting_items: [{ label: "Spec", body: "Read the spec" }],
      acknowledge_duplicate_risk: true
    });
  });

  it("014-FR-006 checks delivery under an idempotency key and carries the password when asked", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "run-1" })));

    await apiClient.checkAgentRunDelivery("run-1", { current_password: null }, "check-key");
    await apiClient.checkAgentRunDelivery(
      "run-1",
      { current_password: "hunter2hunter2" },
      "check-key"
    );

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `${API_BASE_URL}/agent-runs/run-1/check-delivery`,
      `${API_BASE_URL}/agent-runs/run-1/check-delivery`
    ]);
    const inits = fetchMock.mock.calls.map(([, init]) => init as RequestInit);
    // Every identifier the check needs is already on the run, so the key is the
    // run's own: a second check is the same check, never a second send.
    expect(inits.map((init) => new Headers(init.headers).get("Idempotency-Key"))).toEqual([
      "check-key",
      "check-key"
    ]);
    expect(JSON.parse(String(inits[0].body))).toEqual({ current_password: null });
    expect(JSON.parse(String(inits[1].body))).toEqual({ current_password: "hunter2hunter2" });
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

  it("preserves an array returned by the agent run list contract", async () => {
    const runs = [{ id: "run-1" }];
    fetchMock.mockResolvedValue(response(runs));

    await expect(apiClient.listAgentRuns("task-1")).resolves.toEqual(runs);
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
