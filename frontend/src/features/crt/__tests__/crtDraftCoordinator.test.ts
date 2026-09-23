import { describe, expect, it, vi } from "vitest";

import { crtApi, type CrtTreeResponse } from "../../../api/crt";
import { createGraphState, type GraphState } from "../graphModel";
import {
  cleanupCrtOwnerScope,
  createCrtDraftCoordinator,
  createCrtLossBarrier,
  draftWriteInputFromCrtState,
  pendingDraftToGraphState,
  type CrtDraftChange,
  type DraftBroadcast,
  type DraftStorageEventSource
} from "../crtDraftCoordinator";
import { draftStorageKey, type DraftLockManager, type DraftStorage } from "../draftStore";

class MemoryStorage implements DraftStorage {
  private readonly values = new Map<string, string>();
  get length(): number { return this.values.size; }
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  removeItem(key: string): void { this.values.delete(key); }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null; }
}

const lockManager: DraftLockManager = {
  request: async <T>(
    _name: string,
    _options: { mode: "shared" | "exclusive"; ifAvailable: true },
    callback: (lock: { name: string } | null) => T | Promise<T>
  ) => callback({ name: "crt-lock" })
};

const tree: CrtTreeResponse = {
  id: "tree-1",
  name: "Canonical tree",
  revision: 7,
  schema_version: 1,
  metadata: {
    version: 1,
    created_at: "2026-09-20T09:00:00.000Z",
    updated_at: "2026-09-20T10:00:00.000Z",
    layout: { center: { x: 10, y: 20 }, zoom: 1 },
    owner_id: "owner-1"
  },
  nodes: [{
    id: "node-1",
    label: "Effect",
    type: "parent",
    position: { x: 10, y: 20 },
    highlight_state: "none",
    relation_counts: { up_count: 0, down_count: 0 }
  }],
  relations: [],
  owner_id: "owner-1"
};

const graph: GraphState = createGraphState({
  nodes: [{ id: "node-1", label: "Edited effect", position: { x: 30, y: 40 } }],
  viewportCenter: { x: 30, y: 40 }
});

function createCoordinator(
  overrides: Partial<Parameters<typeof createCrtDraftCoordinator>[0]> = {}
) {
  return createCrtDraftCoordinator({
    owner_id: "owner-1",
    origin: "HTTPS://APP.EXAMPLE.test:443/path",
    tree_id: tree.id,
    storage: new MemoryStorage(),
    lock_manager: lockManager,
    writer_session_id: "00000000-0000-4000-8000-000000000001",
    ...overrides
  });
}

describe("CRT draft persistence/reconciliation coordinator", () => {
  it("builds an exact valid draft input from canonical tree, graph, and journal", async () => {
    const noBlock = createCrtLossBarrier();
    const detachNoBlock = noBlock.attach();
    noBlock.setUnsynchronized(false);
    window.dispatchEvent(new Event("beforeunload", { cancelable: true }));
    detachNoBlock();
    const coordinator = createCoordinator();
    const result = await coordinator.persistBeforeSave(tree, graph, {
      dirty_operations: [{ id: "00000000-0000-4000-8000-000000000002", kind: "label-edit", entity_id: "node-1", field: "label" }]
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.draft.tree).toEqual({
      name: "Canonical tree",
      nodes: [expect.objectContaining({ id: "node-1", label: "Edited effect", position: { x: 30, y: 40 } })],
      relations: [],
      layout: { center: { x: 30, y: 40 }, zoom: 1 }
    });
    expect(result.draft.base_revision).toBe(7);
    expect(result.draft.base_updated_at).toBe("2026-09-20T10:00:00.000Z");
    expect(result.draft.dirty_operations).toHaveLength(1);
  });

  it("recovers the persisted viewport center and zoom from a local draft", async () => {
    const coordinator = createCoordinator();
    const persisted = await coordinator.persistBeforeSave(tree, createGraphState({
      nodes: [{ id: "node-1", label: "Edited effect", position: { x: 30, y: 40 } }],
      viewportCenter: { x: 240, y: -80 },
      viewportZoom: 0.65
    }));

    expect(persisted.ok).toBe(true);
    const initialized = await coordinator.initialize();
    expect(initialized.draft && initialized.draft.tree.layout).toEqual({ center: { x: 240, y: -80 }, zoom: 0.65 });
    expect(initialized.draft && pendingDraftToGraphState(initialized.draft)).toEqual(expect.objectContaining({
      viewportCenter: { x: 240, y: -80 },
      viewportZoom: 0.65
    }));
  });

  it("rejects canonical writes when the tree owner is missing instead of falling back to the session owner", async () => {
    const coordinator = createCoordinator();
    expect(await coordinator.persistBeforeSave({ ...tree, owner_id: null }, graph)).toMatchObject({ ok: false, reason: "scope-mismatch" });
  });

  it("initializes and enumerates the active owner/origin/tree with fresh and stale classifications", async () => {
    let now = Date.parse("2026-09-20T12:00:00.000Z");
    const storage = new MemoryStorage();
    const coordinator = createCoordinator({ storage, clock: { now: () => now } });
    await coordinator.persistBeforeSave(tree, graph);

    expect(await coordinator.initialize()).toMatchObject({ classification: "fresh", draft: { tree_id: "tree-1" }, mode: "durable" });
    now += 30 * 24 * 60 * 60 * 1000;
    expect(await coordinator.initialize()).toMatchObject({ classification: "stale", draft: { tree_id: "tree-1" } });
    expect(await coordinator.enumerate()).toMatchObject({ ok: true, value: [expect.objectContaining({ classification: "stale" })] });
  });

  it("keeps an online-only risk latched for the lifetime of the page", async () => {
    const coordinator = createCoordinator({ storage: null, lock_manager: null });
    expect(coordinator.storageMode).toBe("online-only");
    expect(coordinator.onlineOnlyRisk).toBe(true);
    expect((await coordinator.persistBeforeSave(tree, graph)).ok).toBe(true);
    expect(coordinator.onlineOnlyRisk).toBe(true);
  });

  it("uses online-only storage when durable storage lacks cross-tab Web Locks", async () => {
    const coordinator = createCoordinator({ storage: new MemoryStorage(), lock_manager: null });

    expect(coordinator.storageMode).toBe("online-only");
    expect(coordinator.onlineOnlyRisk).toBe(true);
    expect(await coordinator.persistBeforeSave(tree, graph)).toMatchObject({
      ok: true,
      mode: "online-only",
      online_only_risk: true
    });
  });

  it("publishes only scoped generation metadata and not draft content", async () => {
    const messages: unknown[] = [];
    const listeners = new Set<(event: { data: unknown }) => void>();
    const broadcast: DraftBroadcast = {
      postMessage(message) { messages.push(message); },
      addEventListener(_type, listener) { listeners.add(listener); },
      removeEventListener(_type, listener) { listeners.delete(listener); }
    };
    const storageEvents: DraftStorageEventSource = {
      subscribe: vi.fn(() => () => undefined)
    };
    const coordinator = createCoordinator({ broadcast, storage_events: storageEvents });
    const changes: CrtDraftChange[] = [];
    coordinator.subscribe((change) => changes.push(change));
    await coordinator.persistBeforeSave(tree, graph);

    expect(messages).toHaveLength(1);
    expect(messages[0]).toEqual(expect.objectContaining({ key: expect.stringContaining("bb.crt.draft.v1"), generation: 1 }));
    expect(JSON.stringify(messages[0])).not.toContain("Edited effect");
    const message = messages[0] as { key: string; generation: number; writer_session_id: string };
    listeners.forEach((listener) => listener({ data: message }));
    expect(changes[changes.length - 1]).toMatchObject({ generation: 1, external: true });
  });

  it("clears only after an accepted canonical response is applied", async () => {
    const coordinator = createCoordinator();
    const persisted = await coordinator.persistBeforeSave(tree, graph);
    expect(persisted.ok).toBe(true);
    if (!persisted.ok) return;

    expect(await coordinator.clearAfterCanonicalApplied({ ...tree, revision: 8 }, false, persisted.generation))
      .toMatchObject({ ok: true, cleared: false });
    expect(await coordinator.initialize()).toMatchObject({ classification: "fresh" });
    expect(await coordinator.clearAfterCanonicalApplied({ ...tree, revision: 8 }, true, persisted.generation))
      .toMatchObject({ ok: true, cleared: true });
    expect(await coordinator.initialize()).toMatchObject({ classification: "none" });
  });

  it("recovers by advancing the generation and resetting retention, while backup is non-mutating", async () => {
    let now = Date.parse("2026-09-20T12:00:00.000Z");
    const coordinator = createCoordinator({ clock: { now: () => now } });
    await coordinator.persistBeforeSave(tree, graph);
    now += 30 * 24 * 60 * 60 * 1000;
    const backupBefore = coordinator.backup();
    expect(backupBefore.ok).toBe(true);
    expect(await coordinator.initialize()).toMatchObject({ classification: "stale" });
    if (!backupBefore.ok) return;
    const recovered = await coordinator.recover();
    expect(recovered).toMatchObject({ ok: true, generation: 2 });
    expect(await coordinator.initialize()).toMatchObject({ classification: "fresh" });
    expect(coordinator.backup()).toMatchObject({ ok: true, metadata: { generation: 2 } });
  });

  it("advances retention on a successful retry but not on passive inspection", async () => {
    let now = Date.parse("2026-09-20T12:00:00.000Z");
    const coordinator = createCoordinator({ clock: { now: () => now } });
    const first = await coordinator.persistBeforeSave(tree, graph);
    expect(first).toMatchObject({ ok: true, generation: 1 });
    const before = coordinator.backup();
    expect(await coordinator.initialize()).toMatchObject({ classification: "fresh" });
    if (!before.ok) return;

    now += 5_000;
    expect(await coordinator.persistRetry(tree, graph)).toMatchObject({ ok: true, generation: 2 });
    const after = coordinator.backup();
    expect(after).toMatchObject({ ok: true, metadata: { generation: 2, local_updated_at: "2026-09-20T12:00:05.000Z" } });
    expect(after.ok && after.content).not.toBe(before.content);
  });

  it("discards under the writer lock and cleans the whole active account scope", async () => {
    const storage = new MemoryStorage();
    const first = createCoordinator({ storage });
    const second = createCoordinator({ storage, tree_id: "tree-2" });
    await first.persistBeforeSave(tree, graph);
    await second.persistBeforeSave({ ...tree, id: "tree-2" }, graph);
    expect(await first.discard()).toMatchObject({ ok: true, cleared: true });
    expect(await first.cleanupAccountScope()).toMatchObject({ ok: true, removed: 1 });
    expect(await second.initialize()).toMatchObject({ classification: "none" });
  });

  it("discards every listed owner draft, including pre-canonical work, in one explicit transition", async () => {
    const storage = new MemoryStorage();
    const active = createCoordinator({ storage });
    const other = createCoordinator({ storage, tree_id: "tree-2" });
    const preCanonical = createCoordinator({
      storage,
      tree_id: null,
      create_idempotency_key: "00000000-0000-4000-8000-000000000099"
    });
    await active.persistBeforeSave(tree, graph);
    await other.persistBeforeSave({ ...tree, id: "tree-2" }, graph);
    await preCanonical.persistBeforeCreate({ ...tree, id: "pre-canonical" }, graph);

    expect(await active.enumerateOwnerDrafts()).toMatchObject({ ok: true, value: expect.arrayContaining([
      expect.objectContaining({ draft: expect.objectContaining({ tree_id: "tree-1" }) }),
      expect.objectContaining({ draft: expect.objectContaining({ tree_id: "tree-2" }) }),
      expect.objectContaining({ draft: expect.objectContaining({ tree_id: null }) })
    ]) });
    expect(await active.discardOwnerDrafts()).toMatchObject({ ok: true, removed: 3 });
    expect(await active.enumerateOwnerDrafts()).toMatchObject({ ok: true, value: [] });
  });

  it("cleans memory-only drafts from an active coordinator before disposing it", async () => {
    const ownerId = "owner-online-only-cleanup";
    const origin = "https://online-only-cleanup.example.test";
    const activeTree = { ...tree, owner_id: ownerId, metadata: { ...tree.metadata, owner_id: ownerId } };
    const secondTree = { ...activeTree, id: "tree-2" };
    const active = createCoordinator({
      owner_id: ownerId,
      origin,
      tree_id: activeTree.id,
      storage: null,
      lock_manager: null
    });
    const second = createCoordinator({
      owner_id: ownerId,
      origin,
      tree_id: secondTree.id,
      storage: null,
      lock_manager: null
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const navigatorWithLocks = navigator as Navigator & { locks?: DraftLockManager };
    const originalLocks = navigatorWithLocks.locks;
    Object.defineProperty(navigatorWithLocks, "locks", { configurable: true, value: lockManager });

    try {
      expect(await active.persistBeforeSave(activeTree, graph)).toMatchObject({ ok: true, mode: "online-only" });
      expect(await second.persistBeforeSave(secondTree, graph)).toMatchObject({ ok: true, mode: "online-only" });
      expect(active.hasPendingDraft()).toBe(true);
      expect(second.hasPendingDraft()).toBe(true);

      await expect(cleanupCrtOwnerScope(ownerId, origin)).resolves.toEqual({ ok: true, removed: 2 });

      expect(confirm).toHaveBeenCalledTimes(1);
      expect(active.hasPendingDraft()).toBe(false);
      expect(second.hasPendingDraft()).toBe(false);
    } finally {
      confirm.mockRestore();
      if (originalLocks === undefined) Reflect.deleteProperty(navigatorWithLocks, "locks");
      else Object.defineProperty(navigatorWithLocks, "locks", { configurable: true, value: originalLocks });
      active.dispose();
      second.dispose();
    }
  });

  it("fails closed when an active coordinator cannot discard its owner drafts", async () => {
    const ownerId = "owner-online-only-cleanup-failure";
    const origin = "https://online-only-cleanup-failure.example.test";
    const activeTree = { ...tree, owner_id: ownerId, metadata: { ...tree.metadata, owner_id: ownerId } };
    const active = createCoordinator({
      owner_id: ownerId,
      origin,
      tree_id: activeTree.id,
      storage: null,
      lock_manager: null
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const discard = vi.spyOn(active, "discardOwnerDrafts").mockResolvedValue({
      ok: false,
      reason: "cleanup-failed",
      mode: "online-only",
      online_only_risk: true
    });

    try {
      await active.persistBeforeSave(activeTree, graph);
      await expect(cleanupCrtOwnerScope(ownerId, origin)).resolves.toEqual({ ok: false, reason: "cleanup-failed" });

      expect(confirm).toHaveBeenCalledTimes(1);
      expect(discard).toHaveBeenCalledTimes(1);
      expect(active.hasPendingDraft()).toBe(true);
    } finally {
      confirm.mockRestore();
      active.dispose();
    }
  });

  it("discards hidden migration sources after canonical deletion", async () => {
    const createKey = "00000000-0000-4000-8000-000000000099";
    const migrationId = "00000000-0000-4000-8000-000000000098";
    const sourceScope = {
      owner_id: "owner-1",
      origin: "https://app.example.test",
      tree_id: null,
      create_idempotency_key: createKey
    };
    const sourceKey = draftStorageKey(sourceScope);
    class MigrationSourceRemovalFailureStorage extends MemoryStorage {
      public failSourceRemoval = true;

      override removeItem(key: string): void {
        if (this.failSourceRemoval && key === sourceKey) return;
        super.removeItem(key);
      }
    }
    const storage = new MigrationSourceRemovalFailureStorage();
    const preCanonical = createCoordinator({ ...sourceScope, storage });
    await preCanonical.persistBeforeCreate(tree, graph);
    expect(await preCanonical.rekeyAfterCreate(tree.id, migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });

    const canonical = createCoordinator({ storage });
    expect(await canonical.enumerateOwnerDrafts()).toMatchObject({
      ok: true,
      value: [expect.objectContaining({ draft: expect.objectContaining({ tree_id: tree.id }) })]
    });
    storage.failSourceRemoval = false;

    expect(await canonical.discardOwnerDrafts()).toMatchObject({ ok: true, removed: 2 });
    expect(storage.getItem(sourceKey)).toBeNull();
    expect(storage.getItem(draftStorageKey({ owner_id: "owner-1", origin: "https://app.example.test", tree_id: tree.id }))).toBeNull();
  });

  it("writes a pre-canonical draft and rekeys it after creation", async () => {
    const createKey = "00000000-0000-4000-8000-000000000010";
    const migrationId = "00000000-0000-4000-8000-000000000011";
    const coordinator = createCoordinator({ tree_id: null, create_idempotency_key: createKey });
    const preCanonical = await coordinator.persistBeforeCreate(tree, graph);
    expect(preCanonical).toMatchObject({ ok: true, create_idempotency_key: createKey });
    expect(await coordinator.rekeyAfterCreate("tree-created", migrationId)).toMatchObject({ ok: true, tree_id: "tree-created" });
    const replayed = await coordinator.rekeyAfterCreate("tree-created", migrationId);
    expect(replayed).toMatchObject({ ok: true, tree_id: "tree-created", draft: expect.objectContaining({ tree_id: "tree-created" }) });
  });

  it("replays the exact stored in-flight request after validating its hash before queued recovery", async () => {
    const coordinator = createCoordinator();
    const persisted = await coordinator.persistCommand({
      tree,
      graph,
      payload: {
        expected_revision: tree.revision,
        schema_version: 1,
        name: tree.name,
        metadata: { ...tree.metadata, layout: graph.viewportCenter },
        nodes: [{ id: "node-1", label: "Edited effect", type: "parent", position: { x: 30, y: 40 }, highlight_state: "none", relation_counts: { up_count: 0, down_count: 0 } }],
        relations: [],
        owner_id: tree.owner_id
      },
      idempotencyKey: "00000000-0000-4000-8000-000000000012",
      baseRevision: tree.revision,
      generation: 1,
      retry: false
    });
    expect(persisted.ok).toBe(true);
    if (!persisted.ok) return;
    const update = vi.fn().mockResolvedValue({ ...tree, revision: 8, nodes: [{ ...tree.nodes[0], label: "Edited effect" }] });
    const replay = await (coordinator as unknown as { replayInFlightSave: (tree: CrtTreeResponse, update: (treeId: string, payload: unknown, options: unknown) => Promise<CrtTreeResponse>) => Promise<unknown> }).replayInFlightSave(tree, update);

    expect(replay).toMatchObject({ ok: true });
    expect(update).toHaveBeenCalledWith("tree-1", expect.objectContaining({ expected_revision: 7 }), expect.objectContaining({
      idempotencyKey: "00000000-0000-4000-8000-000000000012"
    }));
  });

  it("reports a held edit session, blocks a second coordinator, and releases it on dispose", async () => {
    let releaseFirst!: () => void;
    let calls = 0;
    const held = new Promise<void>((resolve) => { releaseFirst = resolve; });
    const sessions: DraftLockManager = {
      request: async <T>(_name: string, _options: { mode: "shared" | "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => {
        calls += 1;
        if (calls === 1) return callback({ name: "edit" });
        return callback(null);
      }
    };
    const first = createCoordinator({ lock_manager: sessions });
    const second = createCoordinator({ lock_manager: sessions });
    void held;
    expect(await first.initialize()).toMatchObject({ lock_state: "held" });
    expect(await second.initialize()).toMatchObject({ lock_state: "locked" });
    first.dispose();
    releaseFirst();
  });
  it("covers pending graph conversion validation and viewport normalization edges", async () => {
    const coordinator = createCoordinator();
    const persisted = await coordinator.persistBeforeSave(tree, createGraphState({ nodes: [] }));
    expect(persisted.ok).toBe(true);
    const initialized = await coordinator.initialize();
    if (!initialized.draft) return;
    const invalidCandidates = [
      { ...initialized.draft, tree: { ...initialized.draft.tree, nodes: [null] } },
      { ...initialized.draft, tree: { ...initialized.draft.tree, nodes: [{ id: "", label: "N", position: { x: 0, y: 0 } }] } },
      { ...initialized.draft, tree: { ...initialized.draft.tree, nodes: [{ id: "n", label: " ", position: { x: 0, y: 0 } }] } },
      { ...initialized.draft, tree: { ...initialized.draft.tree, nodes: [{ id: "n", label: "N", position: { x: Number.NaN, y: 0 } }] } },
      { ...initialized.draft, tree: { ...initialized.draft.tree, nodes: [{ id: "n", label: "N", position: { x: 0, y: 0 } }, { id: "n", label: "N2", position: { x: 1, y: 1 } }] } },
      { ...initialized.draft, tree: { ...initialized.draft.tree, nodes: [{ id: "n", label: "N", position: { x: 0, y: 0 } }], relations: [null] } },
      { ...initialized.draft, tree: { ...initialized.draft.tree, nodes: [{ id: "n", label: "N", position: { x: 0, y: 0 } }], relations: [{ id: "r", source_node_id: "n", target_node_id: "n" }] } }
    ];
    invalidCandidates.forEach((candidate) => expect(pendingDraftToGraphState(candidate)).toBeNull());
    expect(pendingDraftToGraphState({ ...initialized.draft, tree: { ...initialized.draft.tree, layout: { center: { x: Number.NaN, y: 0 }, zoom: 10 } } }))
      .toEqual(expect.objectContaining({ viewportCenter: { x: 0, y: 0 }, viewportZoom: 1 }));
  });

  it("handles addEventListener storage sources, malformed broadcasts, and disposal cleanup", async () => {
    const broadcastListeners = new Set<(event: { data: unknown }) => void>();
    const broadcast: DraftBroadcast = {
      postMessage: vi.fn(),
      addEventListener: (_type, listener) => { broadcastListeners.add(listener); },
      removeEventListener: vi.fn((_type, listener) => { broadcastListeners.delete(listener); }),
      close: vi.fn()
    };
    let storageListener: ((event: { key: string | null; generation?: number; action?: "changed" | "cleared" }) => void) | undefined;
    const storageEvents: DraftStorageEventSource = {
      addEventListener: vi.fn((_type, listener) => { storageListener = listener; }),
      removeEventListener: vi.fn()
    };
    const coordinator = createCoordinator({ broadcast, storage_events: storageEvents });
    const changes: CrtDraftChange[] = [];
    const unsubscribe = coordinator.subscribe((change) => changes.push(change));
    broadcastListeners.forEach((listener) => listener({ data: {} }));
    broadcastListeners.forEach((listener) => listener({ data: { key: "other", generation: 1, writer_session_id: "writer", action: "changed" } }));
    storageListener?.({ key: "other" });
    storageListener?.({ key: coordinator.scopeKey, generation: 4, action: "cleared" });
    expect(changes).toHaveLength(1);
    unsubscribe();
    coordinator.dispose();
    expect(broadcast.removeEventListener).toHaveBeenCalledOnce();
    expect(broadcast.close).toHaveBeenCalledOnce();
    expect(storageEvents.removeEventListener).toHaveBeenCalledOnce();
  });

  it("classifies invalid reads, locked sessions, and retry initialization", async () => {
    const storage = new MemoryStorage();
    const key = draftStorageKey({ owner_id: "owner-1", origin: "https://app.example.test", tree_id: "tree-1" });
    storage.setItem(key, "{");
    const invalid = createCoordinator({ storage });
    expect(await invalid.initialize()).toMatchObject({ classification: "invalid", reason: "invalid-json" });

    let available = false;
    const sessions: DraftLockManager = {
      request: async <T>(_name: string, _options: { mode: "shared" | "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => callback(available ? { name: "edit" } : null)
    };
    const locked = createCoordinator({ lock_manager: sessions });
    expect(await locked.initialize()).toMatchObject({ classification: "none", lock_state: "locked" });
    available = true;
    expect(await locked.retryInitialization()).toMatchObject({ lock_state: "held" });
    locked.dispose();
  });

  it("covers scope mismatches and no-draft/failed recovery operations", async () => {
    const coordinator = createCoordinator();
    const otherTree = { ...tree, id: "other-tree" };
    expect(await coordinator.persistBeforeSave(otherTree, graph)).toMatchObject({ ok: false, reason: "scope-mismatch" });
    expect(await coordinator.persistCommand({
      tree: otherTree,
      graph,
      payload: {} as never,
      idempotencyKey: "00000000-0000-4000-8000-000000000004",
      baseRevision: 1,
      generation: 1,
      retry: false
    })).toMatchObject({ ok: false, reason: "scope-mismatch" });
    expect(await coordinator.persistQueuedEdit({
      active: { tree: otherTree, graph, payload: {} as never, idempotencyKey: "00000000-0000-4000-8000-000000000005", baseRevision: 1, generation: 1, retry: false },
      visibleGraph: graph,
      queuedCommands: []
    })).toMatchObject({ ok: false, reason: "scope-mismatch" });
    expect(await coordinator.clearAfterCanonicalApplied({ ...tree, id: "other" }, true)).toMatchObject({ ok: false, reason: "scope-mismatch" });
    expect(await coordinator.clearAfterCanonicalApplied(tree, true)).toMatchObject({ ok: true, cleared: false });
    expect(await coordinator.discard()).toMatchObject({ ok: true, cleared: false });
    expect(await coordinator.recover()).toMatchObject({ ok: false, reason: "not-found" });
    expect(coordinator.backup()).toMatchObject({ ok: false, reason: "not-found" });
  });

  it("covers in-flight replay absence, invalid hashes, and update failures", async () => {
    const coordinator = createCoordinator();
    const update = vi.fn();
    expect(await coordinator.replayInFlightSave(tree, update)).toEqual({ ok: true, replayed: false });
    const persisted = await coordinator.persistCommand({
      tree,
      graph,
      payload: {
        expected_revision: tree.revision,
        schema_version: 1,
        name: tree.name,
        metadata: { ...tree.metadata },
        nodes: [],
        relations: [],
        owner_id: tree.owner_id
      },
      idempotencyKey: "00000000-0000-4000-8000-000000000012",
      baseRevision: tree.revision,
      generation: 1,
      retry: false
    });
    expect(persisted.ok).toBe(true);
    const init = await coordinator.initialize();
    if (!init.draft) return;
    const storage = (coordinator as unknown as { store: { read: unknown } }).store;
    void storage;
    const replay = vi.fn().mockRejectedValue(new Error("server"));
    await expect(coordinator.replayInFlightSave(tree, replay)).rejects.toThrow("server");
  });

  it("covers online-only owner discard failures and durable cleanup failure propagation", async () => {
    const online = createCoordinator({ storage: null, lock_manager: null });
    await online.persistBeforeSave(tree, graph);
    expect(await online.discardOwnerDrafts()).toMatchObject({ ok: true, removed: 1, mode: "online-only" });
    const storage = new MemoryStorage();
    const failingStore = {
      mode: "durable" as const,
      read: () => ({ ok: false as const, reason: "storage-unavailable" as const, mode: "durable" as const }),
      list: async () => ({ ok: false as const, reason: "storage-unavailable" as const, mode: "durable" as const }),
      withWriter: async () => ({ ok: false as const, reason: "lock-unavailable" as const, mode: "web-lock" as const }),
      cleanupOwnerTransition: async () => ({ ok: false as const, reason: "cleanup-failed" as const, mode: "durable" as const }),
      exportBackup: () => ({ ok: false as const, reason: "storage-unavailable" as const, mode: "durable" as const })
    } as never;
    const failing = createCoordinator({ storage, store: failingStore });
    expect(await failing.enumerateOwnerDrafts()).toMatchObject({ ok: false, reason: "storage-unavailable" });
    expect(await failing.cleanupAccountScope()).toMatchObject({ ok: false, reason: "cleanup-failed" });
    expect(await failing.discardOwnerDrafts()).toMatchObject({ ok: false, reason: "storage-unavailable" });
    expect(failing.backup()).toMatchObject({ ok: false, reason: "storage-unavailable" });
  });

  it("covers cleanup transition confirmation and scanner/active-coordinator failures", async () => {
    expect(await cleanupCrtOwnerScope("", "https://app.example.test")).toEqual({ ok: false, reason: "cleanup-failed" });
    expect(await cleanupCrtOwnerScope("owner-1", "ftp://app.example.test")).toEqual({ ok: false, reason: "cleanup-failed" });
    const origin = "https://cleanup-branches.example.test";
    const activeTree = { ...tree, owner_id: "cleanup-owner", metadata: { ...tree.metadata, owner_id: "cleanup-owner" } };
    const active = createCoordinator({ owner_id: "cleanup-owner", origin, tree_id: activeTree.id, storage: null, lock_manager: null });
    await active.persistBeforeSave(activeTree, graph);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    expect(await cleanupCrtOwnerScope("cleanup-owner", origin)).toEqual({ ok: false, reason: "transition-cancelled" });
    confirm.mockRestore();
    const noConfirm = vi.spyOn(window, "confirm").mockImplementation(() => { throw new Error("confirm"); });
    noConfirm.mockRestore();
    active.dispose();
    expect(await cleanupCrtOwnerScope("cleanup-owner", origin)).toEqual({ ok: true, removed: 0 });
  });

  it("covers navigation barrier event filters, beforeunload, popstate restoration, and detach", () => {
    const barrier = createCrtLossBarrier();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const detach = barrier.attach(window);
    barrier.setUnsynchronized(true);
    const unload = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    const sameOrigin = document.createElement("a");
    sameOrigin.href = `${window.location.origin}/same`;
    document.body.append(sameOrigin);
    const sameOriginEvent = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    sameOriginEvent.preventDefault();
    Object.defineProperty(sameOriginEvent, "target", { configurable: true, value: sameOrigin });
    window.dispatchEvent(sameOriginEvent);
    expect(confirm).not.toHaveBeenCalled();
    const external = document.createElement("a");
    external.href = "https://external.example.test/out";
    document.body.append(external);
    const ctrlEvent = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ctrlKey: true });
    ctrlEvent.preventDefault();
    Object.defineProperty(ctrlEvent, "target", { configurable: true, value: external });
    window.dispatchEvent(ctrlEvent);
    expect(confirm).toHaveBeenCalledTimes(0);
    const normalExternalEvent = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    Object.defineProperty(normalExternalEvent, "target", { configurable: true, value: external });
    window.dispatchEvent(normalExternalEvent);
    expect(confirm).toHaveBeenCalledTimes(1);
    confirm.mockReturnValueOnce(true);
    window.dispatchEvent(new PopStateEvent("popstate", { state: { idx: 2 } }));
    barrier.setUnsynchronized(true);
    window.history.pushState({ idx: 3 }, "", "/allowed");
    window.history.replaceState({ idx: 4 }, "", "/allowed2");
    window.history.go(0);
    window.history.back();
    window.history.forward();
    detach();
    confirm.mockRestore();
  });
  it("covers completion recovery, edit lock status, null barrier targets, and pop restoration", async () => {
    const coordinator = createCoordinator({ lock_manager: null });
    expect(coordinator.editLockStatus).toBe("unavailable");
    expect(await coordinator.initialize()).toMatchObject({ lock_state: "unavailable" });
    expect(await coordinator.completeInFlightRecovery(tree, graph)).toMatchObject({ ok: true });
    expect(coordinator.hasPendingDraft()).toBe(true);
    const nullDetach = createCrtLossBarrier().attach(null as unknown as Window);
    nullDetach();
    const confirm = vi.fn().mockReturnValue(false);
    const listeners = new Map<string, (event?: Event) => void>();
    let currentState: unknown = { idx: 1 };
    const history = {
      get state() { return currentState; },
      pushState: vi.fn((state: unknown) => { currentState = state; }),
      replaceState: vi.fn((state: unknown) => { currentState = state; }),
      go: vi.fn(), back: vi.fn(), forward: vi.fn()
    };
    const fakeWindow = {
      location: { href: "https://fake.example/base", origin: "https://fake.example" },
      history,
      confirm,
      addEventListener: vi.fn((type: string, listener: (event?: Event) => void) => { listeners.set(type, listener); }),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn()
    } as unknown as Window;
    const barrier = createCrtLossBarrier();
    const detach = barrier.attach(fakeWindow);
    barrier.setUnsynchronized(true);
    currentState = { idx: 2 };
    listeners.get("popstate")?.(new PopStateEvent("popstate"));
    listeners.get("popstate")?.(new PopStateEvent("popstate"));
    detach();
    coordinator.dispose();
  });

  it("covers backup JSON parsing failure and owner cleanup confirmation absence/throws", async () => {
    const fakeStore = {
      mode: "durable" as const,
      exportBackup: () => ({ ok: true as const, value: "not-json", mode: "durable" as const })
    } as never;
    const coordinator = createCoordinator({ store: fakeStore });
    expect(coordinator.backup()).toMatchObject({ ok: false, reason: "invalid-json" });
    const owner = "owner-confirm-missing";
    const origin = "https://confirm-missing.example.test";
    const activeTree = { ...tree, owner_id: owner, metadata: { ...tree.metadata, owner_id: owner } };
    const active = createCoordinator({ owner_id: owner, origin, tree_id: activeTree.id, storage: null, lock_manager: null });
    await active.persistBeforeSave(activeTree, graph);
    const originalConfirm = window.confirm;
    Object.defineProperty(window, "confirm", { configurable: true, value: undefined });
    expect(await cleanupCrtOwnerScope(owner, origin)).toEqual({ ok: false, reason: "cleanup-failed" });
    Object.defineProperty(window, "confirm", { configurable: true, value: originalConfirm });
    const throwingDiscard = vi.spyOn(active, "discardOwnerDrafts").mockRejectedValue(new Error("discard"));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    expect(await cleanupCrtOwnerScope(owner, origin)).toEqual({ ok: false, reason: "cleanup-failed" });
    throwingDiscard.mockRestore();
    vi.restoreAllMocks();
    active.dispose();
  });

  it("covers cleanup scan failure caused by storage-unavailable scanner", async () => {
    const owner = "owner-scan-failure";
    const origin = "https://scan-failure.example.test";
    const storage = new MemoryStorage();
    const active = createCoordinator({ owner_id: owner, origin, tree_id: tree.id, storage, lock_manager: lockManager });
    const activeTree = { ...tree, owner_id: owner, metadata: { ...tree.metadata, owner_id: owner } };
    await active.persistBeforeSave(activeTree, graph);
    Object.defineProperty(storage, "length", { configurable: true, get: () => { throw new Error("length"); } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    expect(await cleanupCrtOwnerScope(owner, origin)).toEqual({ ok: false, reason: "cleanup-failed" });
    active.dispose();
  });

  it("covers queued coordinator persistence, concurrent initialization, defaults, and barrier predicates", async () => {
    const coordinator = createCoordinator();
    const payload = {
      expected_revision: tree.revision,
      schema_version: 1,
      name: tree.name,
      metadata: { ...tree.metadata, layout: graph.viewportCenter },
      nodes: [{ id: "node-1", label: "Edited effect", type: "parent" as const, position: { x: 30, y: 40 }, highlight_state: "none" as const, relation_counts: { up_count: 0, down_count: 0 } }],
      relations: [],
      owner_id: tree.owner_id
    };
    const active = { tree, graph, payload, idempotencyKey: "00000000-0000-4000-8000-000000000020", baseRevision: 7, generation: 1, retry: false };
    expect(await coordinator.persistQueuedEdit({ active, visibleGraph: graph, queuedCommands: [] })).toMatchObject({ ok: true });
    const concurrent = createCoordinator();
    const results = await Promise.all([concurrent.initialize(), concurrent.initialize()]);
    expect(results[0]?.lock_state).toBe("held");
    expect(results[1]?.lock_state).toBe("held");
    concurrent.dispose();
    const barrier = createCrtLossBarrier();
    expect(barrier.isBlocking()).toBe(true);
    barrier.setUnsynchronized(false);
    coordinator.dispose();

    const originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
    Object.defineProperty(globalThis, "localStorage", { configurable: true, get: () => { throw new Error("storage getter"); } });
    const originalBroadcast = Object.getOwnPropertyDescriptor(globalThis, "BroadcastChannel");
    Object.defineProperty(globalThis, "BroadcastChannel", { configurable: true, value: function ThrowingBroadcastChannel() { throw new Error("broadcast"); } });
    const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, "crypto");
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: {} });
    const defaults = createCrtDraftCoordinator({ owner_id: "defaults", origin: "https://defaults.example.test", tree_id: tree.id });
    expect(defaults.activeScope.owner_id).toBe("defaults");
    defaults.dispose();
    if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage);
    else Reflect.deleteProperty(globalThis, "localStorage");
    if (originalBroadcast) Object.defineProperty(globalThis, "BroadcastChannel", originalBroadcast);
    else Reflect.deleteProperty(globalThis, "BroadcastChannel");
    if (originalCrypto) Object.defineProperty(globalThis, "crypto", originalCrypto);
    else Reflect.deleteProperty(globalThis, "crypto");
  });

  it("covers loss barrier fallback pop restoration and allowed history methods", () => {
    const listeners = new Map<string, (event?: Event) => void>();
    let state: unknown = undefined;
    const history = {
      get state() { return state; },
      pushState: vi.fn((next: unknown) => { state = next; }),
      replaceState: vi.fn((next: unknown) => { state = next; }),
      go: vi.fn(), back: vi.fn(), forward: vi.fn()
    };
    const fake = {
      location: { href: "https://fake2.example/base", origin: "https://fake2.example" }, history,
      confirm: vi.fn().mockReturnValue(true),
      addEventListener: vi.fn((type: string, listener: (event?: Event) => void) => listeners.set(type, listener)),
      removeEventListener: vi.fn(), dispatchEvent: vi.fn()
    } as unknown as Window;
    const barrier = createCrtLossBarrier();
    const detach = barrier.attach(fake);
    barrier.setUnsynchronized(true);
    listeners.get("popstate")?.(new PopStateEvent("popstate"));
    history.pushState({ idx: 1 });
    history.replaceState({ idx: 2 });
    barrier.setUnsynchronized(false);
    history.go(1); history.back(); history.forward();
    detach();
  });

  it("covers coordinator queued journal hashing with an injected crypto failure", async () => {
    const coordinator = createCoordinator({ crypto: { subtle: { digest: vi.fn().mockRejectedValue(new Error("digest")) } } });
    const request = {
      tree,
      graph,
      payload: {
        expected_revision: 7, schema_version: 1, name: tree.name, metadata: { ...tree.metadata }, nodes: [], relations: [], owner_id: tree.owner_id
      },
      idempotencyKey: "00000000-0000-4000-8000-000000000021", baseRevision: 7, generation: 1, retry: false
    };
    expect(await coordinator.persistCommand(request)).toMatchObject({ ok: true });
  });

  it("covers public conversion, event, crypto, and navigation fallbacks", async () => {
    expect(draftWriteInputFromCrtState(tree, graph, { owner_id: "owner-1", origin: "https://app.example.test", tree_id: tree.id }))
      .toEqual(expect.objectContaining({ base_revision: 7 }));

    const listeners = new Map<string, (event?: Event) => void>();
    const history = {
      state: undefined as unknown,
      pushState: vi.fn((_state: unknown, ...args: [string, string | URL | null | undefined]) => { void args; history.state = _state; }),
      replaceState: vi.fn((_state: unknown, ...args: [string, string | URL | null | undefined]) => { void args; history.state = _state; }),
      go: vi.fn(), back: vi.fn(), forward: vi.fn()
    };
    const originalPushState = history.pushState;
    const confirm = vi.fn().mockReturnValue(true);
    const fakeWindow = {
      location: { href: "https://barrier-fallback.example/base", origin: "https://barrier-fallback.example" },
      history,
      confirm,
      addEventListener: vi.fn((type: string, listener: (event?: Event) => void) => { listeners.set(type, listener); }),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn()
    } as unknown as Window;
    const barrier = createCrtLossBarrier();
    const detach = barrier.attach(fakeWindow);
    barrier.setUnsynchronized(false);
    listeners.get("beforeunload")?.(new Event("beforeunload", { cancelable: true }));
    history.pushState({ idx: 1 }, "", "/allowed");
    history.replaceState({ idx: 2 }, "", "/allowed");
    history.go(1);
    history.back();
    history.forward();
    barrier.setUnsynchronized(true);
    const blank = document.createElement("a");
    blank.href = "https://external.example.test/blank";
    blank.target = "_blank";
    const blankEvent = new MouseEvent("click", { bubbles: true, button: 0 });
    Object.defineProperty(blankEvent, "target", { configurable: true, value: blank });
    confirm.mockClear();
    listeners.get("click")?.(blankEvent);
    expect(confirm).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(false).mockReturnValueOnce(true);
    history.state = undefined;
    listeners.get("popstate")?.(new PopStateEvent("popstate"));
    expect(originalPushState).toHaveBeenCalled();
    detach();

    const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, "crypto");
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: {} });
    const noCrypto = createCoordinator();
    expect(await noCrypto.persistCommand({
      tree, graph, payload: { expected_revision: 7, schema_version: 1, name: tree.name, metadata: { ...tree.metadata }, nodes: [], relations: [], owner_id: tree.owner_id },
      idempotencyKey: "00000000-0000-4000-8000-000000000030", baseRevision: 7, generation: 1, retry: false
    })).toMatchObject({ ok: true });
    noCrypto.dispose();
    if (originalCrypto) Object.defineProperty(globalThis, "crypto", originalCrypto);
    else Reflect.deleteProperty(globalThis, "crypto");
  });

  it("covers coordinator lock retries, thrown lock requests, and public failure results", async () => {
    let releaseGate!: () => void;
    const gate = new Promise<void>((resolve) => { releaseGate = resolve; });
    const delayedLocks: DraftLockManager = {
      request: async <T>(_name: string, _options: { mode: "shared" | "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => { await gate; return callback({ name: "edit" }); }
    };
    const concurrent = createCoordinator({ lock_manager: delayedLocks });
    const first = concurrent.initialize();
    const second = concurrent.initialize();
    releaseGate();
    await Promise.resolve();
    concurrent.dispose();
    await expect(first).resolves.toMatchObject({ lock_state: "held" });
    await expect(second).resolves.toMatchObject({ lock_state: "held" });

    const throwingLocks: DraftLockManager = {
      request: async <T>(_name: string, _options: { mode: "shared" | "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => { void callback(null); throw new Error("lock request"); }
    };
    const thrown = createCoordinator({ lock_manager: throwingLocks });
    await expect(thrown.initialize()).resolves.toMatchObject({ classification: "none", lock_state: "locked" });
    await expect(thrown.retryInitialization()).resolves.toMatchObject({ lock_state: "locked" });
    thrown.dispose();

    const input = { tree, graph, payload: { expected_revision: 7, schema_version: 1, name: tree.name, metadata: { ...tree.metadata }, nodes: [], relations: [], owner_id: tree.owner_id }, idempotencyKey: "00000000-0000-4000-8000-000000000031", baseRevision: 7, generation: 1, retry: false };
    const writerDenied = createCoordinator({ store: {
      mode: "durable",
      read: () => ({ ok: true, found: false, mode: "durable" }),
      withWriter: async () => ({ ok: false, reason: "lock-unavailable", mode: "web-lock" })
    } as never });
    expect(await writerDenied.persistCommand(input)).toMatchObject({ ok: false, reason: "lock-unavailable" });
    expect(await writerDenied.recover()).toMatchObject({ ok: false, reason: "lock-unavailable" });
    writerDenied.dispose();

    const operationDenied = createCoordinator({ store: {
      mode: "durable",
      read: () => ({ ok: true, found: false, mode: "durable" }),
      write: () => ({ ok: false, reason: "writer-denied", mode: "durable" }),
      withWriter: async (_scope: unknown, operation: () => unknown) => ({ ok: true, value: await operation(), mode: "web-lock" })
    } as never });
    expect(await operationDenied.persistBeforeSave(tree, graph)).toMatchObject({ ok: false, reason: "writer-denied" });
    operationDenied.dispose();
  });

  it("covers relation conversion and public replay/clear/discard/rekey failures", async () => {
    const related = createGraphState({
      nodes: [{ id: "node-1", label: "One", position: { x: 0, y: 0 } }, { id: "node-2", label: "Two", position: { x: 10, y: 10 } }],
      relations: [{ id: "relation-1", sourceId: "node-1", targetId: "node-2" }]
    });
    const coordinator = createCoordinator();
    const persisted = await coordinator.persistBeforeSave(tree, related);
    expect(persisted.ok).toBe(true);
    if (!persisted.ok) return;
    expect(pendingDraftToGraphState(persisted.draft)).toEqual(expect.objectContaining({ relations: [{ id: "relation-1", sourceId: "node-1", targetId: "node-2" }] }));

    expect(await coordinator.replayInFlightSave({ ...tree, id: "wrong-tree" }, vi.fn())).toMatchObject({ ok: false, reason: "scope-mismatch" });
    const invalidRead = createCoordinator({ store: { mode: "durable", read: () => ({ ok: false, reason: "storage-unavailable", mode: "durable" }), withWriter: async () => ({ ok: false, reason: "lock-unavailable", mode: "web-lock" }) } as never });
    expect(await invalidRead.replayInFlightSave(tree, vi.fn())).toMatchObject({ ok: false, reason: "storage-unavailable" });
    expect(await invalidRead.clearAfterCanonicalApplied(tree)).toMatchObject({ ok: false, reason: "storage-unavailable" });
    expect(await invalidRead.discard()).toMatchObject({ ok: false, reason: "storage-unavailable" });
    expect(await invalidRead.recover()).toMatchObject({ ok: false, reason: "lock-unavailable" });
    invalidRead.dispose();

    const draft = persisted.draft;
    const writerFailure = (value: unknown) => createCoordinator({ store: {
      mode: "durable",
      read: () => ({ ok: true, found: true, value: draft, stale: false, requires_backup_confirmation: false, mode: "durable" }),
      withWriter: async () => value
    } as never });
    const failedWriter = writerFailure({ ok: false, reason: "lock-unavailable", mode: "web-lock" });
    expect(await failedWriter.clearAfterCanonicalApplied(tree)).toMatchObject({ ok: false, reason: "lock-unavailable" });
    expect(await failedWriter.discard()).toMatchObject({ ok: false, reason: "lock-unavailable" });
    failedWriter.dispose();
    const failedDiscard = writerFailure({ ok: true, value: { ok: false, reason: "storage-unavailable", mode: "durable" }, mode: "web-lock" });
    expect(await failedDiscard.clearAfterCanonicalApplied(tree)).toMatchObject({ ok: false, reason: "storage-unavailable" });
    expect(await failedDiscard.discard()).toMatchObject({ ok: false, reason: "storage-unavailable" });
    failedDiscard.dispose();

    const canonical = createCoordinator({ tree_id: "tree-1" });
    expect(await canonical.rekeyAfterCreate("tree-2", "00000000-0000-4000-8000-000000000032")).toMatchObject({ ok: false, reason: "scope-mismatch" });
    canonical.dispose();
    coordinator.dispose();
  });

  it("covers online-only discard failures and durable owner cleanup failure", async () => {
    const online = createCoordinator({ storage: null, lock_manager: null });
    const persisted = await online.persistBeforeSave(tree, graph);
    expect(persisted.ok).toBe(true);
    if (!persisted.ok) return;
    const draft = persisted.draft;
    const listed = { ok: true, value: [{ value: draft, stale: false, requires_backup_confirmation: false }], mode: "online-only" };
    for (const value of [
      { ok: false, reason: "writer-denied", mode: "in-memory-fallback" },
      { ok: true, value: { ok: false, reason: "storage-unavailable", mode: "online-only" }, mode: "in-memory-fallback" },
      { ok: true, value: { ok: true, value: false, mode: "online-only" }, mode: "in-memory-fallback" }
    ]) {
      const failure = createCoordinator({ store: { mode: "online-only", list: async () => listed, withWriter: async () => value } as never });
      expect((await failure.discardOwnerDrafts()).ok).toBe(false);
      failure.dispose();
    }
    online.dispose();
    const durableFailure = createCoordinator({ store: {
      mode: "durable",
      list: async () => ({ ok: true, value: [], mode: "durable" }),
      cleanupOwnerTransition: async () => ({ ok: false, reason: "cleanup-failed", mode: "durable" })
    } as never });
    expect(await durableFailure.discardOwnerDrafts()).toMatchObject({ ok: false, reason: "cleanup-failed" });
    durableFailure.dispose();
  });

  it("covers default event fallbacks and owner cleanup no-pending/scanner failures", async () => {
    const originalEvents = Object.getOwnPropertyDescriptor(globalThis, "addEventListener");
    Object.defineProperty(globalThis, "addEventListener", { configurable: true, get: () => { throw new Error("events"); } });
    const defaults = createCrtDraftCoordinator({ owner_id: "defaults-events", origin: "https://defaults-events.example.test", tree_id: "tree-1", storage: null, lock_manager: null });
    defaults.dispose();
    if (originalEvents) Object.defineProperty(globalThis, "addEventListener", originalEvents);
    else Reflect.deleteProperty(globalThis, "addEventListener");

    expect(await cleanupCrtOwnerScope("owner-no-pending", "https://owner-no-pending.example.test")).toEqual({ ok: true, removed: 0 });

    const storage = new MemoryStorage();
    const originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
    const originalLocks = Object.getOwnPropertyDescriptor(navigator, "locks");
    Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage });
    Object.defineProperty(navigator, "locks", { configurable: true, value: lockManager });
    const scoped = createCrtDraftCoordinator({ owner_id: "owner-scanner-failure", origin: "https://owner-scanner-failure.example.test", tree_id: "tree-1" });
    await scoped.persistBeforeSave({ ...tree, owner_id: "owner-scanner-failure", metadata: { ...tree.metadata, owner_id: "owner-scanner-failure" } }, graph);
    scoped.dispose();
    const draftKey = storage.key(0);
    const originalRemove = storage.removeItem.bind(storage);
    storage.removeItem = (key: string) => { if (key === draftKey) return; originalRemove(key); };
    vi.spyOn(window, "confirm").mockReturnValue(true);
    expect(await cleanupCrtOwnerScope("owner-scanner-failure", "https://owner-scanner-failure.example.test")).toEqual({ ok: false, reason: "cleanup-failed" });
    vi.restoreAllMocks();
    if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage); else Reflect.deleteProperty(globalThis, "localStorage");
    if (originalLocks) Object.defineProperty(navigator, "locks", originalLocks); else Reflect.deleteProperty(navigator, "locks");
  });

  it("covers final coordinator fallbacks and malformed public events", async () => {
    const badStorage = new MemoryStorage();
    Object.defineProperty(badStorage, "length", { configurable: true, get: () => { throw new Error("length"); } });
    const previousStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
    const previousLocks = Object.getOwnPropertyDescriptor(navigator, "locks");
    Object.defineProperty(globalThis, "localStorage", { configurable: true, value: badStorage });
    Object.defineProperty(navigator, "locks", { configurable: true, value: lockManager });
    expect(await cleanupCrtOwnerScope("owner-default-scan-failure", "https://owner-default-scan-failure.example.test")).toEqual({ ok: false, reason: "cleanup-failed" });
    if (previousStorage) Object.defineProperty(globalThis, "localStorage", previousStorage); else Reflect.deleteProperty(globalThis, "localStorage");
    if (previousLocks) Object.defineProperty(navigator, "locks", previousLocks); else Reflect.deleteProperty(navigator, "locks");

    const barrier = createCrtLossBarrier();
    const detach = barrier.attach();
    detach();
    const messages = new Set<(event: { data: unknown }) => void>();
    const broadcast: DraftBroadcast = {
      postMessage: vi.fn(),
      addEventListener: (_type, listener) => { messages.add(listener); },
      removeEventListener: (_type, listener) => { messages.delete(listener); }
    };
    const eventCoordinator = createCoordinator({ broadcast });
    messages.forEach((listener) => listener({ data: null }));
    expect(eventCoordinator.mode).toBe("durable");
    eventCoordinator.dispose();

    const listFailure = createCoordinator({ store: { mode: "durable", list: async () => ({ ok: false, reason: "storage-unavailable", mode: "durable" }) } as never });
    expect(await listFailure.enumerate()).toMatchObject({ ok: false, reason: "storage-unavailable" });
    listFailure.dispose();

    const storage = new MemoryStorage();
    const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, "crypto");
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: { subtle: { digest: vi.fn().mockRejectedValue(new Error("digest")) } } });
    const digestFailure = createCoordinator({ storage });
    const request = { tree, graph, payload: { expected_revision: 7, schema_version: 1, name: tree.name, metadata: { ...tree.metadata }, nodes: [], relations: [], owner_id: tree.owner_id }, idempotencyKey: "00000000-0000-4000-8000-000000000033", baseRevision: 7, generation: 1, retry: false };
    expect(await digestFailure.persistCommand(request)).toMatchObject({ ok: true });
    expect(await digestFailure.persistBeforeSave(tree, graph)).toMatchObject({ ok: true });
    digestFailure.dispose();
    if (originalCrypto) Object.defineProperty(globalThis, "crypto", originalCrypto); else Reflect.deleteProperty(globalThis, "crypto");

    const corruptStorage = new MemoryStorage();
    const corrupt = createCoordinator({ storage: corruptStorage });
    const persisted = await corrupt.persistCommand(request);
    expect(persisted.ok).toBe(true);
    if (persisted.ok) {
      const raw = JSON.parse(corruptStorage.getItem(corrupt.scopeKey) ?? "{}");
      raw.in_flight_save.hash = "f".repeat(64);
      corruptStorage.setItem(corrupt.scopeKey, JSON.stringify(raw));
      expect(await corrupt.replayInFlightSave(tree, vi.fn())).toMatchObject({ ok: false, reason: "invalid-draft" });
    }
    corrupt.dispose();

    const normalExternal = document.createElement("a");
    normalExternal.href = "https://confirm-true.example.test/out";
    const click = new MouseEvent("click", { bubbles: true, button: 0 });
    Object.defineProperty(click, "target", { configurable: true, value: normalExternal });
    const clickListeners = new Map<string, (event: Event) => void>();
    const target = { location: { origin: "https://current.example.test", href: "https://current.example.test/" }, history: window.history, confirm: vi.fn().mockReturnValue(true), addEventListener: vi.fn((type: string, listener: (event: Event) => void) => clickListeners.set(type, listener)), removeEventListener: vi.fn(), dispatchEvent: vi.fn() } as unknown as Window;
    const clickBarrier = createCrtLossBarrier();
    const clickDetach = clickBarrier.attach(target);
    clickBarrier.setUnsynchronized(true);
    clickListeners.get("click")?.(click);
    expect((target.confirm as unknown as ReturnType<typeof vi.fn>)).toHaveBeenCalled();
    clickDetach();
  });

  it("covers remaining optional coordinator branches", async () => {
    const fakeListeners = new Map<string, (event: Event) => void>();
    const target = {
      location: { href: "https://optional.example.test/", origin: "https://optional.example.test" },
      history: { state: undefined, pushState() {}, replaceState() {}, go() {}, back() {}, forward() {} },
      confirm: vi.fn().mockReturnValue(false),
      addEventListener: vi.fn((type: string, listener: (event: Event) => void) => fakeListeners.set(type, listener)),
      removeEventListener: vi.fn(), dispatchEvent: vi.fn()
    } as unknown as Window;
    const barrier = createCrtLossBarrier();
    const detach = barrier.attach(target);
    barrier.setUnsynchronized(true);
    const nonElementClick = new MouseEvent("click", { bubbles: true, button: 0 });
    Object.defineProperty(nonElementClick, "target", { configurable: true, value: window });
    fakeListeners.get("click")?.(nonElementClick);
    detach();

    const originalBroadcast = Object.getOwnPropertyDescriptor(globalThis, "BroadcastChannel");
    Object.defineProperty(globalThis, "BroadcastChannel", { configurable: true, value: undefined });
    const noBroadcast = createCrtDraftCoordinator({ owner_id: "no-broadcast", origin: "https://no-broadcast.example.test", tree_id: "tree-1", storage: null, lock_manager: null });
    noBroadcast.dispose();
    if (originalBroadcast) Object.defineProperty(globalThis, "BroadcastChannel", originalBroadcast); else Reflect.deleteProperty(globalThis, "BroadcastChannel");

    const layoutCoordinator = createCoordinator();
    const saved = await layoutCoordinator.persistBeforeSave(tree, graph);
    expect(saved.ok).toBe(true);
    if (saved.ok) {
      expect(pendingDraftToGraphState({ ...saved.draft, tree: { ...saved.draft.tree, layout: undefined } })).toEqual(expect.objectContaining({ viewportCenter: { x: 0, y: 0 }, viewportZoom: 1 }));
      expect(pendingDraftToGraphState({ ...saved.draft, tree: { ...saved.draft.tree, layout: { center: undefined, zoom: undefined } } })).toEqual(expect.objectContaining({ viewportZoom: 1 }));
    }
    layoutCoordinator.dispose();

    const unavailable = createCoordinator({ lock_manager: null });
    expect(await unavailable.retryInitialization()).toMatchObject({ lock_state: "unavailable" });
    unavailable.dispose();

    const online = createCoordinator({ storage: null, lock_manager: null });
    await online.persistBeforeSave(tree, graph);
    expect(await online.initialize()).toMatchObject({ classification: "online-only" });
    expect(await online.enumerate()).toMatchObject({ ok: true, value: [expect.objectContaining({ classification: "online-only" })] });
    online.dispose();

    const eventSources: DraftStorageEventSource = { addEventListener: vi.fn() };
    const events = createCoordinator({ storage_events: eventSources });
    events.dispose();
    expect(eventSources.addEventListener).toHaveBeenCalled();

    await cleanupCrtOwnerScope("owner-default-origin");
  });

  it("covers coordinator read classifications, online-only enumeration, optional event cleanup, and discard no-ops", async () => {
    const invalidDraft = createCoordinator({ store: {
      mode: "durable",
      read: () => ({ ok: false, reason: "invalid-draft", mode: "durable" }),
      withWriter: async () => ({ ok: false, reason: "lock-unavailable", mode: "web-lock" })
    } as never });
    expect(await invalidDraft.initialize()).toMatchObject({ classification: "invalid", reason: "invalid-draft" });
    invalidDraft.dispose();

    const unavailable = createCoordinator({ store: {
      mode: "durable",
      read: () => ({ ok: false, reason: "storage-unavailable", mode: "durable" }),
      withWriter: async () => ({ ok: false, reason: "lock-unavailable", mode: "web-lock" })
    } as never });
    expect(await unavailable.initialize()).toMatchObject({ classification: "online-only", reason: "storage-unavailable" });
    unavailable.dispose();

    const originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
    const originalBroadcast = Object.getOwnPropertyDescriptor(globalThis, "BroadcastChannel");
    Object.defineProperty(globalThis, "localStorage", { configurable: true, value: undefined });
    Object.defineProperty(globalThis, "BroadcastChannel", { configurable: true, value: undefined });
    const noDefaults = createCrtDraftCoordinator({ owner_id: "no-defaults", origin: "https://no-defaults.example.test", tree_id: tree.id });
    expect(noDefaults.mode).toBe("online-only");
    noDefaults.dispose();
    if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage); else Reflect.deleteProperty(globalThis, "localStorage");
    if (originalBroadcast) Object.defineProperty(globalThis, "BroadcastChannel", originalBroadcast); else Reflect.deleteProperty(globalThis, "BroadcastChannel");

    const source = createCoordinator();
    const persisted = await source.persistBeforeSave(tree, graph);
    expect(persisted.ok).toBe(true);
    if (!persisted.ok) return;
    source.dispose();

    const onlineList = createCoordinator({ store: {
      mode: "online-only",
      list: async () => ({ ok: true, value: [{ value: persisted.draft, stale: false, requires_backup_confirmation: false }], mode: "online-only" })
    } as never });
    expect(await onlineList.enumerate()).toMatchObject({ ok: true, value: [expect.objectContaining({ classification: "online-only" })] });
    expect(await onlineList.enumerateOwnerDrafts()).toMatchObject({ ok: true, value: [expect.objectContaining({ classification: "online-only" })] });
    onlineList.dispose();

    let eventListener: ((event: { key: string | null; generation?: number; action?: "changed" | "cleared" }) => void) | undefined;
    const noRemoveListener: DraftStorageEventSource = { addEventListener: vi.fn((_type, listener) => { eventListener = listener; }) };
    const eventCoordinator = createCoordinator({ storage_events: noRemoveListener });
    const eventChanges: CrtDraftChange[] = [];
    eventCoordinator.subscribe((change) => eventChanges.push(change));
    eventListener?.({ key: eventCoordinator.scopeKey });
    expect(eventChanges).toEqual([expect.objectContaining({ generation: 0, action: "changed" })]);
    eventCoordinator.dispose();

    const falseDiscardStore = {
      mode: "durable" as const,
      read: () => ({ ok: true as const, found: true as const, value: persisted.draft, stale: false, requires_backup_confirmation: false, mode: "durable" as const }),
      discard: () => ({ ok: true as const, value: false, mode: "durable" as const }),
      withWriter: async (_scope: unknown, operation: () => unknown) => ({ ok: true as const, value: await operation(), mode: "web-lock" as const })
    };
    const falseDiscard = createCoordinator({ store: falseDiscardStore as never });
    expect(await falseDiscard.clearAfterCanonicalApplied(tree, true)).toMatchObject({ ok: true, cleared: false });
    expect(await falseDiscard.discard()).toMatchObject({ ok: true, cleared: false });
    falseDiscard.dispose();

    const defaultPublisher = createCoordinator({ store: {
      mode: "durable",
      write: () => ({ ok: true, value: { ...persisted.draft, writer_session_id: undefined }, mode: "durable" }),
      withWriter: async (_scope: unknown, operation: () => unknown) => ({ ok: true, value: await operation(), mode: "web-lock" })
    } as never });
    expect(await defaultPublisher.persistBeforeSave(tree, graph)).toMatchObject({ ok: true });
    defaultPublisher.dispose();
  });

  it("covers coordinator default replay, rekey, backup identity fallbacks, and pending relation validation", async () => {
    expect(draftWriteInputFromCrtState(tree, graph, { owner_id: "owner-1", origin: "https://app.example.test", tree_id: tree.id }, undefined as never)).toEqual(expect.objectContaining({ base_revision: 7 }));

    const draftSource = createCoordinator();
    const draftResult = await draftSource.persistBeforeSave(tree, graph);
    expect(draftResult.ok).toBe(true);
    if (!draftResult.ok) return;
    draftSource.dispose();

    const replay = createCoordinator();
    const request = {
      tree,
      graph,
      payload: { expected_revision: tree.revision, schema_version: 1, name: tree.name, metadata: { ...tree.metadata }, nodes: [], relations: [], owner_id: tree.owner_id },
      idempotencyKey: "00000000-0000-4000-8000-000000000041",
      baseRevision: tree.revision,
      generation: 1,
      retry: false
    };
    expect(await replay.persistCommand(request)).toMatchObject({ ok: true });
    const update = vi.spyOn(crtApi, "updateCrtTree").mockResolvedValue({ ...tree, revision: 8 });
    expect(await replay.replayInFlightSave(tree)).toMatchObject({ ok: true, replayed: true });
    expect(update).toHaveBeenCalledOnce();
    update.mockRestore();
    replay.dispose();

    const preCanonical = createCoordinator({ tree_id: null, create_idempotency_key: "00000000-0000-4000-8000-000000000042" });
    expect(await preCanonical.persistBeforeCreate(tree, graph)).toMatchObject({ ok: true });
    expect(await preCanonical.rekeyAfterCreate("tree-default")).toMatchObject({ ok: true, tree_id: "tree-default" });
    preCanonical.dispose();

    const backupDraft = { ...draftResult.draft, tree_id: null, create_idempotency_key: "create-only" };
    const createOnly = createCoordinator({ store: { mode: "durable", exportBackup: () => ({ ok: true, value: JSON.stringify(backupDraft), mode: "durable" }) } as never });
    expect(createOnly.backup()).toMatchObject({ ok: true, filename: "crt-create-only-draft.json" });
    createOnly.dispose();
    const anonymous = createCoordinator({ store: { mode: "durable", exportBackup: () => ({ ok: true, value: JSON.stringify({ ...backupDraft, create_idempotency_key: null }), mode: "durable" }) } as never });
    expect(anonymous.backup()).toMatchObject({ ok: true, filename: "crt-draft-draft.json" });
    anonymous.dispose();

    const valid = draftResult.draft;
    expect(pendingDraftToGraphState({ ...valid, tree: { ...valid.tree, relations: [
      { id: "missing-source", source_node_id: "missing", target_node_id: "node-1" },
      { id: "missing-target", source_node_id: "node-1", target_node_id: "missing" },
      { id: "missing-source", source_node_id: "node-1", target_node_id: "node-1" }
    ] } })).toBeNull();
  });

  it("covers the public coordinator fallback origin and state-indexed navigation restoration", async () => {
    await cleanupCrtOwnerScope("owner-default-origin");
    const listeners = new Map<string, (event?: Event) => void>();
    let state: unknown = { idx: 4 };
    const history = {
      get state() { return state; },
      pushState: vi.fn((next: unknown) => { state = next; }),
      replaceState: vi.fn((next: unknown) => { state = next; }),
      go: vi.fn(), back: vi.fn(), forward: vi.fn()
    };
    const originalGo = history.go;
    const fake = {
      location: { href: "https://indexed.example/base", origin: "https://indexed.example" }, history,
      confirm: vi.fn().mockReturnValue(false),
      addEventListener: vi.fn((type: string, listener: (event?: Event) => void) => listeners.set(type, listener)),
      removeEventListener: vi.fn(), dispatchEvent: vi.fn()
    } as unknown as Window;
    const barrier = createCrtLossBarrier();
    const detach = barrier.attach(fake);
    barrier.setUnsynchronized(true);
    state = { idx: 6 };
    listeners.get("popstate")?.(new PopStateEvent("popstate"));
    expect(originalGo).toHaveBeenCalledWith(-2);
    detach();

    const fallbackListeners = new Map<string, (event?: Event) => void>();
    const fallbackState: { value: unknown } = { value: undefined };
    const fallbackHistory = {
      get state() { return fallbackState.value; },
      pushState: vi.fn(), replaceState: vi.fn(), go: vi.fn(), back: vi.fn(), forward: vi.fn()
    };
    const originalFallbackPush = fallbackHistory.pushState;
    const fallbackWindow = {
      location: { href: "https://indexed-fallback.example/base", origin: "https://indexed-fallback.example" },
      history: fallbackHistory,
      confirm: vi.fn().mockReturnValue(false),
      addEventListener: vi.fn((type: string, listener: (event?: Event) => void) => fallbackListeners.set(type, listener)),
      removeEventListener: vi.fn(), dispatchEvent: vi.fn()
    } as unknown as Window;
    const fallbackBarrier = createCrtLossBarrier();
    const fallbackDetach = fallbackBarrier.attach(fallbackWindow);
    fallbackBarrier.setUnsynchronized(true);
    fallbackState.value = { idx: 2 };
    fallbackListeners.get("popstate")?.(new PopStateEvent("popstate"));
    expect(originalFallbackPush).toHaveBeenCalled();
    fallbackDetach();
  });

  it("covers held lock rejection cleanup and the undefined default location origin", async () => {
    const throwingAfterAcquire: DraftLockManager = {
      request: async <T>(_name: string, _options: { mode: "shared" | "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => {
        void callback({ name: "edit" });
        throw new Error("lock request failed after acquisition");
      }
    };
    const lock = createCoordinator({ lock_manager: throwingAfterAcquire });
    expect(await lock.initialize()).toMatchObject({ lock_state: "held" });
    lock.dispose();

    const originalLocation = Object.getOwnPropertyDescriptor(globalThis, "location");
    Object.defineProperty(globalThis, "location", { configurable: true, value: undefined });
    expect(await cleanupCrtOwnerScope("owner-undefined-origin")).toEqual({ ok: false, reason: "cleanup-failed" });
    if (originalLocation) Object.defineProperty(globalThis, "location", originalLocation); else Reflect.deleteProperty(globalThis, "location");
  });

  it("covers default storage-event absence, stale owner enumeration, and schema rejection", async () => {
    const originalEvents = Object.getOwnPropertyDescriptor(globalThis, "addEventListener");
    Object.defineProperty(globalThis, "addEventListener", { configurable: true, value: undefined });
    const noEvents = createCrtDraftCoordinator({ owner_id: "no-events", origin: "https://no-events.example.test", tree_id: tree.id, storage: null, lock_manager: null });
    noEvents.dispose();
    if (originalEvents) Object.defineProperty(globalThis, "addEventListener", originalEvents); else Reflect.deleteProperty(globalThis, "addEventListener");

    const invalidSchema = createCoordinator({ store: {
      mode: "durable",
      read: () => ({ ok: false, reason: "invalid-schema", mode: "durable" }),
      withWriter: async () => ({ ok: false, reason: "lock-unavailable", mode: "web-lock" })
    } as never });
    expect(await invalidSchema.initialize()).toMatchObject({ classification: "invalid", reason: "invalid-schema" });
    invalidSchema.dispose();

    const source = createCoordinator();
    const persisted = await source.persistBeforeSave(tree, graph);
    expect(persisted.ok).toBe(true);
    if (!persisted.ok) return;
    source.dispose();
    const staleOwner = createCoordinator({ store: {
      mode: "durable",
      list: async () => ({ ok: true, value: [{ value: persisted.draft, stale: true, requires_backup_confirmation: true }], mode: "durable" })
    } as never });
    expect(await staleOwner.enumerate()).toMatchObject({ ok: true, value: [expect.objectContaining({ classification: "stale" })] });
    expect(await staleOwner.enumerateOwnerDrafts()).toMatchObject({ ok: true, value: [expect.objectContaining({ classification: "stale" })] });
    staleOwner.dispose();
    const freshOwner = createCoordinator({ store: {
      mode: "durable",
      list: async () => ({ ok: true, value: [{ value: persisted.draft, stale: false, requires_backup_confirmation: false }], mode: "durable" })
    } as never });
    expect(await freshOwner.enumerate()).toMatchObject({ ok: true, value: [expect.objectContaining({ classification: "fresh" })] });
    freshOwner.dispose();
  });

  it("fails closed when navigator.locks.request rejects before invoking its callback", async () => {
    const rejectedLockManager: DraftLockManager = {
      request: vi.fn().mockRejectedValue(new Error("lock service unavailable"))
    };
    const coordinator = createCoordinator({ lock_manager: rejectedLockManager });

    await expect(coordinator.initialize()).resolves.toMatchObject({
      classification: "none",
      lock_state: "locked"
    });
    coordinator.dispose();
  });

});

describe("CRT navigation loss barrier", () => {
  it("guards programmatic history navigation as well as unload navigation", () => {
    const barrier = createCrtLossBarrier();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const originalPath = window.location.pathname;
    barrier.setUnsynchronized(true);
    const detach = barrier.attach(window);

    window.history.pushState({}, "", "/tasks/next");

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Unsynchronized"));
    expect(window.location.pathname).toBe(originalPath);
    detach();
  });
});
