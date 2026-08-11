/**
 * Storage keys for the two device-local classification stores.
 *
 * Identity lives in the key rather than in a filter (data-model.md, "Storage
 * key"): an entry belonging to another account or server is not hidden from a
 * query, it is in a different key that is never read while this identity is
 * active. That makes FR-011 and SC-007 properties of the structure instead of
 * rules someone has to remember to apply — and it makes the key's injectivity
 * a security property rather than a naming convention.
 *
 * `encodeURIComponent` alone is NOT injective under a `.` separator: it leaves
 * `.` unescaped, so ("a.b", "c") and ("a", "b.c") both render
 * `bb.pendingClassification.a.b.c`. `serverUrl` is typed by hand in Settings
 * and always contains dots, so that collision is reachable, and reaching it
 * means one account reading another's queue with no bug anywhere else in the
 * feature. The separator is therefore escaped inside each component too, which
 * leaves exactly two literal `.` boundaries in a well-formed key.
 */

/** Both prefixes are exported so `AsyncStorage.getAllKeys()` can be filtered
 *  on them by the cross-identity sweep (data-model.md invariant 8b). */
export const QUEUE_KEY_PREFIX = "bb.pendingClassification.";
export const CACHE_KEY_PREFIX = "bb.classificationCache.";
export const CLASSIFICATION_KEY_PREFIXES = [QUEUE_KEY_PREFIX, CACHE_KEY_PREFIX] as const;

export type ClassificationStore = "queue" | "cache";

export interface ClassificationIdentity {
  /** The persisted API base URL (`bb.serverUrl`). */
  serverUrl: string;
  /** The opaque account id persisted from every path that establishes a
   *  session. Never the email. */
  accountId: string;
}

const SEPARATOR = ".";

/**
 * `encodeURIComponent` plus the separator, which it does not escape.
 * Percent-encoding `.` keeps the result decodable by `decodeURIComponent`.
 */
function encodeComponent(raw: string): string {
  return encodeURIComponent(raw).replace(/\./g, "%2E");
}

function requireComponent(name: "serverUrl" | "accountId", value: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    // An empty half would put every account in ONE shared key — the precise
    // disclosure the keyed design exists to prevent. Both halves are readable
    // offline by construction, so an empty one is a caller bug, not a state.
    throw new Error(
      `classification storage key requires a non-empty ${name} (SC-007: a shared key is a cross-account read)`,
    );
  }
  return value;
}

/** The identity half of both keys. The queue and the cache of one identity
 *  share it, so protecting a suffix protects both stores. */
export function identitySuffix(serverUrl: string, accountId: string): string {
  return [
    encodeComponent(requireComponent("serverUrl", serverUrl)),
    encodeComponent(requireComponent("accountId", accountId)),
  ].join(SEPARATOR);
}

export function queueKey(serverUrl: string, accountId: string): string {
  return QUEUE_KEY_PREFIX + identitySuffix(serverUrl, accountId);
}

export function cacheKey(serverUrl: string, accountId: string): string {
  return CACHE_KEY_PREFIX + identitySuffix(serverUrl, accountId);
}

/** Both keys of one identity, in the order [queue, cache]. FR-011 clears them
 *  together — the cache goes even when the queue is empty. */
export function keysForIdentity(serverUrl: string, accountId: string): [string, string] {
  return [queueKey(serverUrl, accountId), cacheKey(serverUrl, accountId)];
}

export function storeOf(key: string): ClassificationStore | null {
  if (key.startsWith(QUEUE_KEY_PREFIX)) {
    return "queue";
  }
  if (key.startsWith(CACHE_KEY_PREFIX)) {
    return "cache";
  }
  return null;
}

export function isClassificationKey(key: string): boolean {
  return storeOf(key) !== null;
}

/** The identity half of a stored key, or `null` when the key is not ours.
 *  Comparing suffixes — not whole keys — is what lets the sweep be handed
 *  either of the active identity's two keys and still protect both. */
export function identitySuffixOf(key: string): string | null {
  const store = storeOf(key);
  if (store === null) {
    return null;
  }
  return key.slice(store === "queue" ? QUEUE_KEY_PREFIX.length : CACHE_KEY_PREFIX.length);
}

/**
 * The inverse of {@link queueKey} / {@link cacheKey}. Its existence is the
 * constructive proof that the derivation is injective: a key that decodes back
 * to exactly one (serverUrl, accountId) pairing cannot be shared by two.
 *
 * Returns `null` for anything malformed rather than guessing an identity — a
 * guessed identity is a cross-account read.
 */
export function parseClassificationKey(
  key: string,
): { store: ClassificationStore; serverUrl: string; accountId: string } | null {
  const store = storeOf(key);
  const suffix = identitySuffixOf(key);
  if (store === null || suffix === null) {
    return null;
  }
  const parts = suffix.split(SEPARATOR);
  if (parts.length !== 2) {
    return null;
  }
  try {
    return {
      store,
      serverUrl: decodeURIComponent(parts[0]),
      accountId: decodeURIComponent(parts[1]),
    };
  } catch {
    // A malformed escape (`%zz`) throws URIError.
    return null;
  }
}
