import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient, setUnauthorizedHandler } from "../client";
import type { RelationCreateRequest, TreeMetadata } from "../types";

const metadata: TreeMetadata = {
  version: 1,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z"
};

function response(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Request failed" : "OK",
    headers: { "Content-Type": "application/json", ...headers }
  });
}

describe("apiClient", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    setUnauthorizedHandler(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setUnauthorizedHandler(null);
  });

  it("preserves form bodies and omits absent relation update fields", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "result" })));

    await apiClient.createRelation("tree-1", {
      source_node_id: "source-1",
      target_node_id: "target-1"
    });
    await apiClient.updateRelation("tree-1", "relation-1", {});
    const form = new FormData();
    form.append("tree", "export");
    await apiClient.createTree(form as unknown as Parameters<typeof apiClient.createTree>[0]);

    const [, createRelationInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(createRelationInit.body).toBe(
      JSON.stringify({ source_node_id: "source-1", target_node_id: "target-1", kind: "why" })
    );
    const [, updateRelationInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(updateRelationInit.body).toBe(JSON.stringify({}));
    const [, formInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(formInit.body).toBe(form);
    expect(new Headers(formInit.headers).has("Content-Type")).toBe(false);
  });

  it("normalizes relation aliases before submitting a relation", async () => {
    fetchMock.mockResolvedValue(response({ id: "relation-1" }));

    await apiClient.createRelation(
      "tree-1",
      { source_id: "source-1", target_id: "target-1", kind: "why" } as RelationCreateRequest
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/trees/tree-1/relations",
      expect.objectContaining({ credentials: "include", method: "POST" })
    );
    expect(init.body).toBe(
      JSON.stringify({ source_node_id: "source-1", target_node_id: "target-1", kind: "why" })
    );
  });

  it("rejects relations without both endpoints before issuing a request", () => {
    expect(() => apiClient.createRelation("tree-1", { kind: "why" } as RelationCreateRequest)).toThrow(
      "source_node_id and target_node_id are required"
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends the complete tree workflow through its typed endpoints", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "result" })));

    await apiClient.listTrees();
    await apiClient.getTree("tree-1");
    await apiClient.createTree({ name: "New tree" });
    await apiClient.updateTree("tree-1", { name: "Renamed", metadata, nodes: [], relations: [] });
    await apiClient.createNode("tree-1", { label: "Root", type: "child", position: { x: 1, y: 2 } });
    await apiClient.updateNode("tree-1", "node-1", { label: "Updated" });
    await apiClient.updateRelation("tree-1", "relation-1", { from_id: "source-1", kind: "why" });
    await apiClient.createVersion("tree-1", { label: "Before", author: null, notes: null });
    await apiClient.listVersions("tree-1");
    await apiClient.restoreVersion("tree-1", "version-1");
    await apiClient.exportTree("tree-1");
    await apiClient.aiFeedback("tree-1", { consent: true });
    await apiClient.importTree({ id: "tree-2", name: "Imported", metadata, nodes: [], relations: [] });
    await apiClient.triggerValidation("tree-1", "node-1", { provider: "mock" });
    await apiClient.getValidationHistory("tree-1", "node-1");

    expect(fetchMock).toHaveBeenCalledTimes(15);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(
      expect.arrayContaining([
        "/api/trees",
        "/api/trees/tree-1/nodes",
        "/api/trees/tree-1/versions",
        "/api/trees/tree-1/validate/node-1"
      ])
    );
    const [, createNodeInit] = fetchMock.mock.calls[4] as [string, RequestInit];
    expect(createNodeInit.body).toBe(
      JSON.stringify({ highlight_state: "none", label: "Root", type: "child", position: { x: 1, y: 2 } })
    );
  });

  it("notifies the session handler and preserves correlation IDs for failed requests", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    fetchMock.mockResolvedValue(response({ detail: "expired" }, 401, { "X-Correlation-ID": "corr-1" }));

    await expect(apiClient.listTrees()).rejects.toMatchObject({
      status: 401,
      correlationId: "corr-1",
      payload: { detail: "expired" }
    });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("treats delete responses without content as successful", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await expect(apiClient.deleteTree("tree-1")).resolves.toBeUndefined();
    await expect(apiClient.deleteNode("tree-1", "node-1", true)).resolves.toBeUndefined();
    await expect(apiClient.deleteRelation("tree-1", "relation-1")).resolves.toBeUndefined();
    await expect(apiClient.deleteVersion("tree-1", "version-1")).resolves.toBeUndefined();
    expect(fetchMock.mock.calls.map(([url]) => url)).toContain("/api/trees/tree-1/nodes/node-1?cascade=true");
  });

  it("serializes JSON bodies with a JSON content type", async () => {
    fetchMock.mockResolvedValue(response({ ok: true }));
    const payload = {
      id: "tree-1",
      name: "Imported",
      metadata: { version: 1, created_at: "2025-01-01", updated_at: "2025-01-01" },
      nodes: [],
      relations: []
    };

    await apiClient.importTree(payload);

    const [, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ tree: payload }));
  });

  it("returns text payloads verbatim when the response is not JSON", async () => {
    fetchMock.mockResolvedValue(new Response("plain failure", { status: 500, headers: { "Content-Type": "text/plain" } }));

    await expect(apiClient.listTrees()).rejects.toMatchObject({ status: 500, payload: "plain failure" });
  });

  it("rethrows network failures without wrapping them", async () => {
    fetchMock.mockRejectedValue(new Error("Network down"));

    await expect(apiClient.getTree("tree-1")).rejects.toThrow("Network down");
  });
});
