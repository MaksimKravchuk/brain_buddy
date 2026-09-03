import { afterEach, describe, expect, it, vi } from "vitest";

import type { TaskResponse } from "../../../api/taskTypes";
import { apiClient, ApiError } from "../../../api/client";
import { createTaskDetailAutosaveController, loadTaskAutosaveRecovery, taskAutosaveStorageKey, validateTaskResponse } from "../taskDetailAutosave";

const task = (overrides: Partial<TaskResponse> = {}): TaskResponse => ({
  id: "task-1", title: "Task", details: "notes", state: "next", project_id: null,
  tag_ids: [], due_date: null, priority: "none", waiting_for: null, waiting_since: null,
  order_key: 1, source_capture_ids: [], created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z", completed_at: null, cancelled_at: null, revision: 1,
  subtasks: [], comments: [],
  ...overrides
});

const patch = { kind: "patch" as const, payload: { details: "changed" } };
const storageKey = (accountId = "account-a", taskId = "task-1") =>
  taskAutosaveStorageKey(accountId, window.location.origin, taskId);
const recovery = (overrides: Record<string, unknown> = {}) => ({
  version: 1,
  identity: { accountId: "account-a", apiOrigin: window.location.origin, taskId: "task-1" },
  baseline: task(),
  draft: { title: "Task", details: "recovered", state: "next", project_id: null, priority: "none", tag_ids: [], waiting_for: null, due_date: null },
  dirty: { details: { baseValue: "notes", generation: 1, value: "recovered" } },
  inFlight: { kind: "patch", body: { details: "recovered", expected_revision: 1 }, generations: { details: 1 }, idempotencyKey: "stable-key", attempt: 1 },
  barriers: [], status: "saving", conflict: null, error: null, retrying: false,
  ...overrides
});

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  localStorage.clear();
});

describe("task acknowledgement validation", () => {
  it("accepts canonical string details and rejects malformed tags", () => {
    const valid = task({ details: "changed", revision: 2 });
    expect(validateTaskResponse(valid, "task-1", 1, patch)).toEqual(valid);
    expect(() => validateTaskResponse({ ...valid, tag_ids: [7] }, "task-1", 1, patch)).toThrow();
  });

  it("enforces transition semantics, including completion timestamp and waiting fields", () => {
    const command = { kind: "transition" as const, payload: { action: "complete" as const } };
    expect(() => validateTaskResponse(task({ revision: 2, state: "completed" }), "task-1", 1, command)).toThrow();
    expect(validateTaskResponse(task({ revision: 2, state: "completed", completed_at: "2026-01-01T01:00:00Z" }), "task-1", 1, command)).toBeTruthy();
  });

  it("requires Reopen to acknowledge the requested open destination", () => {
    const command = { kind: "transition" as const, payload: { action: "reopen" as const, to_state: "inbox" as const } };
    expect(() => validateTaskResponse(task({ revision: 2, state: "next" }), "task-1", 1, command, true, "completed")).toThrow();
  });

  it.each(["completed", "cancelled"] as const)("accepts a %s PATCH acknowledgement that preserves the prior lifecycle", (state) => {
    const response = task({
      revision: 2,
      details: "changed",
      state,
      completed_at: state === "completed" ? "2026-01-01T01:00:00Z" : null,
      cancelled_at: state === "cancelled" ? "2026-01-01T01:00:00Z" : null
    });
    expect(validateTaskResponse(response, "task-1", 1, patch, true, state)).toEqual(response);
  });

  it("still rejects a PATCH acknowledgement that changes lifecycle", () => {
    const response = task({ revision: 2, details: "changed", state: "completed", completed_at: "2026-01-01T01:00:00Z" });
    expect(() => validateTaskResponse(response, "task-1", 1, patch, true, "next")).toThrow();
  });
});

describe("task autosave controller", () => {
  it("serializes rapid field changes against monotonically acknowledged revisions", async () => {
    let releaseFirst: ((value: TaskResponse) => void) | undefined;
    const firstResponse = new Promise<TaskResponse>((resolve) => { releaseFirst = resolve; });
    const update = vi.spyOn(apiClient, "updateTask")
      .mockReturnValueOnce(firstResponse)
      .mockResolvedValueOnce(task({ revision: 3, details: "changed", due_date: "2026-09-03" }));
    const controller = createTaskDetailAutosaveController("account-a", task());

    const first = controller.save(patch, "key-1");
    const second = controller.save({ kind: "patch", payload: { due_date: "2026-09-03" } }, "key-2");
    await Promise.resolve();
    expect(update).toHaveBeenCalledTimes(1);
    releaseFirst?.(task({ revision: 2, details: "changed" }));
    await first;
    await second;

    expect(update.mock.calls[0]?.[1]).toEqual({ details: "changed", expected_revision: 1 });
    expect(update.mock.calls[1]?.[1]).toEqual({ due_date: "2026-09-03", expected_revision: 2 });
  });

  it("serializes moving into Waiting before editing its waiting owner", async () => {
    vi.spyOn(apiClient, "transitionTask").mockResolvedValue(task({
      state: "waiting", waiting_for: "Finance", waiting_since: "2026-09-03T12:00:00Z", revision: 2
    }));
    vi.spyOn(apiClient, "updateTask").mockResolvedValue(task({
      state: "waiting", waiting_for: "Legal", waiting_since: "2026-09-03T12:00:00Z", revision: 3
    }));
    const controller = createTaskDetailAutosaveController("account-a", task());
    const moving = controller.save({ kind: "transition", payload: { action: "move", to_state: "waiting", waiting_for: "Finance" } }, "move-key");
    const editing = controller.save({ kind: "patch", payload: { waiting_for: "Legal" } }, "patch-key");
    await moving;
    await editing;
    expect(apiClient.updateTask).toHaveBeenCalledWith("task-1", { waiting_for: "Legal", expected_revision: 2 }, "patch-key");
  });

  it("keeps the exact body and key for bounded transport retries", async () => {
    vi.useFakeTimers();
    const first = task({ revision: 2, details: "changed" });
    vi.spyOn(apiClient, "updateTask").mockRejectedValueOnce(new TypeError("network")).mockResolvedValueOnce(first);
    const controller = createTaskDetailAutosaveController("account-a", task());
    const promise = controller.save(patch, "key-1");
    await vi.runAllTimersAsync();
    await expect(promise).resolves.toMatchObject({ status: "saved" });
    const calls = vi.mocked(apiClient.updateTask).mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0]?.[1]).toEqual(calls[1]?.[1]);
    expect(calls[0]?.[2]).toBe("key-1");
    expect(calls[1]?.[2]).toBe("key-1");
    vi.useRealTimers();
  });

  it("refetches on conflict and only rebases after explicit retry with a new key", async () => {
    const canonical = task({ revision: 2, details: "server" });
    const updated = task({ revision: 3, details: "changed" });
    vi.spyOn(apiClient, "updateTask").mockRejectedValueOnce(new ApiError("conflict", 409, {})).mockResolvedValue(updated);
    vi.spyOn(apiClient, "getTask").mockResolvedValue(canonical);
    const controller = createTaskDetailAutosaveController("account-a", task());
    const result = await controller.save(patch, "key-1");
    expect(result.status).toBe("conflict");
    expect(apiClient.updateTask).toHaveBeenCalledTimes(1);
    if (result.status === "conflict") await expect(result.retry()).resolves.toMatchObject({ status: "saved" });
    expect(apiClient.updateTask).toHaveBeenLastCalledWith("task-1", { details: "changed", expected_revision: 2 }, expect.not.stringMatching(/^key-1$/));
  });

  it("holds queued successors after conflict until the user explicitly retries", async () => {
    const canonical = task({ revision: 2, details: "server" });
    const rebased = task({ revision: 3, details: "changed", due_date: "2026-09-03" });
    vi.spyOn(apiClient, "updateTask")
      .mockRejectedValueOnce(new ApiError("conflict", 409, {}))
      .mockResolvedValueOnce(rebased);
    vi.spyOn(apiClient, "getTask").mockResolvedValue(canonical);
    const controller = createTaskDetailAutosaveController("account-a", task());
    const conflicted = await controller.save(patch, "key-1");
    const queued = controller.save({ kind: "patch", payload: { due_date: "2026-09-03" } }, "key-2");
    await Promise.resolve();
    expect(apiClient.updateTask).toHaveBeenCalledTimes(1);
    if (conflicted.status !== "conflict") throw new Error("expected conflict");
    await conflicted.retry();
    await queued;
    expect(apiClient.updateTask).toHaveBeenLastCalledWith("task-1", { details: "changed", due_date: "2026-09-03", expected_revision: 2 }, "key-2");
  });

  it("returns the fetched canonical task when a conflict is discarded", async () => {
    const canonical = task({ revision: 2, title: "Canonical", details: "server" });
    vi.spyOn(apiClient, "updateTask").mockRejectedValueOnce(new ApiError("conflict", 409, {}));
    vi.spyOn(apiClient, "getTask").mockResolvedValue(canonical);
    const controller = createTaskDetailAutosaveController("account-a", task());
    const result = await controller.save(patch, "key-1");
    if (result.status !== "conflict") throw new Error("expected conflict");
    expect(result.discard()).toEqual(canonical);
    expect(controller.conflict).toBeNull();
  });

  it("resumes a same-tab in-flight command with its exact body and key", async () => {
    const stored = recovery();
    sessionStorage.setItem(storageKey(), JSON.stringify(stored));
    vi.spyOn(apiClient, "updateTask").mockResolvedValue(task({ revision: 2, details: "recovered" }));
    const controller = createTaskDetailAutosaveController("account-a", task());
    await controller.resumeRecovery();
    expect(apiClient.updateTask).toHaveBeenCalledWith("task-1", stored.inFlight.body, "stable-key");
    expect(sessionStorage.getItem(storageKey())).toBeNull();
  });

  it("never exposes recovery to another identity or task", () => {
    sessionStorage.setItem(storageKey(), JSON.stringify(recovery({
      draft: { ...recovery().draft, details: "secret draft" },
      dirty: { details: { baseValue: "notes", generation: 1, value: "secret draft" } },
      inFlight: { kind: "patch", body: { details: "secret draft", expected_revision: 1 }, generations: { details: 1 }, idempotencyKey: "key", attempt: 1 }
    })));
    expect(loadTaskAutosaveRecovery("account-b", "task-1")).toBeNull();
    expect(loadTaskAutosaveRecovery("account-a", "task-2")).toBeNull();
    expect(loadTaskAutosaveRecovery("account-a", "task-1")?.draft).toMatchObject({ details: "secret draft" });
  });

  it.each([
    ["unbound HTTP body field", { kind: "patch", body: { details: "x", expected_revision: 1, action: "complete" }, generations: { details: 1 }, idempotencyKey: "key", attempt: 1 }],
    ["invalid transition action", { kind: "transition", body: { action: "archive", expected_revision: 1 }, generations: {}, idempotencyKey: "key", attempt: 1 }],
    ["attempt above retry bound", { kind: "patch", body: { details: "x", expected_revision: 1 }, generations: { details: 1 }, idempotencyKey: "key", attempt: 4 }],
    ["attempt below retry bound", { kind: "patch", body: { details: "x", expected_revision: 1 }, generations: { details: 1 }, idempotencyKey: "key", attempt: 0 }],
    ["empty idempotency key", { kind: "patch", body: { details: "x", expected_revision: 1 }, generations: { details: 1 }, idempotencyKey: "", attempt: 1 }],
    ["complete forbids destination", { kind: "transition", body: { action: "complete", to_state: "inbox", expected_revision: 1 }, generations: {}, idempotencyKey: "key", attempt: 1 }],
    ["cancel forbids waiting target", { kind: "transition", body: { action: "cancel", waiting_for: "person", expected_revision: 1 }, generations: {}, idempotencyKey: "key", attempt: 1 }],
    ["move requires destination", { kind: "transition", body: { action: "move", expected_revision: 1 }, generations: {}, idempotencyKey: "key", attempt: 1 }],
    ["reopen requires destination", { kind: "transition", body: { action: "reopen", expected_revision: 1 }, generations: {}, idempotencyKey: "key", attempt: 1 }]
  ] as const)("removes malformed recovery record: %s", (_name, inFlight) => {
    sessionStorage.setItem(storageKey(), JSON.stringify(recovery({ inFlight })));
    expect(loadTaskAutosaveRecovery("account-a", "task-1")).toBeNull();
    expect(sessionStorage.getItem(storageKey())).toBeNull();
  });

  it("uses session storage rather than local storage for recovery", () => {
    localStorage.setItem(storageKey(), JSON.stringify({ version: 1 }));
    expect(loadTaskAutosaveRecovery("account-a", "task-1")).toBeNull();
    expect(localStorage.getItem(storageKey())).toBe(JSON.stringify({ version: 1 }));
  });
});
