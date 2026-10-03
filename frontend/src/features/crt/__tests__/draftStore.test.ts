import { describe, expect, it, vi } from "vitest";

import {
  createCrtDraftStore,
  draftStorageKey,
  normalizeOrigin,
  validateDraftEnvelope,
  type DraftLockManager,
  type DraftStorage,
  type DraftScope
} from "../draftStore";

class MemoryStorage implements DraftStorage {
  private readonly values = new Map<string, string>();
  get length(): number { return this.values.size; }
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string): void { this.values.delete(key); }
  setItem(key: string, value: string): void { this.values.set(key, value); }
}

class ThrowingStorage implements DraftStorage {
  get length(): number { throw new Error("quota"); }
  getItem(): string | null { throw new Error("quota"); }
  key(): string | null { throw new Error("quota"); }
  removeItem(): void { throw new Error("quota"); }
  setItem(): void { throw new Error("quota"); }
}

class FailingCanonicalStorage extends MemoryStorage {
  override setItem(key: string, value: string): void {
    if (value.includes('"tree_id":"tree-canonical"')) throw new Error("quota");
    super.setItem(key, value);
  }
}

class RecoverableStorage extends MemoryStorage {
  public unavailable = false;

  override removeItem(key: string): void {
    if (this.unavailable) throw new Error("storage unavailable");
    super.removeItem(key);
  }

  override setItem(key: string, value: string): void {
    if (this.unavailable) throw new Error("storage unavailable");
    super.setItem(key, value);
  }
}

class StickyRemovalStorage extends MemoryStorage {
  override removeItem(key: string): void {
    if (!key.includes(".probe.")) return;
    super.removeItem(key);
  }
}

const writerSessionId = "00000000-0000-4000-8000-000000000001";
const createKey = "00000000-0000-4000-8000-000000000002";
const migrationId = "00000000-0000-4000-8000-000000000003";
const scope: DraftScope = { owner_id: "owner-a", origin: "https://app.example.test", tree_id: "tree-a" };
const lockManager: DraftLockManager = {
  request: async <T>(_name: string, _options: { mode: "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => callback({ name: "lock" })
};
const draft = {
  tree: {
    name: "Recovery tree",
    nodes: [{
      id: "node-a",
      label: "Effect",
      type: "child",
      position: { x: 1, y: 2 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    }],
    relations: [],
    layout: { center: { x: 1, y: 2 } }
  },
  base_revision: 4,
  base_updated_at: "2026-09-20T10:00:00.000Z",
  dirty_operations: [{ id: writerSessionId, kind: "label-edit", entity_id: "node-a", field: "label" }],
  queued_commands: []
} as const;

async function mutate<T>(store: ReturnType<typeof createCrtDraftStore>, writerScope: DraftScope, operation: () => T): Promise<T> {
  const result = await store.withWriter(writerScope, operation);
  if (!result.ok) throw new Error(result.reason);
  return result.value;
}

describe("CRT durable draft store", () => {
  it("persists and reads only within owner, origin, and tree scope", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const written = await mutate(store, scope, () => store.write(scope, draft));
    expect(written.ok).toBe(true);
    if (!written.ok) return;
    expect(written.value).toMatchObject({ owner_id: "owner-a", origin: scope.origin, tree_id: "tree-a", writer_session_id: writerSessionId, generation: 1 });
    expect(store.read(scope)).toMatchObject({ ok: true, found: true, mode: "durable" });
    expect(store.read({ ...scope, owner_id: "owner-b" })).toEqual({ ok: true, found: false, mode: "durable" });
  });

  it("advances generation and rejects stale asynchronous completion", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const first = await mutate(store, scope, () => store.write(scope, draft));
    if (!first.ok) return;
    const second = await mutate(store, scope, () => store.write(scope, { ...draft, tree: { ...draft.tree, name: "Newer" } }, { expected_generation: first.value.generation }));
    expect(second).toMatchObject({ ok: true, value: expect.objectContaining({ generation: 2 }) });
    const stale = await mutate(store, scope, () => store.write(scope, { ...draft, tree: { ...draft.tree, name: "Late" } }, { expected_generation: first.value.generation }));
    expect(stale).toEqual({ ok: false, reason: "stale-generation", mode: "durable" });
  });

  it("retains stale drafts and resets retention only on explicit recovery", async () => {
    let now = Date.parse("2026-09-20T12:00:00.000Z");
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager, clock: { now: () => now } });
    await mutate(store, scope, () => store.write(scope, draft));
    now += 30 * 24 * 60 * 60 * 1000;
    expect(store.read(scope)).toMatchObject({ ok: true, found: true, stale: true, requires_backup_confirmation: true });
    const recovered = await mutate(store, scope, () => store.recover(scope));
    expect(recovered.ok).toBe(true);
    expect(store.read(scope)).toMatchObject({ ok: true, found: true, stale: false });
  });

  it("lists, exports, and deletes without crossing owner or origin scope", async () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    const otherOwner = { ...scope, owner_id: "owner-b" };
    const otherOrigin = { ...scope, origin: "https://other.example.test" };
    await mutate(store, scope, () => store.write(scope, draft));
    await mutate(store, otherOwner, () => store.write(otherOwner, { ...draft, tree: { ...draft.tree, name: "Other owner" } }));
    await mutate(store, otherOrigin, () => store.write(otherOrigin, { ...draft, tree: { ...draft.tree, name: "Other origin" } }));
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: true, value: [expect.objectContaining({ value: expect.objectContaining({ tree_id: "tree-a" }) })] });
    expect(store.exportBackup(scope)).toMatchObject({ ok: true });
    expect(await mutate(store, scope, () => store.delete(scope))).toMatchObject({ ok: true, value: true });
    expect(store.read(scope)).toEqual({ ok: true, found: false, mode: "durable" });
    expect(store.read(otherOwner)).toMatchObject({ ok: true, found: true });
    expect(store.read(otherOrigin)).toMatchObject({ ok: true, found: true });
  });

  it("denies durable mutation outside a held Web Lock", () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    expect(store.write(scope, draft)).toEqual({ ok: false, reason: "writer-denied", mode: "durable" });
    expect(storage.length).toBe(0);
  });

  it("uses explicit page-lifetime memory mode without Web Locks", async () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: null });
    const result = await store.withWriter(scope, () => store.write(scope, draft));
    expect(result).toMatchObject({ ok: true, mode: "in-memory-fallback", value: { ok: true, mode: "online-only" } });
    expect(storage.length).toBe(0);
  });

  it("does not use a module-static fallback across independent stores", async () => {
    const first = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: null });
    const second = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: null });
    const held = first.withWriter(scope, () => new Promise((resolve) => setTimeout(resolve, 10)));
    const secondResult = await second.withWriter(scope, () => "independent");
    expect(secondResult).toMatchObject({ ok: true, value: "independent", mode: "in-memory-fallback" });
    await held;
  });

  it("serializes concurrent fallback writers within one page", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: null });
    let release!: () => void;
    const held = store.withWriter(scope, () => new Promise<string>((resolve) => { release = () => resolve("first"); }));
    expect(await store.withWriter(scope, () => "second")).toMatchObject({ ok: false, reason: "writer-denied" });
    release();
    expect(await held).toMatchObject({ ok: true, value: "first" });
  });

  it("reports online-only storage and retains the current-page draft after quota failure", async () => {
    const store = createCrtDraftStore({ storage: new ThrowingStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const written = await mutate(store, scope, () => store.write(scope, draft));
    expect(written).toMatchObject({ ok: true, mode: "online-only" });
    expect(store.read(scope)).toMatchObject({ ok: true, found: true, mode: "online-only" });
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: false, reason: "storage-unavailable" });
  });

  it("invalidates stale durable bytes after a later write failure while retaining memory", async () => {
    class FailsAfterFirstWriteStorage extends MemoryStorage {
      private writes = 0;
      override setItem(key: string, value: string): void {
        if (!key.includes(".probe.")) {
          if (this.writes > 0) throw new Error("quota");
          this.writes += 1;
        }
        super.setItem(key, value);
      }
    }
    const storage = new FailsAfterFirstWriteStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    const newer = await mutate(store, scope, () => store.write(scope, { ...draft, tree: { ...draft.tree, name: "Newer" } }));
    expect(newer).toMatchObject({ ok: true, mode: "online-only" });
    expect(storage.getItem(draftStorageKey(scope))).toBeNull();
    expect(store.read(scope)).toMatchObject({ ok: true, found: true, mode: "online-only", value: { tree: { name: "Newer" } } });
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: false, reason: "storage-unavailable" });
  });

  it("cleans a probe only when cleanup is verified", () => {
    class ProbeCleanupFailureStorage extends MemoryStorage {
      override removeItem(key: string): void { if (key.includes(".probe.")) throw new Error("remove denied"); super.removeItem(key); }
    }
    const storage = new ProbeCleanupFailureStorage();
    const store = createCrtDraftStore({ storage, lock_manager: null });
    expect(store.mode).toBe("online-only");
    expect(storage.length).toBe(1);
  });

  it("rejects malformed, mismatched-key, and unsupported-schema physical entries", async () => {
    const storage = new MemoryStorage();
    const key = draftStorageKey(scope);
    storage.setItem(key, JSON.stringify({ schema_version: 99, owner_id: "owner-b", origin: scope.origin, tree_id: scope.tree_id }));
    const store = createCrtDraftStore({ storage, lock_manager: lockManager });
    expect(store.read(scope)).toMatchObject({ ok: false, reason: "invalid-schema" });
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: false, reason: "invalid-schema" });
    expect(storage.getItem(key)).not.toBeNull();
  });

  it("validates graph IDs, labels, finite positions, relations, cycles, layout, and timestamps", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const invalid = { ...draft, tree: {
      ...draft.tree,
      nodes: [
        { id: "node-a", label: " ", position: { x: Number.NaN, y: 0 }, metadata: { created_at: "bad", updated_at: "bad" } },
        { id: "node-a", label: "Duplicate", position: { x: 0, y: 0 }, metadata: { created_at: "2026-09-20T10:00:00.000Z", updated_at: "2026-09-20T10:00:00.000Z" } }
      ],
      relations: [{ id: "relation-a", source_node_id: "node-a", target_node_id: "node-a", kind: "why", created_at: "2026-09-20T10:00:00.000Z" }],
      layout: { zoom: Number.POSITIVE_INFINITY }
    }} as unknown as typeof draft;
    const result = await mutate(store, scope, () => store.write(scope, invalid));
    expect(result).toMatchObject({ ok: false, reason: "invalid-draft" });
  });

  it("requires UUID-like pre-canonical create keys and migration IDs", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const invalidScope = { ...scope, tree_id: null, create_idempotency_key: "create-1" };
    expect(await mutate(store, scope, () => store.write(scope, draft))).toMatchObject({ ok: true });
    expect(store.write(invalidScope, draft)).toMatchObject({ ok: false, reason: "invalid-draft" });
    const validSource = { ...scope, tree_id: null, create_idempotency_key: createKey };
    await mutate(store, validSource, () => store.write(validSource, { ...draft, create_idempotency_key: createKey }));
    expect(await store.rekeyPreCanonical(validSource, "tree-canonical", "migration-1")).toMatchObject({ ok: false, reason: "invalid-draft" });
  });

  it("rekeys by verify-before-source-removal and binds migration to content and create operation", async () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await store.rekeyPreCanonical(source, "tree-canonical", migrationId)).toMatchObject({ ok: true });
    expect(store.read(source)).toEqual({ ok: true, found: false, mode: "durable" });
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: true, value: [expect.objectContaining({ value: expect.objectContaining({ tree_id: "tree-canonical" }) })] });
    const canonical = { ...scope, tree_id: "tree-canonical" };
    const recovered = await mutate(store, canonical, () => store.recover(canonical));
    expect(recovered.ok && recovered.value).toMatchObject({ migration_id: migrationId, migration_source_create_idempotency_key: createKey });
    const changed = await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey, tree: { ...draft.tree, name: "Changed" } }));
    expect(changed).toMatchObject({ ok: true });
    expect(await store.rekeyPreCanonical(source, "tree-canonical", migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });
    expect(store.read(source)).toMatchObject({ ok: true, found: true });
  });

  it("retains the pre-canonical source when canonical verification cannot be written", async () => {
    const store = createCrtDraftStore({ storage: new FailingCanonicalStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await store.rekeyPreCanonical(source, "tree-canonical", migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });
    expect(store.read(source)).toMatchObject({ ok: true, found: true });
  });

  it("fails account cleanup unless every physical key is proven removed", async () => {
    class StickyRemovalStorage extends MemoryStorage { override removeItem(key: string): void { void key; /* retain */ } }
    const store = createCrtDraftStore({ storage: new StickyRemovalStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    expect(await mutate(store, scope, () => store.cleanupOwnerTransition({ owner_id: scope.owner_id, origin: scope.origin }))).toMatchObject({ ok: false, reason: "cleanup-failed" });
  });

  it("uses Web Locks with shared owner and exclusive key semantics", async () => {
    const request = vi.fn(async <T>(_name: string, options: { mode: "shared" | "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => {
      expect(options.ifAvailable).toBe(true);
      expect(["shared", "exclusive"]).toContain(options.mode);
      return callback({ name: "crt-lock" });
    });
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: { request } as DraftLockManager });
    expect(await store.withWriter(scope, () => "locked")).toMatchObject({ ok: true, value: "locked", mode: "web-lock" });
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("never reads or lists pre-existing durable bytes in online-only mode", async () => {
    const storage = new MemoryStorage();
    const durable = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(durable, scope, () => durable.write(scope, draft));
    const onlineOnly = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: null });
    expect(onlineOnly.read(scope)).toEqual({ ok: true, found: false, mode: "online-only" });
    expect(await onlineOnly.list({ owner_id: scope.owner_id, origin: scope.origin })).toEqual({ ok: true, value: [], mode: "online-only" });
  });

  it("treats durable storage as authoritative after another tab removes a key", async () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    storage.removeItem(draftStorageKey(scope));
    expect(store.read(scope)).toEqual({ ok: true, found: false, mode: "durable" });
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toEqual({ ok: true, value: [], mode: "durable" });
  });

  it("authorizes writers and names locks by the exact tree scope", async () => {
    const names: string[] = [];
    const scopedLocks: DraftLockManager = {
      request: async <T>(name: string, _options: { mode: "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => {
        names.push(name);
        return callback({ name });
      }
    };
    const otherTree = { ...scope, tree_id: "tree-b" };
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: scopedLocks });
    await Promise.all([
      mutate(store, scope, () => store.write(scope, draft)),
      mutate(store, otherTree, () => store.write(otherTree, { ...draft, tree: { ...draft.tree, name: "Other" } }))
    ]);
    expect(new Set(names).size).toBe(3);
    expect(names.filter((name) => name.includes(".owner.")).length).toBe(2);
    expect(names).toEqual(expect.arrayContaining([expect.stringContaining(draftStorageKey(scope)), expect.stringContaining(draftStorageKey(otherTree))]));
  });

  it("fails account cleanup closed when a physical-key cleanup lock is unavailable", async () => {
    const storage = new MemoryStorage();
    const requests: string[] = [];
    const cleanupLocks: DraftLockManager = {
      request: async <T>(name: string, _options: { mode: "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => {
        requests.push(name);
        if (name.includes(draftStorageKey(scope)) && requests.filter((requested) => requested.includes(draftStorageKey(scope))).length > 1) return callback(null);
        return callback({ name });
      }
    };
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: cleanupLocks });
    await mutate(store, scope, () => store.write(scope, draft));
    const result = await store.cleanupOwnerTransition({ owner_id: scope.owner_id, origin: scope.origin });
    expect(result).toMatchObject({ ok: false, reason: "cleanup-failed" });
    expect(storage.getItem(draftStorageKey(scope))).not.toBeNull();
    expect(requests.some((name) => name.includes(draftStorageKey(scope)))).toBe(true);
  });

  it("deduplicates verified migration leftovers in favor of the canonical copy", async () => {
    class StickyRemovalStorage extends MemoryStorage {
      override removeItem(key: string): void { if (!key.includes(".probe.")) return; super.removeItem(key); }
    }
    const storage = new StickyRemovalStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    await store.rekeyPreCanonical(source, "tree-canonical", migrationId);
    const listed = await store.list({ owner_id: scope.owner_id, origin: scope.origin });
    expect(listed).toMatchObject({ ok: true, value: [expect.objectContaining({ value: expect.objectContaining({ tree_id: "tree-canonical", migration_id: migrationId }) })] });
    expect(listed.ok && listed.value).toHaveLength(1);
  });

  it("preserves the source when a canonical migration binding cannot be verified", async () => {
    class StickyRemovalStorage extends MemoryStorage {
      override removeItem(key: string): void { if (!key.includes(".probe.")) return; super.removeItem(key); }
    }
    const storage = new StickyRemovalStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-canonical" };
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    await store.rekeyPreCanonical(source, canonical.tree_id, migrationId);
    const canonicalKey = draftStorageKey(canonical);
    const canonicalRaw = storage.getItem(canonicalKey);
    expect(canonicalRaw).not.toBeNull();
    if (!canonicalRaw) return;
    const tampered = JSON.parse(canonicalRaw) as Record<string, unknown>;
    tampered.migration_fingerprint = "00".repeat(32);
    storage.setItem(canonicalKey, JSON.stringify(tampered));
    const listed = await store.list({ owner_id: scope.owner_id, origin: scope.origin });
    expect(listed).toMatchObject({ ok: true, value: [expect.objectContaining({ value: expect.objectContaining({ tree_id: null, create_idempotency_key: createKey }) })] });
  });

  it("binds migration content with injected SHA-256 Web Crypto and persists its version", async () => {
    const digest = vi.fn(async (algorithm: "SHA-256", data: ArrayBuffer) => {
      expect(algorithm).toBe("SHA-256");
      void data;
      return new Uint8Array(32).fill(0xab).buffer;
    });
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager, crypto: { subtle: { digest } } });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    const result = await store.rekeyPreCanonical(source, "tree-canonical", migrationId);
    expect(result).toMatchObject({ ok: true, value: { migration_fingerprint: "ab".repeat(32), migration_hash_algorithm: "sha-256", migration_hash_version: 1 } });
    expect(digest).toHaveBeenCalled();
  });

  it("accepts the current CRT snapshot shape including nullable layout and rejects node metadata", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const accepted = await mutate(store, scope, () => store.write(scope, { ...draft, tree: { ...draft.tree, layout: null } }));
    expect(accepted).toMatchObject({ ok: true });
    const rejected = await mutate(store, { ...scope, tree_id: "tree-with-metadata" }, () => store.write({ ...scope, tree_id: "tree-with-metadata" }, {
      ...draft,
      tree: { ...draft.tree, nodes: [{ ...draft.tree.nodes[0], metadata: { created_at: "2026-09-20T09:00:00.000Z" } }] }
    }));
    expect(rejected).toMatchObject({ ok: false, reason: "invalid-draft" });
  });

  it("accepts only bounded dirty, in-flight, and queued journal schemas", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const valid = await mutate(store, scope, () => store.write(scope, {
      ...draft,
      dirty_operations: [{ id: writerSessionId, kind: "label-edit", entity_id: "node-a", field: "label" }],
      in_flight_save: { idempotency_key: createKey, base_revision: 4, generation: 1, snapshot: draft.tree, hash: "ab".repeat(32) },
      queued_commands: [{ id: migrationId, kind: "label-edit", payload: { node_id: "node-a", label: "Updated" } }]
    }));
    expect(valid).toMatchObject({ ok: true });
    const arbitrary = await mutate(store, { ...scope, tree_id: "tree-arbitrary" }, () => store.write({ ...scope, tree_id: "tree-arbitrary" }, {
      ...draft,
      dirty_operations: [{ arbitrary: "object" } as never]
    }));
    expect(arbitrary).toMatchObject({ ok: false, reason: "invalid-draft" });
  });

  it("propagates writer application exceptions but labels only lock acquisition failures", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    await expect(store.withWriter(scope, () => { throw new Error("application failure"); })).rejects.toThrow("application failure");
    const unavailable: DraftLockManager = { request: async () => { throw new Error("lock backend failure"); } };
    const unavailableStore = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: unavailable });
    expect(await unavailableStore.withWriter(scope, () => "never")).toEqual({ ok: false, reason: "lock-unavailable", mode: "web-lock" });
  });

  it("holds the owner shared lock across a writer so cleanup cannot race it", async () => {
    const storage = new MemoryStorage();
    let writerActive = false;
    const requests: Array<{ name: string; mode: "shared" | "exclusive" }> = [];
    const coordinatedLocks: DraftLockManager = {
      request: async <T>(name: string, options: { mode: "shared" | "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => {
        requests.push({ name, mode: options.mode });
        const isOwnerLock = name.includes(".owner.");
        if (isOwnerLock && options.mode === "shared") {
          writerActive = true;
          try { return await callback({ name }); } finally { writerActive = false; }
        }
        if (isOwnerLock && options.mode === "exclusive" && writerActive) return callback(null);
        return callback({ name });
      }
    };
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: coordinatedLocks });
    let release!: () => void;
    const writing = store.withWriter(scope, async () => {
      expect(store.write(scope, draft)).toMatchObject({ ok: true });
      await new Promise<void>((resolve) => { release = resolve; });
    });
    await Promise.resolve();
    expect(await store.cleanupOwnerTransition({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: false, reason: "cleanup-failed" });
    expect(storage.getItem(draftStorageKey(scope))).not.toBeNull();
    expect(requests).toEqual(expect.arrayContaining([
      expect.objectContaining({ mode: "shared" }),
      expect.objectContaining({ mode: "exclusive" })
    ]));
    release();
    await writing;
  });

  it("tombstones stale physical bytes when deleting a memory-only draft before storage recovers", async () => {
    const storage = new RecoverableStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    storage.unavailable = true;
    expect(await mutate(store, scope, () => store.write(scope, { ...draft, tree: { ...draft.tree, name: "Memory only" } })))
      .toMatchObject({ ok: true, mode: "online-only" });
    expect(storage.getItem(draftStorageKey(scope))).not.toBeNull();
    expect(await mutate(store, scope, () => store.delete(scope))).toMatchObject({ ok: true, mode: "online-only" });
    storage.unavailable = false;
    expect(store.probeStorage()).toBe(true);
    expect(store.read(scope)).toEqual({ ok: true, found: false, mode: "durable" });
  });

  it("tombstones the pre-canonical source removed from memory-only rekey state", async () => {
    const storage = new RecoverableStorage();
    const digest = async () => new Uint8Array(32).fill(0xab).buffer;
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-canonical" };
    const store = createCrtDraftStore({
      storage,
      writer_session_id: writerSessionId,
      lock_manager: lockManager,
      crypto: { subtle: { digest } }
    });
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    storage.unavailable = true;
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey, tree: { ...draft.tree, name: "Memory only" } }));
    expect(await store.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: true, mode: "online-only" });
    await mutate(store, canonical, () => store.delete(canonical));
    storage.unavailable = false;
    expect(store.probeStorage()).toBe(true);
    expect(storage.getItem(draftStorageKey(source))).toBeNull();
    expect(store.read(source)).toEqual({ ok: true, found: false, mode: "durable" });
  });

  it("preserves canonical migration metadata across normal edits and recovery while deduplicating a surviving source", async () => {
    const storage = new StickyRemovalStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-canonical" };
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    await store.rekeyPreCanonical(source, canonical.tree_id, migrationId);
    const edited = await mutate(store, canonical, () => store.write(canonical, { ...draft, tree: { ...draft.tree, name: "Edited canonical" } }));
    expect(edited).toMatchObject({ ok: true, value: { migration_id: migrationId, migration_source_create_idempotency_key: createKey } });
    const recovered = await mutate(store, canonical, () => store.recover(canonical));
    expect(recovered).toMatchObject({ ok: true, value: { migration_id: migrationId, migration_source_create_idempotency_key: createKey } });
    const listed = await store.list({ owner_id: scope.owner_id, origin: scope.origin });
    expect(listed).toMatchObject({ ok: true, value: [expect.objectContaining({ value: expect.objectContaining({ tree_id: canonical.tree_id, migration_id: migrationId }) })] });
    expect(listed.ok && listed.value).toHaveLength(1);
  });

  it("rejects canonical writes that supply conflicting migration metadata", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-canonical" };
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    await store.rekeyPreCanonical(source, canonical.tree_id, migrationId);
    const conflicting = await mutate(store, canonical, () => store.write(canonical, {
      ...draft,
      migration_id: "00000000-0000-4000-8000-000000000004",
      migration_fingerprint: "11".repeat(32),
      migration_source_create_idempotency_key: createKey,
      migration_hash_algorithm: "sha-256",
      migration_hash_version: 1
    }));
    expect(conflicting).toEqual({ ok: false, reason: "rekey-conflict", mode: "durable" });
  });

  it("does not promote durable mode while memory-only drafts remain", async () => {
    class FailsDraftWritesAfterFirstSave extends MemoryStorage {
      public failDraftWrites = false;
      override setItem(key: string, value: string): void {
        if (this.failDraftWrites && !key.includes(".probe.")) throw new Error("quota");
        super.setItem(key, value);
      }
    }
    const storage = new FailsDraftWritesAfterFirstSave();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    storage.failDraftWrites = true;
    expect(await mutate(store, scope, () => store.write(scope, { ...draft, tree: { ...draft.tree, name: "Memory only" } }))).toMatchObject({ ok: true, mode: "online-only" });
    expect(store.probeStorage()).toBe(false);
    expect(store.mode).toBe("online-only");
    expect(store.read(scope)).toMatchObject({ ok: true, found: true, value: { tree: { name: "Memory only" } } });
  });

  it("rejects a pre-canonical write whose input key differs from the scope key", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const otherCreateKey = "00000000-0000-4000-8000-000000000004";
    const result = await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: otherCreateKey }));
    expect(result).toMatchObject({ ok: false, reason: "invalid-draft" });
    expect(store.read(source)).toEqual({ ok: true, found: false, mode: "durable" });
  });

  it("turns Web Crypto digest rejection into typed rekey and list failures", async () => {
    const rejectingCrypto = { subtle: { digest: vi.fn(async () => { throw new Error("digest unavailable"); }) } };
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const rekeyStore = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager, crypto: rejectingCrypto });
    await mutate(rekeyStore, source, () => rekeyStore.write(source, { ...draft, create_idempotency_key: createKey }));
    await expect(rekeyStore.rekeyPreCanonical(source, "tree-canonical", migrationId))
      .resolves.toMatchObject({ ok: false, reason: "storage-unavailable" });

    const storage = new MemoryStorage();
    const digest = async () => new Uint8Array(32).fill(0xab).buffer;
    const goodStore = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager, crypto: { subtle: { digest } } });
    await mutate(goodStore, source, () => goodStore.write(source, { ...draft, create_idempotency_key: createKey }));
    await goodStore.rekeyPreCanonical(source, "tree-canonical", migrationId);
    await mutate(goodStore, source, () => goodStore.write(source, { ...draft, create_idempotency_key: createKey }));
    const rejectingListStore = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager, crypto: rejectingCrypto });
    await expect(rejectingListStore.list({ owner_id: scope.owner_id, origin: scope.origin }))
      .resolves.toMatchObject({ ok: false, reason: "storage-unavailable" });
  });

  it("keeps migration deduplication valid after canonical recovery edits", async () => {
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-canonical" };
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await store.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: true });
    expect(await mutate(store, canonical, () => store.recover(canonical))).toMatchObject({ ok: true });
    const listed = await store.list({ owner_id: scope.owner_id, origin: scope.origin });
    expect(listed).toMatchObject({ ok: true, value: [expect.objectContaining({ value: expect.objectContaining({ tree_id: canonical.tree_id, migration_id: migrationId }) })] });
    expect(listed.ok && listed.value).toHaveLength(1);
  });

  it("covers origin/key normalization and invalid scope matrices", async () => {
    expect(normalizeOrigin("HTTPS://APP.EXAMPLE.test:443/path")).toBe("https://app.example.test");
    expect(normalizeOrigin("ftp://app.example.test")).toBe("");
    expect(normalizeOrigin("not a URL")).toBe("");
    const invalidScopes: DraftScope[] = [
      { ...scope, owner_id: "" },
      { ...scope, origin: "" },
      { ...scope, origin: "ftp://app.example.test" },
      { ...scope, tree_id: "" },
      { ...scope, tree_id: null, create_idempotency_key: "not-a-uuid" },
      { ...scope, tree_id: null, create_idempotency_key: null }
    ];
    const store = createCrtDraftStore({ storage: new MemoryStorage(), lock_manager: lockManager });
    for (const invalidScope of invalidScopes) {
      expect(draftStorageKey(invalidScope)).toBe("");
      expect(store.read(invalidScope)).toMatchObject({ ok: false, reason: "invalid-draft" });
      expect(await store.withWriter(invalidScope, () => "never")).toMatchObject({ ok: false, reason: "writer-denied" });
    }
  });

  it.each([
    ["invalid JSON", "{"],
    ["wrong key identity", JSON.stringify({ ...draft, schema_version: 1, owner_id: "owner-b" })],
    ["unsupported schema", JSON.stringify({ schema_version: 99 })]
  ])("rejects physical %s bytes without deleting them", async (_label, raw) => {
    const storage = new MemoryStorage();
    const key = draftStorageKey(scope);
    storage.setItem(key, raw);
    const store = createCrtDraftStore({ storage, lock_manager: lockManager });
    const result = store.read(scope);
    expect(result.ok).toBe(false);
    expect(storage.getItem(key)).toBe(raw);
  });

  it("exercises envelope, timestamp, graph, journal, command, and migration validation branches", () => {
    const valid = {
      schema_version: 1,
      owner_id: "owner-a",
      origin: scope.origin,
      tree_id: "tree-a",
      create_idempotency_key: null,
      base_revision: 0,
      base_updated_at: "2026-09-20T10:00:00Z",
      local_updated_at: "2026-09-20T10:00:00.000Z",
      writer_session_id: writerSessionId,
      generation: 1,
      tree: draft.tree,
      dirty_operations: [],
      in_flight_save: null,
      queued_commands: [],
      digest_algorithm: "sha-256",
      digest_version: 1
    } as Record<string, unknown>;
    expect(validateDraftEnvelope(valid).ok).toBe(true);
    expect(validateDraftEnvelope({
      ...valid,
      base_updated_at: "2026-09-22T22:42:07.835412Z"
    }).ok).toBe(true);
    expect(validateDraftEnvelope({ ...valid, schema_version: 2 })).toEqual({ ok: false, reason: "invalid-schema" });
    const invalids = [
      { ...valid, origin: "HTTPS://APP.EXAMPLE.test:443/path" },
      { ...valid, tree_id: null, create_idempotency_key: null },
      { ...valid, base_revision: -1 },
      { ...valid, base_updated_at: "bad" },
      { ...valid, local_updated_at: "2026-02-30T10:00:00Z" },
      { ...valid, writer_session_id: "writer" },
      { ...valid, generation: 0 },
      { ...valid, tree: { ...draft.tree, name: " " } },
      { ...valid, tree: { ...draft.tree, nodes: [{ ...draft.tree.nodes[0], type: "unknown" }] } },
      { ...valid, tree: { ...draft.tree, nodes: [{ ...draft.tree.nodes[0], highlight_state: "unknown" }] } },
      { ...valid, tree: { ...draft.tree, nodes: [{ ...draft.tree.nodes[0], relation_counts: { up_count: -1, down_count: 0 } }] } },
      { ...valid, tree: { ...draft.tree, relations: [{ id: "r", source_node_id: "node-a", target_node_id: "missing", kind: "why", created_at: "2026-09-20T10:00:00Z" }] } },
      { ...valid, tree: { ...draft.tree, relations: [{ id: "r", source_node_id: "node-a", target_node_id: "node-a", kind: "why", created_at: "2026-09-20T10:00:00Z" }] } },
      { ...valid, tree: { ...draft.tree, layout: { zoom: Number.NaN } } },
      { ...valid, dirty_operations: [{ id: "bad", kind: "not-a-kind" }] },
      { ...valid, in_flight_save: { idempotency_key: "bad", base_revision: 0, generation: 1, snapshot: draft.tree, hash: "bad" } },
      { ...valid, queued_commands: [{ id: writerSessionId, kind: "layout-change", payload: { layout: { center: { x: 0, y: 0 }, zoom: 1, extra: true } } }] },
      { ...valid, migration_id: migrationId },
      { ...valid, migration_fingerprint: "ab".repeat(32) },
      { ...valid, migration_id: migrationId, migration_fingerprint: "ab".repeat(32), migration_source_create_idempotency_key: createKey, migration_hash_algorithm: "sha-256", migration_hash_version: 1 }
    ];
    for (const invalid of invalids.slice(0, -1)) expect(validateDraftEnvelope(invalid).ok).toBe(false);
    expect(validateDraftEnvelope(invalids[invalids.length - 1]).ok).toBe(true);
    const commands = [
      ["card-create", { node_id: "n", label: "N", position: { x: 0, y: 0 } }],
      ["label-edit", { node_id: "n", label: "N" }],
      ["card-move", { node_id: "n", position: { x: 0, y: 0 } }],
      ["relation-create", { relation_id: "r", source_node_id: "a", target_node_id: "b" }],
      ["relation-delete", { relation_id: "r" }],
      ["card-delete", { node_id: "n", confirmed: true }],
      ["tree-rename", { name: "Tree" }],
      ["layout-change", { layout: { center: { x: 0, y: 0 }, zoom: 1 } }]
    ] as const;
    for (const [kind, payload] of commands) {
      expect(validateDraftEnvelope({ ...valid, queued_commands: [{ id: writerSessionId, kind, payload }] }).ok).toBe(true);
      expect(validateDraftEnvelope({ ...valid, queued_commands: [{ id: writerSessionId, kind, payload: {} }] }).ok).toBe(false);
    }
  });

  it("covers writer denial, lock acquisition, fallback cleanup, and application exception branches", async () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    const ownerDenied: DraftLockManager = { request: async (_name, _options, callback) => callback(null) };
    expect(await createCrtDraftStore({ storage: new MemoryStorage(), lock_manager: ownerDenied }).withWriter(scope, () => "never"))
      .toMatchObject({ ok: false, reason: "writer-denied" });
    const keyDenied: DraftLockManager = { request: async (name, _options, callback) => name.includes(".owner.") ? callback({ name }) : callback(null) };
    expect(await createCrtDraftStore({ storage: new MemoryStorage(), lock_manager: keyDenied }).withWriter(scope, () => "never"))
      .toMatchObject({ ok: false, reason: "writer-denied" });
    await expect(store.withWriter(scope, () => { throw new Error("application"); })).rejects.toThrow("application");

    const fallback = createCrtDraftStore({ storage: null, lock_manager: null });
    let release!: () => void;
    const writing = fallback.withWriter(scope, async () => new Promise<void>((resolve) => { release = resolve; }));
    await Promise.resolve();
    expect(await fallback.cleanupOwnerTransition(scope)).toMatchObject({ ok: false, reason: "cleanup-failed" });
    release();
    await writing;
    expect(await fallback.cleanupOwnerTransition(scope)).toMatchObject({ ok: true, value: 0 });
    const unavailableCleanup: DraftLockManager = { request: async () => { throw new Error("lock"); } };
    expect(await createCrtDraftStore({ storage: null, lock_manager: unavailableCleanup }).cleanupOwnerTransition(scope))
      .toMatchObject({ ok: false, reason: "cleanup-failed" });
  });

  it("covers read-back failures, generation tokens, backup/recovery, and delete failures", async () => {
    class ReadFailStorage extends MemoryStorage {
      public failReads = false;
      override getItem(key: string): string | null { if (this.failReads && !key.includes(".probe.")) throw new Error("read"); return super.getItem(key); }
    }
    const storage = new ReadFailStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    const token = store.captureGeneration(scope);
    expect(token).toMatchObject({ generation: 1, key: draftStorageKey(scope) });
    expect(store.captureGeneration({ ...scope, tree_id: "missing" })).toBeNull();
    expect(await mutate(store, scope, () => store.write(scope, draft, { token: { key: "wrong", generation: 1 } }))).toMatchObject({ ok: false, reason: "stale-generation" });
    expect(await mutate(store, scope, () => store.write(scope, draft, { token: token ?? undefined }))).toMatchObject({ ok: true });
    expect(store.exportBackup({ ...scope, owner_id: "other" })).toMatchObject({ ok: false, reason: "not-found" });
    expect(await mutate(store, { ...scope, tree_id: "missing" }, () => store.recover({ ...scope, tree_id: "missing" }))).toMatchObject({ ok: false, reason: "not-found" });
    expect(await mutate(store, scope, () => store.delete(scope, { expected_generation: 1 }))).toMatchObject({ ok: false, reason: "stale-generation" });
    storage.failReads = true;
    expect(store.read(scope)).toMatchObject({ ok: true, mode: "online-only" });
  });

  it("covers rekey prerequisites, idempotent reconciliation, and missing crypto", async () => {
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const noCrypto = createCrtDraftStore({ storage: new MemoryStorage(), lock_manager: lockManager, crypto: null });
    expect(await noCrypto.rekeyPreCanonical(source, "tree-canonical", migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    expect(await store.rekeyPreCanonical(scope, "tree-canonical", migrationId)).toMatchObject({ ok: false, reason: "invalid-draft" });
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await store.rekeyPreCanonical(source, "tree-canonical", migrationId)).toMatchObject({ ok: true });
    expect(await store.rekeyPreCanonical(source, "tree-canonical", migrationId)).toMatchObject({ ok: true });
    const absent = { ...scope, tree_id: null, create_idempotency_key: "00000000-0000-4000-8000-000000000099" };
    expect(await store.rekeyPreCanonical(absent, "tree-other", migrationId)).toMatchObject({ ok: false, reason: "not-found" });
  });

  it("covers cleanup storage enumeration, lock, removal, and readback failures", async () => {
    class CleanupFailureStorage extends MemoryStorage {
      public mode: "length" | "key" | "remove" | "read" | null = null;
      override get length(): number { if (this.mode === "length") throw new Error("length"); return super.length; }
      override key(index: number): string | null { if (this.mode === "key") throw new Error("key"); return super.key(index); }
      override removeItem(key: string): void { if (this.mode === "remove" && !key.includes(".probe.")) throw new Error("remove"); super.removeItem(key); }
      override getItem(key: string): string | null { if (this.mode === "read" && !key.includes(".probe.")) throw new Error("read"); return super.getItem(key); }
    }
    for (const mode of ["length", "key"] as const) {
      const storage = new CleanupFailureStorage();
      const store = createCrtDraftStore({ storage, lock_manager: lockManager });
      await mutate(store, scope, () => store.write(scope, draft));
      storage.mode = mode;
      expect(await store.cleanupOwnerTransition(scope)).toMatchObject({ ok: false, reason: "cleanup-failed" });
    }
    const storage = new CleanupFailureStorage();
    const store = createCrtDraftStore({ storage, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    for (const mode of ["remove", "read"] as const) {
      storage.mode = mode;
      expect(await store.cleanupOwnerTransition(scope)).toMatchObject({ ok: false, reason: "cleanup-failed" });
      storage.mode = null;
    }
    const denied: DraftLockManager = { request: async (_name, _options, callback) => callback(null) };
    const deniedStorage = new MemoryStorage();
    const durableStore = createCrtDraftStore({ storage: deniedStorage, lock_manager: lockManager });
    await mutate(durableStore, scope, () => durableStore.write(scope, draft));
    const deniedStore = createCrtDraftStore({ storage: deniedStorage, lock_manager: denied });
    expect(await deniedStore.cleanupOwnerTransition(scope)).toMatchObject({ ok: false, reason: "cleanup-failed" });
  });

  it("covers default UUID fallback, valid graph traversal, unknown commands, and clone failures", async () => {
    vi.stubGlobal("crypto", {});
    const generated = createCrtDraftStore({ storage: new MemoryStorage(), lock_manager: lockManager });
    expect(await mutate(generated, scope, () => generated.write(scope, draft))).toMatchObject({ ok: true });
    vi.unstubAllGlobals();
    const validGraph = {
      ...draft,
      tree: {
        ...draft.tree,
        nodes: [
          { id: "a", label: "A", type: "parent", position: { x: 0, y: 0 }, highlight_state: "cause_candidate", relation_counts: { up_count: 1, down_count: 0 } },
          { id: "b", label: "B", type: "child", position: { x: 1, y: 1 }, highlight_state: "effect_spanning", relation_counts: { up_count: 0, down_count: 1 } }
        ],
        relations: [{ id: "r", source_node_id: "a", target_node_id: "b", kind: "why", created_at: "2026-09-20T10:00:00Z" }]
      }
    };
    const store = createCrtDraftStore({ storage: new MemoryStorage(), lock_manager: lockManager });
    expect(await mutate(store, scope, () => store.write(scope, validGraph))).toMatchObject({ ok: true });
    const circular = { ...draft, tree: { ...draft.tree, layout: {} } } as Record<string, unknown>;
    (circular.tree as Record<string, unknown>).layout = circular;
    expect(await mutate(store, { ...scope, tree_id: "circular" }, () => store.write({ ...scope, tree_id: "circular" }, circular as never)));
    const unknown = { ...draft, queued_commands: [{ id: writerSessionId, kind: "unknown", payload: {} }] };
    expect(await mutate(store, { ...scope, tree_id: "unknown" }, () => store.write({ ...scope, tree_id: "unknown" }, unknown as never))).toMatchObject({ ok: false, reason: "invalid-draft" });
  });

  it("covers fallback rekey locks and lock-manager rekey failures", async () => {
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const fallback = createCrtDraftStore({ storage: null, lock_manager: null, crypto: { subtle: { digest: async () => new Uint8Array(32).fill(1).buffer } } });
    await mutate(fallback, source, () => fallback.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await fallback.rekeyPreCanonical(source, "tree-fallback", migrationId)).toMatchObject({ ok: true, mode: "online-only" });
    const throwing: DraftLockManager = { request: async (name, _options, callback) => name.includes(".owner.") ? callback({ name }) : Promise.reject(new Error("lock")) };
    const seededStorage = new MemoryStorage();
    const seeded = createCrtDraftStore({ storage: seededStorage, lock_manager: lockManager });
    await mutate(seeded, source, () => seeded.write(source, { ...draft, create_idempotency_key: createKey }));
    const failing = createCrtDraftStore({ storage: seededStorage, lock_manager: throwing, crypto: { subtle: { digest: async () => new Uint8Array(32).fill(1).buffer } } });
    expect(await failing.rekeyPreCanonical(source, "tree-throw", migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });
  });

  it("covers list physical-key validation, orphan migration markers, and delete readback failures", async () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, lock_manager: lockManager, writer_session_id: writerSessionId });
    await mutate(store, scope, () => store.write(scope, draft));
    const prefix = draftStorageKey(scope).split(".").slice(0, -1).join(".");
    storage.setItem(`${prefix}.bad-key`, storage.getItem(draftStorageKey(scope)) ?? "{}");
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: false, reason: "invalid-draft" });
    storage.removeItem(`${prefix}.bad-key`);
    const orphan = { ...draft, tree_id: "orphan", migration_id: migrationId, migration_fingerprint: "ab".repeat(32), migration_source_create_idempotency_key: createKey, migration_hash_algorithm: "sha-256", migration_hash_version: 1 };
    const orphanScope = { ...scope, tree_id: "orphan" };
    await mutate(store, orphanScope, () => store.write(orphanScope, orphan as never));
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: true, value: expect.arrayContaining([expect.objectContaining({ value: expect.objectContaining({ tree_id: "orphan" }) })]) });
    class DeleteReadbackFailure extends MemoryStorage {
      public fail = false;
      private reads = 0;
      override getItem(key: string): string | null {
        if (this.fail && !key.includes(".probe.") && this.reads++ > 0) return "still-there";
        return super.getItem(key);
      }
    }
    const failingStorage = new DeleteReadbackFailure();
    const failing = createCrtDraftStore({ storage: failingStorage, lock_manager: lockManager });
    await mutate(failing, scope, () => failing.write(scope, draft));
    failingStorage.fail = true;
    expect(await mutate(failing, scope, () => failing.delete(scope))).toMatchObject({ ok: false, reason: "storage-unavailable" });
  });

  it("covers list storage enumeration exceptions and raw-key mismatch rejection", async () => {
    class KeyFailureStorage extends MemoryStorage {
      public fail = false;
      override key(index: number): string | null { if (this.fail) throw new Error("key"); return super.key(index); }
    }
    const storage = new KeyFailureStorage();
    const store = createCrtDraftStore({ storage, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    storage.fail = true;
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: false, reason: "storage-unavailable" });
    const rawStorage = new MemoryStorage();
    const rawStore = createCrtDraftStore({ storage: rawStorage, lock_manager: lockManager });
    await mutate(rawStore, scope, () => rawStore.write(scope, draft));
    const key = draftStorageKey(scope);
    rawStorage.setItem(`${key}.extra`, rawStorage.getItem(key) ?? "{}");
    expect(rawStore.read(scope)).toMatchObject({ ok: true, found: true });
  });

  it("covers tombstone flush, malformed physical identities, and final raw reads", async () => {
    class TombstoneStorage extends MemoryStorage {
      public failTarget = false;
      override setItem(key: string, value: string): void { if (this.failTarget && key === draftStorageKey(scope)) throw new Error("set"); super.setItem(key, value); }
      override removeItem(key: string): void { if (this.failTarget && key === draftStorageKey(scope)) throw new Error("remove"); super.removeItem(key); }
    }
    const storage = new TombstoneStorage();
    const store = createCrtDraftStore({ storage, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    const originalRaw = storage.getItem(draftStorageKey(scope)) ?? "";
    storage.failTarget = true;
    expect(await mutate(store, scope, () => store.write(scope, { ...draft, tree: { ...draft.tree, name: "memory" } }))).toMatchObject({ ok: true, mode: "online-only" });
    expect(await mutate(store, scope, () => store.delete(scope))).toMatchObject({ ok: true, mode: "online-only" });
    storage.failTarget = false;
    expect(store.probeStorage()).toBe(true);
    const key = draftStorageKey(scope);
    const validRaw = originalRaw;
    const parts = key.split(".");
    parts[parts.length - 1] = "3-YmFk";
    storage.setItem(parts.join("."), validRaw);
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: false, reason: "invalid-draft" });
    const unavailable = createCrtDraftStore({ storage: new ThrowingStorage(), lock_manager: lockManager });
    expect(unavailable.read(scope)).toMatchObject({ ok: true, found: false, mode: "online-only" });
  });

  it("covers fallback rekey contention and exact-key lock failures", async () => {
    let releaseDigest!: () => void;
    const digestGate = new Promise<ArrayBuffer>((resolve) => { releaseDigest = () => resolve(new Uint8Array(32).buffer); });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const fallback = createCrtDraftStore({ storage: null, lock_manager: null, crypto: { subtle: { digest: () => digestGate } } });
    await mutate(fallback, source, () => fallback.write(source, { ...draft, create_idempotency_key: createKey }));
    const first = fallback.rekeyPreCanonical(source, "tree-held", migrationId);
    await Promise.resolve();
    const second = await fallback.rekeyPreCanonical(source, "tree-held-2", migrationId);
    expect(second).toMatchObject({ ok: false, reason: "rekey-conflict" });
    releaseDigest();
    await first;
    const throwingOwner: DraftLockManager = { request: async () => { throw new Error("owner lock"); } };
    const seededStorage = new MemoryStorage();
    const seeded = createCrtDraftStore({ storage: seededStorage, lock_manager: lockManager });
    await mutate(seeded, source, () => seeded.write(source, { ...draft, create_idempotency_key: createKey }));
    const failing = createCrtDraftStore({ storage: seededStorage, lock_manager: throwingOwner, crypto: { subtle: { digest: async () => new Uint8Array(32).buffer } } });
    expect(await failing.rekeyPreCanonical(source, "tree-owner-fail", migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });
  });

  it("covers canonical rekey retry after source removal failure and delete exceptions", async () => {
    class SourceRemovalFailure extends MemoryStorage {
      public fail = true;
      override removeItem(key: string): void { if (this.fail && key === draftStorageKey({ ...scope, tree_id: null, create_idempotency_key: createKey })) throw new Error("source remove"); super.removeItem(key); }
    }
    const storage = new SourceRemovalFailure();
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-retry" };
    const store = createCrtDraftStore({ storage, lock_manager: lockManager, crypto: { subtle: { digest: async () => new Uint8Array(32).buffer } } });
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await store.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });
    storage.fail = false;
    expect(await store.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: true });
    class ThrowDelete extends MemoryStorage { override removeItem(key: string): void { if (!key.includes(".probe.")) throw new Error("delete"); super.removeItem(key); } }
    const deleteStorage = new ThrowDelete();
    const deleteStore = createCrtDraftStore({ storage: deleteStorage, lock_manager: lockManager });
    await mutate(deleteStore, scope, () => deleteStore.write(scope, draft));
    expect(await mutate(deleteStore, scope, () => deleteStore.delete(scope))).toMatchObject({ ok: false, reason: "storage-unavailable" });
  });

  it("covers cleanup second-pass failures and phantom durable keys", async () => {
    class PhantomStorage extends MemoryStorage {
      public phantom = false;
      override key(index: number): string | null { if (this.phantom && index === 0) return draftStorageKey(scope); return super.key(index); }
      override getItem(key: string): string | null { if (this.phantom && key === draftStorageKey(scope)) return null; return super.getItem(key); }
    }
    const storage = new PhantomStorage();
    const store = createCrtDraftStore({ storage, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    storage.phantom = true;
    expect(await store.cleanupOwnerTransition(scope)).toMatchObject({ ok: true });
    storage.phantom = false;
    expect(await store.list({ owner_id: scope.owner_id, origin: scope.origin })).toMatchObject({ ok: true });
  });

  it("rekey acquires both exact keys and conflicts with a concurrent canonical writer", async () => {
    const storage = new MemoryStorage();
    const heldLocks = new Set<string>();
    const runtimeLocks: DraftLockManager = {
      request: async <T>(name: string, _options: { mode: "shared" | "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) => {
        if (heldLocks.has(name)) return callback(null);
        heldLocks.add(name);
        try { return await callback({ name }); } finally { heldLocks.delete(name); }
      }
    };
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: runtimeLocks });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-canonical" };
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    let release!: () => void;
    let entered!: () => void;
    const canonicalEntered = new Promise<void>((resolve) => { entered = resolve; });
    const canonicalWriter = store.withWriter(canonical, async () => {
      expect(store.write(canonical, { ...draft, tree: { ...draft.tree, name: "Concurrent canonical" } })).toMatchObject({ ok: true });
      entered();
      await new Promise<void>((resolve) => { release = resolve; });
    });
    await canonicalEntered;
    expect(await store.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });
    release();
    await canonicalWriter;
    expect(store.read(source)).toMatchObject({ ok: true, found: true });
  });

  it("covers default dependency discovery and validation edge paths", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => writerSessionId });
    vi.stubGlobal("navigator", { locks: lockManager });
    try {
      const store = createCrtDraftStore({ storage: new MemoryStorage() });
      vi.stubGlobal("navigator", {});
      const withoutLocks = createCrtDraftStore({ storage: null });
      expect(withoutLocks.mode).toBe("online-only");
      vi.stubGlobal("navigator", { locks: lockManager });
      const written = await mutate(store, scope, () => store.write(scope, draft));
      expect(written).toMatchObject({ ok: true, value: { writer_session_id: writerSessionId } });
      if (!written.ok) return;
      const valid = written.value;
      const graphNodes = [
        { id: "a", label: "A", type: "parent", position: { x: 0, y: 0 }, highlight_state: "none", relation_counts: { up_count: 0, down_count: 0 } },
        { id: "b", label: "B", type: "child", position: { x: 1, y: 1 }, highlight_state: "none", relation_counts: { up_count: 0, down_count: 0 } },
        { id: "c", label: "C", type: "child", position: { x: 2, y: 2 }, highlight_state: "none", relation_counts: { up_count: 0, down_count: 0 } }
      ];
      const validLayout = { ...valid, tree: { ...valid.tree, layout: { nested: [1, { ok: true }] } } };
      expect(validateDraftEnvelope(validLayout).ok).toBe(true);
      const convergingGraph = { ...valid, tree: { name: "converges", nodes: graphNodes, relations: [
        { id: "r1", source_node_id: "a", target_node_id: "b", kind: "why", created_at: "2026-09-20T10:00:00Z" },
        { id: "r2", source_node_id: "a", target_node_id: "c", kind: "why", created_at: "2026-09-20T10:00:00Z" },
        { id: "r3", source_node_id: "b", target_node_id: "c", kind: "why", created_at: "2026-09-20T10:00:00Z" }
      ] } };
      expect(validateDraftEnvelope(convergingGraph).ok).toBe(true);
      const invalids: unknown[] = [
        { ...valid, base_updated_at: "9999-99-99T10:00:00Z" },
        { ...valid, tree: { ...valid.tree, relations: [{ id: "r", source_node_id: "node-a", target_node_id: "node-a", kind: "what", created_at: "2026-09-20T10:00:00Z" }] } },
        { ...valid, tree: { name: "duplicate", nodes: graphNodes, relations: [
          { id: "r1", source_node_id: "a", target_node_id: "b", kind: "why", created_at: "2026-09-20T10:00:00Z" },
          { id: "r2", source_node_id: "a", target_node_id: "b", kind: "why", created_at: "2026-09-20T10:00:00Z" }
        ] } },
        { ...valid, tree: { name: "cycle", nodes: graphNodes.slice(0, 2), relations: [
          { id: "r1", source_node_id: "a", target_node_id: "b", kind: "why", created_at: "2026-09-20T10:00:00Z" },
          { id: "r2", source_node_id: "b", target_node_id: "a", kind: "why", created_at: "2026-09-20T10:00:00Z" }
        ] } },
        { ...valid, tree: { name: "bad-kind", nodes: graphNodes, relations: [{ id: "r", source_node_id: "a", target_node_id: "b", kind: "what", created_at: "2026-09-20T10:00:00Z" }] } },
        { ...valid, queued_commands: [{ id: writerSessionId, kind: "label-edit", payload: null }] }
      ];
      for (const invalid of invalids) expect(validateDraftEnvelope(invalid).ok).toBe(false);
      expect(validateDraftEnvelope(valid).ok).toBe(true);
      expect(validateDraftEnvelope(null)).toEqual({ ok: false, reason: "invalid-schema" });
      expect(validateDraftEnvelope({ ...valid, in_flight_save: {
        idempotency_key: createKey,
        base_revision: 0,
        generation: 1,
        snapshot: valid.tree,
        hash: "ab".repeat(32),
        request_payload: { body: ["request", { retry: false }] }
      } }).ok).toBe(true);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("covers probe readback, durable write readback, malformed current bytes, and writer identity failures", async () => {
    class ProbeMismatchStorage extends MemoryStorage {
      override getItem(key: string): string | null { return key.includes(".probe.") ? "wrong" : super.getItem(key); }
    }
    expect(createCrtDraftStore({ storage: new ProbeMismatchStorage(), lock_manager: lockManager }).mode).toBe("online-only");
    class ProbeSetFailure extends MemoryStorage {
      override setItem(key: string, value: string): void { if (key.includes(".probe.")) throw new Error("set"); super.setItem(key, value); }
      override getItem(key: string): string | null { return key.includes(".probe.") ? "stuck" : super.getItem(key); }
      override removeItem(key: string): void { if (key.includes(".probe.")) return; super.removeItem(key); }
    }
    expect(createCrtDraftStore({ storage: new ProbeSetFailure(), lock_manager: lockManager }).mode).toBe("online-only");

    class WriteMismatchStorage extends MemoryStorage {
      public mismatch = false;
      private targetReads = 0;
      override getItem(key: string): string | null {
        if (key === draftStorageKey(scope)) {
          this.targetReads += 1;
          if (this.mismatch && this.targetReads === 4) return "wrong";
        }
        return super.getItem(key);
      }
    }
    const mismatchStorage = new WriteMismatchStorage();
    const mismatchStore = createCrtDraftStore({ storage: mismatchStorage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(mismatchStore, scope, () => mismatchStore.write(scope, draft));
    mismatchStorage.mismatch = true;
    expect(await mutate(mismatchStore, scope, () => mismatchStore.write(scope, { ...draft, tree: { ...draft.tree, name: "readback" } })))
      .toMatchObject({ ok: true, mode: "online-only" });

    const malformedStorage = new MemoryStorage();
    malformedStorage.setItem(draftStorageKey(scope), "{");
    const malformedStore = createCrtDraftStore({ storage: malformedStorage, writer_session_id: writerSessionId, lock_manager: lockManager });
    expect(await mutate(malformedStore, scope, () => malformedStore.write(scope, draft))).toMatchObject({ ok: false, reason: "invalid-json" });

    const invalidWriter = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: "writer", lock_manager: lockManager });
    expect(await mutate(invalidWriter, scope, () => invalidWriter.write(scope, draft))).toMatchObject({ ok: false, reason: "invalid-draft" });
  });

  it("flushes a tombstone closed when recovered removal still fails", async () => {
    class TombstoneFlushFailure extends MemoryStorage {
      public fail = false;
      public sticky = false;
      override removeItem(key: string): void {
        if (this.fail && key === draftStorageKey(scope)) throw new Error("offline");
        if (this.sticky && key === draftStorageKey(scope)) return;
        super.removeItem(key);
      }
      override setItem(key: string, value: string): void {
        if (this.fail && key === draftStorageKey(scope)) throw new Error("offline");
        super.setItem(key, value);
      }
    }
    const storage = new TombstoneFlushFailure();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    storage.fail = true;
    await mutate(store, scope, () => store.write(scope, { ...draft, tree: { ...draft.tree, name: "memory" } }));
    await mutate(store, scope, () => store.delete(scope));
    storage.fail = false;
    storage.sticky = true;
    expect(store.probeStorage()).toBe(false);
    expect(store.mode).toBe("online-only");
  });

  it("covers fallback memory cleanup and unavailable owner locks", async () => {
    const fallback = createCrtDraftStore({ storage: null, lock_manager: null, writer_session_id: writerSessionId });
    await mutate(fallback, scope, () => fallback.write(scope, draft));
    expect(await fallback.cleanupOwnerTransition({ owner_id: scope.owner_id, origin: scope.origin })).toEqual({ ok: true, value: 1, mode: "online-only" });

    const denied: DraftLockManager = { request: async (_name, _options, callback) => callback(null) };
    const deniedStore = createCrtDraftStore({ storage: null, lock_manager: denied, writer_session_id: writerSessionId });
    expect(await deniedStore.cleanupOwnerTransition(scope)).toMatchObject({ ok: false, reason: "cleanup-failed" });
    expect(await fallback.cleanupOwnerTransition({ owner_id: "", origin: scope.origin })).toMatchObject({ ok: false, reason: "cleanup-failed" });
  });

  it("covers exact rekey lock denial and malformed canonical/source reads", async () => {
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-malformed" };
    const storage = new MemoryStorage();
    const seeded = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(seeded, source, () => seeded.write(source, { ...draft, create_idempotency_key: createKey }));
    storage.setItem(draftStorageKey(canonical), "{");
    expect(await seeded.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "invalid-json" });

    const sourceBadStorage = new MemoryStorage();
    sourceBadStorage.setItem(draftStorageKey(source), "{");
    const sourceBad = createCrtDraftStore({ storage: sourceBadStorage, lock_manager: lockManager, crypto: { subtle: { digest: async () => new Uint8Array(32).buffer } } });
    expect(await sourceBad.rekeyPreCanonical(source, "tree-source-bad", migrationId)).toMatchObject({ ok: false, reason: "invalid-json" });

    const exactDenied: DraftLockManager = { request: async <T>(name: string, _options: { mode: "shared" | "exclusive"; ifAvailable: true }, callback: (lock: { name: string } | null) => T | Promise<T>) =>
      name.includes(".owner.") ? callback({ name }) : callback(null) };
    const lockStore = createCrtDraftStore({ storage, lock_manager: exactDenied, crypto: { subtle: { digest: async () => new Uint8Array(32).buffer } } });
    expect(await lockStore.rekeyPreCanonical(source, "tree-lock-denied", migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });
  });

  it("covers rekey verification, source-generation, fingerprint, and removal failures", async () => {
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-verify" };
    const digest = async () => new Uint8Array(32).fill(0xab).buffer;

    class TamperCanonicalRead extends MemoryStorage {
      private canonicalReads = 0;
      override getItem(key: string): string | null {
        const value = super.getItem(key);
        if (key === draftStorageKey(canonical) && value !== null && ++this.canonicalReads === 2) {
          const tampered = JSON.parse(value) as Record<string, unknown>;
          tampered.migration_fingerprint = "00".repeat(32);
          super.setItem(key, JSON.stringify(tampered));
          return super.getItem(key);
        }
        return value;
      }
    }
    const verifyStorage = new TamperCanonicalRead();
    const verifyStore = createCrtDraftStore({ storage: verifyStorage, lock_manager: lockManager, crypto: { subtle: { digest } } });
    await mutate(verifyStore, source, () => verifyStore.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await verifyStore.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });

    const generationCanonical = { ...scope, tree_id: "tree-generation" };
    class SourceGenerationChange extends MemoryStorage {
      private changed = false;
      override getItem(key: string): string | null {
        const value = super.getItem(key);
        if (!this.changed && key === draftStorageKey(generationCanonical) && value !== null) {
          this.changed = true;
          const sourceRaw = super.getItem(draftStorageKey(source));
          if (sourceRaw) {
            const changedSource = JSON.parse(sourceRaw) as Record<string, unknown>;
            changedSource.generation = 2;
            super.setItem(draftStorageKey(source), JSON.stringify(changedSource));
          }
        }
        return value;
      }
    }
    const generationStorage = new SourceGenerationChange();
    const generationStore = createCrtDraftStore({ storage: generationStorage, lock_manager: lockManager, crypto: { subtle: { digest } } });
    await mutate(generationStore, source, () => generationStore.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await generationStore.rekeyPreCanonical(source, "tree-generation", migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });

    let digestCalls = 0;
    const mismatchedCrypto = { subtle: { digest: async () => new Uint8Array(32).fill(++digestCalls === 1 ? 0xab : 0xcd).buffer } };
    const fingerprintStorage = new MemoryStorage();
    const fingerprintStore = createCrtDraftStore({ storage: fingerprintStorage, lock_manager: lockManager, crypto: mismatchedCrypto });
    await mutate(fingerprintStore, source, () => fingerprintStore.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await fingerprintStore.rekeyPreCanonical(source, "tree-fingerprint", migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });

    const rejectingCrypto = { subtle: { digest: vi.fn(async () => { throw new Error("digest"); }) } };
    const rejectStore = createCrtDraftStore({ storage: fingerprintStorage, lock_manager: lockManager, crypto: rejectingCrypto });
    expect(await rejectStore.rekeyPreCanonical(source, "tree-reject", migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });

    class SourceRemovalThrows extends MemoryStorage {
      public fail = false;
      override removeItem(key: string): void { if (this.fail && key === draftStorageKey(source)) throw new Error("remove"); super.removeItem(key); }
    }
    const removalStorage = new SourceRemovalThrows();
    const removalStore = createCrtDraftStore({ storage: removalStorage, lock_manager: lockManager, crypto: { subtle: { digest } } });
    await mutate(removalStore, source, () => removalStore.write(source, { ...draft, create_idempotency_key: createKey }));
    removalStorage.fail = true;
    expect(await removalStore.rekeyPreCanonical(source, "tree-removal", migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });
  });

  it("covers successful cleanup, phantom second passes, memory cleanup, and outer lock errors", async () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, lock_manager: lockManager, writer_session_id: writerSessionId });
    await mutate(store, scope, () => store.write(scope, draft));
    expect(await store.cleanupOwnerTransition(scope)).toEqual({ ok: true, value: 1, mode: "durable" });

    class SecondPassPhantom extends MemoryStorage {
      public phantom = false;
      public pass = 0;
      override get length(): number { return this.phantom ? 1 : super.length; }
      override key(index: number): string | null {
        if (this.phantom && index === 0) {
          this.pass += 1;
          if (this.pass === 2) return draftStorageKey(scope);
          return draftStorageKey(scope);
        }
        return super.key(index);
      }
    }
    const phantomStorage = new SecondPassPhantom();
    const phantomStore = createCrtDraftStore({ storage: phantomStorage, lock_manager: lockManager });
    await mutate(phantomStore, scope, () => phantomStore.write(scope, draft));
    phantomStorage.phantom = true;
    expect(await phantomStore.cleanupOwnerTransition(scope)).toMatchObject({ ok: false, reason: "cleanup-failed" });

    const memoryStorage = new MemoryStorage();
    const memoryStore = createCrtDraftStore({ storage: memoryStorage, lock_manager: lockManager });
    await mutate(memoryStore, scope, () => memoryStore.write(scope, draft));
    memoryStorage.removeItem(draftStorageKey(scope));
    expect(await memoryStore.cleanupOwnerTransition(scope)).toMatchObject({ ok: true, value: 0 });

    const throwingStorage = new MemoryStorage();
    const throwingStore = createCrtDraftStore({ storage: throwingStorage, lock_manager: lockManager });
    await mutate(throwingStore, scope, () => throwingStore.write(scope, draft));
    const outerThrow: DraftLockManager = { request: async () => { throw new Error("outer"); } };
    const outerStore = createCrtDraftStore({ storage: throwingStorage, lock_manager: outerThrow });
    expect(await outerStore.cleanupOwnerTransition(scope)).toMatchObject({ ok: false, reason: "cleanup-failed" });
  });

  it("covers online-only listing, invalid exports, not-found mutations, and discard", async () => {
    const fallback = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: null });
    await mutate(fallback, scope, () => fallback.write(scope, draft));
    await mutate(fallback, { ...scope, owner_id: "other-owner" }, () => fallback.write({ ...scope, owner_id: "other-owner" }, draft));
    expect(await fallback.list(scope)).toMatchObject({ ok: true, value: [expect.objectContaining({ value: expect.objectContaining({ tree_id: scope.tree_id }) })] });
    expect(fallback.exportBackup({ ...scope, tree_id: "missing" })).toMatchObject({ ok: false, reason: "not-found" });
    expect(fallback.exportBackup({ ...scope, owner_id: "" })).toMatchObject({ ok: false, reason: "invalid-draft" });
    expect(await mutate(fallback, { ...scope, tree_id: "missing" }, () => fallback.delete({ ...scope, tree_id: "missing" }))).toMatchObject({ ok: true, value: true });
    expect(await mutate(fallback, scope, () => fallback.delete(scope, { token: { key: "wrong", generation: 1 } }))).toMatchObject({ ok: false, reason: "stale-generation" });
    expect(await mutate(fallback, scope, () => fallback.discard(scope))).toMatchObject({ ok: true, value: true });

    const malformedStorage = new MemoryStorage();
    malformedStorage.setItem(draftStorageKey(scope), "{");
    const malformed = createCrtDraftStore({ storage: malformedStorage, lock_manager: lockManager });
    expect(await mutate(malformed, scope, () => malformed.delete(scope))).toMatchObject({ ok: false, reason: "invalid-json" });
    expect(await mutate(malformed, scope, () => malformed.recover(scope))).toMatchObject({ ok: false, reason: "invalid-json" });
  });

  it("deduplicates multiple orphan migration markers deterministically", async () => {
    const clock = { now: () => Date.parse("2026-09-20T12:00:00.000Z") };
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager, clock });
    const marker = {
      migration_id: migrationId,
      migration_fingerprint: "ab".repeat(32),
      migration_source_create_idempotency_key: createKey,
      migration_hash_algorithm: "sha-256" as const,
      migration_hash_version: 1 as const
    };
    for (const treeId of ["orphan-a", "orphan-b", "orphan-c"]) {
      const orphanScope = { ...scope, tree_id: treeId };
      await mutate(store, orphanScope, () => store.write(orphanScope, { ...draft, ...marker, tree: { ...draft.tree, name: treeId } }));
    }
    const listed = await store.list(scope);
    expect(listed).toMatchObject({ ok: true, value: [expect.objectContaining({ value: expect.objectContaining({ tree_id: expect.stringMatching(/^orphan-/) }) })] });
    expect(listed.ok && listed.value).toHaveLength(1);
  });

  it("reports missing crypto while listing a source-backed migration", async () => {
    const storage = new StickyRemovalStorage();
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const cryptoStore = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager, crypto: { subtle: { digest: async () => new Uint8Array(32).fill(0xab).buffer } } });
    await mutate(cryptoStore, source, () => cryptoStore.write(source, { ...draft, create_idempotency_key: createKey }));
    await cryptoStore.rekeyPreCanonical(source, "tree-with-source", migrationId);
    const noCrypto = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager, crypto: null });
    expect(await noCrypto.list(scope)).toMatchObject({ ok: false, reason: "storage-unavailable" });
  });

  it("covers fallback shared readers, minimal writes, invalid rekey keys, and locked cleanup", async () => {
    const fallback = createCrtDraftStore({ storage: null, lock_manager: null, writer_session_id: writerSessionId });
    const otherTree = { ...scope, tree_id: "reader-b" };
    let releaseA!: () => void;
    let releaseB!: () => void;
    const first = fallback.withWriter(scope, () => new Promise<void>((resolve) => { releaseA = resolve; }));
    const second = fallback.withWriter(otherTree, () => new Promise<void>((resolve) => { releaseB = resolve; }));
    await Promise.resolve();
    releaseA();
    await first;
    releaseB();
    await second;

    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    expect(await mutate(store, scope, () => store.write(scope, { tree: draft.tree }))).toMatchObject({ ok: true, value: { base_revision: null, base_updated_at: null, dirty_operations: [], queued_commands: [] } });
    const badSource = { ...scope, tree_id: null, create_idempotency_key: "bad" };
    expect(await store.rekeyPreCanonical(badSource, "tree-bad-source", migrationId)).toMatchObject({ ok: false, reason: "invalid-draft" });

    const lockStore = createCrtDraftStore({ storage: null, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(lockStore, scope, () => lockStore.write(scope, draft));
    expect(await lockStore.cleanupOwnerTransition(scope)).toMatchObject({ ok: true, value: 1, mode: "online-only" });
  });

  it("covers cleanup nonmatching keys, source-backed retries, and raw readback races", async () => {
    const storage = new MemoryStorage();
    const other = { ...scope, owner_id: "other-owner" };
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    await mutate(store, other, () => store.write(other, draft));
    expect(await store.cleanupOwnerTransition(scope)).toMatchObject({ ok: true, value: 1 });

    class RawReadbackMismatch extends MemoryStorage {
      public mismatch = false;
      override getItem(key: string): string | null {
        if (this.mismatch && key === draftStorageKey(scope)) return "still-there";
        return super.getItem(key);
      }
    }
    const mismatchStorage = new RawReadbackMismatch();
    const mismatchStore = createCrtDraftStore({ storage: mismatchStorage, lock_manager: lockManager });
    await mutate(mismatchStore, scope, () => mismatchStore.write(scope, draft));
    mismatchStorage.mismatch = true;
    expect(await mismatchStore.cleanupOwnerTransition(scope)).toMatchObject({ ok: false, reason: "cleanup-failed" });

    class EnumerationRace extends MemoryStorage {
      public raced = false;
      override key(index: number): string | null {
        const key = super.key(index);
        if (!this.raced && key === draftStorageKey(scope)) { this.raced = true; super.removeItem(key); }
        return key;
      }
    }
    const raceStorage = new EnumerationRace();
    const raceStore = createCrtDraftStore({ storage: raceStorage, lock_manager: lockManager });
    await mutate(raceStore, scope, () => raceStore.write(scope, draft));
    expect(await raceStore.list(scope)).toMatchObject({ ok: true, value: [] });
  });

  it("covers malformed export/recovery, denied discard, tombstone exceptions, and raw write verification", async () => {
    const malformedStorage = new MemoryStorage();
    malformedStorage.setItem(draftStorageKey(scope), "{");
    const malformed = createCrtDraftStore({ storage: malformedStorage, lock_manager: lockManager });
    expect(malformed.exportBackup(scope)).toMatchObject({ ok: false, reason: "invalid-json" });
    expect(malformed.recover(scope)).toMatchObject({ ok: false, reason: "writer-denied" });
    expect(malformed.discard(scope)).toMatchObject({ ok: false, reason: "writer-denied" });

    class TombstoneThrow extends MemoryStorage {
      public fail = false;
      override removeItem(key: string): void { if (this.fail && key === draftStorageKey(scope)) throw new Error("remove"); super.removeItem(key); }
      override setItem(key: string, value: string): void { if (this.fail && key === draftStorageKey(scope)) throw new Error("set"); super.setItem(key, value); }
    }
    const tombstone = new TombstoneThrow();
    const tombstoneStore = createCrtDraftStore({ storage: tombstone, lock_manager: lockManager });
    await mutate(tombstoneStore, scope, () => tombstoneStore.write(scope, draft));
    tombstone.fail = true;
    await mutate(tombstoneStore, scope, () => tombstoneStore.write(scope, { ...draft, tree: { ...draft.tree, name: "memory" } }));
    await mutate(tombstoneStore, scope, () => tombstoneStore.delete(scope));
    tombstone.fail = false;
    tombstone.fail = true;
    expect(tombstoneStore.probeStorage()).toBe(false);

    class CanonicalReadbackMismatch extends MemoryStorage {
      public canonicalKey = "";
      public mismatch = false;
      override getItem(key: string): string | null {
        const value = super.getItem(key);
        return this.mismatch && key === this.canonicalKey && value !== null ? "wrong" : value;
      }
    }
    const storage = new CanonicalReadbackMismatch();
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-write-verify" };
    const store = createCrtDraftStore({ storage, lock_manager: lockManager, crypto: { subtle: { digest: async () => new Uint8Array(32).buffer } } });
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    storage.canonicalKey = draftStorageKey(canonical);
    storage.mismatch = true;
    expect(await store.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });
  });

  it("covers existing canonical rekey conflicts and final fingerprint failures", async () => {
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-existing" };

    class DropSourceAfterRead extends MemoryStorage {
      public drop = false;
      private sourceReads = 0;
      override removeItem(key: string): void {
        if (!key.includes(".probe.") && !(this.drop && key === draftStorageKey(source))) return;
        super.removeItem(key);
      }
      override getItem(key: string): string | null {
        const value = super.getItem(key);
        if (this.drop && key === draftStorageKey(source) && value !== null && ++this.sourceReads === 1) super.removeItem(key);
        return value;
      }
    }
    const droppedStorage = new DropSourceAfterRead();
    const droppedStore = createCrtDraftStore({ storage: droppedStorage, lock_manager: lockManager, crypto: { subtle: { digest: async () => new Uint8Array(32).fill(0xab).buffer } } });
    await mutate(droppedStore, source, () => droppedStore.write(source, { ...draft, create_idempotency_key: createKey }));
    await droppedStore.rekeyPreCanonical(source, canonical.tree_id, migrationId);
    droppedStorage.drop = true;
    expect(await droppedStore.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });

    class DropAfterSecondRead extends MemoryStorage {
      public drop = false;
      private sourceReads = 0;
      override removeItem(key: string): void {
        if (!key.includes(".probe.") && !(this.drop && key === draftStorageKey(source))) return;
        super.removeItem(key);
      }
      override getItem(key: string): string | null {
        const value = super.getItem(key);
        if (this.drop && key === draftStorageKey(source) && value !== null && ++this.sourceReads === 2) super.removeItem(key);
        return value;
      }
    }
    const removeRaceStorage = new DropAfterSecondRead();
    const removeRaceStore = createCrtDraftStore({ storage: removeRaceStorage, lock_manager: lockManager, crypto: { subtle: { digest: async () => new Uint8Array(32).fill(0xab).buffer } } });
    await mutate(removeRaceStore, source, () => removeRaceStore.write(source, { ...draft, create_idempotency_key: createKey }));
    await removeRaceStore.rekeyPreCanonical(source, canonical.tree_id, migrationId);
    removeRaceStorage.drop = true;
    expect(await removeRaceStore.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });

    let digestCalls = 0;
    const conflictCrypto = { subtle: { digest: async () => new Uint8Array(32).fill(++digestCalls === 4 ? 0xcd : 0xab).buffer } };
    const conflictStorage = new StickyRemovalStorage();
    const conflictStore = createCrtDraftStore({ storage: conflictStorage, lock_manager: lockManager, crypto: conflictCrypto });
    await mutate(conflictStore, source, () => conflictStore.write(source, { ...draft, create_idempotency_key: createKey }));
    await conflictStore.rekeyPreCanonical(source, canonical.tree_id, migrationId);
    expect(await conflictStore.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });

    let rejectingCalls = 0;
    const rejectingExisting = { subtle: { digest: async () => {
      rejectingCalls += 1;
      if (rejectingCalls === 4) throw new Error("digest");
      return new Uint8Array(32).fill(0xab).buffer;
    } } };
    const rejectingStorage = new StickyRemovalStorage();
    const rejectingStore = createCrtDraftStore({ storage: rejectingStorage, lock_manager: lockManager, crypto: rejectingExisting });
    await mutate(rejectingStore, source, () => rejectingStore.write(source, { ...draft, create_idempotency_key: createKey }));
    await rejectingStore.rekeyPreCanonical(source, canonical.tree_id, migrationId);
    expect(await rejectingStore.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });

    class ThrowAfterMigration extends StickyRemovalStorage {
      public fail = false;
      override removeItem(key: string): void { if (this.fail && key === draftStorageKey(source)) throw new Error("remove"); super.removeItem(key); }
    }
    const removalStorage = new ThrowAfterMigration();
    const removalStore = createCrtDraftStore({ storage: removalStorage, lock_manager: lockManager, crypto: { subtle: { digest: async () => new Uint8Array(32).fill(0xab).buffer } } });
    await mutate(removalStore, source, () => removalStore.write(source, { ...draft, create_idempotency_key: createKey }));
    await removalStore.rekeyPreCanonical(source, canonical.tree_id, migrationId);
    removalStorage.fail = true;
    expect(await removalStore.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });

    let newPathCalls = 0;
    const newPathCrypto = { subtle: { digest: async () => {
      newPathCalls += 1;
      if (newPathCalls === 2) throw new Error("digest");
      return new Uint8Array(32).buffer;
    } } };
    const newPathStorage = new MemoryStorage();
    const newPathStore = createCrtDraftStore({ storage: newPathStorage, lock_manager: lockManager, crypto: newPathCrypto });
    await mutate(newPathStore, source, () => newPathStore.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await newPathStore.rekeyPreCanonical(source, "tree-final-fingerprint", migrationId)).toMatchObject({ ok: false, reason: "storage-unavailable" });
  });

  it("covers a storage transition detected during existing rekey removal", async () => {
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-storage-transition" };
    class ProbeFailsLater extends MemoryStorage {
      public failProbe = false;
      override removeItem(key: string): void {
        if (!key.includes(".probe.")) return;
        if (this.failProbe) return;
        super.removeItem(key);
      }
      override setItem(key: string, value: string): void {
        if (this.failProbe && key.includes(".probe.")) throw new Error("probe");
        super.setItem(key, value);
      }
    }
    const storage = new ProbeFailsLater();
    let digestCalls = 0;
    const crypto = { subtle: { digest: async () => {
      digestCalls += 1;
      if (digestCalls === 4) { storage.failProbe = true; store.probeStorage(); }
      return new Uint8Array(32).fill(0xab).buffer;
    } } };
    const store = createCrtDraftStore({ storage, lock_manager: lockManager, crypto });
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    await store.rekeyPreCanonical(source, canonical.tree_id, migrationId);
    expect(await store.rekeyPreCanonical(source, canonical.tree_id, migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });
  });

  it("covers physical invalidation readback, cleanup key exceptions, and invalid lists", async () => {
    class StickyInvalidation extends MemoryStorage {
      public fail = false;
      override setItem(key: string, value: string): void { if (this.fail && key === draftStorageKey(scope)) throw new Error("set"); super.setItem(key, value); }
      override removeItem(key: string): void { if (this.fail && key === draftStorageKey(scope)) return; super.removeItem(key); }
    }
    const invalidationStorage = new StickyInvalidation();
    const invalidationStore = createCrtDraftStore({ storage: invalidationStorage, lock_manager: lockManager });
    await mutate(invalidationStore, scope, () => invalidationStore.write(scope, draft));
    invalidationStorage.fail = true;
    expect(await mutate(invalidationStore, scope, () => invalidationStore.write(scope, { ...draft, tree: { ...draft.tree, name: "invalidate" } })))
      .toMatchObject({ ok: true, mode: "online-only" });

    class KeyThrowsSecondPass extends MemoryStorage {
      public active = false;
      public calls = 0;
      override get length(): number { return this.active ? 1 : super.length; }
      override key(index: number): string | null {
        if (this.active && index === 0) {
          this.calls += 1;
          if (this.calls === 2) throw new Error("second pass");
          return draftStorageKey(scope);
        }
        return super.key(index);
      }
    }
    const keyStorage = new KeyThrowsSecondPass();
    const keyStore = createCrtDraftStore({ storage: keyStorage, lock_manager: lockManager });
    await mutate(keyStore, scope, () => keyStore.write(scope, draft));
    keyStorage.active = true;
    expect(await keyStore.cleanupOwnerTransition(scope)).toMatchObject({ ok: false, reason: "cleanup-failed" });

    const invalidListStore = createCrtDraftStore({ storage: new MemoryStorage(), lock_manager: lockManager });
    expect(await invalidListStore.list({ owner_id: "", origin: scope.origin })).toMatchObject({ ok: false, reason: "invalid-draft" });
  });

  it("covers normalization, canonical envelope alternatives, and migration marker rejection", async () => {
    expect(normalizeOrigin("file:///tmp/brainbuddy")).toBe("");
    const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const written = await mutate(store, scope, () => store.write(scope, draft));
    expect(written.ok).toBe(true);
    if (!written.ok) return;
    const valid = written.value;
    expect(validateDraftEnvelope({ ...valid, tree_id: "", create_idempotency_key: null }).ok).toBe(false);
    expect(validateDraftEnvelope({ ...valid, tree_id: null, create_idempotency_key: null }).ok).toBe(false);
    expect(validateDraftEnvelope({ ...valid, create_idempotency_key: createKey }).ok).toBe(true);
    expect(validateDraftEnvelope({ ...valid, migration_fingerprint: "ab".repeat(32) }).ok).toBe(false);
    expect(validateDraftEnvelope({
      ...valid,
      migration_id: migrationId,
      migration_fingerprint: "ab".repeat(32),
      migration_source_create_idempotency_key: createKey,
      migration_hash_algorithm: "sha-256",
      migration_hash_version: 1
    }).ok).toBe(true);
    expect(validateDraftEnvelope({
      ...valid,
      tree_id: null,
      create_idempotency_key: createKey,
      migration_id: migrationId,
      migration_fingerprint: "ab".repeat(32),
      migration_source_create_idempotency_key: createKey,
      migration_hash_algorithm: "sha-256",
      migration_hash_version: 1
    }).ok).toBe(false);
  });

  it("covers fallback readers sharing an owner and cleanup contention", async () => {
    const fallback = createCrtDraftStore({ storage: null, lock_manager: null, writer_session_id: writerSessionId });
    const otherTree = { ...scope, tree_id: "fallback-reader-b" };
    let releaseA!: () => void;
    let releaseB!: () => void;
    let secondStarted!: () => void;
    const secondReady = new Promise<void>((resolve) => { secondStarted = resolve; });
    const first = fallback.withWriter(scope, () => new Promise<void>((resolve) => { releaseA = resolve; }));
    await Promise.resolve();
    const second = fallback.withWriter(otherTree, () => new Promise<void>((resolve) => { secondStarted(); releaseB = resolve; }));
    await secondReady;
    expect(releaseA).toBeTypeOf("function");
    expect(releaseB).toBeTypeOf("function");
    releaseA();
    await first;
    releaseB();
    await second;
    await mutate(fallback, scope, () => fallback.write(scope, draft));
    expect(await fallback.cleanupOwnerTransition(scope)).toMatchObject({ ok: true, value: 1 });
    expect(await fallback.cleanupOwnerTransition(scope)).toMatchObject({ ok: true, value: 0 });
  });

  it("covers source-backed migration listing with a surviving source copy", async () => {
    class RetainDraftRemoval extends MemoryStorage {
      override removeItem(key: string): void {
        if (!key.includes(".probe.")) return;
        super.removeItem(key);
      }
    }
    const storage = new RetainDraftRemoval();
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const canonical = { ...scope, tree_id: "tree-surviving-source" };
    const crypto = { subtle: { digest: async () => new Uint8Array(32).fill(0xab).buffer } };
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager, crypto });
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    await store.rekeyPreCanonical(source, canonical.tree_id, migrationId);
    const listed = await store.list(scope);
    expect(listed).toMatchObject({ ok: true, value: [expect.objectContaining({ value: expect.objectContaining({ tree_id: canonical.tree_id }) })] });
    expect(listed.ok && listed.value).toHaveLength(1);
  });

  it("covers empty durable reads that transition to online-only without a memory copy", () => {
    class EmptyReadFailure extends MemoryStorage {
      override getItem(key: string): string | null {
        if (!key.includes(".probe.")) throw new Error("read unavailable");
        return super.getItem(key);
      }
    }
    const store = createCrtDraftStore({ storage: new EmptyReadFailure(), lock_manager: lockManager });
    expect(store.read(scope)).toEqual({ ok: true, found: false, mode: "online-only" });
    expect(store.mode).toBe("online-only");
  });

  it("covers malformed encoded physical keys through public reads", async () => {
    for (const encoded of ["!", "A", "A.B"]) {
      vi.stubGlobal("btoa", () => encoded);
      try {
        const store = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
        await mutate(store, scope, () => store.write(scope, draft));
        expect(store.read(scope)).toMatchObject({ ok: false, reason: "invalid-draft" });
      } finally {
        vi.unstubAllGlobals();
      }
    }
  });

  it("covers a missing fallback read and the null-origin URL result", () => {
    const fallback = createCrtDraftStore({ storage: null, lock_manager: null, writer_session_id: writerSessionId });
    expect(fallback.read(scope)).toEqual({ ok: true, found: false, mode: "online-only" });
    class NullOriginUrl {
      public readonly protocol = "http:";
      public readonly origin = "null";
      public constructor(values: string) { void values; }
    }
    vi.stubGlobal("URL", NullOriginUrl);
    try {
      expect(normalizeOrigin("https://opaque.example.test")).toBe("");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("covers source-backed migration reconciliation after a physical source race", async () => {
    class SourceRaceStorage extends MemoryStorage {
      public dropOnRead = false;
      private reads = 0;
      override getItem(key: string): string | null {
        const value = super.getItem(key);
        if (this.dropOnRead && key === draftStorageKey({ ...scope, tree_id: null, create_idempotency_key: createKey }) && value !== null && ++this.reads === 2) {
          super.removeItem(key);
        }
        return value;
      }
    }
    const storage = new SourceRaceStorage();
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager, crypto: { subtle: { digest: async () => new Uint8Array(32).buffer } } });
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    expect(await store.rekeyPreCanonical(source, "tree-race-reconcile", migrationId)).toMatchObject({ ok: true });
    storage.dropOnRead = true;
    expect(await store.rekeyPreCanonical(source, "tree-race-reconcile", migrationId)).toMatchObject({ ok: true });
  });

  it("covers defensive storage and fallback state alternatives", async () => {
    type Internals = {
      flushDeletionTombstones(): boolean;
      markStorageFailed(): void;
      invalidatePhysicalKey(key: string): void;
      fallbackOwnerExclusive: Set<string>;
      fallbackOwnerReaders: Map<string, number>;
      fallbackReleaseShared(ownerKey: string): void;
      memory: Map<string, string>;
      memoryOnlyKeys: Set<string>;
      storageState: "absent" | "available" | "failed";
      readRaw(key: string): { raw: string | null; mode: string };
      writeRaw(key: string, serialized: string): { ok: boolean };
      parseRaw(raw: string): { ok: boolean };
    };
    const fallback = createCrtDraftStore({ storage: null, lock_manager: null, writer_session_id: writerSessionId });
    const fallbackState = fallback as unknown as Internals;
    expect(fallbackState.flushDeletionTombstones()).toBe(true);
    fallbackState.markStorageFailed();
    fallbackState.invalidatePhysicalKey("unused");
    const ownerKey = draftStorageKey(scope).split(".").slice(0, -1).join(".") + ".";
    fallbackState.fallbackOwnerReaders.set(ownerKey, 2);
    fallbackState.fallbackReleaseShared(ownerKey);
    fallbackState.fallbackReleaseShared("missing-owner");
    expect(await fallback.withWriter(scope, () => "blocked")).toMatchObject({ ok: true });
    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    await mutate(fallback, source, () => fallback.write(source, { ...draft, create_idempotency_key: createKey }));
    fallbackState.memoryOnlyKeys.add(draftStorageKey({ ...scope, tree_id: "phantom" }));
    expect(await fallback.list(scope)).toMatchObject({ ok: false, reason: "storage-unavailable" });
    fallbackState.fallbackOwnerExclusive.add(ownerKey);
    expect(await fallback.withWriter({ ...scope, tree_id: "blocked" }, () => "blocked")).toMatchObject({ ok: false, reason: "writer-denied" });
    expect(await fallback.rekeyPreCanonical(source, "blocked-canonical", migrationId)).toMatchObject({ ok: false, reason: "rekey-conflict" });
    fallbackState.fallbackOwnerExclusive.delete(ownerKey);
    class StickyMap extends Map<string, string> {
      override delete(key: string): boolean { void key; return false; }
    }
    const stickyKey = draftStorageKey({ ...scope, tree_id: "sticky-cleanup" });
    fallbackState.memory = new StickyMap([[stickyKey, "raw"]]);
    fallbackState.memoryOnlyKeys.clear();
    expect(await fallback.cleanupOwnerTransition(scope)).toMatchObject({ ok: false, reason: "cleanup-failed" });
    expect(fallbackState.writeRaw("", "{}")).toMatchObject({ ok: false, reason: "invalid-draft" });
    const durable = createCrtDraftStore({ storage: new MemoryStorage(), writer_session_id: writerSessionId, lock_manager: lockManager });
    const written = await mutate(durable, scope, () => durable.write(scope, draft));
    expect(written.ok).toBe(true);
    if (!written.ok) return;
    const durableState = durable as unknown as Internals;
    expect(durableState.parseRaw(JSON.stringify(written.value))).toMatchObject({ ok: true });
    const key = draftStorageKey(scope);
    durableState.memory.delete(key);
    durableState.memoryOnlyKeys.add(key);
    durableState.storageState = "failed";
    expect(durableState.readRaw(key)).toMatchObject({ raw: null, mode: "online-only" });
    class ReadFailure extends MemoryStorage {
      override getItem(readKey: string): string | null {
        if (!readKey.includes(".probe.")) throw new Error("read failure");
        return super.getItem(readKey);
      }
    }
    const readFailureStore = createCrtDraftStore({ storage: new ReadFailure(), lock_manager: lockManager });
    const readFailureState = readFailureStore as unknown as Internals;
    readFailureState.memoryOnlyKeys.add(key);
    expect(readFailureState.readRaw(key)).toMatchObject({ raw: null, mode: "online-only" });
    const malformedSource = { ...scope, tree_id: null, create_idempotency_key: createKey };
    let originReads = 0;
    const changingScope = {
      owner_id: malformedSource.owner_id,
      get origin(): string { originReads += 1; return originReads === 1 ? malformedSource.origin : "ftp://invalid.example.test"; },
      tree_id: null,
      create_idempotency_key: createKey
    };
    expect(await durable.rekeyPreCanonical(changingScope, "dynamic-canonical", migrationId)).toMatchObject({ ok: false, reason: "invalid-draft" });
    durableState.memoryOnlyKeys.delete(key);
    durableState.storageState = "failed";
    durableState.readRaw = () => ({ raw: JSON.stringify(written.value), mode: "online-only" });
    expect(await mutate(durable, scope, () => durable.delete(scope))).toMatchObject({ ok: false, reason: "storage-unavailable" });
  });
  it("covers a decoded create marker that is not UUID-shaped", async () => {
    const originalBtoa = globalThis.btoa;
    vi.stubGlobal("btoa", (value: string) => value === "tree:tree-x" ? originalBtoa("create:bad!") : originalBtoa(value));
    try {
      const storage = new MemoryStorage();
      const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
      const treeScope = { ...scope, tree_id: "tree-x" };
      await mutate(store, treeScope, () => store.write(treeScope, draft));
      expect(store.read(treeScope)).toMatchObject({ ok: false, reason: "invalid-draft" });
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it("covers key-collision read, export, and list scope mismatches", async () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(store, scope, () => store.write(scope, draft));
    const key = draftStorageKey(scope);
    const originalBtoa = globalThis.btoa;
    const raw = storage.getItem(key);
    expect(raw).not.toBeNull();
    if (!raw) return;
    const ownerMismatch = JSON.parse(raw) as Record<string, unknown>;
    ownerMismatch.owner_id = "owner-b";
    storage.setItem(key, JSON.stringify(ownerMismatch));
    vi.stubGlobal("btoa", (value: string) => value === "owner-b" ? originalBtoa("owner-a") : originalBtoa(value));
    try {
      expect(store.read(scope)).toEqual({ ok: true, found: false, mode: "durable" });
      expect(store.exportBackup(scope)).toMatchObject({ ok: false, reason: "not-found" });
      expect(await store.list(scope)).toMatchObject({ ok: false, reason: "invalid-draft" });
    } finally {
      vi.unstubAllGlobals();
    }

    const source = { ...scope, tree_id: null, create_idempotency_key: createKey };
    const otherCreateKey = "00000000-0000-4000-8000-000000000004";
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));
    const sourceKey = draftStorageKey(source);
    const sourceRaw = storage.getItem(sourceKey);
    expect(sourceRaw).not.toBeNull();
    if (!sourceRaw) return;
    const createMismatch = JSON.parse(sourceRaw) as Record<string, unknown>;
    createMismatch.create_idempotency_key = otherCreateKey;
    storage.setItem(sourceKey, JSON.stringify(createMismatch));
    vi.stubGlobal("btoa", (value: string) => {
      if (value === `create:${otherCreateKey}`) return originalBtoa(`create:${createKey}`);
      return originalBtoa(value);
    });
    try {
      expect(store.read(source)).toEqual({ ok: true, found: false, mode: "durable" });
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it("covers physical deletion and memory-only tombstone alternatives", async () => {
    const storage = new MemoryStorage();
    const durable = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    await mutate(durable, scope, () => durable.write(scope, draft));
    expect(await mutate(durable, scope, () => durable.delete(scope))).toMatchObject({ ok: true, mode: "durable" });
    const fallback = createCrtDraftStore({ storage: null, writer_session_id: writerSessionId, lock_manager: null });
    await mutate(fallback, scope, () => fallback.write(scope, draft));
    expect(await mutate(fallback, scope, () => fallback.delete(scope))).toMatchObject({ ok: true, mode: "online-only" });
  });

  it("covers invalid canonical list metadata without a source entry", async () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    const canonical = { ...scope, tree_id: "tree-marker-only" };
    await mutate(store, canonical, () => store.write(canonical, {
      ...draft,
      tree: { ...draft.tree, name: "marker-only" },
      migration_id: migrationId,
      migration_fingerprint: "ab".repeat(32),
      migration_source_create_idempotency_key: createKey,
      migration_hash_algorithm: "sha-256",
      migration_hash_version: 1
    }));
    const listed = await store.list(scope);
    expect(listed).toMatchObject({ ok: true, value: [expect.objectContaining({ value: expect.objectContaining({ tree_id: canonical.tree_id }) })] });
  });

  it("handles a pre-canonical scope whose optional create key disappears during read", async () => {
    const storage = new MemoryStorage();
    const store = createCrtDraftStore({ storage, writer_session_id: writerSessionId, lock_manager: lockManager });
    const source: DraftScope = { ...scope, tree_id: null, create_idempotency_key: createKey };
    await mutate(store, source, () => store.write(source, { ...draft, create_idempotency_key: createKey }));

    let createKeyReads = 0;
    const changingScope: DraftScope = {
      owner_id: source.owner_id,
      origin: source.origin,
      tree_id: null,
      get create_idempotency_key(): string | null | undefined {
        createKeyReads += 1;
        return createKeyReads === 1 ? createKey : undefined;
      }
    };
    expect(store.read(changingScope)).toMatchObject({ ok: true, found: false, mode: "durable" });
  });
});