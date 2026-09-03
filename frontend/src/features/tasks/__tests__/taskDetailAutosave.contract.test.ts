import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import type { TaskResponse } from "../../../api/taskTypes";
import {
  createTaskDetailAutosaveController,
  getTaskDetailAutosaveController,
  loadTaskAutosaveRecovery,
  resetTaskDetailAutosaveControllersForTests,
  taskAutosaveStorageKey,
  validateTaskResponse,
  type AutosaveSnapshot
} from "../taskDetailAutosave";

const task = (overrides: Partial<TaskResponse> = {}): TaskResponse => ({
  id: "task-1", title: "Task", details: "notes", state: "next", project_id: null,
  tag_ids: [], due_date: null, priority: "none", waiting_for: null, waiting_since: null,
  order_key: 1, source_capture_ids: [], created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z", completed_at: null, cancelled_at: null, revision: 1,
  subtasks: [], comments: [], ...overrides
});

const draft = (overrides: Partial<Record<string, unknown>> = {}) => ({
  title: "Task", details: "notes", state: "next", project_id: null,
  priority: "none", tag_ids: [], waiting_for: null, due_date: null, ...overrides
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const settle = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

afterEach(() => {
  resetTaskDetailAutosaveControllersForTests();
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("contract-complete task detail autosave controller", () => {
  it("coalesces successor fields, publishes queued state, and never reports an older acknowledgement as saved", async () => {
    const first = deferred<TaskResponse>();
    const second = deferred<TaskResponse>();
    const update = vi.spyOn(apiClient, "updateTask").mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    const seen: AutosaveSnapshot[] = [];
    controller.subscribe(() => seen.push(controller.getSnapshot()));

    controller.change("title", "First", 0);
    await settle();
    controller.change("details", "Later details", 0);
    controller.change("priority", "high", 0);
    controller.change("due_date", "2026-09-03", 0);
    await settle();

    expect(update).toHaveBeenCalledTimes(1);
    expect(controller.getSnapshot()).toMatchObject({ status: "queued", queuedCount: 3 });
    first.resolve(task({ revision: 2, title: "First" }));
    await settle();
    expect(update).toHaveBeenCalledTimes(2);
    expect(update.mock.calls[1]?.[1]).toEqual({
      details: "Later details", priority: "high", due_date: "2026-09-03", expected_revision: 2
    });
    expect(seen.some((snapshot) => snapshot.status === "saved" && snapshot.dirtyFields.length > 0)).toBe(false);
    second.resolve(task({ revision: 3, title: "First", details: "Later details", priority: "high", due_date: "2026-09-03" }));
    await controller.whenIdle();
    expect(controller.getSnapshot()).toMatchObject({ status: "saved", dirtyFields: [], queuedCount: 0 });
  });

  it("persists the full baseline, eight-field draft, dirty generations, in-flight command, and successor state", async () => {
    const first = deferred<TaskResponse>();
    vi.spyOn(apiClient, "updateTask").mockReturnValue(first.promise);
    const origin = "https://api.example.test/api";
    const controller = createTaskDetailAutosaveController("account-a", origin, task());
    controller.change("title", "In flight", 0);
    await settle();
    controller.change("details", "Successor", 500);

    const raw = sessionStorage.getItem(taskAutosaveStorageKey("account-a", origin, "task-1"));
    expect(raw).not.toBeNull();
    const stored = JSON.parse(raw ?? "{}") as Record<string, unknown>;
    expect(stored).toMatchObject({
      version: 1,
      identity: { accountId: "account-a", apiOrigin: origin, taskId: "task-1" },
      baseline: { id: "task-1", revision: 1, title: "Task" },
      draft: { title: "In flight", details: "Successor", state: "next", project_id: null, priority: "none", tag_ids: [], waiting_for: null, due_date: null },
      dirty: { title: { baseValue: "Task", generation: 1, value: "In flight" }, details: { baseValue: "notes", generation: 1, value: "Successor" } },
      inFlight: { body: { title: "In flight", expected_revision: 1 }, generations: { title: 1 }, attempt: 1 },
      status: "queued"
    });
  });

  it("restores a saving command as queued with the same body/key and preserves later dirty draft", async () => {
    const origin = "https://api.example.test/api";
    const key = taskAutosaveStorageKey("account-a", origin, "task-1");
    sessionStorage.setItem(key, JSON.stringify({
      version: 1,
      identity: { accountId: "account-a", apiOrigin: origin, taskId: "task-1" },
      baseline: task(),
      draft: { title: "Sent", details: "Later", state: "next", project_id: null, priority: "none", tag_ids: [], waiting_for: null, due_date: null },
      dirty: {
        title: { baseValue: "Task", generation: 1, value: "Sent" },
        details: { baseValue: "notes", generation: 1, value: "Later" }
      },
      inFlight: { kind: "patch", body: { title: "Sent", expected_revision: 1 }, generations: { title: 1 }, idempotencyKey: "same-key", attempt: 1 },
      barriers: [], status: "saving", conflict: null, error: null, retrying: false
    }));
    const update = vi.spyOn(apiClient, "updateTask")
      .mockResolvedValueOnce(task({ revision: 2, title: "Sent" }))
      .mockResolvedValueOnce(task({ revision: 3, title: "Sent", details: "Later" }));

    const controller = createTaskDetailAutosaveController("account-a", origin, task());
    await controller.whenIdle();

    expect(update.mock.calls[0]?.slice(1)).toEqual([{ title: "Sent", expected_revision: 1 }, "same-key"]);
    expect(update.mock.calls[1]?.[1]).toEqual({ details: "Later", expected_revision: 2 });
    expect(controller.getSnapshot().draft.details).toBe("Later");
    expect(sessionStorage.getItem(key)).toBeNull();
  });

  it("pauses after a definitive failure and manually retries the exact failed command before its successor", async () => {
    const error = new ApiError("invalid", 422, { detail: "Title is invalid" });
    const update = vi.spyOn(apiClient, "updateTask")
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce(task({ revision: 2, title: "Rejected" }))
      .mockResolvedValueOnce(task({ revision: 3, title: "Rejected", details: "Later" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    controller.change("title", "Rejected", 0);
    await controller.whenPaused();
    const failedCall = update.mock.calls[0];
    controller.change("details", "Later", 0);
    await settle();
    expect(update).toHaveBeenCalledTimes(1);
    expect(controller.getSnapshot()).toMatchObject({ status: "failed", error: { kind: "validation", message: "Title is invalid", retryAllowed: true } });

    controller.retry();
    await controller.whenIdle();
    expect(update.mock.calls[1]).toEqual(failedCall);
    expect(update.mock.calls[2]?.[1]).toEqual({ details: "Later", expected_revision: 2 });
  });

  it.each([408, 429, 500, 503])("retries HTTP %s at most three times with the immutable body and key", async (status) => {
    vi.useFakeTimers();
    const update = vi.spyOn(apiClient, "updateTask")
      .mockRejectedValueOnce(new ApiError("retry", status, {}, undefined, status === 429 ? 20_000 : undefined))
      .mockRejectedValueOnce(new ApiError("retry", status, {}))
      .mockResolvedValueOnce(task({ revision: 2, details: "changed" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("details", "changed", 0);
    await vi.runAllTimersAsync();
    await controller.whenIdle();
    expect(update).toHaveBeenCalledTimes(3);
    expect(update.mock.calls.map((call) => call.slice(1))).toEqual([
      [{ details: "changed", expected_revision: 1 }, expect.any(String)],
      [{ details: "changed", expected_revision: 1 }, expect.any(String)],
      [{ details: "changed", expected_revision: 1 }, expect.any(String)]
    ]);
    expect(update.mock.calls[1]?.[2]).toBe(update.mock.calls[0]?.[2]);
    expect(update.mock.calls[2]?.[2]).toBe(update.mock.calls[0]?.[2]);
  });

  it("treats same-revision different canonical data as a paused protocol failure without replacing dirty fields", async () => {
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("details", "Local", 500);
    controller.sync(task({ title: "Impossible same revision" }));
    expect(controller.getSnapshot()).toMatchObject({
      status: "failed",
      draft: { title: "Task", details: "Local" },
      error: { kind: "protocol", retryAllowed: false }
    });
  });

  it("rebases only clean fields after 409, keeps dirty base values, and uses a fresh key for explicit retry", async () => {
    const canonical = task({ revision: 2, title: "Server title", project_id: "project-server" });
    const update = vi.spyOn(apiClient, "updateTask")
      .mockRejectedValueOnce(new ApiError("conflict", 409, {}, "corr-1"))
      .mockResolvedValueOnce(task({ revision: 3, title: "Local title", project_id: "project-server" }));
    vi.spyOn(apiClient, "getTask").mockResolvedValue(canonical);
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "Local title", 0);
    await controller.whenPaused();

    expect(controller.getSnapshot()).toMatchObject({
      status: "conflicted",
      draft: { title: "Local title", project_id: "project-server" },
      dirty: { title: { baseValue: "Task", value: "Local title" } },
      conflict: { correlationId: "corr-1", latestServerTask: { revision: 2, title: "Server title" } }
    });
    const oldKey = update.mock.calls[0]?.[2];
    controller.retry();
    await controller.whenIdle();
    expect(update.mock.calls[1]?.[1]).toEqual({ title: "Local title", expected_revision: 2 });
    expect(update.mock.calls[1]?.[2]).not.toBe(oldKey);
  });

  it("preserves a rejected Reopen barrier across refetch and only saves after explicit retry acknowledgement", async () => {
    const completed = task({
      revision: 1,
      state: "completed",
      completed_at: "2026-01-02T00:00:00Z"
    });
    const canonical = task({
      revision: 2,
      state: "completed",
      completed_at: "2026-01-02T00:00:00Z",
      updated_at: "2026-01-02T00:01:00Z"
    });
    const reopened = task({
      revision: 3,
      state: "inbox",
      updated_at: "2026-01-02T00:02:00Z"
    });
    const transition = vi.spyOn(apiClient, "transitionTask")
      .mockRejectedValueOnce(new ApiError("conflict", 409, {}, "corr-reopen"))
      .mockResolvedValueOnce(reopened);
    vi.spyOn(apiClient, "getTask").mockResolvedValue(canonical);
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", completed);

    controller.barrier("reopen", "inbox");
    await controller.whenPaused();

    expect(transition).toHaveBeenCalledTimes(1);
    expect(controller.getSnapshot()).toMatchObject({
      status: "conflicted",
      baseline: { revision: 2, state: "completed" },
      conflict: { latestServerTask: { revision: 2 }, rejectedCommandKind: "transition" }
    });
    expect(controller.getSnapshot().barriers).toEqual([{ action: "reopen", toState: "inbox" }]);
    expect(controller.getSnapshot().status).not.toBe("saved");

    const rejectedKey = transition.mock.calls[0]?.[2];
    controller.retry();
    await controller.whenIdle();

    expect(transition).toHaveBeenCalledTimes(2);
    expect(transition.mock.calls[1]?.[1]).toEqual({ action: "reopen", to_state: "inbox", expected_revision: 2 });
    expect(transition.mock.calls[1]?.[2]).not.toBe(rejectedKey);
    expect(controller.getSnapshot()).toMatchObject({ status: "saved", baseline: reopened, dirtyFields: [], queuedCount: 0 });
  });

  it("keeps conflict actionable when refetch fails and can retry the refetch", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("conflict", 409, {}));
    const get = vi.spyOn(apiClient, "getTask").mockRejectedValueOnce(new TypeError("offline")).mockResolvedValueOnce(task({ revision: 2 }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "Local", 0);
    await controller.whenPaused();
    expect(controller.getSnapshot()).toMatchObject({ status: "conflicted", conflict: { refetchFailed: true } });
    controller.retryRefetch();
    await controller.whenPaused();
    expect(get).toHaveBeenCalledTimes(2);
    expect(controller.getSnapshot()).toMatchObject({ status: "conflicted", conflict: { refetchFailed: false, latestServerTask: { revision: 2 } } });
  });

  it("rejects blank Waiting locally and serializes pending edits before lifecycle barriers", async () => {
    const update = vi.spyOn(apiClient, "updateTask").mockResolvedValue(task({ revision: 2, details: "Before barrier" }));
    const transition = vi.spyOn(apiClient, "transitionTask").mockResolvedValue(task({ revision: 3, details: "Before barrier", state: "completed", completed_at: "2026-01-02T00:00:00Z" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    expect(controller.transition("waiting")).toEqual({ accepted: false, reason: "waiting-required" });
    expect(transition).not.toHaveBeenCalled();
    controller.change("details", "Before barrier", 500);
    controller.barrier("complete");
    await controller.whenIdle();
    expect(update).toHaveBeenCalledBefore(transition);
    expect(transition.mock.calls[0]?.[1]).toEqual({ action: "complete", expected_revision: 2 });
  });

  it("validates every lifecycle shape before accepting a server acknowledgement", () => {
    const valid = task({ revision: 2 });
    const malformed: unknown[] = [
      null,
      { ...valid, id: "other-task" },
      { ...valid, state: "archived" },
      { ...valid, details: 7 },
      { ...valid, project_id: 7 },
      { ...valid, tag_ids: [7] },
      { ...valid, due_date: 7 },
      { ...valid, priority: "urgent" },
      { ...valid, waiting_for: 7 },
      { ...valid, revision: 2.5 },
      { ...valid, source_capture_ids: null },
      { ...valid, subtasks: null },
      { ...valid, comments: null },
      task({ revision: 1 }),
      task({ revision: 2, state: "waiting", waiting_for: null, waiting_since: null }),
      task({ revision: 2, waiting_for: "stale owner" }),
      task({ revision: 2, state: "cancelled", completed_at: "wrong", cancelled_at: null })
    ];
    for (const value of malformed) {
      expect(() => validateTaskResponse(value, "task-1", 1)).toThrow("invalid task acknowledgement");
    }

    const cancelled = task({ revision: 2, state: "cancelled", cancelled_at: "2026-01-02T00:00:00Z" });
    expect(validateTaskResponse(cancelled, "task-1", 1)).toEqual(cancelled);
    expect(() => validateTaskResponse(valid, "task-1", 1, { kind: "patch", payload: { title: "different" } }, true, "next"))
      .toThrow("does not match");

    const transitionCases = [
      [{ action: "complete" as const }, valid],
      [{ action: "cancel" as const }, valid],
      [{ action: "move" as const, to_state: "inbox" as const }, valid],
      [{ action: "reopen" as const, to_state: "inbox" as const }, task({ revision: 2, state: "inbox" })],
      [{ action: "move" as const, to_state: "waiting" as const, waiting_for: "Finance" }, task({ revision: 2, state: "waiting", waiting_for: "Legal", waiting_since: "2026-01-02T00:00:00Z" })]
    ] as const;
    for (const [payload, response] of transitionCases) {
      expect(() => validateTaskResponse(response, "task-1", 1, { kind: "transition", payload }, true, "next"))
        .toThrow("invalid task acknowledgement");
    }
  });

  it("normalizes tag sets and nullable text in exact PATCH bodies", async () => {
    const update = vi.spyOn(apiClient, "updateTask")
      .mockResolvedValueOnce(task({ revision: 2, tag_ids: ["a", "z"] }))
      .mockResolvedValueOnce(task({ revision: 3, tag_ids: ["a", "z"], details: null }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    controller.change("tag_ids", ["z", "a", "z"]);
    await controller.whenIdle();
    controller.change("details", "");
    await controller.whenIdle();

    expect(update.mock.calls.map((call) => call[1])).toEqual([
      { tag_ids: ["a", "z"], expected_revision: 1 },
      { details: null, expected_revision: 2 }
    ]);
  });

  it("shares active controllers, supports delayed flush and subscriptions, and ignores stale synchronization", async () => {
    vi.useFakeTimers();
    const accepted = vi.fn();
    const update = vi.spyOn(apiClient, "updateTask").mockResolvedValue(task({ revision: 2, title: "Delayed" }));
    const controller = getTaskDetailAutosaveController("account-a", task(), accepted);
    const listener = vi.fn();
    const unsubscribe = controller.subscribe(listener);

    expect(getTaskDetailAutosaveController("account-a", task(), accepted)).toBe(controller);
    expect(controller.task).toEqual(task());
    controller.change("title", "Delayed", 100);
    expect(update).not.toHaveBeenCalled();
    controller.flush("title");
    await vi.runAllTimersAsync();
    await controller.whenIdle();

    expect(update).toHaveBeenCalledOnce();
    expect(accepted).toHaveBeenCalledWith(expect.objectContaining({ revision: 2, title: "Delayed" }));
    expect(listener).toHaveBeenCalled();
    unsubscribe();
    controller.sync(task({ id: "other-task", revision: 9 }));
    controller.sync(task({ revision: 1, title: "stale" }));
    controller.sync(task({ revision: 3, title: "Canonical", project_id: "project-1" }));
    expect(controller.getSnapshot()).toMatchObject({ baseline: { revision: 3, title: "Canonical" }, draft: { title: "Canonical", project_id: "project-1" } });
    controller.setOnAccepted(undefined);
    await controller.retryRefetch();
  });

  it("drops a corrupt persisted record and removes it instead of crashing", () => {
    const origin = "https://api.example.test/api";
    const key = taskAutosaveStorageKey("account-a", origin, "task-1");
    sessionStorage.setItem(key, "{not-valid-json");
    expect(loadTaskAutosaveRecovery("account-a", "task-1", origin)).toBeNull();
    expect(sessionStorage.getItem(key)).toBeNull();
  });

  it("rejects an incomplete storage identity", () => {
    expect(() => taskAutosaveStorageKey("", "origin", "task")).toThrow("incomplete");
    expect(() => taskAutosaveStorageKey("account-a", "", "task-1")).toThrow("incomplete");
  });

  it("clears a stale waiting_for when the task leaves the waiting list", async () => {
    const waitingTask = task({ state: "waiting", waiting_for: "Finance", waiting_since: "2026-01-01T00:00:00Z" });
    const transition = vi.spyOn(apiClient, "transitionTask").mockResolvedValue(task({ revision: 2, state: "next" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", waitingTask);
    controller.change("waiting_for", "New owner", 0);
    controller.change("state", "next", 0);
    await controller.whenIdle();
    expect(transition).toHaveBeenCalled();
    expect(controller.getSnapshot().draft.waiting_for).toBeNull();
    expect(controller.getSnapshot().dirtyFields).not.toContain("waiting_for");
  });

  it("does not dispatch a waiting transition without a waiting owner", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask");
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("state", "waiting", 0);
    await settle();
    expect(transition).not.toHaveBeenCalled();
  });

  it("binds the waiting_for generation when transitioning into waiting", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask").mockResolvedValue(
      task({ revision: 2, state: "waiting", waiting_for: "Finance", waiting_since: "2026-01-02T00:00:00Z" })
    );
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("waiting_for", "Finance", 0);
    controller.change("state", "waiting", 0);
    await controller.whenIdle();
    expect(transition).toHaveBeenCalledWith("task-1", { action: "move", to_state: "waiting", waiting_for: "Finance", expected_revision: 1 }, expect.any(String));
  });

  it("skips a blank title in a patch body", async () => {
    const update = vi.spyOn(apiClient, "updateTask").mockResolvedValue(task({ revision: 2, details: "changed" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "   ", 0);
    controller.change("details", "changed", 0);
    await settle();
    await settle();
    expect(update).toHaveBeenCalledWith("task-1", { details: "changed", expected_revision: 1 }, expect.any(String));
  });

  it("clears a dirty field that returns to its baseline value", async () => {
    const update = vi.spyOn(apiClient, "updateTask");
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "Changed", 0);
    controller.change("title", "Task", 0);
    await settle();
    expect(update).not.toHaveBeenCalled();
    expect(controller.getSnapshot().dirtyFields).not.toContain("title");
  });

  it("classifies a 401 failure as unauthorized without retry", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValueOnce(new ApiError("unauth", 401, {}));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "X", 0);
    await controller.whenPaused();
    expect(controller.getSnapshot()).toMatchObject({ error: { kind: "unauthorized", retryAllowed: false } });
  });

  it("classifies a 404 failure as unavailable without retry", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValueOnce(new ApiError("missing", 404, {}));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "Y", 0);
    await controller.whenPaused();
    expect(controller.getSnapshot()).toMatchObject({ error: { kind: "unavailable", retryAllowed: false } });
  });

  it("marks a contradictory canonical refetch as refetch-failed", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("conflict", 409, {}));
    vi.spyOn(apiClient, "getTask").mockResolvedValue(task({ revision: 1, title: "different same revision" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "Local", 0);
    await controller.whenPaused();
    expect(controller.getSnapshot()).toMatchObject({ status: "conflicted", conflict: { refetchFailed: true } });
  });

  it("keeps a conflict actionable when an explicit refetch also fails", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("conflict", 409, {}));
    const get = vi.spyOn(apiClient, "getTask").mockRejectedValue(new TypeError("offline"));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "Local", 0);
    await controller.whenPaused();
    expect(controller.getSnapshot()).toMatchObject({ conflict: { refetchFailed: true } });
    controller.retryRefetch();
    await settle();
    expect(get).toHaveBeenCalledTimes(2);
    expect(controller.getSnapshot()).toMatchObject({ conflict: { refetchFailed: true } });
  });

  it("does nothing when retrying a conflict with no refetched canonical task", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("conflict", 409, {}));
    vi.spyOn(apiClient, "getTask").mockRejectedValue(new TypeError("offline"));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "Local", 0);
    await controller.whenPaused();
    expect(controller.getSnapshot().conflict?.latestServerTask).toBeNull();
    controller.retry();
    await settle();
    expect(apiClient.updateTask).toHaveBeenCalledTimes(1);
  });

  it("rejects save with the failure message when the lane pauses on a definitive error", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("invalid", 422, { detail: "Bad input" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    await expect(controller.save({ kind: "patch", payload: { details: "x" } })).rejects.toThrow("Bad input");
  });

  it("routes a move-to-waiting transition with a waiting_for through the controller lane", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask").mockResolvedValue(
      task({ revision: 2, state: "waiting", waiting_for: "Finance", waiting_since: "2026-01-02T00:00:00Z" })
    );
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    const result = await controller.save({ kind: "transition", payload: { action: "move", to_state: "waiting", waiting_for: "Finance" } }, "move-key");
    expect(result.status).toBe("saved");
    expect(transition).toHaveBeenCalledWith("task-1", { action: "move", to_state: "waiting", waiting_for: "Finance", expected_revision: 1 }, "move-key");
  });

  it("replaces a stale controller whose recovery was cleared", () => {
    const first = getTaskDetailAutosaveController("account-a", "https://api.example.test/api", task(), vi.fn());
    first.change("title", "Dirty", 100);
    sessionStorage.clear();
    const second = getTaskDetailAutosaveController("account-a", "https://api.example.test/api", task(), vi.fn());
    expect(second).not.toBe(first);
  });

  it("falls back to a friendly message when the lane pauses on a non-Error rejection", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue("plain rejection");
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "X", 0);
    await controller.whenPaused();
    expect(controller.getSnapshot()).toMatchObject({ status: "failed", error: { message: "Couldn’t save changes" } });
  });

  it("does not retry an unauthorized failure", async () => {
    const update = vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("unauth", 401, {}));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    controller.change("title", "X", 0);
    await controller.whenPaused();
    controller.retry();
    await settle();
    expect(update).toHaveBeenCalledTimes(1);
  });

  it("routes a move transition without a waiting_for through the controller lane", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask").mockResolvedValue(task({ revision: 2, state: "someday" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());
    const result = await controller.save({ kind: "transition", payload: { action: "move", to_state: "someday" } }, "move-key");
    expect(result.status).toBe("saved");
    expect(transition).toHaveBeenCalledWith("task-1", { action: "move", to_state: "someday", expected_revision: 1 }, "move-key");
  });

  it("uses the fallback idempotency key and dispatches when a debounce expires", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("crypto", undefined);
    const update = vi.spyOn(apiClient, "updateTask").mockResolvedValue(task({ revision: 2, details: "Debounced" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    controller.change("details", "Debounced", 100);
    expect(update).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(100);
    await controller.whenIdle();

    expect(update).toHaveBeenCalledWith(
      "task-1",
      { details: "Debounced", expected_revision: 1 },
      expect.stringMatching(/^autosave-/)
    );
  });

  it("keeps saving in memory when session storage is unavailable", async () => {
    vi.stubGlobal("sessionStorage", undefined);
    const update = vi.spyOn(apiClient, "updateTask").mockResolvedValue(task({ revision: 2, title: "In memory" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    controller.change("title", "In memory", 0);
    await controller.whenIdle();

    expect(update).toHaveBeenCalledOnce();
    expect(controller.getSnapshot()).toMatchObject({ status: "saved", draft: { title: "In memory" } });
  });

  it("ignores conflict bookkeeping when Discard wins a pending canonical refetch", async () => {
    const canonical = task({ revision: 2, title: "Canonical" });
    const refetch = deferred<TaskResponse>();
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("conflict", 409, {}));
    const get = vi.spyOn(apiClient, "getTask").mockReturnValue(refetch.promise);
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    controller.change("title", "Local", 0);
    await settle();
    expect(get).toHaveBeenCalledOnce();
    controller.discard();
    refetch.resolve(canonical);
    await settle();

    expect(controller.getSnapshot()).toMatchObject({ conflict: null, baseline: { revision: 2, title: "Canonical" } });
  });

  it("ignores a pending canonical refetch failure after Discard", async () => {
    const refetch = deferred<TaskResponse>();
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("conflict", 409, {}));
    const get = vi.spyOn(apiClient, "getTask").mockReturnValue(refetch.promise);
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    controller.change("title", "Local", 0);
    await settle();
    expect(get).toHaveBeenCalledOnce();
    controller.discard();
    refetch.reject(new TypeError("offline"));
    await settle();

    expect(controller.getSnapshot()).toMatchObject({ conflict: null, status: "clean" });
  });

  it("returns conflict recovery helpers from the compatibility save API", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("conflict", 409, {}));
    vi.spyOn(apiClient, "getTask").mockResolvedValue(task({ revision: 2, title: "Canonical" }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    const result = await controller.save({ kind: "patch", payload: { title: "Local" } });

    expect(result.status).toBe("conflict");
    if (result.status === "conflict") {
      expect(result.task).toMatchObject({ revision: 2, title: "Canonical" });
      expect(result.discard()).toMatchObject({ revision: 2, title: "Canonical" });
    }
  });

  it("retries a terminal cancel barrier after a canonical conflict refetch", async () => {
    vi.spyOn(apiClient, "transitionTask")
      .mockRejectedValueOnce(new ApiError("stale", 409, {}))
      .mockResolvedValueOnce(task({ state: "cancelled", cancelled_at: "2026-01-02T00:00:00Z", revision: 3 }));
    vi.spyOn(apiClient, "getTask").mockResolvedValue(task({ revision: 2 }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    const result = await controller.save({ kind: "transition", payload: { action: "cancel" } });
    expect(result.status).toBe("conflict");
    if (result.status !== "conflict") throw new Error("Expected conflict result");
    await expect(result.retry()).resolves.toMatchObject({ status: "saved", task: { state: "cancelled", revision: 3 } });
    expect(apiClient.transitionTask).toHaveBeenLastCalledWith(
      "task-1",
      expect.objectContaining({ action: "cancel", expected_revision: 2 }),
      expect.any(String)
    );
  });

  it("treats a no-op waiting save as settled without inventing another mutation", async () => {
    const transition = vi.spyOn(apiClient, "transitionTask");
    const controller = createTaskDetailAutosaveController(
      "account-a",
      "https://api.example.test/api",
      task({ state: "waiting", waiting_for: "Bob" })
    );

    controller.change("waiting_for", "Bob", 0);
    await settle();

    expect(controller.getSnapshot().status).toBe("saved");
    expect(transition).not.toHaveBeenCalled();
  });

  it("normalizes a missing server tag collection to an empty editable set", () => {
    const controller = createTaskDetailAutosaveController(
      "account-a",
      "https://api.example.test/api",
      task({ tag_ids: null as unknown as string[] })
    );

    expect(controller.getSnapshot().draft.tag_ids).toEqual([]);
  });

  it("keeps non-terminal transition conflicts out of the terminal barrier queue", async () => {
    vi.spyOn(apiClient, "transitionTask").mockRejectedValue(new ApiError("stale", 409, {}));
    vi.spyOn(apiClient, "getTask").mockResolvedValue(task({ revision: 2 }));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    const result = await controller.save({ kind: "transition", payload: { action: "move", to_state: "inbox" } });

    if (result.status !== "conflict") throw new Error("Expected conflict result");
    result.discard();
  });

  it("returns the baseline task when conflict refetch cannot provide canonical data", async () => {
    vi.spyOn(apiClient, "updateTask").mockRejectedValue(new ApiError("stale", 409, {}));
    vi.spyOn(apiClient, "getTask").mockRejectedValue(new Error("canonical unavailable"));
    const controller = createTaskDetailAutosaveController("account-a", "https://api.example.test/api", task());

    const result = await controller.save({ kind: "patch", payload: { title: "Local" } });

    expect(result).toMatchObject({ status: "conflict", task: { title: "Task", revision: 1 } });
    if (result.status === "conflict") result.discard();
  });

  it("does not resume a recovered command after the user immediately discards it", async () => {
    const origin = "https://api.example.test/api";
    sessionStorage.setItem(taskAutosaveStorageKey("account-a", origin, "task-1"), JSON.stringify({
      version: 1,
      identity: { accountId: "account-a", apiOrigin: origin, taskId: "task-1" },
      baseline: task(),
      draft: draft({ title: "Recovered" }),
      dirty: { title: { baseValue: "Task", generation: 1, value: "Recovered" } },
      inFlight: { kind: "patch", body: { title: "Recovered", expected_revision: 1 }, generations: { title: 1 }, idempotencyKey: "recovered-key", attempt: 1 },
      barriers: [], status: "saving", conflict: null, error: null, retrying: false
    }));
    const update = vi.spyOn(apiClient, "updateTask");

    const controller = createTaskDetailAutosaveController("account-a", origin, task());
    controller.discardRecovery();
    await settle();

    expect(update).not.toHaveBeenCalled();
    expect(controller.getSnapshot()).toMatchObject({ status: "clean", dirtyFields: [] });
  });
});