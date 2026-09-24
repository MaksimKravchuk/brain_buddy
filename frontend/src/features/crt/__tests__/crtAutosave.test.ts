import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderHook, act } from "@testing-library/react";

import { ApiError } from "../../../api/client";
import { crtApi, type CrtTreeResponse } from "../../../api/crt";
import { nowMs, recordTelemetry } from "../../../utils/telemetry";
import { createGraphState, type GraphState } from "../graphModel";
import {
  applyReplayableCommands,
  createCrtAutosaveController,
  type CrtPersistenceResult,
  deriveReplayableCommands,
  graphToCrtUpdatePayload,
  treeToGraph,
  useCrtAutosave
} from "../crtAutosave";

vi.mock("../../../utils/telemetry", () => ({
  nowMs: vi.fn(),
  recordTelemetry: vi.fn()
}));

const telemetryClock = vi.mocked(nowMs);
const telemetryRecord = vi.mocked(recordTelemetry);

const metadata = {
  version: 1,
  created_at: "2026-09-20T09:00:00Z",
  updated_at: "2026-09-20T10:00:00Z",
  layout: { center: { x: 0, y: 0 }, zoom: 1 },
  owner_id: "owner-1"
};

function tree(revision = 1, label = "Canonical"): CrtTreeResponse {
  return {
    id: "tree-1",
    name: "CRT",
    revision,
    schema_version: 1,
    metadata: { ...metadata, updated_at: `2026-09-20T10:${String(revision).padStart(2, "0")}:00Z` },
    nodes: [{
      id: "node-1",
      label,
      type: "parent",
      position: { x: 0, y: 0 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    }],
    relations: [],
    owner_id: "owner-1"
  };
}

function graph(label: string, ui: Partial<GraphState> = {}): GraphState {
  return createGraphState({
    nodes: [{ id: "node-1", label, position: { x: 0, y: 0 } }],
    ...ui
  });
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void } {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

beforeEach(() => {
  telemetryClock.mockReturnValue(0);
  telemetryRecord.mockClear();
});

describe("CRT autosave immutable command queue", () => {
  it("019-SC-004 records one content-free success event for each immutable save", async () => {
    telemetryClock.mockReset().mockReturnValueOnce(100).mockReturnValueOnce(135);
    const update = vi.fn().mockResolvedValue(tree(2, "Saved label"));
    const controller = createCrtAutosaveController(tree(), update);

    await controller.schedule(graph("Local label"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();

    expect(telemetryRecord).toHaveBeenCalledTimes(1);
    expect(telemetryRecord).toHaveBeenCalledWith({
      name: "crt.save",
      durationMs: 35,
      details: { outcome: "success", revision: 2, replay: "initial" }
    });
    const serialized = JSON.stringify(telemetryRecord.mock.calls[0]);
    expect(serialized).not.toContain("Local label");
    expect(serialized).not.toContain("Saved label");
    expect(serialized).not.toContain("owner-1");
    expect(serialized).not.toContain("owner@example.test");
    expect(serialized).not.toContain("expected_revision");
    expect(serialized).not.toContain("idempotencyKey");
    expect(Object.keys(telemetryRecord.mock.calls[0]?.[0] ?? {}).sort()).toEqual(["details", "durationMs", "name"]);
    expect(Object.keys(telemetryRecord.mock.calls[0]?.[0]?.details ?? {}).sort()).toEqual(["outcome", "replay", "revision"]);
  });

  it("019-SC-004 records exactly one allowlisted conflict event with an available correlation ID", async () => {
    telemetryClock.mockReset().mockReturnValueOnce(200).mockReturnValueOnce(245);
    const update = vi.fn().mockRejectedValue(new ApiError(
      "Conflict",
      409,
      { detail: { reason: "stale_revision", label: "do not log" } },
      "corr-crt-1"
    ));
    const controller = createCrtAutosaveController(tree(), update);

    await controller.schedule(graph("Private graph label"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();

    expect(telemetryRecord).toHaveBeenCalledTimes(1);
    expect(telemetryRecord).toHaveBeenCalledWith({
      name: "crt.save",
      durationMs: 45,
      details: { outcome: "conflict", correlationId: "corr-crt-1", replay: "initial" }
    }, "warn");
    const serialized = JSON.stringify(telemetryRecord.mock.calls[0]);
    expect(serialized).not.toContain("Private graph label");
    expect(serialized).not.toContain("owner-1");
    expect(serialized).not.toContain("do not log");
    expect(serialized).not.toContain("expected_revision");
    expect(serialized).not.toContain("idempotencyKey");
  });

  it("019-SC-004 records failure and retry as one event per dispatched attempt", async () => {
    telemetryClock.mockReset().mockReturnValueOnce(300).mockReturnValueOnce(320).mockReturnValueOnce(400).mockReturnValueOnce(430);
    const update = vi.fn()
      .mockRejectedValueOnce(new Error("network body must not be logged"))
      .mockResolvedValueOnce(tree(2, "Retry result"));
    const controller = createCrtAutosaveController(tree(), update);

    await controller.schedule(graph("Failure label"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    controller.retry();
    await settle();

    expect(telemetryRecord).toHaveBeenCalledTimes(2);
    expect(telemetryRecord.mock.calls[0]).toEqual([{
      name: "crt.save",
      durationMs: 20,
      details: { outcome: "failure", replay: "initial" }
    }, "warn"]);
    expect(telemetryRecord.mock.calls[1]).toEqual([{
      name: "crt.save",
      durationMs: 30,
      details: { outcome: "success", revision: 2, replay: "retry" }
    }]);
    const serialized = JSON.stringify(telemetryRecord.mock.calls);
    expect(serialized).not.toContain("Failure label");
    expect(serialized).not.toContain("Retry result");
    expect(serialized).not.toContain("owner-1");
    expect(serialized).not.toContain("network body must not be logged");
    expect(serialized).not.toContain("idempotencyKey");
  });

  it("round-trips viewport pan and zoom through canonical payloads and replay commands", () => {
    const canonical = tree();
    const next = graph("Local", { viewportCenter: { x: 240, y: -80 }, viewportZoom: 0.65 });
    const payload = graphToCrtUpdatePayload(canonical, next);

    expect(payload.metadata.layout).toEqual({ center: { x: 240, y: -80 }, zoom: 0.65 });
    expect(treeToGraph({ ...canonical, metadata: { ...canonical.metadata, layout: payload.metadata.layout } }).viewportZoom).toBe(0.65);
    expect(treeToGraph(canonical).hasPersistedViewport).toBe(true);

    const commands = deriveReplayableCommands(graph("Canonical"), next);
    expect(commands).toContainEqual(expect.objectContaining({
      kind: "layout-change",
      payload: { layout: { center: { x: 240, y: -80 }, zoom: 0.65 } }
    }));
    expect(applyReplayableCommands(graph("Canonical"), commands)).toEqual(expect.objectContaining({
      viewportCenter: { x: 240, y: -80 },
      viewportZoom: 0.65
    }));
  });

  it("does not truncate replay commands when a queued edit exceeds the journal bound", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValue(first.promise);
    const base = createGraphState({ nodes: [] });
    const overflow = createGraphState({
      nodes: Array.from({ length: 101 }, (_, index) => ({
        id: `node-${index}`,
        label: `Node ${index}`,
        position: { x: index, y: index }
      }))
    });
    const controller = createCrtAutosaveController(tree(), update);

    controller.schedule(base);
    await vi.advanceTimersByTimeAsync(300);
    controller.schedule(overflow);
    await settle();

    expect(controller.status).toBe("Save failed");
    first.resolve(tree(2, "First"));
    await settle();
    expect(update).toHaveBeenCalledOnce();
    expect(controller.status).toBe("Save failed");
  });

  it("durably retains an overflow snapshot without dispatching it automatically", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValue(first.promise);
    const persistBeforeSave = vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false });
    const overflow = createGraphState({
      nodes: Array.from({ length: 101 }, (_, index) => ({ id: `node-${index}`, label: `Node ${index}`, position: { x: index, y: index } }))
    });
    const persistence = {
      persistBeforeSave,
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true, cleared: true, mode: "durable", online_only_risk: false })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    controller.schedule(createGraphState({ nodes: [] }));
    await vi.advanceTimersByTimeAsync(300);
    controller.schedule(overflow);
    first.resolve(tree(2, "First"));
    await settle();

    expect(update).toHaveBeenCalledOnce();
    expect(persistBeforeSave).toHaveBeenCalledTimes(2);
    expect(persistBeforeSave.mock.calls[1]?.[0]).toEqual(expect.objectContaining({
      graph: expect.objectContaining({ nodes: expect.arrayContaining([expect.objectContaining({ id: "node-100" })]) })
    }));
    expect(controller.status).toBe("Save failed");
  });

  it("recovers from an overflow latch when the newest queued edit is bounded", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(tree(3, "Bounded"));
    const base = createGraphState({ nodes: [] });
    const overflow = createGraphState({
      nodes: Array.from({ length: 101 }, (_, index) => ({ id: `node-${index}`, label: `Node ${index}`, position: { x: index, y: index } }))
    });
    const bounded = createGraphState({ nodes: [{ id: "node-0", label: "Bounded", position: { x: 0, y: 0 } }] });
    const controller = createCrtAutosaveController(tree(), update);

    controller.schedule(base);
    await vi.advanceTimersByTimeAsync(300);
    controller.schedule(overflow);
    controller.schedule(bounded);
    first.resolve(tree(2, "First"));
    await settle();

    expect(update).toHaveBeenCalledTimes(2);
    expect(update.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ expected_revision: 2, nodes: [expect.objectContaining({ label: "Bounded" })] }));
  });
  it("persists the immutable save attempt before PUT and clears only after visible canonical application", async () => {
    const update = vi.fn().mockResolvedValue(tree(2, "Local"));
    const persistGate = deferred<{ ok: true; generation: number; mode: "durable"; online_only_risk: false }>();
    const order: string[] = [];
    const persistence = {
      persistBeforeSave: vi.fn((request: unknown) => {
        order.push("persist");
        expect(request).toEqual(expect.objectContaining({
          idempotencyKey: expect.any(String),
          baseRevision: 1,
          graph: expect.objectContaining({ nodes: [expect.objectContaining({ label: "Local" })] })
        }));
        return persistGate.promise;
      }),
      clearAfterCanonicalApplied: vi.fn(async () => {
        order.push("clear");
        return { ok: true as const, cleared: true, mode: "durable" as const, online_only_risk: false };
      })
    };
    const onCanonical = vi.fn(() => { order.push("apply"); });
    const controller = createCrtAutosaveController(tree(), update, onCanonical, persistence);

    controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    expect(persistence.persistBeforeSave).toHaveBeenCalledOnce();
    expect(update).not.toHaveBeenCalled();

    persistGate.resolve({ ok: true, generation: 4, mode: "durable", online_only_risk: false });
    await settle();
    expect(update).toHaveBeenCalledOnce();
    await settle();
    expect(order).toEqual(["persist", "apply", "clear"]);
    expect(persistence.clearAfterCanonicalApplied).toHaveBeenCalledWith(expect.objectContaining({ revision: 2 }), true, 4);
  });

  it("does not abort an in-flight command and coalesces newer graph edits behind it", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(tree(3, "Second"));
    const controller = createCrtAutosaveController(tree(), update);

    controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    const firstPayload = update.mock.calls[0]?.[1];
    const firstSignal = update.mock.calls[0]?.[2]?.signal;
    controller.schedule(graph("Second"));

    expect(firstSignal?.aborted).toBe(false);
    expect(update).toHaveBeenCalledTimes(1);
    expect(firstPayload).toEqual(expect.objectContaining({ expected_revision: 1, nodes: [expect.objectContaining({ label: "First" })] }));

    first.resolve(tree(2, "First"));
    await settle();

    expect(update).toHaveBeenCalledTimes(2);
    expect(update.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ expected_revision: 2, nodes: [expect.objectContaining({ label: "Second" })] }));
    expect(update.mock.calls[1]?.[2]?.idempotencyKey).not.toBe(update.mock.calls[0]?.[2]?.idempotencyKey);
    expect(firstPayload).toEqual(expect.objectContaining({ expected_revision: 1, nodes: [expect.objectContaining({ label: "First" })] }));
  });

  it("replays a failed command with the exact frozen payload and idempotency key", async () => {
    const update = vi.fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(tree(2, "Local"));
    const controller = createCrtAutosaveController(tree(), update);

    controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    const firstPayload = update.mock.calls[0]?.[1];
    const firstOptions = update.mock.calls[0]?.[2];
    expect(Object.isFrozen(firstPayload)).toBe(true);

    controller.retry();
    await vi.advanceTimersByTimeAsync(300);
    await settle();

    expect(update).toHaveBeenCalledTimes(2);
    expect(update.mock.calls[1]?.[1]).toBe(firstPayload);
    expect(update.mock.calls[1]?.[2]?.idempotencyKey).toBe(firstOptions?.idempotencyKey);
    expect(update.mock.calls[1]?.[1]).toEqual(firstPayload);
  });

  it("keeps a failed command failed when only UI state changes", async () => {
    const failed = graph("Local");
    const update = vi.fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(tree(2, "Local"));
    const controller = createCrtAutosaveController(tree(), update);

    controller.schedule(failed);
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(controller.status).toBe("Save failed");

    controller.schedule({ ...failed, selectedNodeId: "node-1", editingNodeId: "node-1" });
    expect(controller.status).toBe("Save failed");
    await vi.advanceTimersByTimeAsync(1_000);
    expect(update).toHaveBeenCalledOnce();

    controller.retry();
    await settle();
    expect(update).toHaveBeenCalledTimes(2);
  });

  it("never regresses canonical content when an older response arrives", async () => {
    const request = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValue(request.promise);
    const controller = createCrtAutosaveController(tree(), update);

    controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    controller.syncCanonical(tree(5, "Newer server copy"));
    request.resolve(tree(2, "Older replay"));
    await settle();

    controller.schedule(graph("Next"));
    await vi.advanceTimersByTimeAsync(300);
    expect(update.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ expected_revision: 5 }));
  });

  it("turns stale revision and idempotency conflicts into explicit conflict without blind retry", async () => {
    const update = vi.fn().mockRejectedValue(new ApiError("Conflict", 409, { detail: { reason: "stale_revision" } }, "corr-1"));
    const controller = createCrtAutosaveController(tree(), update);
    const listener = vi.fn();
    controller.subscribe(listener);

    controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();

    expect(controller.status).toBe("Conflict");
    expect(controller.reference).toBe("corr-1");
    const calls = update.mock.calls.length;
    controller.retry();
    await vi.advanceTimersByTimeAsync(300);
    expect(update).toHaveBeenCalledTimes(calls);
    expect(listener).toHaveBeenLastCalledWith("Conflict", "corr-1");
  });

  it("ignores UI-only graph state changes when persisted content is canonical or already pending", async () => {
    const update = vi.fn().mockResolvedValue(tree(2, "Local"));
    const controller = createCrtAutosaveController(tree(), update);
    const canonicalGraph = graph("Canonical");

    controller.schedule({ ...canonicalGraph, selectedNodeId: "node-1", editingNodeId: "node-1" });
    await vi.advanceTimersByTimeAsync(300);
    expect(update).not.toHaveBeenCalled();
    expect(controller.status).toBe("Saved");

    controller.schedule(graph("Local"));
    controller.schedule({ ...graph("Local"), selectedNodeId: "node-1", selectedRelationId: "relation-1" });
    await vi.advanceTimersByTimeAsync(300);
    expect(update).toHaveBeenCalledOnce();
  });

  it("defers an incomplete inline card until its label is valid", async () => {
    const update = vi.fn().mockResolvedValue(tree(2, "Canonical"));
    const persistBeforeSave = vi.fn().mockResolvedValue({
      ok: true,
      generation: 1,
      mode: "durable",
      online_only_risk: false
    });
    const persistence = {
      persistBeforeSave,
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true, cleared: true, mode: "durable", online_only_risk: false })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);
    const incomplete = createGraphState({
      nodes: [
        { id: "node-1", label: "Canonical", position: { x: 0, y: 0 } },
        { id: "node-new", label: "", position: { x: 0, y: 100 } }
      ],
      editingNodeId: "node-new"
    });

    await controller.schedule(incomplete);
    await vi.advanceTimersByTimeAsync(300);
    await settle();

    expect(controller.status).toBe("Unsaved");
    expect(persistBeforeSave).not.toHaveBeenCalled();
    expect(update).not.toHaveBeenCalled();

    await controller.schedule({
      ...incomplete,
      nodes: incomplete.nodes.map((node) => node.id === "node-new" ? { ...node, label: "Valid cause" } : node),
      editingNodeId: null
    });
    await vi.advanceTimersByTimeAsync(300);
    await settle();

    expect(persistBeforeSave).toHaveBeenCalledOnce();
    expect(update).toHaveBeenCalledOnce();
  });

  it("keeps an incomplete queued card local across an active canonical response", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(tree(3, "Canonical"));
    const persistQueuedEdit = vi.fn();
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit,
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true, cleared: true, mode: "durable", online_only_risk: false })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const onCanonical = vi.fn();
    const controller = createCrtAutosaveController(tree(), update, onCanonical, persistence);
    const incomplete = createGraphState({
      nodes: [
        { id: "node-1", label: "First", position: { x: 0, y: 0 } },
        { id: "node-new", label: "", position: { x: 0, y: 100 } }
      ],
      editingNodeId: "node-new"
    });

    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(incomplete);
    first.resolve(tree(2, "First"));
    await settle();

    expect(persistQueuedEdit).not.toHaveBeenCalled();
    expect(onCanonical).not.toHaveBeenCalled();
    expect(controller.status).toBe("Unsaved");

    await controller.schedule({
      ...incomplete,
      nodes: incomplete.nodes.map((node) => node.id === "node-new" ? { ...node, label: "Valid queued cause" } : node),
      editingNodeId: null
    });
    await vi.advanceTimersByTimeAsync(300);
    await settle();

    expect(update).toHaveBeenCalledTimes(2);
    expect(update.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ expected_revision: 2 }));
  });

  it("does not cancel a dispatched command during dispose and suppresses late callbacks", async () => {
    const request = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValue(request.promise);
    const onCanonical = vi.fn();
    const controller = createCrtAutosaveController(tree(), update, onCanonical);

    controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    const signal = update.mock.calls[0]?.[2]?.signal;
    controller.dispose();
    expect(signal?.aborted).toBe(false);
    request.resolve(tree(2, "Local"));
    await settle();
    expect(onCanonical).not.toHaveBeenCalled();
  });

  it("does not dispatch a PUT when disposed during durable persistence", async () => {
    const persistenceGate = deferred<{ ok: true; generation: number; mode: "durable"; online_only_risk: false }>();
    const update = vi.fn().mockResolvedValue(tree(2, "Local"));
    const persistBeforeSave = vi.fn().mockReturnValue(persistenceGate.promise);
    const persistence = {
      persistBeforeSave,
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true, cleared: true, mode: "durable", online_only_risk: false })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    expect(persistBeforeSave).toHaveBeenCalledOnce();

    controller.dispose();
    persistenceGate.resolve({ ok: true, generation: 1, mode: "durable", online_only_risk: false });
    await settle();

    expect(update).not.toHaveBeenCalled();
  });

  it("durably persists the visible graph and stable replay commands before returning an edit behind an active save", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise);
    const queuedPersistence = vi.fn().mockResolvedValue({ ok: true, generation: 2, mode: "durable", online_only_risk: false });
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: queuedPersistence,
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true, cleared: true, mode: "durable", online_only_risk: false })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    controller.schedule(graph("Second"));
    await Promise.resolve();

    expect(queuedPersistence).toHaveBeenCalledOnce();
    expect(queuedPersistence.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      visibleGraph: expect.objectContaining({ nodes: [expect.objectContaining({ label: "Second" })] }),
      queuedCommands: expect.arrayContaining([
        expect.objectContaining({ kind: "label-edit", payload: { node_id: "node-1", label: "Second" } })
      ])
    }));
    first.resolve(tree(2, "First"));
  });

  it("waits for equivalent queued durability before clearing it and reporting Saved", async () => {
    const first = deferred<CrtTreeResponse>();
    const queuedGate = deferred<CrtPersistenceResult>();
    const clearGate = deferred<{
      ok: true;
      cleared: true;
      mode: "durable";
      online_only_risk: false;
    }>();
    const update = vi.fn().mockReturnValueOnce(first.promise);
    const clearAfterCanonicalApplied = vi.fn().mockReturnValue(clearGate.promise);
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockReturnValue(queuedGate.promise),
      clearAfterCanonicalApplied
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    const queuedSchedule = controller.schedule(graph("Second"));
    first.resolve(tree(2, "Second"));
    await settle();

    expect(clearAfterCanonicalApplied).not.toHaveBeenCalled();
    expect(controller.status).toBe("Saving");

    queuedGate.resolve({ ok: true, generation: 2, mode: "durable", online_only_risk: false });
    await queuedSchedule;
    await settle();

    expect(clearAfterCanonicalApplied).toHaveBeenCalledWith(expect.objectContaining({ revision: 2 }), true, 2);
    expect(controller.status).toBe("Saving");

    clearGate.resolve({ ok: true, cleared: true, mode: "durable", online_only_risk: false });
    await settle();

    expect(controller.status).toBe("Saved");
  });

  it("does not dispatch a queued edit after durable queue persistence fails", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise);
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockResolvedValue({ ok: false, reason: "persistence-failed", mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true, cleared: true, mode: "durable", online_only_risk: false })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    controller.schedule(graph("Second"));
    await settle();
    first.resolve(tree(2, "First"));
    await settle();

    expect(update).toHaveBeenCalledOnce();
    expect(controller.status).toBe("Save failed");
  });

  it("019-SC-004 keeps the newest edit after an active durable save fails", async () => {
    const activePersistence = deferred<CrtPersistenceResult>();
    const update = vi.fn().mockResolvedValueOnce(tree(3, "C"));
    const persistence = {
      persistBeforeSave: vi.fn()
        .mockReturnValueOnce(activePersistence.promise)
        .mockResolvedValue({ ok: true, generation: 3, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockResolvedValue({ ok: true, generation: 2, mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    await controller.schedule(graph("A"));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(graph("B"));
    activePersistence.resolve({ ok: false, reason: "persistence-failed", mode: "durable", online_only_risk: false });
    await settle();

    await controller.schedule(graph("C"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    await settle();

    expect(update).toHaveBeenCalledOnce();
    expect(update.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      nodes: [expect.objectContaining({ label: "C" })]
    }));
  });

  it("derives and applies every replay command kind, including missing-entity no-ops", () => {
    const base = createGraphState({
      nodes: [
        { id: "delete", label: "Delete", position: { x: 0, y: 0 } },
        { id: "edit", label: "Old", position: { x: 1, y: 1 } },
        { id: "stay", label: "Stay", position: { x: 2, y: 2 } }
      ],
      relations: [{ id: "old-rel", sourceId: "edit", targetId: "stay" }]
    });
    const next = createGraphState({
      nodes: [
        { id: "edit", label: "New", position: { x: 4, y: 5 } },
        { id: "stay", label: "Stay", position: { x: 2, y: 2 } },
        { id: "created", label: "Created", position: { x: 8, y: 9 } }
      ],
      relations: [{ id: "new-rel", sourceId: "created", targetId: "stay" }],
      viewportCenter: { x: 3, y: 4 },
      viewportZoom: 0.5
    });
    const commands = deriveReplayableCommands(base, next, 0.75);
    expect(commands.map((command) => command.kind)).toEqual(expect.arrayContaining([
      "card-delete", "label-edit", "card-move", "card-create", "relation-delete", "relation-create", "layout-change"
    ]));
    const retainedRelation = deriveReplayableCommands(base, createGraphState({
      ...next,
      relations: [...base.relations]
    }));
    expect(retainedRelation.some((command) => command.kind === "relation-delete")).toBe(false);
    expect(applyReplayableCommands(base, [
      { id: "0", kind: "card-create", payload: { node_id: "created", label: "Created", position: { x: 1, y: 1 } } },
      { id: "1", kind: "label-edit", payload: { node_id: "edit", label: "Edited" } },
      { id: "2", kind: "card-move", payload: { node_id: "edit", position: { x: 3, y: 3 } } },
      { id: "3", kind: "relation-create", payload: { relation_id: "new", source_node_id: "created", target_node_id: "edit" } },
      { id: "4", kind: "layout-change", payload: { layout: { center: { x: 4, y: 5 }, zoom: 0.7 } } },
      { id: "5", kind: "relation-delete", payload: { relation_id: "old-rel" } },
      { id: "6", kind: "card-delete", payload: { node_id: "delete", confirmed: true } },
      { id: "7", kind: "tree-rename", payload: { name: "Renamed" } }
    ])).toEqual(expect.objectContaining({ viewportCenter: { x: 4, y: 5 }, viewportZoom: 0.7 }));
    expect(applyReplayableCommands(base, [
      { id: "8", kind: "label-edit", payload: { node_id: "missing", label: "x" } },
      { id: "2", kind: "card-move", payload: { node_id: "missing", position: { x: 0, y: 0 } } },
      { id: "3", kind: "card-delete", payload: { node_id: "missing", confirmed: true } },
      { id: "4", kind: "tree-rename", payload: { name: "Renamed" } },
      { id: "5", kind: "relation-delete", payload: { relation_id: "missing" } }
    ])).toEqual(expect.objectContaining({ nodes: expect.any(Array), relations: expect.any(Array) }));
  });

  it("covers graph conversion defaults, relation timestamps, selection filtering, and zoom bounds", () => {
    const canonical = { ...tree(), metadata: { ...tree().metadata, layout: undefined } } as unknown as CrtTreeResponse;
    const graphState = createGraphState({
      nodes: [{ id: "node-1", label: "Updated", position: { x: 1, y: 2 } }],
      relations: [{ id: "new-rel", sourceId: "node-1", targetId: "node-1" }],
      viewportCenter: { x: 9, y: 8 },
      viewportZoom: 0.4
    });
    const timestamps = new Map<string, string>();
    const first = graphToCrtUpdatePayload(canonical, graphState, 4, timestamps);
    const second = graphToCrtUpdatePayload(canonical, graphState, 4, timestamps);
    expect(first.metadata.layout).toEqual({ center: { x: 9, y: 8 }, zoom: 0.4 });
    expect(first.relations).toHaveLength(1);
    expect(second.relations?.[0]?.created_at).toBe(first.relations?.[0]?.created_at);
    expect(treeToGraph({ ...canonical, metadata: { ...canonical.metadata, layout: { center: { x: 1, y: 2 }, zoom: 99 } } }, {
      ...graphState, selectedNodeId: "missing", editingNodeId: "missing", selectedRelationId: "missing"
    })).toEqual(expect.objectContaining({ selectedNodeId: null, editingNodeId: null, selectedRelationId: null, viewportZoom: 1 }));
    expect(treeToGraph({ ...canonical, metadata: { ...canonical.metadata, layout: { center: { x: 1, y: 2 }, zoom: -1 } } }).viewportZoom).toBe(0.25);
    expect(treeToGraph({ ...canonical, metadata: { ...canonical.metadata, layout: { center: { x: "bad", y: 2 }, zoom: Number.NaN } } }).viewportCenter).toEqual({ x: 0, y: 0 });
    expect(treeToGraph({ ...canonical, nodes: [], relations: [] }).selectedNodeId).toBeNull();
  });

  it("uses deterministic fallbacks when random UUID generation throws", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => { throw new Error("no uuid"); } });
    const commands = deriveReplayableCommands(createGraphState({ nodes: [] }), graph("Generated"));
    expect(commands[0]?.id).toMatch(/^00000000-0000-4000-8000-/);
    const update = vi.fn().mockResolvedValue(tree(2, "Generated"));
    const controller = createCrtAutosaveController(tree(), update);
    await controller.schedule(graph("Generated"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(update.mock.calls[0]?.[2]?.idempotencyKey).toMatch(/^00000000-0000-4000-8000-/);
    vi.unstubAllGlobals();
  });

  it("keeps durable persistence failures offline, but allows online-only persistence to dispatch", async () => {
    const durable = {
      persistBeforeSave: vi.fn().mockRejectedValue(new Error("disk")),
      clearAfterCanonicalApplied: vi.fn()
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const durableUpdate = vi.fn().mockResolvedValue(tree(2, "Local"));
    const failed = createCrtAutosaveController(tree(), durableUpdate, undefined, durable);
    await failed.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(durableUpdate).not.toHaveBeenCalled();
    expect(failed.status).toBe("Save failed");
    expect(telemetryRecord).toHaveBeenLastCalledWith({
      name: "crt.save",
      durationMs: expect.any(Number),
      details: {
        outcome: "failure",
        replay: "initial",
        storage: "durable",
        failureReason: "persistence-failed"
      }
    }, "warn");

    const online = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: false, reason: "storage-unavailable", mode: "online-only", online_only_risk: true }),
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const onlineUpdate = vi.fn().mockResolvedValue(tree(2, "Local"));
    const allowed = createCrtAutosaveController(tree(), onlineUpdate, undefined, online);
    await allowed.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(onlineUpdate).toHaveBeenCalledOnce();
  });

  it("covers non-conflict ApiErrors, unknown conflict details, and clear failures", async () => {
    const errors = [
      new ApiError("bad request", 400, { detail: "bad" }, "corr-400"),
      new ApiError("unknown conflict", 409, { detail: { reason: "other" } }, "corr-409")
    ];
    for (const error of errors) {
      const update = vi.fn().mockRejectedValue(error);
      const controller = createCrtAutosaveController(tree(), update);
      await controller.schedule(graph("Local"));
      await vi.advanceTimersByTimeAsync(300);
      await settle();
      expect(controller.status).toBe("Save failed");
      expect(controller.reference).toBe(error.correlationId);
    }
    const clear = vi.fn().mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    const controller = createCrtAutosaveController(tree(), vi.fn().mockResolvedValue(tree(2, "Local")), undefined, {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied: clear
    });
    await controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(controller.status).toBe("Save failed");
    expect(clear).toHaveBeenCalledOnce();
  });

  it("covers queued persistence fallback, queue coalescing, and queued clear paths", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(tree(3, "Second"));
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true }),
      persistQueuedEdit: vi.fn().mockResolvedValue({ ok: true, generation: 2, mode: "durable", online_only_risk: false })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);
    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(graph("First"));
    await controller.schedule(graph("Second"));
    await controller.schedule(graph("Second"));
    first.resolve(tree(2, "First"));
    await settle();
    await settle();
    await settle();
    expect(update).toHaveBeenCalledTimes(2);
    expect(persistence?.persistQueuedEdit).toHaveBeenCalled();
    expect(controller.status).toBe("Saved");
  });

  it("rebases conflicts, ignores stale canonical responses, and supports listener replacement", async () => {
    const update = vi.fn().mockRejectedValue(new ApiError("Conflict", 409, { detail: { reason: "idempotency_conflict" } }, "corr"));
    const onCanonical = vi.fn();
    const replacement = vi.fn();
    const controller = createCrtAutosaveController(tree(), update, onCanonical);
    controller.setOnCanonical(replacement);
    await controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(controller.conflict).toEqual({ reason: "idempotency_conflict", reference: "corr" });
    await controller.schedule(graph("Local"));
    controller.syncCanonical({ ...tree(), id: "other", revision: 99 });
    controller.syncCanonical(tree(2, "Local"));
    controller.rebase();
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(update).toHaveBeenCalledTimes(1);
    expect(replacement).toHaveBeenCalledOnce();
    controller.dispose();
    controller.rebase();
    controller.retry();
    await controller.schedule(graph("Ignored"));
    expect(replacement).toHaveBeenCalledTimes(1);
  });

  it("does not reapply an unchanged canonical tree when persistence recreates the hook controller", async () => {
    const canonical = tree();
    const onCanonical = vi.fn();
    const persistence = () => ({
      persistBeforeSave: vi.fn(),
      clearAfterCanonicalApplied: vi.fn()
    } as unknown as Parameters<typeof createCrtAutosaveController>[3]);
    const hook = renderHook(({ adapter }) => useCrtAutosave(canonical, onCanonical, adapter), {
      initialProps: { adapter: persistence() }
    });
    await act(async () => { await Promise.resolve(); });
    onCanonical.mockClear();

    hook.rerender({
      adapter: persistence()
    });
    await act(async () => { await Promise.resolve(); });

    expect(onCanonical).not.toHaveBeenCalled();
    hook.unmount();
  });

  it("clears an overflow snapshot when the canonical response already contains it", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValue(first.promise);
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);
    const base = createGraphState({ nodes: [] });
    const overflow = createGraphState({ nodes: Array.from({ length: 101 }, (_, index) => ({ id: `node-${index}`, label: `Node ${index}`, position: { x: index, y: index } })) });
    await controller.schedule(base);
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(overflow);
    const canonical = {
      ...tree(2, "Canonical"),
      nodes: overflow.nodes.map((node) => ({ id: node.id, label: node.label, type: "child" as const, position: node.position, highlight_state: "none" as const, relation_counts: { up_count: 0, down_count: 0 } }))
    };
    first.resolve(canonical);
    await settle();
    expect(persistence?.clearAfterCanonicalApplied).toHaveBeenCalled();
  });

  it("retains queued edits when queued persistence throws and rebase dispatches changed content", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(tree(3, "Rebased"));
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockRejectedValue(new Error("queue disk")),
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);
    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(graph("Queued"));
    await settle();
    first.resolve(tree(2, "First"));
    await settle();
    expect(update).toHaveBeenCalledOnce();
    expect(controller.status).toBe("Save failed");

    const conflictUpdate = vi.fn()
      .mockRejectedValueOnce(new ApiError("Conflict", 409, { detail: { reason: "stale_revision" } }, "rebase"))
      .mockResolvedValueOnce(tree(3, "Rebased"));
    const rebased = createCrtAutosaveController(tree(), conflictUpdate);
    await rebased.schedule(graph("Rebased"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    rebased.rebase();
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(conflictUpdate).toHaveBeenCalledTimes(2);
  });

  it("covers guards, disposed scheduling, subscriptions, and React hook lifecycle", async () => {
    const controller = createCrtAutosaveController(tree(), vi.fn());
    const listener = vi.fn();
    const unsubscribe = controller.subscribe(listener);
    unsubscribe();
    controller.retry();
    controller.rebase();
    controller.dispose();
    controller.dispose();
    await controller.schedule(graph("Ignored"));
    expect(listener).not.toHaveBeenCalled();

    const canonical = vi.fn();
    const { result, rerender, unmount } = renderHook(({ currentTree }) => {
      return useCrtAutosave(currentTree, canonical);
    }, { initialProps: { currentTree: null as CrtTreeResponse | null } });
    expect(result.current.status).toBe("Saved");
    rerender({ currentTree: tree() });
    await act(async () => { await result.current.schedule(graph("Hook")); });
    expect(result.current.status).toBe("Unsaved");
    result.current.retry();
    result.current.rebase();
    unmount();
  });

  it("covers relation conversion, canonical guards, status notifications, and hook callback replacement", async () => {
    const initialNode = tree().nodes[0];
    if (!initialNode) throw new Error("test tree is missing its fixture node");
    const canonical = {
      ...tree(),
      nodes: [
        initialNode,
        {
          id: "node-2",
          label: "Effect",
          type: "child" as const,
          position: { x: 4, y: 5 },
          highlight_state: "none" as const,
          relation_counts: { up_count: 1, down_count: 0 }
        }
      ],
      relations: [{ id: "relation-1", source_node_id: "node-1", target_node_id: "node-2", kind: "why" as const, created_at: "2026-09-20T10:00:00Z" }]
    };
    const current = graph("Canonical", {
      nodes: [
        { id: "node-1", label: "Canonical", position: { x: 0, y: 0 } },
        { id: "node-2", label: "Effect", position: { x: 4, y: 5 } }
      ],
      relations: [{ id: "relation-1", sourceId: "node-1", targetId: "node-2" }],
      selectedNodeId: "node-1",
      editingNodeId: "node-1",
      selectedRelationId: "relation-1"
    });
    expect(graphToCrtUpdatePayload(canonical, current).relations).toEqual([expect.objectContaining({ kind: "why", created_at: "2026-09-20T10:00:00Z" })]);
    expect(treeToGraph(canonical, current)).toEqual(expect.objectContaining({ selectedNodeId: "node-1", editingNodeId: "node-1", selectedRelationId: "relation-1" }));

    const update = vi.fn().mockResolvedValue(tree(2, "Local"));
    const controller = createCrtAutosaveController(tree(), update);
    const listener = vi.fn();
    controller.subscribe(listener);
    await controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(listener).toHaveBeenCalledWith("Saving", undefined);
    controller.syncCanonical(tree(0, "Old"));
    controller.syncCanonical(tree(1, "Different"));

    const canonicalCallback = vi.fn();
    const replacementCallback = vi.fn();
    const hook = renderHook(({ currentTree, callback }) => useCrtAutosave(currentTree, callback), {
      initialProps: { currentTree: null as CrtTreeResponse | null, callback: canonicalCallback }
    });
    hook.rerender({ currentTree: tree(), callback: replacementCallback });
    act(() => hook.result.current.syncCanonical(tree(2, "Server")));
    expect(replacementCallback).toHaveBeenCalledWith(expect.objectContaining({ revision: 2, nodes: [expect.objectContaining({ label: "Server" })] }));
    hook.unmount();
  });

  it("covers queued canonical no-ops, overflow cleanup failure, and overflow persistence throws", async () => {
    const first = deferred<CrtTreeResponse>();
    const clearAfterCanonicalApplied = vi.fn().mockResolvedValue({ ok: true });
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockResolvedValue({ ok: true, generation: 2, mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const queued = createCrtAutosaveController(tree(), vi.fn().mockReturnValueOnce(first.promise), undefined, persistence);
    await queued.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await queued.schedule(graph("Canonical"));
    first.resolve(tree(2, "Canonical"));
    await settle();
    await settle();
    expect(clearAfterCanonicalApplied).toHaveBeenCalled();
    expect(queued.status).toBe("Saved");

    const overflow = createGraphState({ nodes: Array.from({ length: 101 }, (_, index) => ({ id: `node-${index}`, label: `Node ${index}`, position: { x: index, y: index } })) });
    const overflowCanonical: CrtTreeResponse = {
      ...tree(2, "Overflow"),
      nodes: overflow.nodes.map((node) => ({ id: node.id, label: node.label, type: "child" as const, position: node.position, highlight_state: "none" as const, relation_counts: { up_count: 0, down_count: 0 } }))
    };
    const clearFailure = vi.fn().mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    const overflowPersistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied: clearFailure
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const overflowRequest = deferred<CrtTreeResponse>();
    const overflowController = createCrtAutosaveController(tree(), vi.fn().mockReturnValue(overflowRequest.promise), undefined, overflowPersistence);
    await overflowController.schedule(createGraphState({ nodes: [] }));
    await vi.advanceTimersByTimeAsync(300);
    await overflowController.schedule(overflow);
    overflowRequest.resolve(overflowCanonical);
    await settle();
    expect(clearFailure).toHaveBeenCalled();
    expect(overflowController.status).toBe("Save failed");

    const throwingPersistence = {
      persistBeforeSave: vi.fn()
        .mockResolvedValueOnce({ ok: true, generation: 1, mode: "durable", online_only_risk: false })
        .mockRejectedValueOnce(new Error("queue disk")),
      clearAfterCanonicalApplied: vi.fn()
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const throwingRequest = deferred<CrtTreeResponse>();
    const throwingController = createCrtAutosaveController(tree(), vi.fn().mockReturnValue(throwingRequest.promise), undefined, throwingPersistence);
    await throwingController.schedule(createGraphState({ nodes: [] }));
    await vi.advanceTimersByTimeAsync(300);
    await throwingController.schedule(overflow);
    throwingRequest.resolve(tree(2, "First"));
    await settle();
    expect(throwingController.status).toBe("Save failed");
    expect(throwingPersistence?.persistBeforeSave).toHaveBeenCalledTimes(2);

    const falsePersist = {
      persistBeforeSave: vi.fn()
        .mockResolvedValueOnce({ ok: true, generation: 1, mode: "durable", online_only_risk: false })
        .mockResolvedValueOnce({ ok: false, reason: "disk", mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied: vi.fn()
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const falseRequest = deferred<CrtTreeResponse>();
    const falseController = createCrtAutosaveController(tree(), vi.fn().mockReturnValue(falseRequest.promise), undefined, falsePersist);
    await falseController.schedule(createGraphState({ nodes: [] }));
    await vi.advanceTimersByTimeAsync(300);
    await falseController.schedule(overflow);
    falseRequest.resolve(tree(2, "First"));
    await settle();
    expect(falseController.status).toBe("Save failed");
  });

  it("covers default update, retry persistence, conflict payload shapes, and null-hook guards", async () => {
    const update = vi.spyOn(crtApi, "updateCrtTree").mockResolvedValue(tree(2, "Default"));
    const defaultController = createCrtAutosaveController(tree());
    await defaultController.schedule(graph("Default"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(update).toHaveBeenCalledOnce();

    const retryPersistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistRetry: vi.fn().mockResolvedValue({ ok: true, generation: 2, mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const retryUpdate = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(tree(2, "Retry"));
    const retryController = createCrtAutosaveController(tree(), retryUpdate, undefined, retryPersistence);
    await retryController.schedule(graph("Retry"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    retryController.retry();
    await settle();
    expect(retryPersistence?.persistRetry).toHaveBeenCalledOnce();

    for (const payload of [{ reason: "stale_revision" }, { detail: { reason: "idempotency_conflict" } }, null]) {
      const conflictUpdate = vi.fn().mockRejectedValue(new ApiError("Conflict", 409, payload, "shape"));
      const conflictController = createCrtAutosaveController(tree(), conflictUpdate);
      await conflictController.schedule(graph("Conflict"));
      await vi.advanceTimersByTimeAsync(300);
      await settle();
      expect(conflictController.status).toBe(payload === null ? "Save failed" : "Conflict");
    }

    const nullHook = renderHook(() => useCrtAutosave(null, vi.fn()));
    await act(async () => { await nullHook.result.current.schedule(graph("Ignored")); });
    nullHook.result.current.syncCanonical(tree(2, "Ignored"));
    nullHook.unmount();

    vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000099" });
    expect(deriveReplayableCommands(createGraphState({ nodes: [] }), graph("UUID"))[0]?.id).toBe("00000000-0000-4000-8000-000000000099");
    const guard = createCrtAutosaveController(tree());
    const guardNode = tree().nodes[0];
    if (!guardNode) throw new Error("test tree is missing its fixture node");
    guard.syncCanonical({ ...tree(), nodes: [{ ...guardNode, label: "same revision, different content" }] });
    const durableFailure = createCrtAutosaveController(tree(), vi.fn(), undefined, {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: false, reason: "disk", mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied: vi.fn()
    });
    await durableFailure.schedule(graph("Durable failure"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(durableFailure.status).toBe("Save failed");
  });

  it("uses the online-only fallback for an undefined queued persistence result and cancels timers on dispose", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(tree(3, "Second"));
    const onModeChange = vi.fn();
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockResolvedValue(undefined),
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true }),
      onModeChange
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);
    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(graph("Second"));
    first.resolve(tree(2, "First"));
    await settle();
    await settle();
    expect(update).toHaveBeenCalledTimes(2);
    expect(onModeChange).toHaveBeenCalledWith("online-only", true);

    const disposed = createCrtAutosaveController(tree(), vi.fn());
    await disposed.schedule(graph("Timer"));
    disposed.dispose();
    await vi.advanceTimersByTimeAsync(300);
    expect(disposed.status).toBe("Unsaved");
  });

  it("covers UUID absence, retry guards, queued no-persistence completion, and optional canonical callbacks", async () => {
    vi.stubGlobal("crypto", {});
    const generated = deriveReplayableCommands(createGraphState({ nodes: [] }), graph("Generated"));
    expect(generated[0]?.id).toMatch(/^00000000-0000-4000-8000-/);
    const update = vi.fn().mockResolvedValue(tree(2, "Generated"));
    const controller = createCrtAutosaveController(tree(), update);
    controller.retry();
    controller.setOnCanonical(undefined);
    await controller.schedule(graph("Generated"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(update).toHaveBeenCalledOnce();
    controller.dispose();
    controller.retry();
    vi.unstubAllGlobals();

    const first = deferred<CrtTreeResponse>();
    const queuedUpdate = vi.fn().mockReturnValueOnce(first.promise);
    const queued = createCrtAutosaveController(tree(), queuedUpdate);
    await queued.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await queued.schedule(graph("Second"));
    first.resolve(tree(2, "Second"));
    await settle();
    expect(queuedUpdate).toHaveBeenCalledOnce();
    expect(queued.status).toBe("Saved");
  });

  it("stops after disposal while a durable persistence promise resolves", async () => {
    const gate = deferred<{ ok: true; generation: number; mode: "durable"; online_only_risk: false }>();
    const update = vi.fn().mockResolvedValue(tree(2, "Local"));
    const controller = createCrtAutosaveController(tree(), update, undefined, {
      persistBeforeSave: vi.fn().mockReturnValue(gate.promise),
      clearAfterCanonicalApplied: vi.fn()
    });
    await controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    controller.dispose();
    gate.resolve({ ok: true, generation: 1, mode: "durable", online_only_risk: false });
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
    expect(update).not.toHaveBeenCalled();
  });

  it("clears a bounded overflow edit without persistence when the response is already canonical", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValue(first.promise);
    const overflow = createGraphState({ nodes: Array.from({ length: 101 }, (_, index) => ({ id: `overflow-${index}`, label: `Overflow ${index}`, position: { x: index, y: index } })) });
    const controller = createCrtAutosaveController(tree(), update);
    await controller.schedule(createGraphState({ nodes: [] }));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(overflow);
    first.resolve({
      ...tree(2, "Canonical overflow"),
      nodes: overflow.nodes.map((node) => ({ id: node.id, label: node.label, type: "child" as const, position: node.position, highlight_state: "none" as const, relation_counts: { up_count: 0, down_count: 0 } }))
    });
    await settle();
    expect(update).toHaveBeenCalledOnce();
    expect(controller.status).toBe("Saved");
  });

  it("suppresses status listeners when queued persistence finishes after disposal", async () => {
    const first = deferred<CrtTreeResponse>();
    const queuedGate = deferred<{ ok: false; reason: string; mode: "durable"; online_only_risk: false }>();
    const update = vi.fn().mockReturnValue(first.promise);
    const listener = vi.fn();
    const controller = createCrtAutosaveController(tree(), update, undefined, {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockReturnValue(queuedGate.promise),
      clearAfterCanonicalApplied: vi.fn()
    });
    controller.subscribe(listener);
    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    void controller.schedule(graph("Second"));
    await Promise.resolve();
    controller.dispose();
    queuedGate.resolve({ ok: false, reason: "disk", mode: "durable", online_only_risk: false });
    first.resolve(tree(2, "First"));
    await settle();
    expect(update).toHaveBeenCalledOnce();
  });

  it("ignores a stale debounce callback after its pending graph was cleared", async () => {
    let captured: (() => void) | undefined;
    const timer = vi.spyOn(globalThis, "setTimeout").mockImplementation(((handler: () => void) => {
      captured = handler;
      return 1 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout);
    const controller = createCrtAutosaveController(tree(), vi.fn());
    await controller.schedule(graph("Pending"));
    await controller.schedule(graph("Canonical"));
    captured?.();
    expect(controller.status).toBe("Saved");
    timer.mockRestore();
  });

  it("stops a save when a status observer disposes during dispatch", async () => {
    const gate = deferred<{ ok: true; generation: number; mode: "durable"; online_only_risk: false }>();
    const update = vi.fn();
    const controller = createCrtAutosaveController(tree(), update, undefined, {
      persistBeforeSave: vi.fn().mockReturnValue(gate.promise),
      clearAfterCanonicalApplied: vi.fn()
    });
    controller.subscribe((status) => { if (status === "Saving") controller.dispose(); });
    await controller.schedule(graph("Observed"));
    await vi.advanceTimersByTimeAsync(300);
    gate.resolve({ ok: true, generation: 1, mode: "durable", online_only_risk: false });
    await settle();
    expect(update).not.toHaveBeenCalled();
  });

  it("suppresses a durable persistence failure after disposal", async () => {
    const gate = deferred<CrtPersistenceResult>();
    const update = vi.fn();
    const controller = createCrtAutosaveController(tree(), update, undefined, {
      persistBeforeSave: vi.fn().mockReturnValue(gate.promise),
      clearAfterCanonicalApplied: vi.fn()
    });

    await controller.schedule(graph("Disposed failure"));
    await vi.advanceTimersByTimeAsync(300);
    controller.dispose();
    gate.resolve({ ok: false, reason: "disk", mode: "durable", online_only_risk: false });
    await settle();

    expect(update).not.toHaveBeenCalled();
  });

  it("preserves an undefined conflict correlation reference", async () => {
    const update = vi.fn().mockRejectedValue(
      new ApiError("Conflict", 409, { detail: { reason: "stale_revision" } })
    );
    const controller = createCrtAutosaveController(tree(), update);

    await controller.schedule(graph("Conflict without reference"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();

    expect(controller.status).toBe("Conflict");
    expect(controller.reference).toBeUndefined();
  });

  it("dispatches a pending command from the post-save debounce callback", async () => {
    const update = vi.fn()
      .mockResolvedValueOnce(tree(2, "Server normalized"))
      .mockResolvedValueOnce(tree(3, "Local"));
    const controller = createCrtAutosaveController(tree(), update);

    await controller.schedule(graph("Local"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(controller.status).toBe("Unsaved");

    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(update).toHaveBeenCalledTimes(2);
  });

  it("does not dispatch queued work after canonical delivery disposes the controller", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise);
    const controller = createCrtAutosaveController(tree(), update, () => controller.dispose());

    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(graph("Second"));
    first.resolve(tree(2, "First"));
    await settle();

    expect(update).toHaveBeenCalledOnce();
  });

  it("ignores a cleared post-save debounce callback", async () => {
    let callback: (() => void) | undefined;
    const timer = vi.spyOn(globalThis, "setTimeout").mockImplementation(((handler: () => void) => {
      callback = handler;
      return 1 as unknown as ReturnType<typeof setTimeout>;
    }) as typeof setTimeout);
    const update = vi.fn().mockResolvedValue(tree(2, "Server normalized"));
    const controller = createCrtAutosaveController(tree(), update);

    await controller.schedule(graph("Local"));
    callback?.();
    await settle();
    await controller.schedule(graph("Server normalized"));
    callback?.();

    expect(update).toHaveBeenCalledOnce();
    timer.mockRestore();
  });

  it("freezes relation snapshots before dispatching a save", async () => {
    const update = vi.fn().mockResolvedValue(tree(2, "Local"));
    const controller = createCrtAutosaveController(tree(), update);
    const local = createGraphState({
      nodes: [
        { id: "node-1", label: "Local", position: { x: 0, y: 0 } },
        { id: "node-2", label: "Effect", position: { x: 0, y: 100 } }
      ],
      relations: [{ id: "relation-1", sourceId: "node-1", targetId: "node-2" }]
    });

    await controller.schedule(local);
    await vi.advanceTimersByTimeAsync(300);
    await settle();

    expect(update.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      relations: [expect.objectContaining({ id: "relation-1", source_node_id: "node-1", target_node_id: "node-2" })]
    }));
  });

  it("keeps a retry failed when durable retry persistence is rejected", async () => {
    const persistRetry = vi.fn().mockResolvedValue({ ok: false, reason: "writer-denied", mode: "durable", online_only_risk: false });
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistRetry,
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const update = vi.fn().mockRejectedValue(new Error("network down"));
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    await controller.schedule(graph("Retry"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    expect(controller.status).toBe("Save failed");

    controller.retry();
    await settle();

    expect(persistRetry).toHaveBeenCalledOnce();
    expect(update).toHaveBeenCalledOnce();
    expect(controller.status).toBe("Save failed");
  });

  it("reports queued cleanup failure when the canonical response already contains the edit", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise);
    const clearAfterCanonicalApplied = vi.fn().mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockResolvedValue({ ok: true, generation: 2, mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(graph("Canonical"));
    first.resolve(tree(2, "Canonical"));
    await settle();
    await settle();

    expect(clearAfterCanonicalApplied).toHaveBeenCalledWith(expect.objectContaining({ revision: 2 }), true, 2);
    expect(controller.status).toBe("Save failed");
  });

  it("replays queued content when durable queue persistence is unavailable", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(tree(3, "Second"));
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(graph("Second"));
    first.resolve(tree(2, "First"));
    await settle();
    await settle();

    expect(update).toHaveBeenCalledTimes(2);
    expect(update.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      expected_revision: 2,
      nodes: [expect.objectContaining({ label: "Second" })]
    }));
  });

  it("persists an unchanged active edit with an empty replay command list", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise);
    const persistQueuedEdit = vi.fn().mockResolvedValue({ ok: true, generation: 2, mode: "durable", online_only_risk: false });
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit,
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true })
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(graph("First"));
    first.resolve(tree(2, "First"));
    await settle();
    await settle();

    expect(persistQueuedEdit).toHaveBeenCalledWith(expect.objectContaining({ queuedCommands: [] }));
    expect(update).toHaveBeenCalledOnce();
  });

  it("stops after queued durability resolves when disposed during canonical delivery", async () => {
    const first = deferred<CrtTreeResponse>();
    const queuedGate = deferred<CrtPersistenceResult>();
    const update = vi.fn().mockReturnValueOnce(first.promise);
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockReturnValue(queuedGate.promise),
      clearAfterCanonicalApplied: vi.fn()
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    void controller.schedule(graph("Second"));
    first.resolve(tree(2, "First"));
    await settle();
    controller.dispose();
    queuedGate.resolve({ ok: true, generation: 2, mode: "durable", online_only_risk: false });
    await settle();

    expect(update).toHaveBeenCalledOnce();
  });

  it("uses the active generation when online-only queued durability has no generation", async () => {
    const first = deferred<CrtTreeResponse>();
    const update = vi.fn().mockReturnValueOnce(first.promise);
    const clearAfterCanonicalApplied = vi.fn().mockResolvedValue({ ok: true });
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockResolvedValue({ ok: false, reason: "storage-unavailable", mode: "online-only", online_only_risk: true }),
      clearAfterCanonicalApplied
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);
    await controller.schedule(graph("First"));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(graph("Canonical"));
    first.resolve(tree(2, "Canonical"));
    await settle();
    await settle();

    expect(clearAfterCanonicalApplied).toHaveBeenCalledWith(expect.objectContaining({ revision: 2 }), true, 1);
    expect(controller.status).toBe("Saved");
  });

  it("replays a conflict on retry without blindly losing the command", async () => {
    const update = vi.fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockRejectedValueOnce(new ApiError("Conflict", 409, { detail: { reason: "stale_revision" } }, "retry-conflict"));
    const controller = createCrtAutosaveController(tree(), update);

    await controller.schedule(graph("Retry conflict"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    controller.retry();
    await settle();

    expect(update).toHaveBeenCalledTimes(2);
    expect(controller.status).toBe("Conflict");
    expect(controller.reference).toBe("retry-conflict");
  });

  it("records a generic retry failure while retaining the frozen command", async () => {
    const update = vi.fn()
      .mockRejectedValueOnce(new Error("first network failure"))
      .mockRejectedValueOnce(new Error("retry network failure"));
    const controller = createCrtAutosaveController(tree(), update);

    await controller.schedule(graph("Retry failure"));
    await vi.advanceTimersByTimeAsync(300);
    await settle();
    controller.retry();
    await settle();

    expect(update).toHaveBeenCalledTimes(2);
    expect(controller.status).toBe("Save failed");
  });

  it("uses queued durability generation when an overflow response is canonical", async () => {
    const first = deferred<CrtTreeResponse>();
    const overflow = createGraphState({
      nodes: Array.from({ length: 101 }, (_, index) => ({ id: `overflow-${index}`, label: `Overflow ${index}`, position: { x: index, y: index } }))
    });
    const canonical: CrtTreeResponse = {
      ...tree(2, "Overflow"),
      nodes: overflow.nodes.map((node) => ({
        id: node.id,
        label: node.label,
        type: "child" as const,
        position: node.position,
        highlight_state: "none" as const,
        relation_counts: { up_count: 0, down_count: 0 }
      }))
    };
    const update = vi.fn().mockReturnValueOnce(first.promise);
    const clearAfterCanonicalApplied = vi.fn().mockResolvedValue({ ok: true });
    const persistence = {
      persistBeforeSave: vi.fn().mockResolvedValue({ ok: true, generation: 1, mode: "durable", online_only_risk: false }),
      persistQueuedEdit: vi.fn().mockResolvedValue({ ok: true, generation: 2, mode: "durable", online_only_risk: false }),
      clearAfterCanonicalApplied
    } as unknown as Parameters<typeof createCrtAutosaveController>[3];
    const controller = createCrtAutosaveController(tree(), update, undefined, persistence);

    await controller.schedule(createGraphState({ nodes: [] }));
    await vi.advanceTimersByTimeAsync(300);
    await controller.schedule(overflow);
    first.resolve(canonical);
    await settle();
    await settle();

    expect(clearAfterCanonicalApplied).toHaveBeenCalledWith(expect.objectContaining({ revision: 2 }), true, 1);
    expect(controller.status).toBe("Saved");
  });
 });
