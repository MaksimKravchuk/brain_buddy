/**
 * 006-SC-007 — the storage key is the SOLE enforcement of identity isolation.
 *
 * data-model.md deliberately rejects a filter: "an entry belonging to another
 * account or server is not hidden from a query — it is in a different key that
 * is never read while this identity is active". That makes the key's
 * injectivity a security property, not a naming convention. If two distinct
 * (serverUrl, accountId) pairings can render to one key string, one account
 * reads another's queue with no bug anywhere else in the feature.
 *
 * `serverUrl` is user-typed and always contains dots, so the separator is the
 * whole risk. These tests exist to make a naive `${enc(a)}.${enc(b)}` fail.
 */

import {
  CACHE_KEY_PREFIX,
  CLASSIFICATION_KEY_PREFIXES,
  QUEUE_KEY_PREFIX,
  cacheKey,
  identitySuffixOf,
  isClassificationKey,
  keysForIdentity,
  parseClassificationKey,
  queueKey,
} from "../storageKeys";

/**
 * Adversarial components. Every one of these is reachable: `serverUrl` is typed
 * by hand in Settings, and `accountId` is an opaque server string.
 */
const COMPONENTS = [
  "a",
  "b",
  "c",
  "a.b",
  "b.c",
  "a.b.c",
  "https://x.test/api",
  "https://x.test/api.b",
  "http://192.168.1.10:8000/api",
  "1.2",
  "1%2E2",
  "a%2Eb",
  "%",
  "..",
  "a b",
  "%2E",
  "acc-1",
];

describe("006-SC-007 classification storage key derivation", () => {
  it("006-SC-007 renders the documented shape with each component escaped separately", () => {
    expect(queueKey("https://x.test/api", "acc-1")).toBe(
      "bb.pendingClassification.https%3A%2F%2Fx%2Etest%2Fapi.acc-1",
    );
    expect(cacheKey("https://x.test/api", "acc-1")).toBe(
      "bb.classificationCache.https%3A%2F%2Fx%2Etest%2Fapi.acc-1",
    );
  });

  it("006-SC-007 never lets the separator be smuggled in from either side", () => {
    // The counterexample that plain encodeURIComponent loses: it leaves `.`
    // unescaped, so ("a.b", "c") and ("a", "b.c") both render `...a.b.c`.
    expect(queueKey("a.b", "c")).not.toBe(queueKey("a", "b.c"));
    expect(cacheKey("a.b", "c")).not.toBe(cacheKey("a", "b.c"));
    // The realistic form of the same collision: a server URL always contains
    // dots, so the boundary between the two components is not self-evident.
    expect(queueKey("https://x.test/api", "b.c")).not.toBe(
      queueKey("https://x.test/api.b", "c"),
    );
  });

  it("006-SC-007 maps every distinct (serverUrl, accountId) pairing to a distinct key", () => {
    const pairs: [string, string][] = [];
    for (const serverUrl of COMPONENTS) {
      for (const accountId of COMPONENTS) {
        pairs.push([serverUrl, accountId]);
      }
    }

    const keys = pairs.flatMap(([serverUrl, accountId]) => [
      queueKey(serverUrl, accountId),
      cacheKey(serverUrl, accountId),
    ]);

    // One key per (store, serverUrl, accountId). A collision here is a
    // cross-account read, which is exactly what SC-007 forbids.
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("006-SC-007 round-trips both halves of the identity back out of the key", () => {
    for (const serverUrl of COMPONENTS) {
      for (const accountId of COMPONENTS) {
        expect(parseClassificationKey(queueKey(serverUrl, accountId))).toEqual({
          store: "queue",
          serverUrl,
          accountId,
        });
        expect(parseClassificationKey(cacheKey(serverUrl, accountId))).toEqual({
          store: "cache",
          serverUrl,
          accountId,
        });
      }
    }
  });

  it("006-SC-007 keeps the queue and the cache of one identity in different keys", () => {
    expect(queueKey("s", "a")).not.toBe(cacheKey("s", "a"));
    expect(keysForIdentity("s", "a")).toEqual([queueKey("s", "a"), cacheKey("s", "a")]);
  });

  it("006-SC-007 refuses to build a key from a half-known identity", () => {
    // An empty accountId would put every account in ONE shared key — the
    // precise disclosure the keyed design exists to prevent. Failing loudly
    // beats a key that silently pools two identities.
    expect(() => queueKey("https://x.test/api", "")).toThrow(/accountId/);
    expect(() => cacheKey("https://x.test/api", "  ")).toThrow(/accountId/);
    expect(() => queueKey("", "acc-1")).toThrow(/serverUrl/);
  });
});

describe("006-FR-018 key enumeration for the cross-identity sweep", () => {
  it("006-FR-018 exports both prefixes so getAllKeys can be filtered on them", () => {
    expect(QUEUE_KEY_PREFIX).toBe("bb.pendingClassification.");
    expect(CACHE_KEY_PREFIX).toBe("bb.classificationCache.");
    expect([...CLASSIFICATION_KEY_PREFIXES]).toEqual([QUEUE_KEY_PREFIX, CACHE_KEY_PREFIX]);
  });

  it("006-FR-018 recognises only its own keys", () => {
    expect(isClassificationKey(queueKey("s", "a"))).toBe(true);
    expect(isClassificationKey(cacheKey("s", "a"))).toBe(true);
    expect(isClassificationKey("bb.serverUrl")).toBe(false);
    expect(isClassificationKey("bb.accountId")).toBe(false);
    expect(isClassificationKey("bb.pendingClassificationOther")).toBe(false);
  });

  it("006-FR-018 gives the queue and the cache of one identity the same suffix", () => {
    // The sweep protects an identity by suffix, so passing either of its two
    // keys as the active one protects both.
    expect(identitySuffixOf(queueKey("https://x.test/api", "acc-1"))).toBe(
      identitySuffixOf(cacheKey("https://x.test/api", "acc-1")),
    );
    expect(identitySuffixOf(queueKey("s", "a"))).not.toBe(identitySuffixOf(queueKey("s", "b")));
    expect(identitySuffixOf("bb.serverUrl")).toBeNull();
  });

  it("006-SC-007 rejects a malformed key rather than guessing an identity", () => {
    expect(parseClassificationKey("bb.pendingClassification.only-one-part")).toBeNull();
    expect(parseClassificationKey("bb.pendingClassification.a.b.c")).toBeNull();
    expect(parseClassificationKey("bb.pendingClassification.%zz.a")).toBeNull();
    expect(parseClassificationKey("bb.serverUrl")).toBeNull();
  });
});
