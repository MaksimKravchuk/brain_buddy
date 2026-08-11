/**
 * 006-FR-011 / 006-FR-018 / 006-SC-007 — the AsyncStorage adapter and the
 * cross-identity sweep.
 *
 * Two properties are under test that nothing else in the feature can provide:
 *
 * 1. Identity-in-the-key closes *disclosure* but cannot *delete*. A key nobody
 *    reads never expires, so without a sweep over `getAllKeys()` account A's
 *    queue and A's project and Tag names stay on the device forever the moment
 *    account B signs in (data-model.md invariant 8b).
 * 2. Defence in depth on read: every entry's own `accountId`/`serverUrl` is
 *    checked against the active identity, so SC-007 does not rest on string
 *    derivation alone.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

import type { CachedClassificationLists, PendingClassificationChange } from "../classificationTypes";
import { RETENTION_MS } from "../classificationTypes";
import {
  clearCacheFor,
  clearIdentityStores,
  clearQueue,
  isBeyondRetention,
  loadQueue,
  loadServerTime,
  saveQueue,
  saveServerTime,
  sweepAllIdentities,
} from "../classificationQueue.storage";
import { cacheKey, queueKey } from "../storageKeys";

jest.mock("@react-native-async-storage/async-storage", () => {
  const store = new Map<string, string>();
  return {
    __esModule: true,
    default: {
      getItem: jest.fn(async (key: string) => store.get(key) ?? null),
      setItem: jest.fn(async (key: string, value: string) => {
        store.set(key, value);
      }),
      removeItem: jest.fn(async (key: string) => {
        store.delete(key);
      }),
      multiRemove: jest.fn(async (keys: readonly string[]) => {
        for (const key of keys) {
          store.delete(key);
        }
      }),
      getAllKeys: jest.fn(async () => Array.from(store.keys())),
      clear: jest.fn(async () => {
        store.clear();
      }),
    },
  };
});

const SERVER_A = "https://x.test/api";
const SERVER_B = "http://192.168.1.10:8000/api";
const ACCOUNT_A = "acc-a";
const ACCOUNT_B = "acc-b";

const IDENTITY_A = { serverUrl: SERVER_A, accountId: ACCOUNT_A };
const IDENTITY_B = { serverUrl: SERVER_B, accountId: ACCOUNT_B };

const NOW = Date.parse("2026-08-11T12:00:00.000Z");

function iso(epochMs: number): string {
  return new Date(epochMs).toISOString();
}

function entry(overrides: Partial<PendingClassificationChange> = {}): PendingClassificationChange {
  return {
    taskId: "task-1",
    accountId: ACCOUNT_A,
    serverUrl: SERVER_A,
    value: { projectId: "proj-1", tagIds: ["tag-1"] },
    observedRevision: 3,
    originalValue: { projectId: null, tagIds: [] },
    firstQueuedAt: iso(NOW - 60_000),
    lastEditedAt: iso(NOW - 60_000),
    idempotencyKey: "idem-1",
    sendState: "queued",
    ...overrides,
  };
}

async function seed(key: string, value: unknown): Promise<void> {
  await AsyncStorage.setItem(key, JSON.stringify(value));
}

async function read(key: string): Promise<unknown> {
  const raw = await AsyncStorage.getItem(key);
  return raw === null ? null : JSON.parse(raw);
}

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe("006-SC-007 defence in depth on every read", () => {
  it("006-SC-007 discards an entry whose own accountId is not the active identity", async () => {
    await seed(queueKey(SERVER_A, ACCOUNT_A), [
      entry({ taskId: "mine" }),
      entry({ taskId: "smuggled", accountId: ACCOUNT_B }),
    ]);

    const loaded = await loadQueue(IDENTITY_A, { now: NOW });

    expect(loaded.map((e) => e.taskId)).toEqual(["mine"]);
  });

  it("006-SC-007 discards an entry whose own serverUrl is not the active identity", async () => {
    await seed(queueKey(SERVER_A, ACCOUNT_A), [
      entry({ taskId: "mine" }),
      entry({ taskId: "other-server", serverUrl: SERVER_B }),
    ]);

    const loaded = await loadQueue(IDENTITY_A, { now: NOW });

    expect(loaded.map((e) => e.taskId)).toEqual(["mine"]);
  });

  it("006-SC-007 does not leave the discarded entry on the device", async () => {
    // Dropping it only from the returned array would keep another identity's
    // content on disk indefinitely: nothing else ever reads this key.
    await seed(queueKey(SERVER_A, ACCOUNT_A), [
      entry({ taskId: "mine" }),
      entry({ taskId: "smuggled", accountId: ACCOUNT_B }),
    ]);

    await loadQueue(IDENTITY_A, { now: NOW });

    expect(await read(queueKey(SERVER_A, ACCOUNT_A))).toHaveLength(1);
  });

  it("006-SC-007 refuses to persist an entry belonging to another identity", async () => {
    await saveQueue(IDENTITY_A, [entry({ taskId: "mine" }), entry({ taskId: "theirs", accountId: ACCOUNT_B })], NOW);

    const stored = (await read(queueKey(SERVER_A, ACCOUNT_A))) as PendingClassificationChange[];
    expect(stored.map((e) => e.taskId)).toEqual(["mine"]);
  });

  it("006-SC-007 survives a corrupt or hand-edited key without reading it as a queue", async () => {
    await AsyncStorage.setItem(queueKey(SERVER_A, ACCOUNT_A), "{not json");
    expect(await loadQueue(IDENTITY_A, { now: NOW })).toEqual([]);

    await seed(queueKey(SERVER_A, ACCOUNT_A), { nope: true });
    expect(await loadQueue(IDENTITY_A, { now: NOW })).toEqual([]);

    await seed(queueKey(SERVER_A, ACCOUNT_A), [entry(), { taskId: 7 }, null]);
    expect(await loadQueue(IDENTITY_A, { now: NOW })).toHaveLength(1);
  });

  it("006-SC-007 reads and writes only its own identity's key", async () => {
    await saveQueue(IDENTITY_A, [entry()], NOW);
    await saveQueue(IDENTITY_B, [entry({ accountId: ACCOUNT_B, serverUrl: SERVER_B })], NOW);

    expect(await loadQueue(IDENTITY_A, { now: NOW })).toHaveLength(1);
    expect(await read(queueKey(SERVER_B, ACCOUNT_B))).toHaveLength(1);

    await clearQueue(IDENTITY_A);

    expect(await read(queueKey(SERVER_A, ACCOUNT_A))).toBeNull();
    expect(await read(queueKey(SERVER_B, ACCOUNT_B))).toHaveLength(1);
  });

  it("006-FR-011 clears the cached project and Tag names even with an empty queue", async () => {
    // M-05 never appears with an empty queue, so a sign-out with nothing
    // pending would otherwise leave one account's whole vocabulary behind.
    await seed(cacheKey(SERVER_A, ACCOUNT_A), {
      projects: [{ id: "p1", name: "Divorce paperwork" }],
      tags: [],
      fetchedAt: iso(NOW),
    } satisfies CachedClassificationLists);

    await clearCacheFor(IDENTITY_A);

    expect(await read(cacheKey(SERVER_A, ACCOUNT_A))).toBeNull();
  });

  it("006-FR-011 clears both stores of one identity together", async () => {
    await saveQueue(IDENTITY_A, [entry()], NOW);
    await seed(cacheKey(SERVER_A, ACCOUNT_A), { projects: [], tags: [], fetchedAt: iso(NOW) });

    await clearIdentityStores(IDENTITY_A);

    expect(await read(queueKey(SERVER_A, ACCOUNT_A))).toBeNull();
    expect(await read(cacheKey(SERVER_A, ACCOUNT_A))).toBeNull();
  });
});

describe("006-FR-021 cold read of an interrupted send", () => {
  it("006-FR-021 applies the injected resetInterrupted before returning", async () => {
    await seed(queueKey(SERVER_A, ACCOUNT_A), [entry({ sendState: "sending" })]);

    const resetInterrupted = jest.fn((entries: PendingClassificationChange[]) =>
      entries.map((e) => (e.sendState === "sending" ? { ...e, sendState: "queued" as const } : e)),
    );

    const loaded = await loadQueue(IDENTITY_A, { now: NOW, resetInterrupted });

    expect(resetInterrupted).toHaveBeenCalledTimes(1);
    expect(loaded[0].sendState).toBe("queued");
    // Persisted, so a second interruption before the next save cannot strand it
    // again: `sending` is never authoritative across a restart (invariant 5c).
    expect((await read(queueKey(SERVER_A, ACCOUNT_A))) as PendingClassificationChange[]).toEqual([
      expect.objectContaining({ sendState: "queued" }),
    ]);
  });

  it("006-FR-021 returns the stored entries unchanged when no reset is injected", async () => {
    await seed(queueKey(SERVER_A, ACCOUNT_A), [entry({ sendState: "sending" })]);

    const loaded = await loadQueue(IDENTITY_A, { now: NOW });

    expect(loaded[0].sendState).toBe("sending");
  });
});

describe("006-FR-018 the retention bound and its clocks", () => {
  it("006-FR-018 clamps a future timestamp at write time", async () => {
    // A clock that was ahead when the entry was written makes
    // `now - lastEditedAt` negative, and the 30-day bound then never fires on
    // exactly the entries whose timestamps are least trustworthy.
    await saveQueue(
      IDENTITY_A,
      [entry({ firstQueuedAt: iso(NOW + RETENTION_MS), lastEditedAt: iso(NOW + RETENTION_MS) })],
      NOW,
    );

    const stored = (await read(queueKey(SERVER_A, ACCOUNT_A))) as PendingClassificationChange[];
    expect(stored[0].lastEditedAt).toBe(iso(NOW));
    expect(stored[0].firstQueuedAt).toBe(iso(NOW));
  });

  it("006-FR-018 holds the boundary at 30 days", () => {
    expect(isBeyondRetention(iso(NOW - RETENTION_MS + 60 * 60 * 1000), NOW)).toBe(false);
    expect(isBeyondRetention(iso(NOW - RETENTION_MS - 60_000), NOW)).toBe(true);
  });

  it("006-FR-018 requires the server clock to agree before anything is destroyed", async () => {
    const aged = iso(NOW - RETENTION_MS - 60_000);

    // Device clock jumped 30 days forward; the last server `Date` seen says
    // otherwise, so the entry is not expired on the device's word alone.
    const serverNow = NOW - RETENTION_MS;
    expect(isBeyondRetention(aged, NOW, serverNow)).toBe(false);
    expect(isBeyondRetention(aged, NOW, NOW)).toBe(true);

    // With no server time ever seen there is nothing better than the device
    // clock — FR-018's bound must still be enforceable.
    expect(isBeyondRetention(aged, NOW, null)).toBe(true);
  });

  it("006-FR-018 persists the last server Date header seen", async () => {
    expect(await loadServerTime()).toBeNull();

    await saveServerTime("Tue, 11 Aug 2026 12:00:00 GMT");
    expect(await loadServerTime()).toBe(Date.parse("Tue, 11 Aug 2026 12:00:00 GMT"));

    // An older or unparseable header never moves the bound backwards: a cached
    // or malformed `Date` must not become a licence to expire a queue.
    await saveServerTime("Mon, 10 Aug 2026 12:00:00 GMT");
    await saveServerTime("not a date");
    await saveServerTime(null);
    expect(await loadServerTime()).toBe(Date.parse("Tue, 11 Aug 2026 12:00:00 GMT"));

    await saveServerTime("Wed, 12 Aug 2026 12:00:00 GMT");
    expect(await loadServerTime()).toBe(Date.parse("Wed, 12 Aug 2026 12:00:00 GMT"));
  });

  it("006-FR-018 keeps the server clock out of the swept prefixes", async () => {
    await saveServerTime("Tue, 11 Aug 2026 12:00:00 GMT");
    const result = await sweepAllIdentities({ activeKey: queueKey(SERVER_A, ACCOUNT_A), now: NOW });

    expect(result.deletedKeys).toEqual([]);
    expect(await loadServerTime()).not.toBeNull();
  });
});

describe("006-FR-018 the cross-identity sweep", () => {
  const activeKey = queueKey(SERVER_A, ACCOUNT_A);

  it("006-FR-011 deletes a foreign key with fresh entries once a different identity has signed in", async () => {
    // Identity-in-the-key made A's queue unreadable under B. Unreadable is not
    // deleted, and read-scoped expiry never runs on a key nobody reads.
    await seed(queueKey(SERVER_B, ACCOUNT_B), [
      entry({ accountId: ACCOUNT_B, serverUrl: SERVER_B, lastEditedAt: iso(NOW) }),
    ]);

    const result = await sweepAllIdentities({ activeKey, now: NOW });

    expect(await read(queueKey(SERVER_B, ACCOUNT_B))).toBeNull();
    expect(result.deletedKeys).toContain(queueKey(SERVER_B, ACCOUNT_B));
  });

  it("006-FR-011 deletes a foreign cache key too, because it holds the names the person wrote", async () => {
    await seed(cacheKey(SERVER_B, ACCOUNT_B), {
      projects: [{ id: "p1", name: "Divorce paperwork" }],
      tags: [{ id: "t1", name: "Oncologist" }],
      fetchedAt: iso(NOW),
    } satisfies CachedClassificationLists);

    await sweepAllIdentities({ activeKey, now: NOW });

    expect(await read(cacheKey(SERVER_B, ACCOUNT_B))).toBeNull();
  });

  it("006-SC-007 never deletes the active identity's own keys", async () => {
    await seed(activeKey, [entry({ lastEditedAt: iso(NOW) })]);
    await seed(cacheKey(SERVER_A, ACCOUNT_A), { projects: [], tags: [], fetchedAt: iso(NOW) });

    const result = await sweepAllIdentities({ activeKey, now: NOW });

    expect(result.deletedKeys).toEqual([]);
    expect(await read(activeKey)).toHaveLength(1);
    expect(await read(cacheKey(SERVER_A, ACCOUNT_A))).not.toBeNull();
  });

  it("006-SC-007 protects the active identity's queue when passed its cache key", async () => {
    await seed(activeKey, [entry({ lastEditedAt: iso(NOW) })]);

    await sweepAllIdentities({ activeKey: cacheKey(SERVER_A, ACCOUNT_A), now: NOW });

    expect(await read(activeKey)).toHaveLength(1);
  });

  it("006-FR-018 age-sweeps a foreign key even when nobody is signed in", async () => {
    // The involuntary-session case: the key is retained (FR-011) but nothing
    // reads it, so the age rule has to reach it from outside.
    const foreign = queueKey(SERVER_B, ACCOUNT_B);
    await seed(foreign, [
      entry({
        taskId: "old",
        accountId: ACCOUNT_B,
        serverUrl: SERVER_B,
        lastEditedAt: iso(NOW - RETENTION_MS - 60_000),
      }),
      entry({
        taskId: "fresh",
        accountId: ACCOUNT_B,
        serverUrl: SERVER_B,
        lastEditedAt: iso(NOW - 60_000),
      }),
    ]);

    const result = await sweepAllIdentities({ activeKey: null, now: NOW });

    const remaining = (await read(foreign)) as PendingClassificationChange[];
    expect(remaining.map((e) => e.taskId)).toEqual(["fresh"]);
    expect(result.foreignEntriesDropped).toBe(1);
    expect(result.deletedKeys).toEqual([]);
  });

  it("006-FR-018 removes a foreign key that the age rule empties", async () => {
    const foreign = queueKey(SERVER_B, ACCOUNT_B);
    await seed(foreign, [
      entry({
        accountId: ACCOUNT_B,
        serverUrl: SERVER_B,
        lastEditedAt: iso(NOW - RETENTION_MS - 60_000),
      }),
    ]);

    const result = await sweepAllIdentities({ activeKey: null, now: NOW });

    expect(await read(foreign)).toBeNull();
    expect(result.deletedKeys).toEqual([foreign]);
  });

  it("006-FR-018 counts the active identity's aged entries without destroying them", async () => {
    // `expired` retains the payload until the person dismisses the notice, so a
    // clock error stays recoverable. The count sources the FR-018 notice.
    await seed(activeKey, [
      entry({ taskId: "old", lastEditedAt: iso(NOW - RETENTION_MS - 60_000) }),
      entry({ taskId: "fresh", lastEditedAt: iso(NOW - 60_000) }),
    ]);

    const result = await sweepAllIdentities({ activeKey, now: NOW });

    expect(result.activeEntriesExpired).toBe(1);
    expect(await read(activeKey)).toHaveLength(2);
  });

  it("006-FR-018 applies the age rule to every stored key, not only the one being read", async () => {
    const foreignOne = queueKey(SERVER_B, ACCOUNT_B);
    const foreignTwo = queueKey(SERVER_A, "acc-c");
    await seed(activeKey, [entry({ lastEditedAt: iso(NOW - RETENTION_MS - 60_000) })]);
    await seed(foreignOne, [
      entry({ accountId: ACCOUNT_B, serverUrl: SERVER_B, lastEditedAt: iso(NOW - RETENTION_MS - 60_000) }),
    ]);
    await seed(foreignTwo, [
      entry({ accountId: "acc-c", lastEditedAt: iso(NOW - RETENTION_MS - 60_000) }),
    ]);
    await seed(cacheKey(SERVER_A, "acc-c"), {
      projects: [],
      tags: [],
      fetchedAt: iso(NOW - RETENTION_MS - 60_000),
    } satisfies CachedClassificationLists);

    // Nobody is signed in, so every key here is one nobody reads — which is
    // precisely the state where read-scoped expiry never runs.
    const result = await sweepAllIdentities({ activeKey: null, now: NOW });

    expect(result.scannedKeys).toBe(4);
    expect(result.deletedKeys.sort()).toEqual(
      [activeKey, cacheKey(SERVER_A, "acc-c"), foreignOne, foreignTwo].sort(),
    );
    expect(result.activeEntriesExpired).toBe(0);
  });

  it("006-FR-018 drops the active identity's stale cache, which loses nothing", async () => {
    await seed(cacheKey(SERVER_A, ACCOUNT_A), {
      projects: [{ id: "p1", name: "Divorce paperwork" }],
      tags: [],
      fetchedAt: iso(NOW - RETENTION_MS - 60_000),
    } satisfies CachedClassificationLists);

    await sweepAllIdentities({ activeKey, now: NOW });

    expect(await read(cacheKey(SERVER_A, ACCOUNT_A))).toBeNull();
  });

  it("006-FR-018 leaves keys that are not ours alone", async () => {
    await AsyncStorage.setItem("bb.serverUrl", SERVER_B);
    await AsyncStorage.setItem("bb.accountId", ACCOUNT_B);

    const result = await sweepAllIdentities({ activeKey, now: NOW });

    expect(result.scannedKeys).toBe(0);
    expect(await AsyncStorage.getItem("bb.serverUrl")).toBe(SERVER_B);
  });

  it("006-FR-018 accepts an injected age rule so the server clock can be cross-checked", async () => {
    const foreign = queueKey(SERVER_B, ACCOUNT_B);
    await seed(foreign, [
      entry({ accountId: ACCOUNT_B, serverUrl: SERVER_B, lastEditedAt: iso(NOW - RETENTION_MS - 60_000) }),
    ]);

    const isExpired = jest.fn(() => false);
    const result = await sweepAllIdentities({ activeKey: null, now: NOW, isExpired });

    expect(isExpired).toHaveBeenCalled();
    expect(result.foreignEntriesDropped).toBe(0);
    expect(await read(foreign)).toHaveLength(1);
  });

  it("006-FR-018 deletes a foreign key it cannot parse rather than leaving it forever", async () => {
    await AsyncStorage.setItem(queueKey(SERVER_B, ACCOUNT_B), "{not json");

    const result = await sweepAllIdentities({ activeKey: null, now: NOW });

    expect(await read(queueKey(SERVER_B, ACCOUNT_B))).toBeNull();
    expect(result.deletedKeys).toEqual([queueKey(SERVER_B, ACCOUNT_B)]);
  });
});
