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

  it("rethrows a non-Error network failure without wrapping it either", async () => {
    fetchMock.mockRejectedValue("socket hang up");

    await expect(apiClient.getTask("task-1")).rejects.toBe("socket hang up");
  });

  it("serializes every date, priority, sort and cancelled filter of the task query", async () => {
    fetchMock.mockResolvedValue(response({ items: [], counts_by_state: {} }));

    await apiClient.listTasks({
      includeCancelled: true,
      priority: ["high", "medium"],
      dueBefore: "2026-08-01",
      dueOn: "2026-08-02",
      dueAfter: "2026-08-03",
      sort: "due"
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/tasks?include_cancelled=true&priority=high&priority=medium&due_before=2026-08-01&due_on=2026-08-02&due_after=2026-08-03&sort=due"
    );
  });

  it("leaves manual order, blank searches and absent filters out of the task query", async () => {
    fetchMock.mockResolvedValue(response({ items: [], counts_by_state: {} }));

    await apiClient.listTasks({ sort: "manual", q: "   ", includeCompleted: false, unassignedProject: false });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/tasks");
  });

  it("sends subtask and comment edits with their own idempotency keys", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "subtask-1", revision: 2 })));

    await apiClient.createSubtask("task-1", { title: "Draft" }, "subtask-create-key");
    await apiClient.updateSubtask("task-1", "subtask-1", { title: "Draft again", expected_revision: 1 }, "subtask-update-key");
    await apiClient.transitionSubtask("task-1", "subtask-1", { action: "complete", expected_revision: 2 }, "subtask-move-key");
    await apiClient.createComment("task-1", { body: "Noted" }, "comment-create-key");
    await apiClient.updateComment("task-1", "comment-1", { body: "Noted again", expected_revision: 1 }, "comment-update-key");

    expect(fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method])).toEqual([
      ["/api/tasks/task-1/subtasks", "POST"],
      ["/api/tasks/task-1/subtasks/subtask-1", "PATCH"],
      ["/api/tasks/task-1/subtasks/subtask-1/transitions", "POST"],
      ["/api/tasks/task-1/comments", "POST"],
      ["/api/tasks/task-1/comments/comment-1", "PATCH"]
    ]);
    expect(
      fetchMock.mock.calls.map(([, init]) => new Headers((init as RequestInit).headers).get("Idempotency-Key"))
    ).toEqual([
      "subtask-create-key",
      "subtask-update-key",
      "subtask-move-key",
      "comment-create-key",
      "comment-update-key"
    ]);
  });

  it("leaves an unhandled 401 alone when no session handler is registered", async () => {
    fetchMock.mockResolvedValue(response({ detail: "expired" }, 401));

    await expect(apiClient.listTags()).rejects.toMatchObject({ status: 401, correlationId: undefined });
  });

  it("names its own error type, so a caller can tell an ApiError from any other throw", async () => {
    fetchMock.mockResolvedValue(response({ detail: "nope" }, 409));

    const failure = await apiClient.listTags().catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).name).toBe("ApiError");
  });

  it("sends no body and no JSON content type on reads", async () => {
    fetchMock.mockResolvedValue(response({ items: [], counts_by_state: {} }));

    await apiClient.listTasks();

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeUndefined();
    expect(new Headers(init.headers).get("Content-Type")).toBeNull();
    expect(init.credentials).toBe("include");
  });

  // Every read takes an AbortSignal so React Query can cancel it when the
  // component unmounts; a request that ignores it keeps running after the view
  // is gone and resolves into nothing.
  it.each([
    ["listTasks", (signal: AbortSignal) => apiClient.listTasks({}, signal)],
    ["getTask", (signal: AbortSignal) => apiClient.getTask("task-1", signal)],
    ["listProjects", (signal: AbortSignal) => apiClient.listProjects(signal)],
    ["listTags", (signal: AbortSignal) => apiClient.listTags(signal)],
    ["getAccount", (signal: AbortSignal) => apiClient.getAccount(signal)],
    ["getBrainDumpProviders", (signal: AbortSignal) => apiClient.getBrainDumpProviders(signal)],
    ["getBrainDump", (signal: AbortSignal) => apiClient.getBrainDump("op-1", signal)]
  ])("forwards the caller's abort signal on %s", async (_name, call) => {
    fetchMock.mockResolvedValue(response({ items: [], counts_by_state: {} }));
    const controller = new AbortController();

    await call(controller.signal);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBe(controller.signal);
  });

  // The backend deduplicates a retried write by its Idempotency-Key. A write
  // that drops the header turns a retry into a second task, project or tag.
  it.each([
    ["createProject", () => apiClient.createProject({ name: "Launch" }, "key-1"), "POST", "/api/projects"],
    [
      "updateProject",
      () => apiClient.updateProject("project-1", { name: "Launch", expected_revision: 2 }, "key-2"),
      "PATCH",
      "/api/projects/project-1"
    ],
    [
      "archiveProject",
      () => apiClient.archiveProject("project-1", 3, "key-3"),
      "POST",
      "/api/projects/project-1/archive"
    ],
    ["createTag", () => apiClient.createTag({ name: "calls" }, "key-4"), "POST", "/api/tags"],
    [
      "updateTag",
      () => apiClient.updateTag("tag-1", { name: "calls", expected_revision: 1 }, "key-5"),
      "PATCH",
      "/api/tags/tag-1"
    ],
    [
      "deleteTag",
      () => apiClient.deleteTag("tag-1", 4, "key-6"),
      "DELETE",
      "/api/tags/tag-1?expected_revision=4"
    ],
    [
      "startBrainDump",
      () => apiClient.startBrainDump({ mode: "voice" } as never, "key-7"),
      "POST",
      "/api/brain-dump-operations"
    ],
    [
      "appendBrainDumpTranscript",
      () => apiClient.appendBrainDumpTranscript("op-1", { text: "hi" } as never, "key-8"),
      "POST",
      "/api/brain-dump-operations/op-1/transcript"
    ],
    [
      "sealBrainDump",
      () =>
        apiClient.sealBrainDump(
          "op-1",
          { expected_revision: 1, expected_chunks: 2, manifest_hash: "hash" },
          "key-9"
        ),
      "POST",
      "/api/brain-dump-operations/op-1/seal"
    ],
    [
      "updateBrainDumpProposal",
      () => apiClient.updateBrainDumpProposal("op-1", "proposal-1", { expected_revision: 1 }, "key-10"),
      "PATCH",
      "/api/brain-dump-operations/op-1/proposals/proposal-1"
    ],
    [
      "commandBrainDump",
      () => apiClient.commandBrainDump("op-1", "commit", 2, "key-11"),
      "POST",
      "/api/brain-dump-operations/op-1/commit"
    ]
  ])("sends %s with its method, path and idempotency key", async (_name, call, method, url) => {
    fetchMock.mockResolvedValue(response({ id: "created" }));

    await call();

    const [requestUrl, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toBe(url);
    expect(init.method).toBe(method);
    expect(new Headers(init.headers).get("Idempotency-Key")).toMatch(/^key-\d+$/);
  });

  it("carries the expected revision of the write it is guarding", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "project-1" })));

    await apiClient.archiveProject("project-1", 7, "key-archive");
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      expected_revision: 7
    });

    fetchMock.mockClear();
    await apiClient.commandBrainDump("op-1", "cancel", 9, "key-cancel");
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      expected_revision: 9
    });
  });

  it("uploads an audio chunk as raw bytes rather than JSON", async () => {
    fetchMock.mockResolvedValue(response({ id: "op-1" }));
    const audio = new Uint8Array([4, 5, 6]).buffer;

    await apiClient.uploadBrainDumpAudio("op-1", 3, audio, "sha", "audio/webm");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/brain-dump-operations/op-1/audio/3");
    expect(init.method).toBe("PUT");
    expect(init.body).toBe(audio);
    expect(new Headers(init.headers).get("Content-Type")).toBe("audio/webm");
  });

  it("falls back to a generic message when the failed response has no status text", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "boom" }), {
        status: 500,
        statusText: "",
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(apiClient.listTags()).rejects.toThrow("Request failed");
  });
});
