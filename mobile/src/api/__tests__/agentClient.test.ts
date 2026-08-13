/**
 * External-agent relay client surface.
 *
 * The backend request models are `extra="forbid"`, and keyed mutations require
 * an `Idempotency-Key`. These tests assert the exact wire shape—including the
 * intentionally unkeyed test and preview routes—rather than "it called something".
 */

import type { AgentManifestResponse } from "../types";
import { createApiClient } from "../client";

const reportingContract = {
  callback_url: "https://brain.example.test/api/agent-runs/run1/reports",
  connection_id: "conn1",
  connection_header: "X-BrainBuddy-Connection",
  timestamp_header: "X-BrainBuddy-Timestamp",
  signature_header: "X-BrainBuddy-Signature",
  timestamp_format: "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero",
  signature_algorithm: "hmac-sha256",
  signing_bytes: "timestamp_bytes + b'.' + raw_body",
  signature_format: "v1=<lowercase hex>",
  body_envelope_version: "1",
} satisfies AgentManifestResponse["reporting"];

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

function makeFailingClient(error: Error = new TypeError("Network request failed")) {
  const fetchImpl = jest.fn(async () => {
    throw error;
  }) as unknown as typeof fetch;
  return {
    client: createApiClient({
      getBaseUrl: () => "https://example.test/api/",
      fetchImpl,
    }),
    fetchImpl,
  };
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

  it("updates connection metadata with PUT, revision, and idempotency key", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "conn1", revision: 5 })]);

    await client.updateAgentConnection(
      "conn1",
      {
        name: "Renamed agent",
        endpoint_url: "https://next.example.test/hook",
        current_password: "correct-horse",
        expected_revision: 4,
      },
      "key-update",
    );

    expect(calls[0].url).toBe("https://example.test/api/agent-connections/conn1");
    expect(calls[0].init.method).toBe("PUT");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBe("key-update");
    expect(bodyOf(calls[0])).toEqual({
      name: "Renamed agent",
      endpoint_url: "https://next.example.test/hook",
      current_password: "correct-horse",
      expected_revision: 4,
    });
  });

  // `test_agent_connection` (backend/app/api/agents.py) declares no
  // `Idempotency-Key` header and passes none to the service, so a key sent here
  // would be discarded by FastAPI. Sending one anyway would advertise a dedupe
  // the server does not perform.
  it("tests a connection with a POST that carries no body and no Idempotency-Key", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "conn1", status: "ready" })]);
    await client.testAgentConnection("conn1");
    expect(calls[0].url).toBe("https://example.test/api/agent-connections/conn1/test");
    expect(calls[0].init.method).toBe("POST");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBeUndefined();
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
  // specs/006 plan: "preview creates a versioned immutable manifest/token.
  // Confirmation requires the same manifest plus an idempotency key." The key
  // belongs to the confirm step; `preview_agent_handoff` declares no
  // `Idempotency-Key` header, so re-previewing is meant to mint a fresh token.
  it("previews a hand-off without an Idempotency-Key (nothing is dispatched yet)", async () => {
    const { client, calls } = makeClient([
      jsonResponse({ token: "a".repeat(64), reporting: reportingContract }),
    ]);
    const preview = await client.previewAgentHandoff("task1", {
      connection_id: "conn1",
      include_details: false,
      context_items: [{ label: "Subtasks", body: "- book venue" }],
    });
    expect(preview.reporting).toEqual(reportingContract);
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

  it("replies with the message and displayed revision", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "run1" })]);
    await client.replyToAgentRun(
      "run1",
      { message: "Use the second quote.", expected_revision: 7 },
      "key-reply",
    );
    expect(calls[0].url).toBe("https://example.test/api/agent-runs/run1/reply");
    expect(calls[0].init.method).toBe("POST");
    expect(headersOf(calls[0])["Idempotency-Key"]).toBe("key-reply");
    expect(bodyOf(calls[0])).toEqual({
      message: "Use the second quote.",
      expected_revision: 7,
    });
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

describe("relay mutation intent boundary", () => {
  const createPayload = {
    name: "Hermes",
    endpoint_url: "https://agent.example.test/hook",
    auth_header_name: "X-Agent-Key",
    credential: "secret",
    current_password: "password",
  };
  const dispatchPayload = {
    connection_id: "conn1",
    include_details: true,
    context_items: [],
    manifest_token: "b".repeat(64),
    current_password: "password",
  };

  const relayMutations = [
    ["create", (client: ReturnType<typeof createApiClient>, key: string) =>
      client.createAgentConnection(createPayload, key)],
    ["rotate credential", (client: ReturnType<typeof createApiClient>, key: string) =>
      client.rotateAgentCredential(
        "conn1",
        { credential: "next", current_password: "password", expected_revision: 1 },
        key,
      )],
    ["rotate signing secret", (client: ReturnType<typeof createApiClient>, key: string) =>
      client.rotateAgentSigningSecret(
        "conn1",
        { current_password: "password", expected_revision: 1 },
        key,
      )],
    ["disconnect", (client: ReturnType<typeof createApiClient>, key: string) =>
      client.disconnectAgentConnection(
        "conn1",
        { current_password: "password", expected_revision: 1 },
        key,
      )],
    ["dispatch", (client: ReturnType<typeof createApiClient>, key: string) =>
      client.confirmAgentHandoff("task1", dispatchPayload, key)],
    ["reply", (client: ReturnType<typeof createApiClient>, key: string) =>
      client.replyToAgentRun(
        "run1",
        { message: "Answer", expected_revision: 1 },
        key,
      )],
    ["cancel", (client: ReturnType<typeof createApiClient>, key: string) =>
      client.cancelAgentRun("run1", key)],
  ] as const;

  describe.each([undefined, "", "   "])("with invalid key %p", (key) => {
    it.each(relayMutations)("refuses %s before fetch", async (_name, invoke) => {
      const { client, calls } = makeClient([]);
      await expect(invoke(client, key as string)).rejects.toThrow("caller-owned Idempotency-Key");
      expect(calls).toHaveLength(0);
    });
  });

  it("rejects a missing key before reading transport or API-origin state", async () => {
    const getBaseUrl = jest.fn(() => "https://example.test/api");
    const getSessionEpoch = jest.fn(() => 1);
    const fetchImpl = jest.fn() as unknown as typeof fetch;
    const client = createApiClient({ getBaseUrl, getSessionEpoch, fetchImpl });

    await expect(client.cancelAgentRun("run1", " ")).rejects.toThrow(
      "caller-owned Idempotency-Key",
    );
    expect(getBaseUrl).not.toHaveBeenCalled();
    expect(getSessionEpoch).not.toHaveBeenCalled();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("preserves a create key with its exact body after an ambiguous failure", async () => {
    const { client, fetchImpl } = makeFailingClient();
    await expect(client.createAgentConnection(createPayload, "create-key")).rejects.toThrow(
      "Network request failed",
    );

    await expect(
      client.createAgentConnection({ ...createPayload, credential: "changed" }, "create-key"),
    ).rejects.toThrow("cannot be reused with a different request");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("preserves a dispatch key with its exact body after an ambiguous failure", async () => {
    const { client, fetchImpl } = makeFailingClient();
    await expect(client.confirmAgentHandoff("task1", dispatchPayload, "dispatch-key")).rejects.toThrow();

    await expect(
      client.confirmAgentHandoff(
        "task1",
        { ...dispatchPayload, current_password: "changed" },
        "dispatch-key",
      ),
    ).rejects.toThrow("cannot be reused with a different request");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("preserves a reply key with the displayed revision and message after ambiguity", async () => {
    const { client, fetchImpl } = makeFailingClient();
    await expect(
      client.replyToAgentRun("run1", { message: "Answer", expected_revision: 7 }, "reply-key"),
    ).rejects.toThrow();

    await expect(
      client.replyToAgentRun("run1", { message: "Answer", expected_revision: 8 }, "reply-key"),
    ).rejects.toThrow("cannot be reused with a different request");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("preserves a cancel key with its exact run target after ambiguity", async () => {
    const { client, fetchImpl } = makeFailingClient();
    await expect(client.cancelAgentRun("run1", "cancel-key")).rejects.toThrow();

    await expect(client.cancelAgentRun("run2", "cancel-key")).rejects.toThrow(
      "cannot be reused with a different request",
    );
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("binds an ambiguous key to the captured session and API origin", async () => {
    let epoch = 3;
    let baseUrl = "https://account-a.example.test/api";
    const fetchImpl = jest.fn(async () => {
      throw new TypeError("Network request failed");
    }) as unknown as typeof fetch;
    const client = createApiClient({
      getBaseUrl: () => baseUrl,
      getSessionEpoch: () => epoch,
      fetchImpl,
    });

    await expect(client.cancelAgentRun("run1", "session-key")).rejects.toThrow();
    epoch = 4;
    await expect(client.cancelAgentRun("run1", "session-key")).rejects.toThrow(
      "cannot be reused with a different request",
    );
    epoch = 3;
    baseUrl = "https://account-b.example.test/api";
    await expect(client.cancelAgentRun("run1", "session-key")).rejects.toThrow(
      "cannot be reused with a different request",
    );
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("preserves the frozen body after a 5xx response", async () => {
    const { client, calls } = makeClient([
      jsonResponse({ message: "Unavailable" }, 503),
      jsonResponse({ id: "unused" }, 201),
    ]);
    await expect(client.createAgentConnection(createPayload, "server-key")).rejects.toMatchObject({
      status: 503,
    });
    await expect(
      client.createAgentConnection({ ...createPayload, name: "Changed" }, "server-key"),
    ).rejects.toThrow("cannot be reused with a different request");
    expect(calls).toHaveLength(1);
  });

  it("retires a key after a definitive 4xx settlement", async () => {
    const { client, calls } = makeClient([
      jsonResponse({ message: "Bad request" }, 400),
      jsonResponse({ id: "conn1" }, 201),
    ]);
    await expect(client.createAgentConnection(createPayload, "settled-key")).rejects.toMatchObject({
      status: 400,
    });
    await client.createAgentConnection(
      { ...createPayload, credential: "corrected" },
      "settled-key",
    );
    expect(calls).toHaveLength(2);
  });

  it("retires a key after successful settlement", async () => {
    const { client, calls } = makeClient([
      jsonResponse({ id: "conn1" }, 201),
      jsonResponse({ id: "conn2" }, 201),
    ]);
    await client.createAgentConnection(createPayload, "success-key");
    await client.createAgentConnection(
      { ...createPayload, endpoint_url: "https://other.example.test/hook" },
      "success-key",
    );
    expect(calls).toHaveLength(2);
  });

  // 408 and 429 answer with a 4xx status but say nothing about whether the
  // command ran: a request timeout can fire after the server read and executed
  // the body, and a throttle can be applied by an edge that has already
  // forwarded it. Retiring the key on those would let the user's retry land as
  // a second connection, dispatch, reply or cancel, so they hold the key on
  // exactly the terms a dropped connection or a 5xx does.
  describe.each([408, 429])("after an ambiguous %i", (status) => {
    it("keeps the key bound to the exact frozen request", async () => {
      const { client, calls } = makeClient([
        jsonResponse({ message: "Ambiguous" }, status),
        jsonResponse({ id: "unused" }, 201),
      ]);
      await expect(
        client.createAgentConnection(createPayload, `ambiguous-${status}`),
      ).rejects.toMatchObject({ status });

      await expect(
        client.createAgentConnection({ ...createPayload, name: "Changed" }, `ambiguous-${status}`),
      ).rejects.toThrow("cannot be reused with a different request");
      expect(calls).toHaveLength(1);
    });

    it("rejects a changed dispatch body under the same key", async () => {
      const { client, calls } = makeClient([jsonResponse({ message: "Ambiguous" }, status)]);
      await expect(
        client.confirmAgentHandoff("task1", dispatchPayload, `dispatch-${status}`),
      ).rejects.toMatchObject({ status });

      await expect(
        client.confirmAgentHandoff(
          "task1",
          { ...dispatchPayload, manifest_token: "c".repeat(64) },
          `dispatch-${status}`,
        ),
      ).rejects.toThrow("cannot be reused with a different request");
      expect(calls).toHaveLength(1);
    });

    it("rejects a changed reply body under the same key", async () => {
      const { client, calls } = makeClient([jsonResponse({ message: "Ambiguous" }, status)]);
      await expect(
        client.replyToAgentRun("run1", { message: "Answer", expected_revision: 7 }, `reply-${status}`),
      ).rejects.toMatchObject({ status });

      await expect(
        client.replyToAgentRun(
          "run1",
          { message: "Different answer", expected_revision: 7 },
          `reply-${status}`,
        ),
      ).rejects.toThrow("cannot be reused with a different request");
      expect(calls).toHaveLength(1);
    });

    it("lets the identical intent retry under the same key", async () => {
      const { client, calls } = makeClient([
        jsonResponse({ message: "Ambiguous" }, status),
        jsonResponse({ id: "run1" }),
      ]);
      await expect(client.cancelAgentRun("run1", `retry-${status}`)).rejects.toMatchObject({
        status,
      });
      await client.cancelAgentRun("run1", `retry-${status}`);

      expect(calls).toHaveLength(2);
      expect(headersOf(calls[1])["Idempotency-Key"]).toBe(`retry-${status}`);
    });
  });

  it.each([400, 401, 403, 404, 409, 422])(
    "retires the key after a definitive %i",
    async (status) => {
      const { client, calls } = makeClient([
        jsonResponse({ message: "Definitive" }, status),
        jsonResponse({ id: "run1" }),
      ]);
      await expect(client.cancelAgentRun("run1", `definitive-${status}`)).rejects.toMatchObject({
        status,
      });
      // A different run under the retired key is a new intent, not a reuse.
      await client.cancelAgentRun("run2", `definitive-${status}`);
      expect(calls).toHaveLength(2);
    },
  );
});

describe("unkeyed relay POST contracts", () => {
  const previewPayload = {
    connection_id: "conn1",
    include_details: false,
    context_items: [],
  };

  // The standing at-most-once connector requirement (FR-006) covers start,
  // reply and cancel — the calls that reach the external agent. Test and
  // preview stay inside BrainBuddy, and their routes
  // (`test_agent_connection`, `preview_agent_handoff`) take no
  // `Idempotency-Key`. Routing them through `relayMutation` would attach a key
  // FastAPI discards: the client would refuse a retry it believes is a
  // duplicate while the server happily runs every call it receives. That is a
  // false guarantee, so these two deliberately stay plain requests.
  it("never attaches an Idempotency-Key to a test or a preview", async () => {
    const { client, calls } = makeClient([
      jsonResponse({ id: "conn1", status: "ready" }),
      jsonResponse({ token: "b".repeat(64), reporting: reportingContract }),
    ]);

    await client.testAgentConnection("conn1");
    await client.previewAgentHandoff("task1", previewPayload);

    expect(calls).toHaveLength(2);
    for (const call of calls) {
      expect(call.init.method).toBe("POST");
      expect(headersOf(call)["Idempotency-Key"]).toBeUndefined();
    }
  });

  // A relay-keyed call freezes its request, so a second call under the same key
  // with different arguments throws "cannot be reused with a different
  // request". These routes must never do that: the client cannot dedupe what
  // the server does not, so it must not pretend to.
  it("re-tests and re-previews freely after an ambiguous failure", async () => {
    const { client, calls } = makeClient([
      jsonResponse({ message: "Ambiguous" }, 408),
      jsonResponse({ id: "conn2", status: "ready" }),
      jsonResponse({ message: "Ambiguous" }, 429),
      jsonResponse({ token: "c".repeat(64), reporting: reportingContract }),
    ]);

    await expect(client.testAgentConnection("conn1")).rejects.toMatchObject({ status: 408 });
    // A different target, which a frozen relay intent would have rejected.
    await client.testAgentConnection("conn2");

    await expect(client.previewAgentHandoff("task1", previewPayload)).rejects.toMatchObject({
      status: 429,
    });
    await client.previewAgentHandoff("task1", { ...previewPayload, include_details: true });

    expect(calls).toHaveLength(4);
  });

  // Each preview is an independent reservation: the server mints a new manifest
  // token per call, and the client holds no key that could collapse two
  // previews into one.
  it("sends every preview to the server rather than replaying a held one", async () => {
    const { client, calls } = makeClient([
      jsonResponse({ token: "d".repeat(64), reporting: reportingContract }),
      jsonResponse({ token: "e".repeat(64), reporting: reportingContract }),
    ]);

    const first = await client.previewAgentHandoff("task1", previewPayload);
    const second = await client.previewAgentHandoff("task1", previewPayload);

    expect(calls).toHaveLength(2);
    expect(first.token).not.toBe(second.token);
  });
});
