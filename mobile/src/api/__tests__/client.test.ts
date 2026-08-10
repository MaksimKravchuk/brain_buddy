import { ApiError, createApiClient } from "../client";

type FetchArgs = { url: string; init: RequestInit };

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function makeClient(responses: Response[], onUnauthorized?: () => void) {
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
    onUnauthorized,
    fetchImpl,
  });
  return { client, calls };
}

describe("createApiClient", () => {
  it("normalizes the base URL and sends JSON bodies with Idempotency-Key", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "t1" }, 201)]);
    await client.createTask({ title: "Call the notary", state: "inbox" }, "key-1");

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("https://example.test/api/tasks");
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBe("key-1");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(calls[0].init.credentials).toBe("include");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      title: "Call the notary",
      state: "inbox",
    });
  });

  it("builds listTasks query params exactly like the web client", async () => {
    const { client, calls } = makeClient([
      jsonResponse({ items: [], next_cursor: null, has_more: false, counts_by_state: {} }),
    ]);
    await client.listTasks({
      state: "next",
      projectId: "p1",
      tagId: "g1",
      cursor: "c1",
      limit: 50,
      includeCompleted: true,
      includeCancelled: true,
      q: "  venue  ",
      unassignedProject: true,
      priority: ["high", "medium"],
      dueBefore: "2026-08-01",
      dueOn: "2026-08-02",
      dueAfter: "2026-08-03",
      sort: "due",
    });

    const url = new URL(calls[0].url);
    expect(url.pathname).toBe("/api/tasks");
    expect(url.searchParams.get("state")).toBe("next");
    expect(url.searchParams.get("project_id")).toBe("p1");
    expect(url.searchParams.get("tag_id")).toBe("g1");
    expect(url.searchParams.get("cursor")).toBe("c1");
    expect(url.searchParams.get("limit")).toBe("50");
    expect(url.searchParams.get("include_completed")).toBe("true");
    expect(url.searchParams.get("include_cancelled")).toBe("true");
    expect(url.searchParams.get("q")).toBe("venue");
    expect(url.searchParams.get("unassigned_project")).toBe("true");
    expect(url.searchParams.getAll("priority")).toEqual(["high", "medium"]);
    expect(url.searchParams.get("due_before")).toBe("2026-08-01");
    expect(url.searchParams.get("due_on")).toBe("2026-08-02");
    expect(url.searchParams.get("due_after")).toBe("2026-08-03");
    expect(url.searchParams.get("sort")).toBe("due");
  });

  it("omits the manual sort and empty filters", async () => {
    const { client, calls } = makeClient([
      jsonResponse({ items: [], next_cursor: null, has_more: false, counts_by_state: {} }),
    ]);
    await client.listTasks({ sort: "manual", q: "   " });
    expect(calls[0].url).toBe("https://example.test/api/tasks");
  });

  it("sends audio chunks as raw binary with the exact headers", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "op1" })]);
    const bytes = new Uint8Array([1, 2, 3, 4]);
    await client.uploadBrainDumpAudio("op1", 0, bytes, "ff".repeat(32), "audio/wav");

    expect(calls[0].url).toBe("https://example.test/api/brain-dump-operations/op1/audio/0");
    expect(calls[0].init.method).toBe("PUT");
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("audio/wav");
    expect(headers["X-Content-SHA256"]).toBe("ff".repeat(32));
    const body = calls[0].init.body as ArrayBuffer;
    expect(body).toBeInstanceOf(ArrayBuffer);
    expect(Array.from(new Uint8Array(body))).toEqual([1, 2, 3, 4]);
  });

  it("maps error bodies to ApiError with correlation and reference ids", async () => {
    const { client } = makeClient([
      jsonResponse(
        { message: "Task revision is stale.", detail: null, reference_id: "ref-9" },
        409,
        { "X-Correlation-ID": "corr-1" },
      ),
    ]);
    await expect(client.getTask("t1")).rejects.toMatchObject({
      status: 409,
      correlationId: "corr-1",
    });

    const { client: client2 } = makeClient([
      jsonResponse({ message: "Task revision is stale.", reference_id: "ref-9" }, 409),
    ]);
    try {
      await client2.getTask("t1");
      throw new Error("expected rejection");
    } catch (error) {
      const apiError = error as ApiError;
      expect(apiError.serverMessage).toBe("Task revision is stale.");
      expect(apiError.referenceId).toBe("ref-9");
    }
  });

  it("fires onUnauthorized on 401 responses", async () => {
    const onUnauthorized = jest.fn();
    const { client } = makeClient(
      [jsonResponse({ message: "Authentication required." }, 401)],
      onUnauthorized,
    );
    await expect(client.me()).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("brain-dump commands send only expected_revision", async () => {
    const { client, calls } = makeClient([jsonResponse({ id: "op1" })]);
    await client.commandBrainDump("op1", "commit", 12, "key-2");
    expect(calls[0].url).toBe("https://example.test/api/brain-dump-operations/op1/commit");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ expected_revision: 12 });
  });
});
