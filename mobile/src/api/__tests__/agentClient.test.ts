/**
 * External-agent relay client surface.
 *
 * The backend request models are `extra="forbid"` and every mutation needs an
 * `Idempotency-Key`, so these tests assert the exact wire shape rather than
 * "it called something".
 */

import { createApiClient } from "../client";

type FetchArgs = { url: string; init: RequestInit };

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function makeClient(responses: Response[]) {
  const calls: FetchArgs[] = [];
  const fetchImpl = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    const next = responses.shift();
    if (!next) {
      throw new Error("no response queued");
    }
    return next;
  }) as unknown as typeof fetch;
  const client = createApiClient({
    getBaseUrl: () => "https://example.test/api/",
    fetchImpl,
  });
  return { client, calls };
}

const headersOf = (call: FetchArgs) => call.init.headers as Record<string, string>;
const bodyOf = (call: FetchArgs) => JSON.parse(String(call.init.body)) as unknown;

describe("agent connections", () => {
  it("lists connections with a plain GET", async () => {
    const { client, calls } = makeClient([jsonResponse([])]);
    await client.listAgentConnections();
    expect(calls[0].url).toBe("https://example.test/api/agent-connections");
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.credentials).toBe("include");
  });

  it("creates a connection with an Idempotency-Key and no extra body keys", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "conn1" }, 201)]);
    await client.createAgentConnection(
      {
        name: "Hermes",
        endpoint_url: "https://agent.example.test/hook",
        auth_header_name: "Authorization",
        credential: "super-secret",
        current_password: "correct-horse",
      },
      "key-create",
    );

    expect(calls[0].url).toBe("https://example.test/api/agent-connections");
    expect(calls[0].init.method).toBe("POST");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBe("key-create");
    expect(headersOf(calls[0])["Content-Type"]).toBe("application/json");
    expect(bodyOf(calls[0])).toEqual({
      name: "Hermes",
      endpoint_url: "https://agent.example.test/hook",
      auth_header_name: "Authorization",
      credential: "super-secret",
      current_password: "correct-horse",
    });
  });

  it("reads one connection by id", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "conn1" })]);
    await client.getAgentConnection("conn1");
    expect(calls[0].url).toBe("https://example.test/api/agent-connections/conn1");
    expect(calls[0].init.method).toBe("GET");
  });

  it("tests a connection with a POST that carries no body", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "conn1", status: "ready" })]);
    await client.testAgentConnection("conn1");
    expect(calls[0].url).toBe("https://example.test/api/agent-connections/conn1/test");
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].init.body).toBeUndefined();
    expect(headersOf(calls[0])["Content-Type"]).toBeUndefined();
  });

  it("rotates a credential with expected_revision and the account password", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "conn1" })]);
    await client.rotateAgentCredential(
      "conn1",
      { credential: "next-secret", current_password: "correct-horse", expected_revision: 4 },
      "key-rotate",
    );
    expect(calls[0].url).toBe("https://example.test/api/agent-connections/conn1/credential");
    expect(calls[0].init.method).toBe("POST");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBe("key-rotate");
    expect(bodyOf(calls[0])).toEqual({
      credential: "next-secret",
      current_password: "correct-horse",
      expected_revision: 4,
    });
  });

  it("replaces the signing secret on its own route, carrying no credential", async () => {
    const { client, calls } = makeClient([
      jsonResponse({ id: "conn1", revision: 5, inbound_signing_secret: "sk-inbound-new" }),
    ]);
    const replaced = await client.rotateAgentSigningSecret(
      "conn1",
      { current_password: "correct-horse", expected_revision: 4 },
      "key-signing",
    );

    expect(calls[0].url).toBe("https://example.test/api/agent-connections/conn1/signing-secret");
    expect(calls[0].init.method).toBe("POST");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBe("key-signing");
    // The inbound secret and the outbound credential are different secrets on
    // different routes; the body must never blur them.
    expect(bodyOf(calls[0])).toEqual({
      current_password: "correct-horse",
      expected_revision: 4,
    });
    expect(replaced.inbound_signing_secret).toBe("sk-inbound-new");
  });

  it("disconnects with the account password and expected_revision", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "conn1" })]);
    await client.disconnectAgentConnection(
      "conn1",
      { current_password: "correct-horse", expected_revision: 5 },
      "key-disconnect",
    );
    expect(calls[0].url).toBe("https://example.test/api/agent-connections/conn1/disconnect");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBe("key-disconnect");
    expect(bodyOf(calls[0])).toEqual({ current_password: "correct-horse", expected_revision: 5 });
  });
});

describe("agent hand-off", () => {
  it("previews a hand-off without an Idempotency-Key (nothing is created yet)", async () => {
    const { client, calls } = makeClient([jsonResponse({ token: "a".repeat(64) })]);
    await client.previewAgentHandoff("task1", {
      connection_id: "conn1",
      include_details: false,
      context_items: [{ label: "Subtasks", body: "- book venue" }],
    });
    expect(calls[0].url).toBe("https://example.test/api/tasks/task1/agent-runs/preview");
    expect(calls[0].init.method).toBe("POST");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBeUndefined();
    expect(bodyOf(calls[0])).toEqual({
      connection_id: "conn1",
      include_details: false,
      context_items: [{ label: "Subtasks", body: "- book venue" }],
    });
  });

  it("confirms a hand-off with the reviewed manifest token and an Idempotency-Key", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "run1" }, 201)]);
    await client.confirmAgentHandoff(
      "task1",
      {
        connection_id: "conn1",
        include_details: true,
        context_items: [],
        manifest_token: "b".repeat(64),
        current_password: "correct-horse",
      },
      "key-confirm",
    );
    expect(calls[0].url).toBe("https://example.test/api/tasks/task1/agent-runs");
    expect(calls[0].init.method).toBe("POST");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBe("key-confirm");
    expect(bodyOf(calls[0])).toEqual({
      connection_id: "conn1",
      include_details: true,
      context_items: [],
      manifest_token: "b".repeat(64),
      current_password: "correct-horse",
    });
  });
});

describe("agent runs", () => {
  it("lists the runs attached to one task", async () => {
    const { client, calls } = makeClient([jsonResponse([])]);
    await client.listAgentRuns("task1");
    expect(calls[0].url).toBe("https://example.test/api/tasks/task1/agent-runs");
    expect(calls[0].init.method).toBe("GET");
  });

  it("reads one run by id", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "run1" })]);
    await client.getAgentRun("run1");
    expect(calls[0].url).toBe("https://example.test/api/agent-runs/run1");
    expect(calls[0].init.method).toBe("GET");
  });

  it("replies with only the message body", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "run1" })]);
    await client.replyToAgentRun("run1", { message: "Use the second quote." }, "key-reply");
    expect(calls[0].url).toBe("https://example.test/api/agent-runs/run1/reply");
    expect(calls[0].init.method).toBe("POST");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBe("key-reply");
    expect(bodyOf(calls[0])).toEqual({ message: "Use the second quote." });
  });

  it("requests cancellation with an Idempotency-Key and no body", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "run1" })]);
    await client.cancelAgentRun("run1", "key-cancel");
    expect(calls[0].url).toBe("https://example.test/api/agent-runs/run1/cancel");
    expect(calls[0].init.method).toBe("POST");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBe("key-cancel");
    expect(calls[0].init.body).toBeUndefined();
    expect(headersOf(calls[0])["Content-Type"]).toBeUndefined();
  });
});
