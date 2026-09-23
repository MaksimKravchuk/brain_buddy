import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  crtApi,
  type CrtTreeExportResponse,
  type CrtTreeListItem,
  type CrtTreeResponse,
  type CrtTreeImportPayload,
  type CrtTreeUpdatePayload
} from "../crt";
import { setUnauthorizedHandler } from "../client";

const CORRELATION_ID = "123e4567-e89b-42d3-a456-426614174000";
const GENERATED_IDEMPOTENCY_KEY = "123e4567-e89b-42d3-a456-426614174001";

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Request failed" : "OK",
    headers: { "Content-Type": "application/json", ...headers }
  });
}

describe("019-FR-001 CRT exposure client", () => {
  const fetchMock = vi.fn<typeof fetch>();
  let randomUuid: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    randomUuid = vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(CORRELATION_ID);
    setUnauthorizedHandler(null);
  });

  afterEach(() => {
    setUnauthorizedHandler(null);
    randomUuid.mockRestore();
    vi.unstubAllGlobals();
  });

  it("019-FR-001 probes exposure without requesting tree content and sends the CRT request contract", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204, headers: { "X-Correlation-ID": CORRELATION_ID } }));

    await expect(crtApi.probeCrtExposure()).resolves.toBeUndefined();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/crt/exposure");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(init.body).toBeUndefined();
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("Content-Type")).toBeNull();
    expect(headers.get("X-Correlation-ID")).toBe(CORRELATION_ID);
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("019-FR-003 lists owner-scoped trees using the canonical list-item contract", async () => {
    const trees: CrtTreeListItem[] = [
      {
        id: "tree-1",
        name: "Current reality",
        updated_at: "2026-09-20T10:00:00Z",
        owner_id: "owner-1"
      }
    ];
    fetchMock.mockResolvedValue(jsonResponse(trees));

    const result = await crtApi.listCrtTrees();

    expect(result).toEqual(trees);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/crt/trees");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(init.body).toBeUndefined();
  });

  it("019-FR-003 gets an owner-scoped tree with the canonical graph envelope", async () => {
    const tree = {
      id: "tree-1",
      name: "Current reality",
      revision: 7,
      schema_version: 1,
      metadata: {
        version: 1,
        created_at: "2026-09-20T09:00:00Z",
        updated_at: "2026-09-20T10:00:00Z",
        layout: { zoom: 1 },
        owner_id: "owner-1"
      },
      nodes: [],
      relations: [],
      owner_id: "owner-1"
    };
    fetchMock.mockResolvedValue(jsonResponse(tree));

    const result = await crtApi.getCrtTree("tree-1");

    expect(result).toEqual(tree);
    expect(result.revision).toBe(7);
    expect(result.schema_version).toBe(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/crt/trees/tree-1");
  });

  it("019-FR-020 retains the server correlation ID in ApiError", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ message: "Flag unavailable" }, 503, { "X-Correlation-ID": "server-correlation" })
    );

    await expect(crtApi.listCrtTrees()).rejects.toMatchObject({
      name: "ApiError",
      status: 503,
      correlationId: "server-correlation",
      payload: { message: "Flag unavailable" }
    });
  });

  it("routes a CRT 401 through the shared unauthorized session handler", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    fetchMock.mockResolvedValue(jsonResponse({ detail: "expired" }, 401, { "X-Correlation-ID": "server-correlation" }));

    await expect(crtApi.listCrtTrees()).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      correlationId: "server-correlation"
    });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("019-FR-020 retains the generated correlation ID when no response arrives", async () => {
    fetchMock.mockRejectedValue(new Error("Network down"));

    await expect(crtApi.getCrtTree("tree-1")).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      correlationId: CORRELATION_ID
    });
  });

  it("019-FR-021 composes the caller signal with the bounded 15-second read timeout", async () => {
    vi.useFakeTimers();
    try {
      fetchMock.mockImplementation((_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
        })
      );

      const caller = new AbortController();
      const pending = crtApi.getCrtTree("tree-1", caller.signal);
      const rejection = expect(pending).rejects.toMatchObject({
        name: "ApiError",
        status: 0,
        correlationId: CORRELATION_ID
      });
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(init.signal).not.toBe(caller.signal);

      await vi.advanceTimersByTimeAsync(15_000);
      await rejection;
    } finally {
      vi.useRealTimers();
    }
  });

  it("019-FR-004 creates a tree with the exact JSON body and mutation request contract", async () => {
    const created: CrtTreeResponse = {
      id: "tree-1",
      name: "New tree",
      revision: 1,
      schema_version: 1,
      metadata: {
        version: 1,
        created_at: "2026-09-20T09:00:00Z",
        updated_at: "2026-09-20T09:00:00Z",
        layout: null,
        owner_id: "owner-1"
      },
      nodes: [],
      relations: [],
      owner_id: "owner-1"
    };
    const payload = { name: "New tree" };
    fetchMock.mockResolvedValue(jsonResponse(created, 201, { "X-Correlation-ID": CORRELATION_ID }));

    await expect(crtApi.createCrtTree(payload, { idempotencyKey: "create-key" })).resolves.toEqual(created);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/crt/trees");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.body).toBe(JSON.stringify(payload));
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Idempotency-Key")).toBe("create-key");
    expect(headers.get("X-Correlation-ID")).toBe(CORRELATION_ID);
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("019-FR-004 updates a tree with the exact expected revision and schema version payload", async () => {
    const payload: CrtTreeUpdatePayload = {
      expected_revision: 7,
      schema_version: 1,
      name: "Current reality",
      metadata: {
        version: 1,
        created_at: "2026-09-19T10:00:00Z",
        updated_at: "2026-09-19T10:05:00Z",
        layout: { zoom: 1, center: { x: 0, y: 0 } },
        owner_id: null
      },
      nodes: [],
      relations: [],
      owner_id: null
    };
    const updated = { id: "tree-1", ...payload, revision: 8 };
    fetchMock.mockResolvedValue(jsonResponse(updated, 200, { "X-Correlation-ID": CORRELATION_ID }));

    await expect(crtApi.updateCrtTree("tree-1", payload, { idempotencyKey: "update-key" })).resolves.toEqual(updated);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/crt/trees/tree-1");
    expect(init.method).toBe("PUT");
    expect(init.credentials).toBe("include");
    expect(init.body).toBe(JSON.stringify(payload));
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Idempotency-Key")).toBe("update-key");
    expect(headers.get("X-Correlation-ID")).toBe(CORRELATION_ID);
  });

  it("019-FR-004 generates an idempotency key when the caller omits one", async () => {
    randomUuid.mockReturnValueOnce(CORRELATION_ID).mockReturnValueOnce(GENERATED_IDEMPOTENCY_KEY);
    fetchMock.mockResolvedValue(jsonResponse({ id: "tree-1" }, 201));

    await crtApi.createCrtTree({ name: "Generated key" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe(GENERATED_IDEMPOTENCY_KEY);
  });

  it("019-FR-020 retains mutation correlation on network failure", async () => {
    fetchMock.mockRejectedValue(new Error("Network down"));

    await expect(crtApi.createCrtTree({ name: "Network failure" }, { idempotencyKey: "network-key" })).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      correlationId: CORRELATION_ID,
      message: "Network down"
    });
  });

  it("019-FR-021 composes mutation timeout with the caller signal", async () => {
    vi.useFakeTimers();
    try {
      fetchMock.mockImplementation((_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
        })
      );

      const caller = new AbortController();
      const pending = crtApi.updateCrtTree(
        "tree-1",
        {
          expected_revision: 1,
          schema_version: 1,
          name: "Timeout",
          metadata: {
            version: 1,
            created_at: "2026-09-20T09:00:00Z",
            updated_at: "2026-09-20T09:00:00Z",
            layout: null,
            owner_id: null
          },
          nodes: [],
          relations: [],
          owner_id: null
        },
        { idempotencyKey: "timeout-key", signal: caller.signal }
      );
      const rejection = expect(pending).rejects.toMatchObject({
        name: "ApiError",
        status: 0,
        correlationId: CORRELATION_ID,
        message: "CRT request timed out"
      });
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(init.signal).not.toBe(caller.signal);

      await vi.advanceTimersByTimeAsync(30_000);
      await rejection;
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([
    [409, { reason: "stale_revision", current_revision: 8 }],
    [409, { reason: "idempotency_conflict" }]
  ])("019-FR-020 projects CRT mutation HTTP errors with correlation (%s)", async (status, payload) => {
    fetchMock.mockResolvedValue(jsonResponse(payload, status, { "X-Correlation-ID": "server-correlation" }));

    await expect(crtApi.createCrtTree({ name: "Rejected" }, { idempotencyKey: "error-key" })).rejects.toMatchObject({
      name: "ApiError",
      status,
      correlationId: "server-correlation",
      payload
    });
  });

  it("019-FR-004 deletes a tree with the expected revision and mutation request contract", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204, headers: { "X-Correlation-ID": CORRELATION_ID } }));

    await expect(
      crtApi.deleteCrtTree("tree/1", { expectedRevision: 7, idempotencyKey: "delete-key" })
    ).resolves.toBeUndefined();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/crt/trees/tree%2F1?expected_revision=7");
    expect(init.method).toBe("DELETE");
    expect(init.credentials).toBe("include");
    expect(init.body).toBeUndefined();
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("Content-Type")).toBeNull();
    expect(headers.get("Idempotency-Key")).toBe("delete-key");
    expect(headers.get("X-Correlation-ID")).toBe(CORRELATION_ID);
  });

  it("019-FR-004 imports a typed tree envelope with the exact JSON body", async () => {
    const payload: CrtTreeImportPayload = {
      tree: {
        id: "source-tree",
        name: "Imported tree",
        revision: 3,
        schema_version: 1,
        metadata: {
          version: 1,
          created_at: "2026-09-20T09:00:00Z",
          updated_at: "2026-09-20T10:00:00Z",
          layout: null,
          owner_id: "owner-1"
        },
        nodes: [],
        relations: [],
        owner_id: "owner-1"
      }
    };
    const imported = { ...payload.tree, id: "fresh-tree", revision: 1 };
    fetchMock.mockResolvedValue(jsonResponse(imported, 201, { "X-Correlation-ID": CORRELATION_ID }));

    await expect(crtApi.importCrtTree(payload, { idempotencyKey: "import-key" })).resolves.toEqual(imported);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/crt/trees/import");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.body).toBe(JSON.stringify(payload));
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Idempotency-Key")).toBe("import-key");
    expect(headers.get("X-Correlation-ID")).toBe(CORRELATION_ID);
  });

  it("019-FR-004 exports the canonical tree envelope without an idempotency key", async () => {
    const exported: CrtTreeExportResponse = {
      tree: {
        id: "tree-1",
        name: "Current reality",
        revision: 7,
        schema_version: 1,
        metadata: {
          version: 1,
          created_at: "2026-09-20T09:00:00Z",
          updated_at: "2026-09-20T10:00:00Z",
          layout: { zoom: 1 },
          owner_id: "owner-1"
        },
        nodes: [],
        relations: [],
        owner_id: "owner-1"
      }
    };
    fetchMock.mockResolvedValue(jsonResponse(exported));

    await expect(crtApi.exportCrtTree("tree/1")).resolves.toEqual(exported);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/crt/trees/tree%2F1/export");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.body).toBeUndefined();
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("Content-Type")).toBeNull();
    expect(headers.get("Idempotency-Key")).toBeNull();
    expect(headers.get("X-Correlation-ID")).toBe(CORRELATION_ID);
  });

  it("uses default mutation options for update and import operations", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ id: "updated" }))
      .mockResolvedValueOnce(jsonResponse({ id: "imported" }));

    await expect(crtApi.updateCrtTree("tree-1", {} as CrtTreeUpdatePayload)).resolves.toEqual({ id: "updated" });
    await expect(crtApi.importCrtTree({} as CrtTreeImportPayload)).resolves.toEqual({ id: "imported" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reads successful non-JSON responses as text", async () => {
    fetchMock.mockResolvedValue(new Response("plain result", { status: 200, headers: { "Content-Type": "text/plain" } }));

    await expect(crtApi.probeCrtExposure()).resolves.toBe("plain result");
  });

  it("preserves non-JSON error details and falls back when the status text is empty", async () => {
    fetchMock.mockResolvedValue(
      new Response("plain detail", { status: 418, statusText: "", headers: { "Content-Type": "text/plain" } })
    );

    await expect(crtApi.listCrtTrees()).rejects.toMatchObject({
      name: "ApiError",
      message: "Request failed",
      status: 418,
      payload: "plain detail",
      correlationId: CORRELATION_ID
    });
  });

  it("normalizes an already-aborted caller signal into an ApiError", async () => {
    const caller = new AbortController();
    caller.abort(new DOMException("Caller cancelled", "AbortError"));
    fetchMock.mockImplementation((_input, init) => Promise.reject(init?.signal?.reason));

    await expect(crtApi.getCrtTree("tree-1", caller.signal)).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      message: "Caller cancelled",
      correlationId: CORRELATION_ID
    });
  });

  it.each([
    [{ message: "object failure" }, "object failure"],
    [{ reason: "unknown" }, "CRT request failed"]
  ] as const)("uses a stable message for non-Error fetch rejection %j", async (failure, message) => {
    fetchMock.mockRejectedValue(failure);

    await expect(crtApi.getCrtTree("tree-1")).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      message,
      payload: failure,
      correlationId: CORRELATION_ID
    });
  });
});

