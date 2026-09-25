import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { crtApi, type CrtTreeResponse } from "../../../api/crt";
import { ApiError } from "../../../api/client";
import { nowMs, recordTelemetry } from "../../../utils/telemetry";
import { createGraphState } from "../graphModel";
import { CrtWorkspace } from "../CrtWorkspace";
import * as crtTreeMenuModule from "../CrtTreeMenu";
import * as crtRecoveryDialogModule from "../CrtRecoveryDialog";
import * as crtDeleteConfirmationModule from "../CrtDeleteConfirmation";
import { graphToCrtUpdatePayload, treeToGraph as graphFromTree } from "../crtAutosave";
import * as crtAutosaveModule from "../crtAutosave";
import { createCrtDraftCoordinator, type CrtDraftCoordinator, type CrtDraftCoordinatorOptions } from "../crtDraftCoordinator";
import { rememberCrtLastTreePreference } from "../crtLastTreePreference";
import { draftStorageKey, type DraftLockManager, type DraftStorage, type PendingDraftEnvelope } from "../draftStore";
import { useAuthStore } from "../../../stores/authStore";

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
  layout: null,
  owner_id: "owner-1"
};

function tree(id: string, name: string, updatedAt: string, revision = 1, label = "The server is unreliable", causeLabel = "Deployments are rushed"): CrtTreeResponse {
  return {
    id,
    name,
    revision,
    schema_version: 1,
    metadata: { ...metadata, updated_at: updatedAt },
    nodes: [
      {
        id: `${id}-effect`,
        label,
        type: "parent",
        position: { x: 260, y: 40 },
        highlight_state: "none",
        relation_counts: { up_count: 0, down_count: 1 }
      },
      {
        id: `${id}-cause`,
        label: causeLabel,
        type: "child",
        position: { x: 260, y: 260 },
        highlight_state: "none",
        relation_counts: { up_count: 1, down_count: 0 }
      }
    ],
    relations: [
      {
        id: `${id}-relation`,
        source_node_id: `${id}-cause`,
        target_node_id: `${id}-effect`,
        kind: "why",
        created_at: updatedAt
      }
    ],
    owner_id: "owner-1"
  };
}

function emptyTree(id: string, name: string): CrtTreeResponse {
  return {
    id,
    name,
    revision: 1,
    schema_version: 1,
    metadata,
    nodes: [],
    relations: [],
    owner_id: "owner-1"
  };
}

class DraftMemoryStorage implements DraftStorage {
  private readonly values = new Map<string, string>();
  get length(): number { return this.values.size; }
  clear(): void { this.values.clear(); }
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  removeItem(key: string): void { this.values.delete(key); }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null; }
}

const draftLockManager: DraftLockManager = {
  async request<T>(_name: string, _options: { mode: "shared" | "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>): Promise<T> {
    return callback({ name: "crt-test-lock" });
  }
};

function coordinatorStub(overrides: Record<string, unknown> = {}): CrtDraftCoordinator {
  const stub = {
    onlineOnlyRisk: false,
    initialize: vi.fn().mockResolvedValue({ classification: "none", mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
    enumerateOwnerDrafts: vi.fn().mockResolvedValue({ ok: true, value: [], mode: "durable" }),
    subscribe: vi.fn(() => vi.fn()),
    dispose: vi.fn(),
    persistBeforeCreate: vi.fn().mockResolvedValue({ ok: true, mode: "durable", online_only_risk: false }),
    persistCommand: vi.fn().mockResolvedValue({ ok: true, mode: "durable", online_only_risk: false }),
    persistQueuedEdit: vi.fn().mockResolvedValue({ ok: true, mode: "durable", online_only_risk: false }),
    rekeyAfterCreate: vi.fn().mockResolvedValue({ ok: true, value: { generation: 1 }, mode: "durable" }),
    clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: true, cleared: true, mode: "durable", online_only_risk: false }),
    replayInFlightSave: vi.fn().mockResolvedValue({ ok: true, replayed: false }),
    completeInFlightRecovery: vi.fn().mockResolvedValue({ ok: true, mode: "durable", online_only_risk: false }),
    recover: vi.fn(),
    discard: vi.fn().mockResolvedValue({ ok: true, cleared: true, mode: "durable", online_only_risk: false }),
    discardOwnerDrafts: vi.fn().mockResolvedValue({ ok: true, removed: 1, mode: "durable", online_only_risk: false }),
    backup: vi.fn().mockReturnValue({ ok: true, content: "{}", filename: "crt-draft.json", mime_type: "application/json" }),
    ...overrides
  };
  return stub as unknown as CrtDraftCoordinator;
}

function recoveryDraft(treeId: string | null = "tree-recovery", overrides: Partial<PendingDraftEnvelope> = {}): PendingDraftEnvelope {
  return {
    schema_version: 1,
    owner_id: "owner-1",
    origin: window.location.origin,
    tree_id: treeId,
    create_idempotency_key: null,
    base_revision: 1,
    base_updated_at: "2026-09-20T10:00:00.000Z",
    local_updated_at: "2026-09-20T10:01:00.000Z",
    writer_session_id: "00000000-0000-4000-8000-000000000071",
    generation: 1,
    tree: { name: "Recovery tree", nodes: [], relations: [], layout: null },
    dirty_operations: [{ id: "00000000-0000-4000-8000-000000000072", kind: "tree-rename", field: "name" }],
    in_flight_save: null,
    queued_commands: [],
    digest_algorithm: "sha-256",
    digest_version: 1,
    ...overrides
  };
}

let previousNavigatorLocks: PropertyDescriptor | undefined;

beforeEach(() => {
  telemetryClock.mockReturnValue(0);
  telemetryRecord.mockClear();
  previousNavigatorLocks = Object.getOwnPropertyDescriptor(navigator, "locks");
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: navigator });
  Object.defineProperty(navigator, "locks", { configurable: true, value: draftLockManager });
  const storage = new DraftMemoryStorage();
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage });
  useAuthStore.setState({ user: { id: "owner-1", email: "owner@example.test" }, status: "authed" });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    () => new DOMRect(0, 0, 220, 100)
  );
  vi.stubGlobal(
    "DOMMatrixReadOnly",
    class {
      readonly m22 = 1;
    }
  );
  globalThis.ResizeObserver = class {
    private readonly callback: ResizeObserverCallback;

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
    }

    observe(target: Element): void {
      this.callback(
        [{ target, contentRect: { width: 220, height: 100 } } as ResizeObserverEntry],
        this as unknown as ResizeObserver
      );
    }

    unobserve(): void {}
    disconnect(): void {}
  } as unknown as typeof ResizeObserver;
  (window as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver = globalThis.ResizeObserver;
});

afterEach(async () => {
  // React Flow can flush pending work during unmount; keep that cleanup inside act
  // before restoring the DOM and browser mocks used by the workspace.
  await act(async () => {
    cleanup();
  });
  vi.useRealTimers();
  vi.restoreAllMocks();
  if (previousNavigatorLocks) Object.defineProperty(navigator, "locks", previousNavigatorLocks);
  else Reflect.deleteProperty(navigator, "locks");
  useAuthStore.setState({ user: null, status: "loading" });
});

describe("CrtWorkspace tree lifecycle", () => {
  it("019-FR-003 emits one content-free canvas-open event per editable tree activation", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-open", name: "Private tree name", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-open", "Private tree name", "2026-09-20T10:00:00Z"));

    const rendered = render(<CrtWorkspace />);
    await screen.findByRole("group", { name: "Current Reality Tree canvas" });
    await act(async () => {
      rendered.rerender(<CrtWorkspace />);
      await Promise.resolve();
    });

    const canvasEvents = telemetryRecord.mock.calls.filter(([event]) => event.name === "crt.canvas_open");
    expect(canvasEvents).toHaveLength(1);
    expect(canvasEvents[0]).toEqual([{
      name: "crt.canvas_open",
      details: { outcome: "success", revision: 1 }
    }]);
    const serialized = JSON.stringify(canvasEvents);
    expect(serialized).not.toContain("Private tree name");
    expect(serialized).not.toContain("The server is unreliable");
    expect(serialized).not.toContain("Deployments are rushed");
    expect(serialized).not.toContain("owner-1");
    expect(serialized).not.toContain("owner@example.test");
    expect(serialized).not.toContain("expected_revision");
    expect(serialized).not.toContain("idempotencyKey");
    expect(Object.keys(canvasEvents[0]?.[0] ?? {}).sort()).toEqual(["details", "name"]);
    expect(Object.keys(canvasEvents[0]?.[0]?.details ?? {}).sort()).toEqual(["outcome", "revision"]);
  });

  it("bounds the canvas to the viewport space remaining below the tree menu", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-layout", name: "Layout tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-layout", "Layout tree", "2026-09-20T10:00:00Z"));

    render(<CrtWorkspace />);

    await screen.findByRole("button", { name: "Current tree: Layout tree" });
    const workspace = screen.getByRole("main");
    expect(workspace).toHaveClass("flex", "h-dvh", "min-h-0", "flex-col", "overflow-hidden");
  });

  it("reconciles a pre-canonical draft with its original create idempotency key", async () => {
    const storage = new DraftMemoryStorage();
    const createKey = "00000000-0000-4000-8000-000000000031";
    const seed = createCrtDraftCoordinator({
      owner_id: "owner-1",
      origin: window.location.origin,
      tree_id: null,
      create_idempotency_key: createKey,
      storage,
      lock_manager: draftLockManager,
      writer_session_id: "00000000-0000-4000-8000-000000000032"
    });
    await seed.persistBeforeCreate(emptyTree("pre-canonical", "My first tree"), createGraphState({ nodes: [] }));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    const createTree = vi.spyOn(crtApi, "createCrtTree").mockResolvedValue(emptyTree("tree-reconciled", "My first tree"));

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage, lock_manager: draftLockManager })} />);

    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    });
    await waitFor(() => expect(createTree).toHaveBeenCalled());

    expect(createTree.mock.calls[0]?.[1]?.idempotencyKey).toBe(createKey);
  });

  it("retains a zoom-only pre-canonical draft during first-tree recovery", async () => {
    const storage = new DraftMemoryStorage();
    const createKey = "00000000-0000-4000-8000-000000000033";
    const seed = createCrtDraftCoordinator({
      owner_id: "owner-1",
      origin: window.location.origin,
      tree_id: null,
      create_idempotency_key: createKey,
      storage,
      lock_manager: draftLockManager,
      writer_session_id: "00000000-0000-4000-8000-000000000034"
    });
    await seed.persistBeforeCreate(
      emptyTree("pre-canonical", "My first tree"),
      createGraphState({ viewportZoom: 0.75 })
    );
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    vi.spyOn(crtApi, "createCrtTree").mockResolvedValue(emptyTree("tree-reconciled", "My first tree"));

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage, lock_manager: draftLockManager })} />);

    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    });

    expect(await screen.findByLabelText("Zoom level")).toHaveTextContent("75%");
  });

  it("reconciles an already-rekeyed pre-canonical draft as local recovery", async () => {
    const storage = new DraftMemoryStorage();
    const createKey = "00000000-0000-4000-8000-000000000041";
    const migrationId = "00000000-0000-4000-8000-000000000042";
    const graph = createGraphState({ nodes: [{ id: "local-node", label: "Local node", position: { x: 1, y: 2 } }] });
    const seed = createCrtDraftCoordinator({ owner_id: "owner-1", origin: window.location.origin, tree_id: null, create_idempotency_key: createKey, storage, lock_manager: draftLockManager, writer_session_id: "00000000-0000-4000-8000-000000000043" });
    await seed.persistBeforeCreate(emptyTree("pre-canonical", "My first tree"), graph);
    await seed.rekeyAfterCreate("tree-reconciled", migrationId);
    seed.dispose();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-reconciled", name: "My first tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(emptyTree("tree-reconciled", "My first tree"));

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage, lock_manager: draftLockManager })} />);

    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
  });

  it("updates the visible revision after an in-flight replay before management mutations", async () => {
    const storage = new DraftMemoryStorage();
    const canonical = tree("tree-replay", "Replay tree", "2026-09-20T10:00:00Z");
    const baseGraph = graphFromTree(canonical);
    const localGraph = {
      ...baseGraph,
      nodes: baseGraph.nodes.map((node, index) => index === 0 ? { ...node, label: "Replayed local effect" } : node)
    };
    const idempotencyKey = "00000000-0000-4000-8000-000000000051";
    const seed = createCrtDraftCoordinator({
      owner_id: "owner-1",
      origin: window.location.origin,
      tree_id: canonical.id,
      storage,
      lock_manager: draftLockManager,
      writer_session_id: "00000000-0000-4000-8000-000000000052"
    });
    await seed.persistCommand({
      tree: canonical,
      graph: localGraph,
      payload: graphToCrtUpdatePayload(canonical, localGraph, canonical.revision),
      idempotencyKey,
      baseRevision: canonical.revision,
      generation: 1,
      retry: false
    });
    seed.dispose();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: canonical.id, name: canonical.name, updated_at: canonical.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(canonical);
    const replayed = tree(canonical.id, canonical.name, "2026-09-20T10:01:00Z", 2, "Replayed local effect");
    const update = vi.spyOn(crtApi, "updateCrtTree").mockResolvedValue(replayed);
    vi.spyOn(crtAutosaveModule, "useCrtAutosave").mockReturnValue({
      status: "Saved",
      reference: undefined,
      conflict: undefined,
      schedule: vi.fn().mockResolvedValue(undefined),
      retry: vi.fn(),
      rebase: vi.fn(),
      syncCanonical: vi.fn(),
      setOnCanonical: vi.fn(),
      subscribe: vi.fn(() => vi.fn()),
      dispose: vi.fn()
    } as never);

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage, lock_manager: draftLockManager })} />);

    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    });
    await waitFor(() => expect(update).toHaveBeenCalledWith(canonical.id, expect.anything(), expect.objectContaining({ idempotencyKey })));
    await waitFor(() => expect(screen.getByRole("group", { name: "Current Reality Tree canvas" })).toBeInTheDocument());

    vi.stubGlobal("prompt", vi.fn().mockReturnValue("Renamed after replay"));
    fireEvent.click(screen.getByRole("button", { name: /current tree: replay tree/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename tree" }));
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
    expect(update.mock.calls[1]?.[1]).toMatchObject({ expected_revision: 2 });
    expect(storage.getItem(draftStorageKey({ owner_id: "owner-1", origin: window.location.origin, tree_id: canonical.id }))).toBeNull();
  });

  it("classifies a fresh compatible draft before mounting the editable canvas and requires recovery", async () => {
    const storage = new DraftMemoryStorage();
    const seed = createCrtDraftCoordinator({ owner_id: "owner-1", origin: window.location.origin, tree_id: "tree-recover", storage, lock_manager: draftLockManager, writer_session_id: "00000000-0000-4000-8000-000000000021" });
    await seed.persistBeforeSave(tree("tree-recover", "Recover tree", "2026-09-20T10:00:00Z"), createGraphState({ nodes: [{ id: "tree-recover-effect", label: "Local draft", position: { x: 1, y: 2 } }] }));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-recover", name: "Recover tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-recover", "Recover tree", "2026-09-20T10:00:00Z"));

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage, lock_manager: draftLockManager })} />);

    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Current Reality Tree canvas" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(await screen.findByRole("button", { name: "Local draft" })).toBeInTheDocument();
  });

  it("opens the stale D-06 recovery choice without applying or deleting the draft", async () => {
    const storage = new DraftMemoryStorage();
    const now = Date.parse("2026-09-20T12:00:00.000Z");
    const clock = { now: () => now + 30 * 24 * 60 * 60 * 1000 };
    const seed = createCrtDraftCoordinator({ owner_id: "owner-1", origin: window.location.origin, tree_id: "tree-stale", storage, lock_manager: draftLockManager, clock: { now: () => now }, writer_session_id: "00000000-0000-4000-8000-000000000022" });
    await seed.persistBeforeSave(tree("tree-stale", "Stale tree", "2026-09-20T10:00:00Z"), createGraphState({ nodes: [{ id: "tree-stale-effect", label: "Stale local", position: { x: 1, y: 2 } }] }));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-stale", name: "Stale tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-stale", "Stale tree", "2026-09-20T10:00:00Z"));

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage, lock_manager: draftLockManager, clock })} />);

    expect(await screen.findByRole("heading", { name: "Recover stale draft" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Current Reality Tree canvas" })).not.toBeInTheDocument();
  });

  it("classifies a base revision mismatch as a conflict while preserving both copies", async () => {
    const storage = new DraftMemoryStorage();
    const seed = createCrtDraftCoordinator({ owner_id: "owner-1", origin: window.location.origin, tree_id: "tree-conflict-startup", storage, lock_manager: draftLockManager, writer_session_id: "00000000-0000-4000-8000-000000000023" });
    await seed.persistBeforeSave(tree("tree-conflict-startup", "Conflict tree", "2026-09-20T10:00:00Z", 1), createGraphState({ nodes: [{ id: "tree-conflict-startup-effect", label: "Local conflict", position: { x: 1, y: 2 } }] }));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-conflict-startup", name: "Conflict tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-conflict-startup", "Conflict tree", "2026-09-20T11:00:00Z", 2, "Server copy"));

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage, lock_manager: draftLockManager })} />);

    expect(await screen.findByRole("heading", { name: "Review the sync conflict" })).toBeInTheDocument();
    expect(screen.getByText("Server copy")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Local draft" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Current Reality Tree canvas" })).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(await screen.findByText(/Local draft retained/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review local draft" }));
    expect(await screen.findByRole("heading", { name: "Review the sync conflict" })).toBeInTheDocument();
    expect(screen.getByText("Server copy")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Current Reality Tree canvas" })).not.toBeInTheDocument();
  });

  it("merges canonical graph data without dropping valid UI-only selection state", () => {
    const canonical = tree("tree-ui", "Canonical tree", "2026-09-20T10:02:00Z", 2, "Updated effect", "Updated cause");
    const current = createGraphState({
      nodes: [
        { id: "tree-ui-effect", label: "Local effect", position: { x: 1, y: 2 } },
        { id: "tree-ui-cause", label: "Local cause", position: { x: 3, y: 4 } }
      ],
      relations: [{ id: "tree-ui-relation", sourceId: "tree-ui-cause", targetId: "tree-ui-effect" }],
      selectedNodeId: "tree-ui-effect",
      editingNodeId: "tree-ui-cause",
      selectedRelationId: "tree-ui-relation",
      viewportCenter: { x: 99, y: 100 }
    });

    const merged = graphFromTree(canonical, current);

    expect(merged.nodes).toEqual([
      { id: "tree-ui-effect", label: "Updated effect", position: { x: 260, y: 40 } },
      { id: "tree-ui-cause", label: "Updated cause", position: { x: 260, y: 260 } }
    ]);
    expect(merged.relations).toEqual([
      { id: "tree-ui-relation", sourceId: "tree-ui-cause", targetId: "tree-ui-effect" }
    ]);
    expect(merged.selectedNodeId).toBe("tree-ui-effect");
    expect(merged.editingNodeId).toBe("tree-ui-cause");
    expect(merged.selectedRelationId).toBe("tree-ui-relation");
  });

  it("019-FR-003 exposes the integrated tree management menu for the loaded workspace", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-old", name: "Older tree", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" },
      { id: "tree-new", name: "Newest tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-new", "Newest tree", "2026-09-20T10:00:00Z"));

    render(<CrtWorkspace />);

    expect(await screen.findByRole("button", { name: /current tree: newest tree/i })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /current tree: newest tree/i }));
    });
    expect(screen.getByRole("menu", { name: "Tree menu" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Rename tree" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Export saved server copy" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Delete tree" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Switch to Older tree" })).toBeInTheDocument();
  });

  it("opens the owner-scoped last tree preference before falling back to the newest tree", async () => {
    rememberCrtLastTreePreference({ ownerId: "owner-1", origin: window.location.origin }, "tree-old");
    const getTree = vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-old", "Older tree", "2026-09-19T10:00:00Z"));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-old", name: "Older tree", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" },
      { id: "tree-new", name: "Newest tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }
    ]);

    render(<CrtWorkspace />);

    expect(await screen.findByRole("button", { name: /current tree: older tree/i })).toBeInTheDocument();
    expect(getTree).toHaveBeenCalledWith("tree-old", expect.any(AbortSignal));
  });

  it("019-FR-004 manages create, rename, switch, export, and delete from the workspace menu", async () => {
    const initialItems = [
      { id: "tree-old", name: "Older tree", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" },
      { id: "tree-new", name: "Newest tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }
    ];
    const newest = tree("tree-new", "Newest tree", "2026-09-20T10:00:00Z");
    const older = tree("tree-old", "Older tree", "2026-09-19T10:00:00Z");
    const created = emptyTree("tree-created", "Created tree");
    const renamed = tree("tree-created", "Renamed tree", "2026-09-20T10:02:00Z");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue(initialItems);
    const getTree = vi.spyOn(crtApi, "getCrtTree").mockResolvedValueOnce(newest).mockResolvedValueOnce(older).mockResolvedValueOnce(renamed);
    const createTree = vi.spyOn(crtApi, "createCrtTree").mockResolvedValue(created);
    const updateTree = vi.spyOn(crtApi, "updateCrtTree").mockResolvedValue(renamed);
    const exportTree = vi.spyOn(crtApi, "exportCrtTree").mockResolvedValue({ tree: renamed });
    const deleteTree = vi.spyOn(crtApi, "deleteCrtTree").mockResolvedValue(undefined);
    const downloadBackup = vi.fn();
    vi.stubGlobal("prompt", vi.fn()
      .mockReturnValueOnce("Created tree")
      .mockReturnValueOnce("Renamed tree"));

    render(<CrtWorkspace downloadBackup={downloadBackup} />);
    await screen.findByRole("button", { name: /current tree: newest tree/i });

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: newest tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Create a new tree" }));
    await waitFor(() => expect(createTree).toHaveBeenCalledWith({ name: "Created tree" }, expect.objectContaining({ idempotencyKey: expect.any(String) })));

    const createdTreeTrigger = await screen.findByRole("button", { name: /current tree: created tree/i });
    await act(async () => { fireEvent.click(createdTreeTrigger); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename tree" }));
    await waitFor(() => expect(updateTree).toHaveBeenCalledWith("tree-created", expect.objectContaining({ name: "Renamed tree" }), expect.objectContaining({ idempotencyKey: expect.any(String) })));

    const renamedTreeTrigger = await screen.findByRole("button", { name: /current tree: renamed tree/i });
    await act(async () => { fireEvent.click(renamedTreeTrigger); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Older tree" }));
    await waitFor(() => expect(getTree).toHaveBeenCalledWith("tree-old"));
    expect(await screen.findByRole("button", { name: /current tree: older tree/i })).toBeInTheDocument();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: older tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    await waitFor(() => expect(exportTree).toHaveBeenCalledWith("tree-old"));
    expect(downloadBackup).toHaveBeenCalledWith(expect.objectContaining({ filename: "Older-tree.json", mime_type: "application/json" }));

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: older tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));
    expect(await screen.findByRole("alertdialog", { name: "Delete ‘Older tree’?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete tree" }));
    await waitFor(() => expect(deleteTree).toHaveBeenCalledWith("tree-old", expect.objectContaining({ expectedRevision: 1, idempotencyKey: expect.any(String) })));
    expect(await screen.findByRole("button", { name: /current tree: renamed tree/i })).toBeInTheDocument();
  });

  it("019-FR-020 requires an explicit pending-work choice before switching trees", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-old", name: "Older tree", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" },
      { id: "tree-new", name: "Newest tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }
    ]);
    const getTree = vi.spyOn(crtApi, "getCrtTree").mockResolvedValueOnce(tree("tree-new", "Newest tree", "2026-09-20T10:00:00Z")).mockResolvedValueOnce(tree("tree-old", "Older tree", "2026-09-19T10:00:00Z"));

    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved local edit" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: newest tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Older tree" }));

    expect(await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard and continue" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    await waitFor(() => expect(getTree).toHaveBeenCalledWith("tree-old"));
    expect(await screen.findByRole("button", { name: /current tree: older tree/i })).toBeInTheDocument();
  });

  it("019-FR-020 applies the pending-work barrier before opening destructive delete confirmation", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-new", name: "Newest tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-new", "Newest tree", "2026-09-20T10:00:00Z"));

    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved local edit" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: newest tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));

    expect(await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog", { name: "Delete ‘Newest tree’?" })).not.toBeInTheDocument();
  });

  it("fails closed when pending-work discard cannot enumerate drafts", async () => {
    const coordinator = coordinatorStub({
      enumerateOwnerDrafts: vi.fn().mockResolvedValue({ ok: false, reason: "enumeration-failed", mode: "durable" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-old", name: "Older tree", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" },
      { id: "tree-new", name: "Newest tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }
    ]);
    const getTree = vi.spyOn(crtApi, "getCrtTree")
      .mockResolvedValueOnce(tree("tree-new", "Newest tree", "2026-09-20T10:00:00Z"))
      .mockResolvedValueOnce(tree("tree-old", "Older tree", "2026-09-19T10:00:00Z"));

    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved local edit" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: newest tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Older tree" }));

    expect(await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(getTree).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
  });

  it("does not clear a remaining tree draft while selecting the fallback after deletion", async () => {
    const storage = new DraftMemoryStorage();
    const remaining = tree("tree-remaining", "Remaining tree", "2026-09-19T10:00:00Z");
    const seed = createCrtDraftCoordinator({ owner_id: "owner-1", origin: window.location.origin, tree_id: remaining.id, storage, lock_manager: draftLockManager, writer_session_id: "00000000-0000-4000-8000-000000000061" });
    await seed.persistBeforeSave(remaining, createGraphState({ nodes: [{ id: "tree-remaining-effect", label: "Keep this draft", position: { x: 1, y: 2 } }] }));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-active", name: "Active tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" },
      { id: remaining.id, name: remaining.name, updated_at: remaining.metadata.updated_at, owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValueOnce(tree("tree-active", "Active tree", "2026-09-20T10:00:00Z")).mockResolvedValueOnce(remaining);
    vi.spyOn(crtApi, "deleteCrtTree").mockResolvedValue(undefined);

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage, lock_manager: draftLockManager })} />);
    await screen.findByRole("button", { name: /current tree: active tree/i });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: active tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete tree" }));

    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Current Reality Tree canvas" })).not.toBeInTheDocument();
  });

  it("lists every pending tree in the transition barrier with its edit count", async () => {
    const storage = new DraftMemoryStorage();
    const remaining = tree("tree-remaining", "Remaining tree", "2026-09-19T10:00:00Z");
    const seed = createCrtDraftCoordinator({ owner_id: "owner-1", origin: window.location.origin, tree_id: remaining.id, storage, lock_manager: draftLockManager, writer_session_id: "00000000-0000-4000-8000-000000000062" });
    await seed.persistBeforeSave(remaining, createGraphState({ nodes: [{ id: "tree-remaining-effect", label: "Other draft", position: { x: 1, y: 2 } }] }));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-active", name: "Active tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" },
      { id: remaining.id, name: remaining.name, updated_at: remaining.metadata.updated_at, owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValueOnce(tree("tree-active", "Active tree", "2026-09-20T10:00:00Z")).mockResolvedValueOnce(remaining);

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage, lock_manager: draftLockManager })} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Active draft" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: active tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Remaining tree" }));

    expect(await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
    expect(screen.getByText("Active tree · 1 unsynced edit")).toBeInTheDocument();
    expect(screen.getByText("Remaining tree · 1 unsynced edit")).toBeInTheDocument();
  });

  it("discards every listed pending tree before continuing the transition", async () => {
    const storage = new DraftMemoryStorage();
    const remaining = tree("tree-remaining", "Remaining tree", "2026-09-19T10:00:00Z");
    const seed = createCrtDraftCoordinator({ owner_id: "owner-1", origin: window.location.origin, tree_id: remaining.id, storage, lock_manager: draftLockManager, writer_session_id: "00000000-0000-4000-8000-000000000063" });
    await seed.persistBeforeSave(remaining, createGraphState({ nodes: [{ id: "tree-remaining-effect", label: "Other draft", position: { x: 1, y: 2 } }] }));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-active", name: "Active tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" },
      { id: remaining.id, name: remaining.name, updated_at: remaining.metadata.updated_at, owner_id: "owner-1" }
    ]);
    const getTree = vi.spyOn(crtApi, "getCrtTree").mockResolvedValueOnce(tree("tree-active", "Active tree", "2026-09-20T10:00:00Z")).mockResolvedValueOnce(remaining);

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage, lock_manager: draftLockManager })} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Active draft" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: active tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Remaining tree" }));
    await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" });

    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    await waitFor(() => expect(getTree).toHaveBeenCalledWith("tree-remaining"));
    expect(storage.getItem(draftStorageKey({ owner_id: "owner-1", origin: window.location.origin, tree_id: remaining.id }))).toBeNull();
  });

  it("reuses a management idempotency key when create is retried after an unknown outcome", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-active", name: "Active tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-active", "Active tree", "2026-09-20T10:00:00Z"));
    vi.spyOn(crtApi, "createCrtTree")
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce(emptyTree("tree-created", "Created tree"));
    vi.stubGlobal("prompt", vi.fn().mockReturnValue("Created tree"));

    render(<CrtWorkspace />);
    await screen.findByRole("button", { name: /current tree: active tree/i });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: active tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Create a new tree" }));
    expect(await screen.findByText("We couldn't create this tree.")).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: active tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Create a new tree" }));

    await waitFor(() => expect(crtApi.createCrtTree).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(crtApi.createCrtTree).mock.calls;
    expect(calls[1]?.[1]?.idempotencyKey).toBe(calls[0]?.[1]?.idempotencyKey);
  });

  it("019-FR-018 019-FR-020 keeps unsynchronized export on the server-copy barrier and offers a local backup", async () => {
    const downloadBackup = vi.fn();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: "tree-new", name: "Newest tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-new", "Newest tree", "2026-09-20T10:00:00Z"));
    const exportTree = vi.spyOn(crtApi, "exportCrtTree");

    render(<CrtWorkspace downloadBackup={downloadBackup} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved local edit" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: newest tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));

    expect(await screen.findByText(/unsynchronized changes are excluded/i)).toBeInTheDocument();
    expect(exportTree).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Download local backup" }));
    expect(downloadBackup).not.toHaveBeenCalled();
  });

  it("019-FR-003 loads the newest tree and renders its cards and one directed edge", async () => {
    const older = { id: "tree-old", name: "Older tree", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" };
    const newer = { id: "tree-new", name: "Newest tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" };
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([older, newer]);
    const getTree = vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-new", "Newest tree", newer.updated_at));
    render(<CrtWorkspace />);

    expect(await screen.findByRole("button", { name: "Effect: The server is unreliable" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Effect: The server is unreliable" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Current Reality Tree" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Root cause: Deployments are rushed" })).toBeInTheDocument();
    expect(await screen.findByTestId("crt-edge-tree-new-relation")).toBeInTheDocument();
    expect(screen.getByText("Saved", { selector: ".crt-save-status" })).toBeInTheDocument();
    expect(getTree).toHaveBeenCalledWith("tree-new", expect.any(AbortSignal));
  });

  it("019-FR-004 gives the truthful first-run state a working create-first-tree action", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    const createTree = vi.spyOn(crtApi, "createCrtTree").mockResolvedValue(emptyTree("tree-created", "My first tree"));

    render(<CrtWorkspace />);

    expect(await screen.findByText("No demo content is added for you.")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Create first tree" }));
    });

    expect(createTree).toHaveBeenCalledWith({ name: "My first tree" }, expect.objectContaining({ idempotencyKey: expect.any(String) }));
    expect(await screen.findByText("My first tree")).toBeInTheDocument();
    expect(screen.getByText("My first tree")).toBeInTheDocument();
    expect(screen.getByText("Start with your first undesired effect")).toBeInTheDocument();
  });

  it("warns before first create when draft storage is unavailable", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage: null, lock_manager: null })} />);

    expect(await screen.findByText("Saved online only")).toBeInTheDocument();
    expect(screen.getByText(/resizing below the supported width, signing out, or an access change can close the editor and lose unsynchronized changes/i)).toBeInTheDocument();
  });

  it("allows saved management transitions while warning when cross-tab Web Locks are unavailable", async () => {
    const loaded = emptyTree("tree-no-lock", "No-lock tree");
    const update = vi.spyOn(crtApi, "updateCrtTree").mockResolvedValue({ ...loaded, revision: 2, name: "Unsafe rename" });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.stubGlobal("prompt", vi.fn().mockReturnValue("Unsafe rename"));

    render(<CrtWorkspace createDraftCoordinator={(options) => createCrtDraftCoordinator({ ...options, storage: new DraftMemoryStorage(), lock_manager: null })} />);

    await screen.findByRole("button", { name: /current tree: no-lock tree/i });
    fireEvent.click(screen.getByRole("button", { name: /current tree: no-lock tree/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename tree" }));

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Saved online only")).toBeInTheDocument();
  });

  it("019-FR-004 retries first-tree creation with the same idempotency key", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    vi.spyOn(crtApi, "createCrtTree")
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(emptyTree("tree-created", "My first tree"));

    render(<CrtWorkspace />);
    await screen.findByText("No demo content is added for you.");
    fireEvent.click(screen.getByRole("button", { name: "Create first tree" }));
    expect(await screen.findByRole("heading", { name: "We couldn't create this tree" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry creating tree" }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(await screen.findByText("My first tree")).toBeInTheDocument();

    const calls = vi.mocked(crtApi.createCrtTree).mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[1]?.[1]?.idempotencyKey).toBe(calls[0]?.[1]?.idempotencyKey);
  });

  it("019-FR-004 ignores a late first-tree completion after the workspace unmounts", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    let resolveCreate!: (value: CrtTreeResponse) => void;
    vi.spyOn(crtApi, "createCrtTree").mockReturnValue(new Promise((resolve) => { resolveCreate = resolve; }));

    const rendered = render(<CrtWorkspace />);
    await screen.findByText("No demo content is added for you.");
    fireEvent.click(screen.getByRole("button", { name: "Create first tree" }));
    rendered.unmount();
    resolveCreate(emptyTree("tree-late", "Late tree"));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.queryByText("Late tree")).not.toBeInTheDocument();
  });

  it("019-FR-020 retries a failed tree load without leaving /crt or showing a stale graph", async () => {
    const listTrees = vi
      .spyOn(crtApi, "listCrtTrees")
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce([{ id: "tree-retry", name: "Retry tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-retry", "Retry tree", "2026-09-20T10:00:00Z"));

    render(<CrtWorkspace />);

    expect(await screen.findByRole("heading", { name: "We couldn't load this tree" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Effect:/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));

    expect(await screen.findByRole("button", { name: "Effect: The server is unreliable" })).toBeInTheDocument();
    expect(listTrees).toHaveBeenCalledTimes(2);
  });

  it("019-FR-017 debounces a graph snapshot and marks it saved from the canonical response", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-dirty", name: "Dirty tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    const getTree = vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-dirty", "Dirty tree", "2026-09-20T10:00:00Z"));
    let resolveUpdate!: (value: CrtTreeResponse) => void;
    const pendingUpdate = new Promise<CrtTreeResponse>((resolve) => { resolveUpdate = resolve; });
    const updateTree = vi.spyOn(crtApi, "updateCrtTree").mockReturnValue(pendingUpdate);

    render(<CrtWorkspace />);

    const label = await screen.findByRole("textbox", { name: "Card label" });
    vi.useFakeTimers();
    fireEvent.change(label, { target: { value: "Changed locally" } });

    expect(screen.getByText("Unsaved", { selector: ".crt-save-status" })).toBeInTheDocument();
    expect(updateTree).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(updateTree).toHaveBeenCalledWith(
      "tree-dirty",
      expect.objectContaining({ expected_revision: 1, schema_version: 1, name: "Dirty tree" }),
      expect.objectContaining({ idempotencyKey: expect.any(String), signal: expect.any(AbortSignal) })
    );
    expect(screen.getByText("Saving", { selector: ".crt-save-status" })).toBeInTheDocument();
    resolveUpdate(tree("tree-dirty", "Dirty tree", "2026-10-20T10:01:00Z", 2, "The server is unreliable", "Changed locally"));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Saved", { selector: ".crt-save-status" })).toBeInTheDocument();
    expect(getTree).toHaveBeenCalledTimes(1);
  });

  it("019-FR-021 exposes conflict refetch and preserves the local graph before explicit rebase", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-conflict", name: "Conflict tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-conflict", "Conflict tree", "2026-09-20T10:00:00Z", 2, "Server copy"));
    const updateTree = vi.spyOn(crtApi, "updateCrtTree").mockRejectedValue(new ApiError("Conflict", 409, { detail: { reason: "stale_revision" } }, "corr-conflict"));

    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    vi.useFakeTimers();
    fireEvent.change(label, { target: { value: "Local copy" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); await Promise.resolve(); await Promise.resolve(); });

    expect(screen.getByText(/server changed this tree/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Card label" })).toHaveValue("Local copy");
    fireEvent.click(screen.getByRole("button", { name: "Refresh server copy" }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByRole("textbox", { name: "Card label" })).toHaveValue("Local copy");
    expect(screen.getByRole("button", { name: "Save local changes" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save local changes" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(updateTree.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ expected_revision: 2 }));
  });
  it("surfaces a retryable conflict refresh failure with its support reference", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-conflict", name: "Conflict tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree")
      .mockResolvedValueOnce(tree("tree-conflict", "Conflict tree", "2026-09-20T10:00:00Z"))
      .mockRejectedValueOnce(new ApiError("Refresh failed", 503, { detail: "unavailable" }, "corr-refresh"));
    vi.spyOn(crtApi, "updateCrtTree").mockRejectedValue(new ApiError("Conflict", 409, { detail: { reason: "stale_revision" } }, "corr-conflict"));

    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    vi.useFakeTimers();
    fireEvent.change(label, { target: { value: "Local copy" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); await Promise.resolve(); await Promise.resolve(); });

    fireEvent.click(screen.getByRole("button", { name: "Refresh server copy" }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(screen.getByText(/couldn't refresh the server copy/i)).toBeInTheDocument();
    expect(screen.getByText(/corr-refresh/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh server copy" })).toBeInTheDocument();
  });

  it("requires a fresh server refresh after resolving one conflict before saving through another", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-conflict", name: "Conflict tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree")
      .mockResolvedValueOnce(tree("tree-conflict", "Conflict tree", "2026-09-20T10:00:00Z"))
      .mockResolvedValue(tree("tree-conflict", "Conflict tree", "2026-09-20T10:01:00Z", 2, "Server copy"));
    const updateTree = vi.spyOn(crtApi, "updateCrtTree")
      .mockRejectedValueOnce(new ApiError("Conflict", 409, { detail: { reason: "stale_revision" } }, "corr-first"))
      .mockRejectedValueOnce(new ApiError("Conflict", 409, { detail: { reason: "stale_revision" } }, "corr-second"));

    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    vi.useFakeTimers();
    fireEvent.change(label, { target: { value: "Local copy" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); await Promise.resolve(); await Promise.resolve(); });

    fireEvent.click(screen.getByRole("button", { name: "Refresh server copy" }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByRole("button", { name: "Save local changes" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save local changes" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(300); await Promise.resolve(); await Promise.resolve(); });

    expect(updateTree).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: "Save local changes" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh server copy" })).toBeInTheDocument();
  });

  it("019-FR-017 019-SC-004 keeps edits unsaved and exposes a failed save after a rejected update", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-failed", name: "Failed tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-failed", "Failed tree", "2026-09-20T10:00:00Z"));
    const updateTree = vi.spyOn(crtApi, "updateCrtTree").mockRejectedValue(new Error("network down"));

    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    vi.useFakeTimers();
    fireEvent.change(label, { target: { value: "Still local" } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(updateTree).toHaveBeenCalledOnce();
    expect(screen.getByText("Save failed", { selector: ".crt-save-status" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Card label" })).toHaveValue("Still local");
  });

  it("019-FR-017 keeps dispatched saves immutable and queues newer edits", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-order", name: "Order tree", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(tree("tree-order", "Order tree", "2026-09-20T10:00:00Z"));
    let resolveFirst!: (value: CrtTreeResponse) => void;
    const first = new Promise<CrtTreeResponse>((resolve) => { resolveFirst = resolve; });
    const updateTree = vi.spyOn(crtApi, "updateCrtTree").mockReturnValueOnce(first).mockResolvedValueOnce(tree("tree-order", "Order tree", "2026-09-20T10:02:00Z", 3, "The server is unreliable", "Second local"));

    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    vi.useFakeTimers();
    fireEvent.change(label, { target: { value: "First local" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    const firstSignal = updateTree.mock.calls[0]?.[2]?.signal;
    expect(firstSignal).toBeInstanceOf(AbortSignal);

    fireEvent.change(label, { target: { value: "Second local" } });
    expect(firstSignal?.aborted).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(updateTree).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
    resolveFirst(tree("tree-order", "Order tree", "2026-09-20T10:01:00Z", 2, "The server is unreliable", "First local"));
    await waitFor(() => expect(updateTree).toHaveBeenCalledTimes(2));
    expect(updateTree.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ expected_revision: 2 }));

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText("Saved", { selector: ".crt-save-status" })).toBeInTheDocument();
  });

  it("fails closed for unauthenticated owners and owner-mismatched responses", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "foreign", name: "Foreign", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue({ ...emptyTree("foreign", "Foreign"), owner_id: "owner-2", metadata: { ...metadata, owner_id: "owner-2" } });
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    expect(await screen.findByRole("heading", { name: "We couldn't verify this tree" })).toBeInTheDocument();
    cleanup();
    useAuthStore.setState({ user: null, status: "anon" });
    vi.restoreAllMocks();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    expect(await screen.findByRole("heading", { name: "We couldn't verify this tree" })).toBeInTheDocument();
  });

  it("renders locked, invalid, and online-only coordinator outcomes", async () => {
    const loaded = emptyTree("tree-state", "State tree");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    const locked = coordinatorStub({ initialize: vi.fn().mockResolvedValue({ classification: "none", mode: "durable", online_only_risk: false, lock_state: "locked" }) });
    render(<CrtWorkspace createDraftCoordinator={() => locked} />);
    expect(await screen.findByRole("heading", { name: "This tree is open in another tab" })).toBeInTheDocument();
    cleanup();
    vi.restoreAllMocks();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    const invalid = coordinatorStub({ initialize: vi.fn().mockResolvedValue({ classification: "invalid", reason: "invalid-json", mode: "durable", online_only_risk: false, lock_state: "unavailable" }) });
    render(<CrtWorkspace createDraftCoordinator={() => invalid} />);
    expect(await screen.findByRole("heading", { name: "We couldn't verify the local draft" })).toBeInTheDocument();
    expect(screen.getByText("Recovery reference: invalid-json")).toBeInTheDocument();
    cleanup();
    vi.restoreAllMocks();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    const onlineOnly = coordinatorStub({ onlineOnlyRisk: true, initialize: vi.fn().mockResolvedValue({ classification: "none", mode: "online-only", online_only_risk: true, lock_state: "unavailable" }) });
    render(<CrtWorkspace createDraftCoordinator={() => onlineOnly} />);
    expect(await screen.findByText("Saved online only")).toBeInTheDocument();
  });

  it("shows support references for create, rename, switch, export, import, and delete failures", async () => {
    const current = tree("tree-errors", "Error tree", "2026-09-20T10:00:00Z");
    const apiError = () => new ApiError("failed", 503, { detail: "failed" }, "workspace-ref");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: current.id, name: current.name, updated_at: current.metadata.updated_at, owner_id: "owner-1" },
      { id: "other-tree", name: "Other tree", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValueOnce(current).mockRejectedValue(apiError());
    vi.spyOn(crtApi, "createCrtTree").mockRejectedValue(apiError());
    vi.spyOn(crtApi, "updateCrtTree").mockRejectedValue(apiError());
    vi.spyOn(crtApi, "exportCrtTree").mockRejectedValue(apiError());
    vi.spyOn(crtApi, "deleteCrtTree").mockRejectedValue(apiError());
    vi.spyOn(crtApi, "importCrtTree").mockRejectedValue(apiError());
    vi.stubGlobal("prompt", vi.fn().mockReturnValueOnce("New tree").mockReturnValueOnce("Renamed tree"));
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    await screen.findByRole("button", { name: /current tree: error tree/i });
    const openMenu = async () => { await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: error tree/i })); }); };
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Create a new tree" }));
    expect(await screen.findByText(/Support reference: workspace-ref/)).toBeInTheDocument();
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename tree" }));
    expect(await screen.findByText(/couldn't rename this tree/)).toBeInTheDocument();
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Other tree" }));
    expect(await screen.findByText(/couldn't switch trees/)).toBeInTheDocument();
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    expect(await screen.findByText(/couldn't export this tree/)).toBeInTheDocument();
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete tree" }));
    await waitFor(() => expect(screen.getByRole("alertdialog")).toHaveTextContent("Nothing was deleted"));
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Import tree JSON" }));
    const invalidFile = Object.assign(new File(["not-json"], "tree.json", { type: "application/json" }), { text: async () => "not-json" });
    fireEvent.change(screen.getByLabelText("Choose tree JSON file"), { target: { files: [invalidFile] } });
    expect(await screen.findByText(/Unexpected token|couldn't import this tree/)).toBeInTheDocument();
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Import tree JSON" }));
    const validFile = Object.assign(new File([JSON.stringify({ tree: current })], "tree.json", { type: "application/json" }), { text: async () => JSON.stringify({ tree: current }) });
    fireEvent.change(screen.getByLabelText("Choose tree JSON file"), { target: { files: [validFile] } });
    expect(await screen.findByText(/Support reference: workspace-ref/)).toBeInTheDocument();
  });

  it("uses the default backup download and ignores cancelled prompts", async () => {
    const current = emptyTree("tree-download", "Download tree");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: current.id, name: current.name, updated_at: current.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(current);
    vi.spyOn(crtApi, "exportCrtTree").mockResolvedValue({ tree: current });
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.stubGlobal("prompt", vi.fn().mockReturnValueOnce(null).mockReturnValueOnce(" "));
    render(<CrtWorkspace />);
    await screen.findByRole("button", { name: /current tree: download tree/i });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: download tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Create a new tree" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: download tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename tree" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /current tree: download tree/i })); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test");
  });

  it("renders a recoverable draft and defers it without opening the editable recovery canvas", async () => {
    const loaded = emptyTree("tree-recovery", "Recovery tree");
    const draft = recoveryDraft(loaded.id);
    const recover = vi.fn().mockResolvedValue({ ok: true, draft });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      recover
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(await screen.findByText(/Local draft retained/)).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Current Reality Tree canvas" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Review local draft" }));
    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Current Reality Tree canvas" })).not.toBeInTheDocument();
  });

  it("keeps a recovery draft visible when recovery fails and permits retry", async () => {
    const loaded = emptyTree("tree-recovery-error", "Recovery error tree");
    const draft = recoveryDraft(loaded.id);
    const recover = vi.fn().mockRejectedValueOnce(new Error("recovery failed")).mockResolvedValueOnce({ ok: true, draft });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "stale", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      recover
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover stale draft" });
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't recover the draft");
    await waitFor(() => expect(screen.getByRole("button", { name: "Recover draft" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    await waitFor(() => expect(recover).toHaveBeenCalledTimes(2));
  });

  it("shows the invalid-draft recovery boundary when the local graph cannot be verified", async () => {
    const loaded = emptyTree("tree-invalid", "Invalid tree");
    const draft = recoveryDraft(loaded.id, { tree: { name: "Invalid", nodes: [{ id: "", label: "", position: { x: Number.NaN, y: 0 } }], relations: [], layout: null } });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    expect(await screen.findByRole("heading", { name: "We couldn't verify the local draft" })).toBeInTheDocument();
    expect(screen.getByText("Recovery reference: draft-graph-integrity")).toBeInTheDocument();
  });

  it("covers first-tree persistence and rekey failures as retryable create errors", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    const persistFailure = coordinatorStub({
      persistBeforeCreate: vi.fn().mockResolvedValue({ ok: false, reason: "storage-unavailable", mode: "durable", online_only_risk: false })
    });
    render(<CrtWorkspace createDraftCoordinator={() => persistFailure} />);
    await screen.findByRole("button", { name: "Create first tree" });
    fireEvent.click(screen.getByRole("button", { name: "Create first tree" }));
    expect(await screen.findByRole("heading", { name: "We couldn't create this tree" })).toBeInTheDocument();
    cleanup();
    vi.restoreAllMocks();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    vi.spyOn(crtApi, "createCrtTree").mockResolvedValue(emptyTree("tree-rekey-failed", "My first tree"));
    const rekeyFailure = coordinatorStub({
      rekeyAfterCreate: vi.fn().mockResolvedValue({ ok: false, reason: "rekey-failed", mode: "durable", online_only_risk: false })
    });
    render(<CrtWorkspace createDraftCoordinator={() => rekeyFailure} />);
    await screen.findByRole("button", { name: "Create first tree" });
    fireEvent.click(screen.getByRole("button", { name: "Create first tree" }));
    expect(await screen.findByRole("heading", { name: "We couldn't create this tree" })).toBeInTheDocument();
  });

  it("returns to the empty state after deleting the only tree", async () => {
    const loaded = emptyTree("tree-only", "Only tree");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "deleteCrtTree").mockResolvedValue(undefined);
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    await screen.findByRole("button", { name: /current tree: only tree/i });
    fireEvent.click(screen.getByRole("button", { name: /current tree: only tree/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete tree" }));
    expect(await screen.findByText("No demo content is added for you.")).toBeInTheDocument();
  });

  it("reports backup preparation failures from the unsynchronized export barrier", async () => {
    const loaded = tree("tree-backup-error", "Backup error tree", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub({ backup: vi.fn().mockReturnValue({ ok: false, reason: "storage-unavailable" }) });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: backup error tree/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    fireEvent.click(screen.getByRole("button", { name: "Download local backup" }));
    expect((await screen.findAllByRole("alert")).some((alert) => alert.textContent?.includes("Draft backup unavailable: storage-unavailable"))).toBe(true);
  });

  it("replays an in-flight save with queued commands before opening the canvas", async () => {
    const loaded = tree("tree-replay-queued", "Queued recovery", "2026-09-20T10:00:00Z");
    const latest = tree(loaded.id, loaded.name, "2026-09-20T10:01:00Z", 2);
    const baseDraft = recoveryDraft(loaded.id);
    const draft = recoveryDraft(loaded.id, {
      in_flight_save: { idempotency_key: "00000000-0000-4000-8000-000000000081", base_revision: 1, generation: 1, snapshot: baseDraft.tree, hash: "hash" },
      queued_commands: [{ id: "00000000-0000-4000-8000-000000000082", kind: "tree-rename", payload: { name: "Queued recovery" } }]
    });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      replayInFlightSave: vi.fn().mockResolvedValue({ ok: true, replayed: true, response: latest }),
      completeInFlightRecovery: vi.fn().mockResolvedValue({ ok: true, mode: "durable", online_only_risk: false })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    await waitFor(() => expect(coordinator.completeInFlightRecovery).toHaveBeenCalled());
    expect(await screen.findByRole("group", { name: "Current Reality Tree canvas" })).toBeInTheDocument();
  });

  it("shows the local-graph fallback in conflict recovery and keeps the local copy", async () => {
    const loaded = tree("tree-conflict-choice", "Conflict choice", "2026-09-20T10:00:00Z", 2);
    const draft = recoveryDraft(loaded.id, { base_revision: 1, dirty_operations: [] });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    expect(await screen.findByRole("heading", { name: "Review the sync conflict" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review differences" }));
    expect(screen.getByText("Local graph changes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Keep local and retry" }));
    expect(await screen.findByRole("group", { name: "Current Reality Tree canvas" })).toBeInTheDocument();
  });

  it("requires confirmation before using the server copy during workspace conflict recovery", async () => {
    const loaded = tree("tree-server-choice", "Server choice", "2026-09-20T10:00:00Z", 2);
    const draft = recoveryDraft(loaded.id, { base_revision: 1 });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      discard: vi.fn().mockRejectedValueOnce(new Error("discard failed")).mockResolvedValueOnce({ ok: true, cleared: true, mode: "durable", online_only_risk: false })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Review the sync conflict" });
    fireEvent.click(screen.getByRole("button", { name: "Use server copy" }));
    fireEvent.click(screen.getByRole("button", { name: /Discard 1 local edit and use server copy/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was discarded");
    fireEvent.click(screen.getByRole("button", { name: "Discard 1 local edit and use server copy" }));
    expect(await screen.findByRole("group", { name: "Current Reality Tree canvas" })).toBeInTheDocument();
  });


  it("reports workspace discard failures and downloads a recovery backup", async () => {
    const loaded = tree("tree-discard-error", "Discard error", "2026-09-20T10:00:00Z");
    const draft = recoveryDraft(loaded.id);
    const downloadBackup = vi.fn();
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "stale", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      discard: vi.fn().mockRejectedValue(new Error("discard failed"))
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} downloadBackup={downloadBackup} />);
    await screen.findByRole("heading", { name: "Recover stale draft" });
    fireEvent.click(screen.getByRole("button", { name: "Download local backup" }));
    expect(downloadBackup).toHaveBeenCalledOnce();
    await screen.findByText("Local backup downloaded.", { selector: "[aria-live]" });
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    await screen.findByRole("heading", { name: "Discard draft?" });
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't discard the draft");
    fireEvent.keyDown(document, { key: "Escape" });
  });

  it("discards pending work before importing and then installs the imported tree", async () => {
    const loaded = tree("tree-pending-import", "Pending import", "2026-09-20T10:00:00Z");
    const imported = emptyTree("tree-import-after-discard", "Imported after discard");
    const coordinator = coordinatorStub({ onlineOnlyRisk: true });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "updateCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "importCrtTree").mockResolvedValue(imported);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Pending local edit" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: pending import/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Import tree JSON" }));
    const file = Object.assign(new File([JSON.stringify(imported)], "tree.json", { type: "application/json" }), { text: async () => JSON.stringify(imported) });
    fireEvent.change(screen.getByLabelText("Choose tree JSON file"), { target: { files: [file] } });
    expect(await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect(await screen.findByRole("button", { name: /current tree: imported after discard/i })).toBeInTheDocument();
  });

  it("discards pending work before opening delete confirmation and lets the user cancel", async () => {
    const loaded = tree("tree-pending-delete", "Pending delete", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub({ onlineOnlyRisk: true });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "updateCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Pending local edit" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: pending delete/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));
    await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" });
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect(await screen.findByRole("alertdialog", { name: "Delete ‘Pending delete’?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog", { name: "Delete ‘Pending delete’?" })).not.toBeInTheDocument();
  });


  it("completes a successful workspace draft discard and returns to the canvas", async () => {
    const loaded = tree("tree-discard-success", "Discard success", "2026-09-20T10:00:00Z");
    const draft = recoveryDraft(loaded.id);
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "stale", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      discard: vi.fn().mockResolvedValue({ ok: true, cleared: true, mode: "durable", online_only_risk: false })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover stale draft" });
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    await screen.findByRole("heading", { name: "Discard draft?" });
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(await screen.findByRole("group", { name: "Current Reality Tree canvas" })).toBeInTheDocument();
  });

  it("marks the workspace unavailable when another writer claims the draft", async () => {
    const loaded = emptyTree("tree-owner-loss", "Owner loss");
    const coordinator = coordinatorStub({
      subscribe: vi.fn((listener: (change: { external: boolean; writer_session_id?: string }) => void) => {
        queueMicrotask(() => listener({ external: true, writer_session_id: "other-session" }));
        return vi.fn();
      })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    expect(await screen.findByRole("heading", { name: "This tree is open in another tab" })).toBeInTheDocument();
  });

  it("rejects a parsed import envelope without a tree name", async () => {
    const loaded = tree("tree-parse", "Parse tree", "2026-09-20T10:00:00Z");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    void label;
    fireEvent.click(screen.getByRole("button", { name: /current tree: parse tree/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Import tree JSON" }));
    const malformedEnvelope = Object.assign(new File([JSON.stringify({ tree: {} })], "bad.json", { type: "application/json" }), { text: async () => JSON.stringify({ tree: {} }) });
    fireEvent.change(screen.getByLabelText("Choose tree JSON file"), { target: { files: [malformedEnvelope] } });
    expect(await screen.findByText(/The selected file is not a CRT tree export/)).toBeInTheDocument();
    expect(screen.getByText(/Support reference:/)).toBeInTheDocument();
  });


  it("falls back to a deterministic idempotency key when page crypto is unavailable", async () => {
    const loaded = emptyTree("tree-crypto", "Crypto tree");
    const created = emptyTree("tree-crypto-created", "Created with fallback");
    vi.stubGlobal("crypto", { randomUUID: () => { throw new Error("crypto unavailable"); } });
    vi.stubGlobal("prompt", vi.fn().mockReturnValue("Fallback tree"));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    const createTree = vi.spyOn(crtApi, "createCrtTree").mockResolvedValue(created);
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    await screen.findByRole("button", { name: /current tree: crypto tree/i });
    fireEvent.click(screen.getByRole("button", { name: /current tree: crypto tree/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Create a new tree" }));
    await waitFor(() => expect(createTree).toHaveBeenCalled());
    expect(createTree.mock.calls[0]?.[1]?.idempotencyKey).toMatch(/^00000000-0000-4000-8000-/);
  });


  it("imports a valid envelope and installs the imported tree", async () => {
    const current = emptyTree("tree-import-current", "Current tree");
    const imported = emptyTree("tree-imported", "Imported tree");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: current.id, name: current.name, updated_at: current.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(current);
    vi.spyOn(crtApi, "importCrtTree").mockResolvedValue(imported);
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    await screen.findByRole("button", { name: /current tree: current tree/i });
    fireEvent.click(screen.getByRole("button", { name: /current tree: current tree/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Import tree JSON" }));
    const file = Object.assign(new File([JSON.stringify({ tree: imported })], "import.json", { type: "application/json" }), { text: async () => JSON.stringify({ tree: imported }) });
    await act(async () => { fireEvent.change(screen.getByLabelText("Choose tree JSON file"), { target: { files: [file] } }); });
    expect(await screen.findByRole("button", { name: /current tree: imported tree/i })).toBeInTheDocument();
  });

  it("fails open to the newest tree when owner-draft enumeration is unavailable", async () => {
    const loaded = emptyTree("tree-enumeration", "Enumeration fallback");
    const coordinator = coordinatorStub({
      enumerateOwnerDrafts: vi.fn().mockResolvedValue({ ok: false, reason: "storage-unavailable", mode: "online-only" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);

    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);

    expect(await screen.findByRole("button", { name: /current tree: enumeration fallback/i })).toBeInTheDocument();
    expect(coordinator.dispose).toHaveBeenCalled();
  });

  it("shows ownership loss when a pre-canonical draft is locked", async () => {
    const key = "00000000-0000-4000-8000-000000000091";
    const draft = recoveryDraft("ignored", { tree_id: null, create_idempotency_key: key });
    const scan = coordinatorStub({
      enumerateOwnerDrafts: vi.fn().mockResolvedValue({ ok: true, value: [{ draft, classification: "fresh" }], mode: "durable" })
    });
    const recovery = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "none", mode: "durable", online_only_risk: false, lock_state: "locked" })
    });
    const factory = vi.fn((options: { create_idempotency_key?: string | null }) => options.create_idempotency_key ? recovery : scan);
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);

    render(<CrtWorkspace createDraftCoordinator={factory as unknown as typeof createCrtDraftCoordinator} />);

    expect(await screen.findByRole("heading", { name: "This tree is open in another tab" })).toBeInTheDocument();
  });

  it("preserves an invalid pre-canonical draft at the recovery boundary", async () => {
    const key = "00000000-0000-4000-8000-000000000092";
    const draft = recoveryDraft("ignored", {
      tree_id: null,
      create_idempotency_key: key,
      tree: { name: "Broken first tree", nodes: [{ id: "", label: "", position: { x: Number.NaN, y: 0 } }], relations: [], layout: null }
    });
    const scan = coordinatorStub({
      enumerateOwnerDrafts: vi.fn().mockResolvedValue({ ok: true, value: [{ draft, classification: "fresh" }], mode: "durable" })
    });
    const recovery = coordinatorStub();
    const factory = vi.fn((options: { create_idempotency_key?: string | null }) => options.create_idempotency_key ? recovery : scan);
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);

    render(<CrtWorkspace createDraftCoordinator={factory as unknown as typeof createCrtDraftCoordinator} />);

    expect(await screen.findByRole("heading", { name: "We couldn't verify the local draft" })).toBeInTheDocument();
  });

  it("ignores a late startup list result after unmount and aborts its epoch", async () => {
    let resolveList!: (trees: never[]) => void;
    vi.spyOn(crtApi, "listCrtTrees").mockReturnValue(new Promise((resolve) => { resolveList = resolve; }));
    const rendered = render(<CrtWorkspace />);
    rendered.unmount();
    resolveList([]);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.body.querySelector("main")).not.toBeInTheDocument();
  });

  it("allows an online-only first create to proceed and reports API references", async () => {
    const created = emptyTree("tree-online-create", "Online create");
    const coordinator = coordinatorStub({
      onlineOnlyRisk: true,
      persistBeforeCreate: vi.fn().mockResolvedValue({ ok: false, mode: "online-only", online_only_risk: true })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    vi.spyOn(crtApi, "createCrtTree").mockResolvedValue(created);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("button", { name: "Create first tree" });
    fireEvent.click(screen.getByRole("button", { name: "Create first tree" }));
    expect(await screen.findByRole("button", { name: /current tree: online create/i })).toBeInTheDocument();
    expect(screen.getByText("Saved online only")).toBeInTheDocument();

    cleanup();
    vi.restoreAllMocks();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    vi.spyOn(crtApi, "createCrtTree").mockRejectedValue(new ApiError("Create failed", 503, { detail: "failed" }, "create-first-ref"));
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Create first tree" }));
    expect(await screen.findByText("Support reference: create-first-ref")).toBeInTheDocument();
  });

  it("reports in-flight replay, cleanup, queued persistence, and normal recovery failures", async () => {
    const loaded = emptyTree("tree-recovery-errors", "Recovery errors");
    const draft = recoveryDraft(loaded.id, {
      in_flight_save: { idempotency_key: "00000000-0000-4000-8000-000000000093", base_revision: 1, generation: 1, snapshot: recoveryDraft(loaded.id).tree, hash: "hash" }
    });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      replayInFlightSave: vi.fn().mockResolvedValue({ ok: false, replayed: false, reason: "replay-failed" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't recover the draft");

    cleanup();
    vi.restoreAllMocks();
    const cleanupDraft = recoveryDraft(loaded.id, {
      in_flight_save: { idempotency_key: "00000000-0000-4000-8000-000000000094", base_revision: 1, generation: 1, snapshot: recoveryDraft(loaded.id).tree, hash: "hash" }
    });
    const cleanupCoordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft: cleanupDraft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      replayInFlightSave: vi.fn().mockResolvedValue({ ok: true, replayed: true, response: loaded }),
      clearAfterCanonicalApplied: vi.fn().mockResolvedValue({ ok: false, reason: "cleanup-failed" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => cleanupCoordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't recover the draft");
  });

  it("discards a pre-canonical draft back to the empty state", async () => {
    const key = "00000000-0000-4000-8000-000000000095";
    const draft = recoveryDraft("ignored", { tree_id: null, create_idempotency_key: key });
    const coordinator = coordinatorStub({
      enumerateOwnerDrafts: vi.fn().mockResolvedValue({ ok: true, value: [{ draft, classification: "fresh" }], mode: "durable" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(await screen.findByText("No demo content is added for you.")).toBeInTheDocument();
  });

  it("covers the conflict comparison retry and local-backup actions", async () => {
    const loaded = emptyTree("tree-conflict-actions", "Conflict actions");
    const draft = recoveryDraft(loaded.id, { base_revision: 0 });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" })
    });
    const downloadBackup = vi.fn();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue({ ...loaded, revision: 1 });
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} downloadBackup={downloadBackup} />);
    await screen.findByRole("heading", { name: "Review the sync conflict" });
    fireEvent.click(screen.getByRole("button", { name: "Use server copy" }));
    fireEvent.click(screen.getByRole("button", { name: "Download local backup" }));
    expect(downloadBackup).toHaveBeenCalledOnce();
    await screen.findByText("Local backup downloaded.", { selector: "[aria-live]" });
    fireEvent.click(screen.getByRole("button", { name: /Discard 1 local edit and use server copy/ }));
    await waitFor(() => expect(coordinator.discard).toHaveBeenCalled());
  });

  it("rejects a second online-only risk discovered during pending discard", async () => {
    const loaded = tree("tree-risk-transition", "Risk transition", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub({ onlineOnlyRisk: false });
    let risk = false;
    Object.defineProperty(coordinator, "onlineOnlyRisk", { get: () => risk });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    risk = true;
    fireEvent.change(label, { target: { value: "Risky edit" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: risk transition/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));
    expect(await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect((await screen.findAllByRole("alert")).some((alert) => alert.textContent?.includes("Nothing was discarded"))).toBe(true);
  });

  it("offers and cancels a local backup before exporting the saved copy", async () => {
    const loaded = tree("tree-export-cancel", "Export cancel", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub();
    const downloadBackup = vi.fn();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "exportCrtTree").mockResolvedValue({ tree: loaded });
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} downloadBackup={downloadBackup} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved export" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: export cancel/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    expect(await screen.findByText(/unsynchronized changes are excluded/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download local backup" }));
    expect(downloadBackup).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: /current tree: export cancel/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/unsynchronized changes are excluded/i)).not.toBeInTheDocument();
  });

  it("keeps a generic delete failure recoverable", async () => {
    const loaded = emptyTree("tree-delete-generic", "Delete generic");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "deleteCrtTree").mockRejectedValue(new Error("network"));
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    await screen.findByRole("button", { name: /current tree: delete generic/i });
    fireEvent.click(screen.getByRole("button", { name: /current tree: delete generic/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete tree" }));
    expect((await screen.findAllByRole("alert")).some((alert) => alert.textContent?.includes("Nothing was deleted"))).toBe(true);
  });

  it("ignores late scan and tree-fetch epochs after unmount", async () => {
    const scan = coordinatorStub();
    let resolveScan!: (result: { ok: true; value: never[]; mode: "durable" }) => void;
    scan.enumerateOwnerDrafts = vi.fn().mockReturnValue(new Promise((resolve) => { resolveScan = resolve; }));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-late-scan", name: "Late scan", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    const rendered = render(<CrtWorkspace createDraftCoordinator={() => scan} />);
    await act(async () => { await Promise.resolve(); });
    rendered.unmount();
    resolveScan({ ok: true, value: [], mode: "durable" });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    let resolveTree!: (value: CrtTreeResponse) => void;
    vi.restoreAllMocks();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: "tree-late-fetch", name: "Late fetch", updated_at: "2026-09-20T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockReturnValue(new Promise((resolve) => { resolveTree = resolve; }));
    const second = render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    second.unmount();
    resolveTree(emptyTree("tree-late-fetch", "Late fetch"));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  });

  it("reports normal recovery and queued persistence failures without applying a draft", async () => {
    const loaded = emptyTree("tree-normal-recovery-error", "Normal recovery error");
    const draft = recoveryDraft(loaded.id);
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      recover: vi.fn().mockResolvedValue({ ok: false, reason: "recover-failed" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't recover the draft");

    cleanup();
    vi.restoreAllMocks();
    const queuedDraft = recoveryDraft(loaded.id, {
      in_flight_save: { idempotency_key: "00000000-0000-4000-8000-000000000096", base_revision: 1, generation: 1, snapshot: recoveryDraft(loaded.id).tree, hash: "hash" },
      queued_commands: [{ id: "00000000-0000-4000-8000-000000000097", kind: "tree-rename", payload: { name: "Queued failure" } }]
    });
    const queuedCoordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft: queuedDraft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      replayInFlightSave: vi.fn().mockResolvedValue({ ok: true, replayed: true, response: loaded }),
      completeInFlightRecovery: vi.fn().mockResolvedValue({ ok: false, reason: "queue-failed" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => queuedCoordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't recover the draft");
  });

  it("keeps a conflict local copy after refetch and exposes empty differences", async () => {
    const loaded = emptyTree("tree-keep-local", "Keep local");
    const draft = recoveryDraft(loaded.id, { base_revision: 0, dirty_operations: [] });
    const coordinator = coordinatorStub({ initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }) });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Review the sync conflict" });
    fireEvent.click(screen.getByRole("button", { name: "Review differences" }));
    expect(screen.getByText("Local graph changes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Keep local and retry" }));
    expect(await screen.findByRole("group", { name: "Current Reality Tree canvas" })).toBeInTheDocument();
  });

  it("keeps conflict recovery open when the server-copy discard fails", async () => {
    const loaded = emptyTree("tree-server-failure", "Server failure");
    const draft = recoveryDraft(loaded.id, { base_revision: 0 });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      discard: vi.fn().mockResolvedValue({ ok: false, reason: "discard-failed" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Review the sync conflict" });
    fireEvent.click(screen.getByRole("button", { name: "Use server copy" }));
    fireEvent.click(screen.getByRole("button", { name: /Discard 1 local edit and use server copy/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't open the server copy");
  });

  it("falls back from a replay without a canonical response and rejects an invalid recovered graph", async () => {
    const loaded = emptyTree("tree-replay-fallback", "Replay fallback");
    const draft = recoveryDraft(loaded.id, { in_flight_save: { idempotency_key: "00000000-0000-4000-8000-000000000099", base_revision: 1, generation: 1, snapshot: recoveryDraft(loaded.id).tree, hash: "hash" } });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      replayInFlightSave: vi.fn().mockResolvedValue({ ok: true, replayed: true }),
      recover: vi.fn().mockResolvedValue({ ok: true, draft })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(await screen.findByRole("group", { name: "Current Reality Tree canvas" })).toBeInTheDocument();

    cleanup();
    vi.clearAllMocks();
    const invalidCoordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      replayInFlightSave: vi.fn().mockResolvedValue({ ok: true, replayed: false }),
      recover: vi.fn().mockResolvedValue({ ok: true, draft: { ...draft, tree: { name: "bad", nodes: [{ id: "", label: "", position: { x: Number.NaN, y: 0 } }], relations: [], layout: null } } })
    });
    vi.mocked(crtApi.listCrtTrees).mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.mocked(crtApi.getCrtTree).mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => invalidCoordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't recover the draft");
  });
  it("exercises every pending-work transition action and cancellation", async () => {
    const loaded = tree("tree-pending-actions", "Pending actions", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub({ onlineOnlyRisk: true });
    const backup = coordinator.backup as ReturnType<typeof vi.fn>;
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }, { id: "tree-other", name: "Other", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Pending edit" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: pending actions/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Other" }));
    const pending = await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" });
    expect(pending).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stay and retry" }));
    await screen.findByText("Save retry started.", { selector: "[aria-live]" });
    fireEvent.click(screen.getByRole("button", { name: "Download backup" }));
    await screen.findByText("Backup download started.", { selector: "[aria-live]" });
    expect(backup).toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
  });

  it("fails closed for pending enumeration and discard errors", async () => {
    const loaded = tree("tree-pending-errors", "Pending errors", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub({ onlineOnlyRisk: true });
    coordinator.enumerateOwnerDrafts = vi.fn()
      .mockResolvedValueOnce({ ok: true, value: [], mode: "durable" })
      .mockResolvedValueOnce({ ok: true, value: [], mode: "durable" })
      .mockResolvedValueOnce({ ok: false, reason: "enumeration-failed", mode: "durable" });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }, { id: "tree-other", name: "Other", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Pending edit" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: pending errors/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Other" }));
    await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" });
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect((await screen.findAllByRole("alert")).some((alert) => alert.textContent?.includes("verify every unsynced change"))).toBe(true);

    cleanup();
    vi.restoreAllMocks();
    const discardCoordinator = coordinatorStub({ onlineOnlyRisk: true, discardOwnerDrafts: vi.fn().mockResolvedValue({ ok: false, reason: "discard-failed" }) });
    discardCoordinator.enumerateOwnerDrafts = vi.fn().mockResolvedValue({ ok: true, value: [], mode: "durable" });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }, { id: "tree-other", name: "Other", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => discardCoordinator} />);
    const discardLabel = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(discardLabel, { target: { value: "Discard error" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: pending errors/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Other" }));
    await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" });
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect((await screen.findAllByRole("alert")).some((alert) => alert.textContent?.includes("couldn't discard the local changes"))).toBe(true);
  });

  it("covers generic startup failure, retry, and unauthenticated owner handling", async () => {
    const loaded = tree("tree-retry-load", "Retry load", "2026-09-20T10:00:00Z");
    const list = vi.spyOn(crtApi, "listCrtTrees")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace />);
    expect(await screen.findByRole("heading", { name: "We couldn't load this tree" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  });

  it("fails closed when the authenticated owner is unavailable", async () => {
    useAuthStore.setState({ user: null, status: "authed" });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace />);
    expect(await screen.findByRole("heading", { name: "We couldn't verify this tree" })).toBeInTheDocument();
  });

  it("handles owner-draft scan entries without create keys and stale pre-canonical recovery", async () => {
    const noKey = recoveryDraft(null, { create_idempotency_key: null });
    const scan = coordinatorStub({ enumerateOwnerDrafts: vi.fn().mockResolvedValue({ ok: true, value: [{ draft: noKey, classification: "none" }], mode: "durable" }) });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace createDraftCoordinator={() => scan} />);
    expect(await screen.findByRole("heading", { name: "Start with your first undesired effect" })).toBeInTheDocument();
    expect(scan.dispose).toHaveBeenCalled();

    cleanup();
    vi.clearAllMocks();
    vi.mocked(crtApi.listCrtTrees).mockResolvedValue([]);
    const key = "00000000-0000-4000-8000-000000000098";
    const stale = recoveryDraft(null, { create_idempotency_key: key });
    const scanStale = coordinatorStub({ enumerateOwnerDrafts: vi.fn().mockResolvedValue({ ok: true, value: [{ draft: stale, classification: "stale" }], mode: "durable" }) });
    const recoveryCoordinator = coordinatorStub({ onlineOnlyRisk: true, initialize: vi.fn().mockResolvedValue({ classification: "stale", draft: stale, mode: "online-only", online_only_risk: true, lock_state: "unavailable" }) });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace createDraftCoordinator={(options) => options.create_idempotency_key ? recoveryCoordinator : scanStale} />);
    expect(await screen.findByRole("heading", { name: "Recover stale draft" })).toBeInTheDocument();
  });

  it("reports generic management failures and ignores no-op prompts", async () => {
    const loaded = tree("tree-management-errors", "Management errors", "2026-09-20T10:00:00Z");
    const created = emptyTree("tree-created-error", "Created error");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "createCrtTree").mockRejectedValue(new Error("create failed"));
    vi.spyOn(crtApi, "updateCrtTree").mockRejectedValue(new Error("rename failed"));
    vi.spyOn(crtApi, "exportCrtTree").mockRejectedValue(new Error("export failed"));
    vi.spyOn(crtApi, "importCrtTree").mockRejectedValue("import failed");
    vi.stubGlobal("prompt", vi.fn().mockReturnValueOnce(null).mockReturnValueOnce("New tree").mockReturnValueOnce("Renamed"));
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    await screen.findByRole("button", { name: /current tree: management errors/i });
    fireEvent.click(screen.getByRole("button", { name: /current tree: management errors/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Create a new tree" }));
    await act(async () => { await Promise.resolve(); });
    expect(crtApi.createCrtTree).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /current tree: management errors/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Create a new tree" }));
    expect(await screen.findByText("We couldn't create this tree.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /current tree: management errors/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename tree" }));
    expect(await screen.findByText("We couldn't rename this tree.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /current tree: management errors/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    expect(await screen.findByText("We couldn't export this tree.")).toBeInTheDocument();

    const input = screen.getByLabelText("Choose tree JSON file");
    const invalidImport = Object.assign(new File([JSON.stringify({ tree: created })], "tree.json", { type: "application/json" }), { text: async () => JSON.stringify({ tree: created }) });
    fireEvent.change(input, { target: { files: [invalidImport] } });
    expect(await screen.findByText(/We couldn't import this tree/)).toBeInTheDocument();
  });

  it("keeps empty-state management actions safely inert", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    await screen.findByRole("heading", { name: "Start with your first undesired effect" });
    fireEvent.click(screen.getByRole("button", { name: "Choose a tree to continue" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename tree" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));
    expect(screen.getByRole("heading", { name: "Start with your first undesired effect" })).toBeInTheDocument();
  });
  it("uses a safe export filename and reports non-Error local backup failures", async () => {
    const loaded = tree("tree-symbol-name", "!!!", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub({ backup: vi.fn().mockImplementation(() => { throw "backup-failed"; }) });
    const downloadBackup = vi.fn();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "exportCrtTree").mockResolvedValue({ tree: loaded });
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} downloadBackup={downloadBackup} />);
    expect(await screen.findByRole("button", { name: /current tree: !!!/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /current tree: !!!/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    await waitFor(() => expect(downloadBackup).toHaveBeenCalledWith(expect.objectContaining({ filename: "crt-tree.json" })));

    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved backup" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: !!!/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    expect(await screen.findByText(/unsynchronized changes are excluded/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download local backup" }));
    expect(await screen.findByText("Local backup is unavailable.")).toBeInTheDocument();
  });

  it("renders conflict copies with missing revisions and an invalid boundary without a reference", async () => {
    const loaded = emptyTree("tree-missing-revision", "Missing revision");
    const draft = recoveryDraft(loaded.id, { base_revision: null });
    const coordinator = coordinatorStub({ initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }) });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    expect(await screen.findByRole("heading", { name: "Review the sync conflict" })).toBeInTheDocument();

    cleanup();
    vi.clearAllMocks();
    const invalid = coordinatorStub({ initialize: vi.fn().mockResolvedValue({ classification: "invalid", mode: "durable", online_only_risk: false, lock_state: "unavailable" }) });
    vi.mocked(crtApi.listCrtTrees).mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => invalid} />);
    expect(await screen.findByRole("heading", { name: "We couldn't verify the local draft" })).toBeInTheDocument();
    expect(screen.queryByText(/Recovery reference/)).not.toBeInTheDocument();
  });
  it("keeps a stale draft after discard failure and retries the discard", async () => {
    const loaded = emptyTree("tree-discard-retry", "Discard retry");
    const draft = recoveryDraft(loaded.id);
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      discard: vi.fn().mockResolvedValueOnce({ ok: false, reason: "storage" }).mockResolvedValueOnce({ ok: true, cleared: true, mode: "durable", online_only_risk: false })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't discard the draft");
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(await screen.findByRole("group", { name: "Current Reality Tree canvas" })).toBeInTheDocument();
  });

  it("fails closed when pending enumeration fails before opening a transition", async () => {
    const loaded = tree("tree-enumeration-transition", "Enumeration transition", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub({
      enumerateOwnerDrafts: vi.fn()
        .mockResolvedValueOnce({ ok: true, value: [], mode: "durable" })
        .mockResolvedValueOnce({ ok: false, reason: "storage", mode: "durable" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }, { id: "tree-other", name: "Other", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: enumeration transition/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Other" }));
    expect(await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
    expect(screen.getAllByRole("alert").some((alert) => alert.textContent?.includes("verify every unsynced change"))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect((await screen.findAllByRole("alert")).some((alert) => alert.textContent?.includes("verify every unsynced change"))).toBe(true);
  });
  it("keeps startup error handling quiet after an aborted rejection and retries a loaded-tree failure", async () => {
    let rejectList!: (reason?: unknown) => void;
    vi.spyOn(crtApi, "listCrtTrees").mockReturnValue(new Promise((_resolve, reject) => { rejectList = reject; }));
    const rendered = render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    rendered.unmount();
    await act(async () => { rejectList(new Error("late list failure")); await Promise.resolve(); });

    cleanup();
    vi.clearAllMocks();
    const loaded = tree("tree-load-retry-error", "Load retry error", "2026-09-20T10:00:00Z");
    vi.mocked(crtApi.listCrtTrees).mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockRejectedValueOnce(new Error("tree fetch failed")).mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    expect(await screen.findByRole("heading", { name: "We couldn't load this tree" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    expect(await screen.findByRole("button", { name: /current tree: load retry error/i })).toBeInTheDocument();
  });

  it("lets an invalid recovery boundary retry startup", async () => {
    const loaded = emptyTree("tree-invalid-retry", "Invalid retry");
    const coordinator = coordinatorStub({ initialize: vi.fn()
      .mockResolvedValueOnce({ classification: "invalid", reason: "invalid-json", mode: "durable", online_only_risk: false, lock_state: "unavailable" })
      .mockResolvedValue({ classification: "none", mode: "durable", online_only_risk: false, lock_state: "unavailable" }) });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    expect(await screen.findByRole("heading", { name: "We couldn't verify the local draft" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    expect(await screen.findByRole("button", { name: /current tree: invalid retry/i })).toBeInTheDocument();
  });
  it("persists an edited graph through the coordinator adapter", async () => {
    const loaded = tree("tree-persist-adapter", "Persist adapter", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "updateCrtTree").mockResolvedValue({ ...loaded, revision: 2 });
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Persisted change" } });
    await waitFor(() => expect(coordinator.persistCommand).toHaveBeenCalled(), { timeout: 2000 });
  });
  it("covers pending enumeration entries, generic backup failure, and external ownership loss", async () => {
    const loaded = tree("tree-pending-enumerated", "Pending enumerated", "2026-09-20T10:00:00Z");
    const other = recoveryDraft(null, { create_idempotency_key: null, tree: { name: "Named fallback", nodes: [], relations: [], layout: null }, dirty_operations: [], queued_commands: [] });
    const coordinator = coordinatorStub({
      enumerateOwnerDrafts: vi.fn()
        .mockResolvedValueOnce({ ok: true, value: [], mode: "durable" })
        .mockResolvedValueOnce({ ok: true, value: [{ draft: recoveryDraft(loaded.id) }, { draft: other }], mode: "durable" })
        .mockResolvedValueOnce({ ok: true, value: [{ draft: recoveryDraft(loaded.id) }, { draft: other }], mode: "durable" }),
      backup: vi.fn().mockImplementation(() => { throw "backup unavailable"; })
    });
    let onOwnershipChange!: (change: { external: boolean; writer_session_id?: string }) => void;
    coordinator.subscribe = vi.fn((listener: (change: { external: boolean; writer_session_id?: string }) => void) => { onOwnershipChange = listener; return vi.fn(); });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }, { id: "tree-other", name: "Other", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    expect(await screen.findByRole("button", { name: /current tree: pending enumerated/i })).toBeInTheDocument();
    const label = screen.getByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: pending enumerated/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Other" }));
    const pending = await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" });
    expect(pending).toHaveTextContent("Named fallback");
    fireEvent.click(screen.getByRole("button", { name: "Download backup" }));
    expect((await screen.findAllByText("We couldn't prepare the backup. Nothing was discarded.")).length).toBeGreaterThan(0);
    act(() => onOwnershipChange({ external: true, writer_session_id: "writer-2" }));
    expect(await screen.findByRole("heading", { name: "This tree is open in another tab" })).toBeInTheDocument();
  });

  it("covers UUID fallback when the page exposes no randomUUID implementation", async () => {
    const loaded = emptyTree("tree-safe-uuid", "Safe UUID");
    vi.stubGlobal("crypto", {});
    vi.stubGlobal("prompt", vi.fn().mockReturnValue("Fallback key tree"));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    const createTree = vi.spyOn(crtApi, "createCrtTree").mockResolvedValue(emptyTree("tree-created-fallback", "Fallback key tree"));
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    await screen.findByRole("button", { name: /current tree: safe uuid/i });
    fireEvent.click(screen.getByRole("button", { name: /current tree: safe uuid/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Create a new tree" }));
    await waitFor(() => expect(createTree).toHaveBeenCalled());
    expect(createTree.mock.calls[0]?.[1]?.idempotencyKey).toMatch(/^00000000-0000-4000-8000-/);
  });

  it("shows entity-specific recovery summaries for conflicting local operations", async () => {
    const loaded = emptyTree("tree-entity-conflict", "Entity conflict");
    const draft = recoveryDraft(loaded.id, {
      base_revision: 0,
      dirty_operations: [{ id: "00000000-0000-4000-8000-000000000101", kind: "label-edit", entity_id: "node-1" }]
    });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    expect(await screen.findByRole("heading", { name: "Review the sync conflict" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review differences" }));
    expect(screen.getByText("label-edit (node-1)")).toBeInTheDocument();
  });

  it("reports the in-flight pending edit count in the transition barrier", async () => {
    const loaded = tree("tree-inflight-pending", "In-flight pending", "2026-09-20T10:00:00Z");
    const otherDraft = recoveryDraft("tree-other-inflight", {
      tree: { name: "Other in-flight", nodes: [], relations: [], layout: null },
      dirty_operations: [],
      queued_commands: [],
      in_flight_save: { idempotency_key: "00000000-0000-4000-8000-000000000102", base_revision: 1, generation: 1, snapshot: recoveryDraft("tree-other-inflight").tree, hash: "hash" }
    });
    const coordinator = coordinatorStub();
    coordinator.enumerateOwnerDrafts = vi.fn()
      .mockResolvedValueOnce({ ok: true, value: [], mode: "durable" })
      .mockResolvedValueOnce({ ok: true, value: [{ draft: otherDraft }], mode: "durable" });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" },
      { id: "tree-other-inflight", name: "Other in-flight", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved current" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: in-flight pending/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Other in-flight" }));
    expect(await screen.findByText("Other in-flight · 1 unsynced edit")).toBeInTheDocument();
  });

  it("renders a save support reference when the server rejects an edit", async () => {
    const loaded = tree("tree-save-reference", "Save reference", "2026-09-20T10:00:00Z");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "updateCrtTree").mockRejectedValue(new ApiError("Save failed", 503, { detail: "unavailable" }, "save-reference"));
    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    vi.useFakeTimers();
    fireEvent.change(label, { target: { value: "Local save" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText("Save failed", { selector: ".crt-save-status" })).toBeInTheDocument();
    expect(screen.getByText("Support reference: save-reference")).toBeInTheDocument();
  });

  it("retries startup after ownership loss and restores the editable tree", async () => {
    const loaded = emptyTree("tree-ownership-retry", "Ownership retry");
    const locked = coordinatorStub({ initialize: vi.fn().mockResolvedValue({ classification: "none", mode: "durable", online_only_risk: false, lock_state: "locked" }) });
    const available = coordinatorStub();
    let factoryCalls = 0;
    const factory = vi.fn(() => factoryCalls++ === 1 ? locked : available);
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={factory} />);
    expect(await screen.findByRole("heading", { name: "This tree is open in another tab" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry ownership" }));
    expect(await screen.findByRole("button", { name: /current tree: ownership retry/i })).toBeInTheDocument();
    expect(factory).toHaveBeenCalledTimes(4);
  });

  it("uses safe defaults when optional workspace dependencies are explicitly undefined", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace createDraftCoordinator={undefined} downloadBackup={undefined} />);
    expect(await screen.findByRole("heading", { name: "Start with your first undesired effect" })).toBeInTheDocument();
  });

  it("uses an empty origin when the location has no origin", async () => {
    const loaded = emptyTree("tree-no-origin", "No origin");
    const previousLocation = globalThis.location;
    vi.stubGlobal("location", { href: "http://localhost/", origin: undefined });
    try {
      vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
      vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
      render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
      expect(await screen.findByRole("button", { name: /current tree: no origin/i })).toBeInTheDocument();
    } finally {
      vi.stubGlobal("location", previousLocation);
    }
  });

  it("keeps deletion navigable when the location origin is absent", async () => {
    const loaded = emptyTree("tree-delete-no-origin", "Delete no origin");
    const previousLocation = globalThis.location;
    vi.stubGlobal("location", { href: "http://localhost/", origin: undefined });
    try {
      vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
      vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
      vi.spyOn(crtApi, "deleteCrtTree").mockResolvedValue(undefined);
      render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
      await screen.findByRole("button", { name: /current tree: delete no origin/i });
      fireEvent.click(screen.getByRole("button", { name: /current tree: delete no origin/i }));
      fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));
      fireEvent.click(await screen.findByRole("button", { name: "Delete tree" }));
      await waitFor(() => expect(crtApi.deleteCrtTree).toHaveBeenCalled());
    } finally {
      vi.stubGlobal("location", previousLocation);
    }
  });

  it("treats an unavailable coordinator risk flag as the safe durable default", async () => {
    const loaded = emptyTree("tree-missing-risk", "Missing risk");
    const coordinator = coordinatorStub({ onlineOnlyRisk: undefined });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    expect(await screen.findByRole("button", { name: /current tree: missing risk/i })).toBeInTheDocument();
    expect(screen.queryByText("Saved online only")).not.toBeInTheDocument();
  });

  it("stops safely when the remaining tree id cannot be selected after deletion", async () => {
    const loaded = emptyTree("tree-malformed-delete", "Malformed delete");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" },
      { id: "", name: "Malformed remaining", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "deleteCrtTree").mockResolvedValue(undefined);
    render(<CrtWorkspace />);
    await screen.findByRole("button", { name: /current tree: malformed delete/i });
    fireEvent.click(screen.getByRole("button", { name: /current tree: malformed delete/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete tree" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete tree" }));
    await waitFor(() => expect(crtApi.deleteCrtTree).toHaveBeenCalled());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("fails closed when auth disappears during first-tree activation", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace createDraftCoordinator={() => coordinatorStub()} />);
    const button = await screen.findByRole("button", { name: "Create first tree" });
    const clearAuth = () => useAuthStore.setState({ user: null, status: "anon" });
    document.addEventListener("click", clearAuth, { capture: true, once: true });
    fireEvent.click(button);
    expect(await screen.findByRole("heading", { name: "We couldn't verify this tree" })).toBeInTheDocument();
  });

  it("recovers an online-only draft classification without dropping the local copy", async () => {
    const loaded = emptyTree("tree-online-only-recovery", "Online-only recovery");
    const draft = recoveryDraft(loaded.id);
    const coordinator = coordinatorStub({
      onlineOnlyRisk: true,
      initialize: vi.fn().mockResolvedValue({ classification: "online-only", draft, mode: "online-only", online_only_risk: true, lock_state: "unavailable" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
    expect(screen.queryByText("Saved online only")).not.toBeInTheDocument();
  });


  it("retains a deferred draft as pending work before switching trees", async () => {
    const loaded = emptyTree("tree-deferred-transition", "Deferred transition");
    const draft = recoveryDraft(loaded.id);
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" },
      { id: "tree-deferred-other", name: "Deferred other", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Recover draft" })).toHaveFocus());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(await screen.findByText(/Local draft retained/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /current tree: deferred transition/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Deferred other" }));
    expect(await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
  });

  it("reports a generic tree-switch failure without a support reference", async () => {
    const loaded = emptyTree("tree-switch-generic", "Switch generic");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" },
      { id: "tree-switch-other", name: "Switch other", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValueOnce(loaded).mockRejectedValueOnce(new Error("switch unavailable"));
    render(<CrtWorkspace />);
    await screen.findByRole("button", { name: /current tree: switch generic/i });
    fireEvent.click(screen.getByRole("button", { name: /current tree: switch generic/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Switch other" }));
    expect(await screen.findByText("We couldn't switch trees.")).toBeInTheDocument();
  });

  it("reports a generic import Error separately from non-Error import failures", async () => {
    const loaded = emptyTree("tree-import-generic", "Import generic");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "importCrtTree").mockRejectedValue(new Error("import unavailable"));
    render(<CrtWorkspace />);
    await screen.findByRole("button", { name: /current tree: import generic/i });
    fireEvent.click(screen.getByRole("button", { name: /current tree: import generic/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Import tree JSON" }));
    const file = Object.assign(new File([JSON.stringify(loaded)], "import.json", { type: "application/json" }), { text: async () => JSON.stringify(loaded) });
    fireEvent.change(screen.getByLabelText("Choose tree JSON file"), { target: { files: [file] } });
    expect(await screen.findByText(/import unavailable/)).toBeInTheDocument();
  });

  it("reconciles a pre-canonical draft without a page origin", async () => {
    const createKey = "00000000-0000-4000-8000-000000000121";
    const draft = recoveryDraft(null, { create_idempotency_key: createKey });
    const scanCoordinator = coordinatorStub({
      enumerateOwnerDrafts: vi.fn().mockResolvedValue({ ok: true, value: [{ draft, classification: "fresh" }], mode: "durable" })
    });
    const recoveryCoordinator = coordinatorStub();
    const loaded = emptyTree("tree-origin-reconciled", "Origin reconciled");
    const previousLocation = globalThis.location;
    vi.stubGlobal("location", { href: "http://localhost/", origin: undefined });
    try {
      vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
      vi.spyOn(crtApi, "createCrtTree").mockResolvedValue(loaded);
      const factory = (options: CrtDraftCoordinatorOptions) => options.create_idempotency_key ? recoveryCoordinator : scanCoordinator;
      render(<CrtWorkspace createDraftCoordinator={factory} />);
      expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
      expect(await screen.findByRole("button", { name: /current tree: origin reconciled/i })).toBeInTheDocument();
    } finally {
      vi.stubGlobal("location", previousLocation);
    }
  });

  it("fails safely when a pre-canonical draft changes before recovery", async () => {
    const createKey = "00000000-0000-4000-8000-000000000122";
    const draft = recoveryDraft(null, { create_idempotency_key: createKey });
    const scanCoordinator = coordinatorStub({
      enumerateOwnerDrafts: vi.fn().mockResolvedValue({ ok: true, value: [{ draft, classification: "fresh" }], mode: "durable" })
    });
    const recoveryCoordinator = coordinatorStub();
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    const factory = (options: CrtDraftCoordinatorOptions) => options.create_idempotency_key ? recoveryCoordinator : scanCoordinator;
    render(<CrtWorkspace createDraftCoordinator={factory} />);
    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
    Object.assign(draft, { tree: { name: "Broken", nodes: [{}], relations: [], layout: null } });
    fireEvent.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(await screen.findByRole("heading", { name: "We couldn't create this tree" })).toBeInTheDocument();
  });

  it("keeps a conflict alert without a support reference when the API omits correlation data", async () => {
    const loaded = tree("tree-conflict-no-reference", "Conflict no reference", "2026-09-20T10:00:00Z");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "updateCrtTree").mockRejectedValue(new ApiError("Conflict", 409, { detail: { reason: "stale_revision" } }));
    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    vi.useFakeTimers();
    fireEvent.change(label, { target: { value: "Local conflict" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText(/server changed this tree/i)).toBeInTheDocument();
    expect(screen.queryByText(/Support reference:/)).not.toBeInTheDocument();
  });

  it("retains the pending barrier when an online-only save is reported and cancels it with Escape", async () => {
    const loaded = tree("tree-online-save", "Online save", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub({
      persistCommand: vi.fn().mockResolvedValue({ ok: true, mode: "online-only", online_only_risk: true })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" },
      { id: "tree-online-other", name: "Online other", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "updateCrtTree").mockRejectedValue(new Error("offline"));
    const previousOnline = navigator.onLine;
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    try {
      render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
      const label = await screen.findByRole("textbox", { name: "Card label" });
      vi.useFakeTimers();
      fireEvent.change(label, { target: { value: "Online-only edit" } });
      await act(async () => { await vi.advanceTimersByTimeAsync(300); await Promise.resolve(); await Promise.resolve(); });
      vi.useRealTimers();
      expect(screen.getByText("Saved online only")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /current tree: online save/i }));
      fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Online other" }));
      expect(await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
      fireEvent.keyDown(document, { key: "Escape" });
      await waitFor(() => {
        expect(screen.queryByRole("dialog", { name: "Resolve unsynced changes before continuing" })).not.toBeInTheDocument();
      });
    } finally {
      Object.defineProperty(navigator, "onLine", { configurable: true, value: previousOnline });
    }
  });

  it("uses the empty page origin while creating the first tree", async () => {
    const created = emptyTree("tree-empty-origin-created", "Originless first tree");
    const previousLocation = globalThis.location;
    const factory = vi.fn((options: CrtDraftCoordinatorOptions) => coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "none", mode: "durable", online_only_risk: false, lock_state: "unavailable" }),
      rekeyAfterCreate: vi.fn().mockResolvedValue({ ok: true, value: { generation: 1 }, mode: "durable" }),
      options
    }));
    vi.stubGlobal("location", { href: "http://localhost/", origin: undefined });
    try {
      vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
      vi.spyOn(crtApi, "createCrtTree").mockResolvedValue(created);
      render(<CrtWorkspace createDraftCoordinator={factory} />);
      fireEvent.click(await screen.findByRole("button", { name: "Create first tree" }));
      expect(await screen.findByRole("button", { name: /current tree: originless first tree/i })).toBeInTheDocument();
      expect(factory.mock.calls.some(([options]) => options.origin === "")).toBe(true);
    } finally {
      vi.stubGlobal("location", previousLocation);
    }
  });

  it("blocks rename while local edits are unsynchronized", async () => {
    const loaded = tree("tree-rename-barrier", "Rename barrier", "2026-09-20T10:00:00Z");
    const updateTree = vi.spyOn(crtApi, "updateCrtTree");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.stubGlobal("prompt", vi.fn().mockReturnValue("Renamed locally"));
    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved rename barrier" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: rename barrier/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename tree" }));
    expect(await screen.findByText("Save or resolve local changes before changing trees.")).toBeInTheDocument();
    expect(updateTree).not.toHaveBeenCalled();
  });

  it("blocks management creation while unsaved work is present", async () => {
    const loaded = tree("tree-create-barrier", "Create barrier", "2026-09-20T10:00:00Z");
    const createTree = vi.spyOn(crtApi, "createCrtTree");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.stubGlobal("prompt", vi.fn().mockReturnValue("Blocked create"));
    render(<CrtWorkspace />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Unsaved create barrier" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: create barrier/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Create a new tree" }));
    expect(await screen.findByText("Save or resolve local changes before changing trees.")).toBeInTheDocument();
    expect(createTree).not.toHaveBeenCalled();
  });

  it("fails closed when auth is cleared immediately before first-tree activation", async () => {
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace />);
    const create = await screen.findByRole("button", { name: "Create first tree" });
    act(() => { useAuthStore.setState({ user: null, status: "anon" }); });
    fireEvent.click(create);
    expect(await screen.findByRole("heading", { name: "We couldn't verify this tree" })).toBeInTheDocument();
  });

  it("keeps callback guards safe for current-tree no-ops and unmounted recovery actions", async () => {
    const loaded = tree("tree-callback-guards", "Callback guards", "2026-09-20T10:00:00Z");
    const menu = vi.spyOn(crtTreeMenuModule, "CrtTreeMenu");
    const recoveryDialog = vi.spyOn(crtRecoveryDialogModule, "CrtRecoveryDialog");
    const pendingDialog = vi.spyOn(crtDeleteConfirmationModule, "CrtPendingWorkDialog");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace />);
    await screen.findByRole("button", { name: /current tree: callback guards/i });
    const menuProps = menu.mock.calls[menu.mock.calls.length - 1]?.[0];
    expect(menuProps).toBeDefined();
    await act(async () => { await menuProps?.onSelectTree(loaded.id); });

    cleanup();
    vi.clearAllMocks();
    const draft = recoveryDraft(loaded.id);
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    const recoveryProps = recoveryDialog.mock.calls[recoveryDialog.mock.calls.length - 1]?.[0];
    expect(recoveryProps).toBeDefined();
    cleanup();
    await act(async () => {
      if (recoveryProps && "onRecover" in recoveryProps) {
        await recoveryProps.onRecover();
        await recoveryProps.onDiscard();
      }
    });

    const pendingProps = pendingDialog.mock.calls[pendingDialog.mock.calls.length - 1]?.[0];
    if (pendingProps?.onDiscardAndContinue) {
      await act(async () => { await pendingProps.onDiscardAndContinue(); });
    }
  });

  it("invokes the empty-state management callbacks without opening a tree", async () => {
    const menu = vi.spyOn(crtTreeMenuModule, "CrtTreeMenu");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    render(<CrtWorkspace />);
    await screen.findByRole("heading", { name: "Start with your first undesired effect" });
    const props = menu.mock.calls[menu.mock.calls.length - 1]?.[0];
    expect(props).toBeDefined();
    await act(async () => {
      await props?.onRename();
      await props?.onExport();
      await props?.onDelete();
    });
  });

  it("keeps recovery callbacks safe across conflict refresh and invalid local data", async () => {
    const loaded = emptyTree("tree-recovery-callbacks", "Recovery callbacks");
    const draft = recoveryDraft(loaded.id, { base_revision: 0 });
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" })
    });
    const recoveryDialog = vi.spyOn(crtRecoveryDialogModule, "CrtRecoveryDialog");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Review the sync conflict" });
    const props = recoveryDialog.mock.calls[recoveryDialog.mock.calls.length - 1]?.[0];
    if (props && props.kind === "conflict") {
      await act(async () => { await props.onRetryComparison?.(); });
      cleanup();
      await expect(props.onUseServerCopy()).resolves.toBeUndefined();
      draft.tree = { name: "Broken", nodes: [{ id: "", label: "", position: { x: Number.NaN, y: 0 } }], relations: [], layout: null };
      await expect(props.onKeepLocalAndRetry()).rejects.toThrow("Local draft failed integrity checks");
    }
  });

  it("fails safely when a pending transition callback runs after unmount", async () => {
    const loaded = tree("tree-pending-unmounted", "Pending unmounted", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub();
    const pendingDialog = vi.spyOn(crtDeleteConfirmationModule, "CrtPendingWorkDialog");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([
      { id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" },
      { id: "tree-pending-other", name: "Pending other", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }
    ]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Pending edit" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: pending unmounted/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Pending other" }));
    await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" });
    const props = pendingDialog.mock.calls[pendingDialog.mock.calls.length - 1]?.[0];
    expect(props).toBeDefined();
    cleanup();
    await expect(props?.onDiscardAndContinue()).resolves.toBeUndefined();
  });

  it("does not clear a newer management key when duplicate creates overlap", async () => {
    const loaded = emptyTree("tree-overlap-base", "Overlap base");
    const first = emptyTree("tree-overlap-first", "First overlap");
    const second = emptyTree("tree-overlap-second", "Second overlap");
    let resolveFirst!: (value: CrtTreeResponse) => void;
    let resolveSecond!: (value: CrtTreeResponse) => void;
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    vi.spyOn(crtApi, "createCrtTree")
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));
    const menu = vi.spyOn(crtTreeMenuModule, "CrtTreeMenu");
    vi.stubGlobal("prompt", vi.fn().mockReturnValueOnce("First overlap").mockReturnValueOnce("Second overlap"));
    render(<CrtWorkspace />);
    await screen.findByRole("button", { name: /current tree: overlap base/i });
    const props = menu.mock.calls[menu.mock.calls.length - 1]?.[0];
    expect(props).toBeDefined();
    let firstCreate!: Promise<void> | void;
    let secondCreate!: Promise<void> | void;
    await act(async () => {
      firstCreate = props?.onCreate();
      secondCreate = props?.onCreate();
      resolveFirst(first);
      resolveSecond(second);
      await firstCreate;
      await secondCreate;
    });
    expect(crtApi.createCrtTree).toHaveBeenCalledTimes(2);
  });

  it("ignores a create completion after a new startup epoch begins", async () => {
    const created = emptyTree("tree-stale-create", "Stale create");
    let resolveCreate!: (value: CrtTreeResponse) => void;
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    vi.spyOn(crtApi, "createCrtTree").mockReturnValue(new Promise((resolve) => { resolveCreate = resolve; }));
    render(<CrtWorkspace />);
    const create = await screen.findByRole("button", { name: "Create first tree" });
    fireEvent.click(create);
    act(() => { useAuthStore.setState({ user: null, status: "anon" }); });
    resolveCreate(created);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.queryByText("Stale create")).not.toBeInTheDocument();
  });

  it("reopens a deferred draft from its retained-local-work banner", async () => {
    const loaded = emptyTree("tree-review-deferred", "Review deferred");
    const draft = recoveryDraft(loaded.id);
    const coordinator = coordinatorStub({
      initialize: vi.fn().mockResolvedValue({ classification: "fresh", draft, mode: "durable", online_only_risk: false, lock_state: "unavailable" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    await screen.findByRole("heading", { name: "Recover local draft" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Recover draft" })).toHaveFocus());
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(await screen.findByRole("button", { name: "Review local draft" }));
    expect(await screen.findByRole("heading", { name: "Recover local draft" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Current Reality Tree canvas" })).not.toBeInTheDocument();
  });

  it("surfaces structured import reasons and the ApiError fallback message", async () => {
    const loaded = emptyTree("tree-import-reasons", "Import reasons");
    const importTree = vi.spyOn(crtApi, "importCrtTree")
      .mockRejectedValueOnce(new ApiError("ignored", 422, { detail: { reason: "reason from validation" } }, "reason-ref"))
      .mockRejectedValueOnce(new ApiError("ignored", 422, { detail: { message: "message from validation" } }, "message-ref"))
      .mockRejectedValueOnce(new ApiError("fallback from ApiError", 422, { detail: {} }, "fallback-ref"))
      .mockRejectedValueOnce(new ApiError("fallback without detail", 422, { unexpected: true }, "no-detail-ref"))
      .mockRejectedValueOnce(new ApiError("null detail fallback", 422, { detail: null }, "null-detail-ref"))
      .mockRejectedValueOnce(new ApiError("", 422, { detail: null }, "empty-message-ref"));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace />);
    await screen.findByRole("button", { name: /current tree: import reasons/i });

    const importFile = (name: string) => Object.assign(
      new File([JSON.stringify(loaded)], name, { type: "application/json" }),
      { text: async () => JSON.stringify(loaded) }
    );
    const importWithReason = async (file: File, expected: string) => {
      fireEvent.click(screen.getByRole("button", { name: /current tree: import reasons/i }));
      fireEvent.click(screen.getByRole("menuitem", { name: "Import tree JSON" }));
      fireEvent.change(screen.getByLabelText("Choose tree JSON file"), { target: { files: [file] } });
      expect(await screen.findByText(new RegExp(expected))).toBeInTheDocument();
    };

    await importWithReason(importFile("reason.json"), "reason from validation");
    await importWithReason(importFile("message.json"), "message from validation");
    await importWithReason(importFile("empty-detail.json"), "fallback from ApiError");
    await importWithReason(importFile("no-detail.json"), "fallback without detail");
    await importWithReason(importFile("null-detail.json"), "null detail fallback");
    await importWithReason(importFile("empty-message.json"), "The server rejected the tree import\\.");
    expect(importTree).toHaveBeenCalledTimes(6);
  });

  it("fails closed for an online-only coordinator during pending-work discard", async () => {
    const loaded = tree("tree-online-only-mode", "Online-only mode", "2026-09-20T10:00:00Z");
    const coordinator = coordinatorStub({
      mode: "online-only",
      enumerateOwnerDrafts: vi.fn()
        .mockResolvedValueOnce({ ok: true, value: [], mode: "durable" })
        .mockResolvedValueOnce({ ok: true, value: [], mode: "durable" })
        .mockResolvedValueOnce({ ok: true, value: [], mode: "online-only" })
    });
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([{ id: loaded.id, name: loaded.name, updated_at: loaded.metadata.updated_at, owner_id: "owner-1" }, { id: "tree-online-other", name: "Online other", updated_at: "2026-09-19T10:00:00Z", owner_id: "owner-1" }]);
    vi.spyOn(crtApi, "getCrtTree").mockResolvedValue(loaded);
    render(<CrtWorkspace createDraftCoordinator={() => coordinator} />);
    const label = await screen.findByRole("textbox", { name: "Card label" });
    fireEvent.change(label, { target: { value: "Online-only local edit" } });
    fireEvent.click(screen.getByRole("button", { name: /current tree: online-only mode/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Switch to Online other" }));
    expect(await screen.findByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
    expect(screen.getAllByText(/cross-tab-safe recovery is unavailable/i).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect((await screen.findAllByText(/cross-tab-safe recovery is unavailable/i)).length).toBeGreaterThan(0);
    expect(screen.getByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
  });

  it("ignores a create callback invoked after the workspace unmounts", async () => {
    const menu = vi.spyOn(crtTreeMenuModule, "CrtTreeMenu");
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    const rendered = render(<CrtWorkspace />);
    await screen.findByRole("heading", { name: "Start with your first undesired effect" });
    const props = menu.mock.calls[menu.mock.calls.length - 1]?.[0];
    expect(props).toBeDefined();
    rendered.unmount();
    await act(async () => { await props?.onCreate(); });
    expect(document.body.querySelector("main")).not.toBeInTheDocument();
  });
});
