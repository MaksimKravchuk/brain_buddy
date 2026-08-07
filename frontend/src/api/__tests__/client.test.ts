import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient, setUnauthorizedHandler } from "../client";

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

  it("declares the recorded media MIME type on audio uploads", async () => {
    fetchMock.mockResolvedValue(response({ id: "brain-dump-1" }));
    const audio = new Uint8Array([1, 2, 3]).buffer;

    await apiClient.uploadBrainDumpAudio(
      "brain-dump-1",
      0,
      audio,
      "fixture-sha",
      "audio/webm;codecs=opus"
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("audio/webm;codecs=opus");
    expect(headers.get("X-Content-SHA256")).toBe("fixture-sha");
    expect(init.body).toBe(audio);
  });

  it("uses the account management API contracts", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({})));

    await apiClient.getAccount();
    await apiClient.updateProfile({ display_name: "Maks" });
    await apiClient.changeEmail({ new_email: "a@b.c", current_password: "pw" });
    await apiClient.changePassword({ current_password: "pw", new_password: "pw2" });
    await apiClient.requestAccountDeletion({ current_password: "pw" });

    expect(
      fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method])
    ).toEqual([
      ["/api/account", "GET"],
      ["/api/account/profile", "PATCH"],
      ["/api/account/email", "POST"],
      ["/api/account/password", "POST"],
      ["/api/account/delete", "POST"]
    ]);
    const [, deleteInit] = fetchMock.mock.calls[4] as [string, RequestInit];
    expect(JSON.parse(String(deleteInit.body))).toEqual({ current_password: "pw" });
  });

  it("uses the public task, project, and tag API contracts", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ items: [], counts_by_state: {} })));

    await apiClient.listTasks({ state: "next", projectId: "project-1", tagId: "tag-1", includeCompleted: true });
    await apiClient.listProjects();
    await apiClient.listTags();

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/tasks?state=next&project_id=project-1&tag_id=tag-1&include_completed=true",
      "/api/projects",
      "/api/tags"
    ]);
  });

  it("serializes the projectless Inbox projection filter with the rest of the task query", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ items: [], counts_by_state: {} })));

    await apiClient.listTasks({ state: "inbox", unassignedProject: true, q: " shared ", cursor: "page-2", limit: 25 });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/tasks?state=inbox&cursor=page-2&limit=25&q=shared&unassigned_project=true"
    );
  });

  it("sends native task create, update, and transition idempotency contracts", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "task-1", revision: 2 })));

    await apiClient.createTask({ title: "New task", state: "inbox" }, "create-key");
    await apiClient.updateTask("task-1", { title: "Updated task", expected_revision: 1 }, "update-key");
    await apiClient.transitionTask("task-1", { action: "move", to_state: "next", expected_revision: 2 }, "move-key");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/tasks", "/api/tasks/task-1", "/api/tasks/task-1/transitions"]);
    const inits = fetchMock.mock.calls.map(([, init]) => init as RequestInit);
    expect(inits.map((init) => new Headers(init.headers).get("Idempotency-Key"))).toEqual(["create-key", "update-key", "move-key"]);
    expect(inits.map((init) => init.method)).toEqual(["POST", "PATCH", "POST"]);
    expect(inits[2].body).toBe(JSON.stringify({ action: "move", to_state: "next", expected_revision: 2 }));
  });

  it("sends Smart Add task classification through the compound endpoint", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ task: { id: "task-1", revision: 1 }, tags: [], created: { project_id: null, tag_ids: [] } })));

    await apiClient.smartAddTask(
      {
        title: "Call supplier",
        state: "next",
        project: { name: "Vendor launch" },
        tags: [{ id: "tag-calls" }, { name: "vendor" }]
      },
      "smart-add-key"
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/tasks/smart-add",
      expect.objectContaining({ credentials: "include", method: "POST" })
    );
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("smart-add-key");
    expect(init.body).toBe(JSON.stringify({
      title: "Call supplier",
      state: "next",
      project: { name: "Vendor launch" },
      tags: [{ id: "tag-calls" }, { name: "vendor" }]
    }));
  });

  it("omits task query parameters when filters are absent", async () => {
    fetchMock.mockResolvedValue(response({ items: [], counts_by_state: {} }));

    await apiClient.listTasks();

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/tasks");
  });

  it("notifies the session handler and preserves correlation IDs for failed requests", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    fetchMock.mockResolvedValue(response({ detail: "expired" }, 401, { "X-Correlation-ID": "corr-1" }));

    await expect(apiClient.listTasks()).rejects.toMatchObject({
      status: 401,
      correlationId: "corr-1",
      payload: { detail: "expired" }
    });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("treats delete responses without content as successful", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await expect(apiClient.deleteTag("tag-1", 3, "idem-delete-tag")).resolves.toBeUndefined();
    expect(fetchMock.mock.calls.map(([url]) => url)).toContain("/api/tags/tag-1?expected_revision=3");
  });

  it("serializes JSON bodies with a JSON content type", async () => {
    fetchMock.mockResolvedValue(response({ ok: true }));
    await apiClient.createProject({ name: "Launch v2" }, "idem-create-project");

    const [, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ name: "Launch v2" }));
  });

  it("returns text payloads verbatim when the response is not JSON", async () => {
    fetchMock.mockResolvedValue(new Response("plain failure", { status: 500, headers: { "Content-Type": "text/plain" } }));

    await expect(apiClient.listTasks()).rejects.toMatchObject({ status: 500, payload: "plain failure" });
  });

  it("rethrows network failures without wrapping them", async () => {
    fetchMock.mockRejectedValue(new Error("Network down"));

    await expect(apiClient.getTask("task-1")).rejects.toThrow("Network down");
  });
});
