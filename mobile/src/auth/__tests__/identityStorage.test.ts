/**
 * 006-FR-009 / 006-FR-011 / 006-FR-020 — what the device remembers about who
 * is signed in, so that a cold start with no connection can name its own
 * storage key and read its own rollout flag.
 *
 * `/auth/me` is the only live source of the account id, and it is exactly the
 * call that fails offline.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

import type { MeResponse } from "../../api/types";
import type { PendingClassificationChange } from "../../features/tasks/classificationTypes";
import {
  clearIdentityStores,
  saveQueue,
} from "../../features/tasks/classificationQueue.storage";
import { cacheKey, queueKey } from "../../features/tasks/storageKeys";
import { TASK_CLASSIFICATION_FLAG, flagStorageKey, identityStorageKey } from "../flagResolution";
import {
  clearPersistedIdentity,
  loadPersistedFlags,
  loadPersistedIdentity,
  markSessionRejected,
  persistIdentity,
} from "../identityStorage";

// AsyncStorage's native module is null under Jest. An in-memory stand-in keeps
// this a test of the adapter's own rules — what is written, what is deleted —
// rather than of the native bridge. `jest.mock` is hoisted above the imports.
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
      multiGet: jest.fn(async (keys: string[]) =>
        keys.map((key) => [key, store.get(key) ?? null] as [string, string | null]),
      ),
      multiSet: jest.fn(async (pairs: [string, string][]) => {
        for (const [key, value] of pairs) {
          store.set(key, value);
        }
      }),
      multiRemove: jest.fn(async (keys: string[]) => {
        for (const key of keys) {
          store.delete(key);
        }
      }),
      getAllKeys: jest.fn(async () => [...store.keys()]),
      clear: jest.fn(async () => {
        store.clear();
      }),
    },
  };
});

const SERVER = "https://x.test/api";

function profile(id: string, flags: Record<string, boolean> = {}): MeResponse {
  return { id, email: `${id}@example.test`, feature_flags: flags };
}

/** A queue entry `saveQueue` will accept — it drops anything whose identity
 *  does not match the key it is being written under (invariant 4). */
function queueEntry(
  over: Pick<PendingClassificationChange, "taskId" | "accountId" | "serverUrl">,
): PendingClassificationChange {
  const at = new Date().toISOString();
  return {
    ...over,
    value: { projectId: "p1", tagIds: undefined },
    observedRevision: 1,
    originalValue: { projectId: null, tagIds: [] },
    firstQueuedAt: at,
    lastEditedAt: at,
    idempotencyKey: `key-${over.taskId}`,
    sendState: "queued",
  };
}

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe("persisted identity", () => {
  it("006-FR-009 reads back the account id with no live profile", async () => {
    await persistIdentity(SERVER, profile("acct-1"));

    const identity = await loadPersistedIdentity(SERVER);
    expect(identity?.accountId).toBe("acct-1");
  });

  it("006-FR-011 stores the opaque id and never the email", async () => {
    await persistIdentity(SERVER, profile("acct-1"));

    const raw = JSON.stringify(
      await AsyncStorage.multiGet(await AsyncStorage.getAllKeys()),
    );
    expect(raw).toContain("acct-1");
    expect(raw).not.toContain("@example.test");
  });

  it("006-SC-007 keeps one server's identity invisible to another", async () => {
    await persistIdentity(SERVER, profile("acct-1"));

    expect(await loadPersistedIdentity("https://other.test/api")).toBeNull();
  });

  it("006-FR-011 clears the identity and its flags on a deliberate transition", async () => {
    await persistIdentity(SERVER, profile("acct-1", { [TASK_CLASSIFICATION_FLAG]: true }));

    await clearPersistedIdentity(SERVER);

    expect(await loadPersistedIdentity(SERVER)).toBeNull();
    expect(await loadPersistedFlags(SERVER, "acct-1")).toBeNull();
    expect(await AsyncStorage.getAllKeys()).toEqual([]);
  });

  it("006-FR-011 deletes the previous identity's stored keys when a different account signs in", async () => {
    await persistIdentity(SERVER, profile("acct-1", { [TASK_CLASSIFICATION_FLAG]: true }));
    // All three of the previous account's stores, not just the one this test
    // used to check. The assertion below said "the key itself is gone" while
    // naming only the flag record, and the queue and the picker cache were in
    // fact left behind — which is how they came to be left behind.
    await AsyncStorage.setItem(queueKey(SERVER, "acct-1"), JSON.stringify([{ taskId: "t1" }]));
    await AsyncStorage.setItem(
      cacheKey(SERVER, "acct-1"),
      JSON.stringify({ projects: [{ id: "p1", name: "Wedding" }], tags: [], fetchedAt: "x" }),
    );

    await persistIdentity(SERVER, profile("acct-2", { [TASK_CLASSIFICATION_FLAG]: false }));

    // Not merely unread: the keys themselves are gone. Nothing ever reads a key
    // it will never open again, so deletion needs its own mechanism — and it
    // may not be delegated to the classification hook's cross-identity sweep,
    // which runs only when the *new* account has the rollout flag on. This
    // profile has it off, which is exactly the case that used to leak.
    const remaining = await AsyncStorage.getAllKeys();
    expect(remaining).not.toContain(flagStorageKey(SERVER, "acct-1"));
    expect(remaining).not.toContain(queueKey(SERVER, "acct-1"));
    expect(remaining).not.toContain(cacheKey(SERVER, "acct-1"));
    // The names the person wrote are the point: a project called "Wedding" is
    // not something to leave on a device for the next account.
    expect(JSON.stringify(await AsyncStorage.multiGet(remaining))).not.toContain("Wedding");
    expect(await loadPersistedFlags(SERVER, "acct-1")).toBeNull();
    expect((await loadPersistedIdentity(SERVER))?.accountId).toBe("acct-2");
  });

  it("006-FR-011 leaves the incoming account's own stores alone", async () => {
    // The other half of the same rule, and the reason it cannot simply clear
    // everything: acct-2 signing in after acct-1 must keep whatever acct-2 left
    // behind the last time it was here. Deleting one account's work is FR-011;
    // deleting the arriving account's work is a bug wearing FR-011's clothes.
    await persistIdentity(SERVER, profile("acct-1"));
    await AsyncStorage.setItem(queueKey(SERVER, "acct-2"), JSON.stringify([{ taskId: "t9" }]));

    await persistIdentity(SERVER, profile("acct-2"));

    expect(await AsyncStorage.getItem(queueKey(SERVER, "acct-2"))).toContain("t9");
  });

  it("006-FR-011 lets a re-signed-in identity write again after being forgotten", async () => {
    // `clearIdentityStores` tombstones the identity so writes still in flight
    // cannot resurrect it. Signing back in must lift that, or the account's
    // queue would be silently unwritable for the rest of the process.
    await persistIdentity(SERVER, profile("acct-1"));
    await clearIdentityStores({ serverUrl: SERVER, accountId: "acct-1" });

    await persistIdentity(SERVER, profile("acct-1"));
    await saveQueue({ serverUrl: SERVER, accountId: "acct-1" }, [
      queueEntry({ taskId: "t1", accountId: "acct-1", serverUrl: SERVER }),
    ]);

    expect(await AsyncStorage.getItem(queueKey(SERVER, "acct-1"))).toContain("t1");
  });

  it("006-FR-019 marks a rejected session without forgetting who it belonged to", async () => {
    await persistIdentity(SERVER, profile("acct-1"));

    const marked = await markSessionRejected(SERVER);

    // FR-011: an involuntary end keeps the work, so the identity that owns the
    // queue must survive it — but the device now knows the session is over.
    expect(marked?.accountId).toBe("acct-1");
    expect(marked?.sessionRejectedAt).toEqual(expect.any(String));
    expect((await loadPersistedIdentity(SERVER))?.sessionRejectedAt).toEqual(expect.any(String));
  });

  it("006-FR-019 clears the rejection marker when the same account signs in again", async () => {
    await persistIdentity(SERVER, profile("acct-1"));
    await markSessionRejected(SERVER);

    await persistIdentity(SERVER, profile("acct-1"));

    expect((await loadPersistedIdentity(SERVER))?.sessionRejectedAt).toBeUndefined();
  });

  it("006-FR-019 marking a session rejected with nothing persisted is a no-op", async () => {
    expect(await markSessionRejected(SERVER)).toBeNull();
    expect(await AsyncStorage.getAllKeys()).toEqual([]);
  });

  it("006-FR-011 clearing a server that holds nothing is a no-op, not a throw", async () => {
    await expect(clearPersistedIdentity(SERVER)).resolves.toBeUndefined();
    expect(await AsyncStorage.getAllKeys()).toEqual([]);
  });

  it.each([
    ["not json at all", "{not json"],
    ["a record with no account id", JSON.stringify({ savedAt: "2026-08-11T09:00:00.000Z" })],
    ["a record whose account id is not a string", JSON.stringify({ accountId: 7 })],
    ["a record whose account id is empty", JSON.stringify({ accountId: "" })],
    ["a JSON scalar", JSON.stringify("acct-1")],
  ])("006-FR-009 reads %s as no identity, rather than a broken one", async (_label, stored) => {
    // A broken identity would derive a storage key that belongs to nobody, so
    // the safe direction is to have none: the person signs in again.
    await AsyncStorage.setItem(identityStorageKey(SERVER), stored);

    expect(await loadPersistedIdentity(SERVER)).toBeNull();
  });
});

describe("persisted rollout flags", () => {
  it("006-FR-020 reads the last known flags back for the same identity", async () => {
    await persistIdentity(SERVER, profile("acct-1", { [TASK_CLASSIFICATION_FLAG]: true }));

    expect(await loadPersistedFlags(SERVER, "acct-1")).toEqual({
      [TASK_CLASSIFICATION_FLAG]: true,
    });
  });

  it("006-FR-020 returns null for an identity the answer was never known for", async () => {
    await persistIdentity(SERVER, profile("acct-1", { [TASK_CLASSIFICATION_FLAG]: true }));

    // Fail closed means closed when never known for *this* identity — the
    // other account's true does not leak across.
    expect(await loadPersistedFlags(SERVER, "acct-2")).toBeNull();
    expect(await loadPersistedFlags("https://other.test/api", "acct-1")).toBeNull();
  });

  it("006-FR-020 survives a corrupted record rather than crashing the launch", async () => {
    await AsyncStorage.setItem(flagStorageKey(SERVER, "acct-1"), "{not json");

    expect(await loadPersistedFlags(SERVER, "acct-1")).toBeNull();
  });

  it.each([
    ["a record with no flags object", JSON.stringify({ savedAt: "2026-08-11T09:00:00.000Z" })],
    ["a record whose flags are not an object", JSON.stringify({ flags: "on" })],
  ])("006-FR-015 reads %s as never known", async (_label, stored) => {
    await AsyncStorage.setItem(flagStorageKey(SERVER, "acct-1"), stored);

    expect(await loadPersistedFlags(SERVER, "acct-1")).toBeNull();
  });

  it("006-FR-015 drops a non-boolean flag value on write, so a malformed payload cannot turn one on", async () => {
    const malformed = {
      id: "acct-1",
      email: "acct-1@example.test",
      feature_flags: { [TASK_CLASSIFICATION_FLAG]: "true" },
    } as unknown as MeResponse;

    await persistIdentity(SERVER, malformed);

    expect(await loadPersistedFlags(SERVER, "acct-1")).toEqual({});
  });
});
