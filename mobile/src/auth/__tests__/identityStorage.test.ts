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
import { TASK_CLASSIFICATION_FLAG, flagStorageKey } from "../flagResolution";
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

    await persistIdentity(SERVER, profile("acct-2", { [TASK_CLASSIFICATION_FLAG]: false }));

    // Not merely unread: the key itself is gone. Nothing ever reads a key it
    // will never open again, so deletion needs its own mechanism.
    expect(await AsyncStorage.getAllKeys()).not.toContain(flagStorageKey(SERVER, "acct-1"));
    expect(await loadPersistedFlags(SERVER, "acct-1")).toBeNull();
    expect((await loadPersistedIdentity(SERVER))?.accountId).toBe("acct-2");
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
});
