/**
 * AsyncStorage adapter for the two device-local classification stores, plus
 * the cross-identity sweep.
 *
 * Three jobs, none of which belongs in the reducer:
 *
 * 1. **Read and write the active identity's queue** (FR-009), verifying each
 *    entry's own `accountId`/`serverUrl` against the active identity before
 *    returning it. The key already scopes the store; this is defence in depth,
 *    so SC-007 does not rest on string derivation alone.
 * 2. **Sweep every stored key, not only the active one** (invariant 8b).
 *    Identity-in-the-key closes disclosure but cannot delete: a key nobody
 *    reads never expires, so without this, account A's queue and A's project
 *    and Tag names stay on the device forever the moment account B signs in.
 * 3. **Remember the last server `Date` header seen** (FR-018), so the 30-day
 *    bound — the only path in the feature that destroys the person's work
 *    without asking — cannot fire on a device clock that jumped forward alone.
 *
 * No module here reads the clock: `now` is an argument, as the plan requires.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

import type {
  CachedClassificationLists,
  PendingClassificationChange,
  SendState,
} from "./classificationTypes";
import { RETENTION_MS } from "./classificationTypes";
import type { ClassificationIdentity } from "./storageKeys";
import {
  cacheKey,
  forgetIdentityStores,
  identitySuffixOf,
  isClassificationKey,
  isForgottenKey,
  keysForIdentity,
  queueKey,
  storeOf,
} from "./storageKeys";

/** The last server `Date` header seen, as epoch ms. Deliberately outside both
 *  swept prefixes: it is the server's clock, not account content, and the
 *  sweep must not parse it as a store. */
export const SERVER_TIME_KEY = "bb.serverTime";

const SEND_STATES: ReadonlySet<string> = new Set<SendState>([
  "queued",
  "sending",
  "conflicted",
  "expired",
]);

/** Whether a timestamp has passed the retention bound. Injected into the sweep
 *  so the caller can supply the server-cross-checked rule. */
export type RetentionRule = (timestamp: string | undefined, now: number) => boolean;

export interface LoadQueueOptions {
  /** Injected clock, used only if a read has to repair the stored value. */
  now?: number;
  /**
   * `resetInterrupted` from `./classificationQueue`, applied on a cold read.
   *
   * Taken as an argument rather than imported: the adapter must not depend on
   * the reducer, and `sending` is a liveness marker for the running process
   * that is never authoritative across a restart (invariant 5c). Without it an
   * app kill mid-send strands the entry — every later drain skips it, so it is
   * never sent, never conflicts, never errors.
   */
  resetInterrupted?: (entries: PendingClassificationChange[]) => PendingClassificationChange[];
}

export interface SweepOptions {
  /**
   * Either of the active identity's two keys, or `null` when nobody is signed
   * in. Both stores of that identity are protected — they share a suffix.
   */
  activeKey: string | null;
  now: number;
  /** Defaults to the 30-day bound cross-checked against the last server
   *  `Date` seen. */
  isExpired?: RetentionRule;
}

export interface SweepResult {
  /** Classification keys examined. Keys belonging to anything else are not
   *  touched, counted, or parsed. */
  scannedKeys: number;
  /** Keys removed outright: every non-active key once a different identity is
   *  signed in, plus any key the age rule emptied. */
  deletedKeys: string[];
  /** Entries removed from keys that are not the active identity's. Nobody can
   *  be told about these — SC-003 accepts that cost explicitly. */
  foreignEntriesDropped: number;
  /**
   * Entries under the ACTIVE key that the age rule has caught. The sweep
   * counts them and destroys nothing: `expired` retains the payload until the
   * person dismisses the notice, so a clock error stays recoverable
   * (invariant 8). The count is what lets the notice state a total.
   */
  activeEntriesExpired: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Validates only what this adapter depends on — identity, the retention
 * timestamp, and the send state. The rest of the shape is the reducer's
 * contract in `classificationTypes.ts`; dropping an entry is destructive, so
 * this refuses to be stricter than its own needs.
 */
function isPendingEntry(value: unknown): value is PendingClassificationChange {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.taskId === "string" &&
    value.taskId !== "" &&
    typeof value.accountId === "string" &&
    typeof value.serverUrl === "string" &&
    isRecord(value.value) &&
    typeof value.idempotencyKey === "string" &&
    typeof value.lastEditedAt === "string" &&
    typeof value.sendState === "string" &&
    SEND_STATES.has(value.sendState)
  );
}

function isCachedLists(value: unknown): value is CachedClassificationLists {
  return (
    isRecord(value) &&
    Array.isArray(value.projects) &&
    Array.isArray(value.tags) &&
    typeof value.fetchedAt === "string"
  );
}

function belongsTo(entry: PendingClassificationChange, identity: ClassificationIdentity): boolean {
  return entry.accountId === identity.accountId && entry.serverUrl === identity.serverUrl;
}

async function readJson(key: string): Promise<{ text: string | null; value: unknown }> {
  const text = await AsyncStorage.getItem(key);
  if (text === null) {
    return { text: null, value: null };
  }
  try {
    return { text, value: JSON.parse(text) as unknown };
  } catch {
    return { text, value: undefined };
  }
}

/**
 * A timestamp in the future is stored as `now`.
 *
 * Otherwise a clock that was ahead when the entry was written makes
 * `now - lastEditedAt` negative and the 30-day bound never fires — on exactly
 * the entries whose timestamps are least trustworthy (invariant 8).
 */
function clampTimestamp(value: string | undefined, now: number): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed) || parsed > now) {
    return new Date(now).toISOString();
  }
  return value;
}

function clampEntry(
  entry: PendingClassificationChange,
  now: number,
): PendingClassificationChange {
  const firstQueuedAt = clampTimestamp(entry.firstQueuedAt, now) ?? new Date(now).toISOString();
  const lastEditedAt = clampTimestamp(entry.lastEditedAt, now) ?? new Date(now).toISOString();
  const firstSentAt = clampTimestamp(entry.firstSentAt, now);
  if (
    firstQueuedAt === entry.firstQueuedAt &&
    lastEditedAt === entry.lastEditedAt &&
    firstSentAt === entry.firstSentAt
  ) {
    return entry;
  }
  return { ...entry, firstQueuedAt, lastEditedAt, ...(firstSentAt ? { firstSentAt } : {}) };
}

// ---------------------------------------------------------------- server clock

export function parseServerDate(header: string | number | null | undefined): number | null {
  if (header === null || header === undefined) {
    return null;
  }
  const parsed = typeof header === "number" ? header : Date.parse(header);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Records the last server `Date` header seen (FR-018).
 *
 * Never moves backwards. A cached, proxied or malformed `Date` must not become
 * a licence to expire a queue, and the asymmetry is deliberate: too *low* a
 * server time only delays expiry, while too *high* a one merely returns the
 * bound to the device clock it already had.
 */
export async function saveServerTime(
  header: string | number | null | undefined,
): Promise<number | null> {
  const parsed = parseServerDate(header);
  const previous = await loadServerTime();
  if (parsed === null || (previous !== null && parsed <= previous)) {
    return previous;
  }
  await AsyncStorage.setItem(SERVER_TIME_KEY, String(parsed));
  return parsed;
}

export async function loadServerTime(): Promise<number | null> {
  const raw = await AsyncStorage.getItem(SERVER_TIME_KEY);
  if (raw === null) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * The 30-day bound, evaluated against both clocks.
 *
 * Both must agree before anything is destroyed, so a device clock jumped
 * forward cannot delete a queue on its own. With no server time ever seen
 * there is nothing better than the device clock, and FR-018's bound must still
 * be enforceable — an entry that can never expire is the other failure.
 */
export function isBeyondRetention(
  timestamp: string | undefined,
  deviceNow: number,
  serverNow?: number | null,
): boolean {
  const at = timestamp === undefined ? Number.NaN : Date.parse(timestamp);
  if (!Number.isFinite(at)) {
    // An entry that cannot be dated cannot be bounded, and FR-018 is a MUST.
    return true;
  }
  if (deviceNow - at <= RETENTION_MS) {
    return false;
  }
  if (serverNow !== undefined && serverNow !== null && serverNow - at <= RETENTION_MS) {
    return false;
  }
  return true;
}

/** The retention rule with the persisted server clock already bound into it,
 *  so the read path and the sweep apply the same test. */
export async function loadRetentionRule(): Promise<RetentionRule> {
  const serverNow = await loadServerTime();
  return (timestamp, now) => isBeyondRetention(timestamp, now, serverNow);
}

// --------------------------------------------------------------- queue adapter

/**
 * Reads the active identity's queue.
 *
 * Every entry is checked against the active identity before it is returned,
 * and a mismatch is removed from the device rather than merely filtered out of
 * the result — nothing else ever reads this key, so filtering alone would keep
 * another identity's content forever.
 */
export async function loadQueue(
  identity: ClassificationIdentity,
  options: LoadQueueOptions = {},
): Promise<PendingClassificationChange[]> {
  const key = queueKey(identity.serverUrl, identity.accountId);
  const { text, value } = await readJson(key);

  if (!Array.isArray(value)) {
    if (text !== null) {
      await AsyncStorage.removeItem(key);
    }
    return [];
  }

  const kept = (value as unknown[]).filter(isPendingEntry).filter((e) => belongsTo(e, identity));
  const entries = options.resetInterrupted ? options.resetInterrupted(kept) : kept;

  // Persist any repair — a pruned foreign entry, or a `sending` entry reset by
  // the cold read — so a second interruption cannot strand it again.
  const next = JSON.stringify(entries);
  if (next !== text) {
    if (entries.length === 0) {
      await AsyncStorage.removeItem(key);
    } else {
      await AsyncStorage.setItem(key, next);
    }
  }
  return entries;
}

/**
 * Writes the active identity's queue.
 *
 * Entries belonging to another identity are refused rather than re-keyed:
 * entries are never migrated across identities (invariant 4), and writing the
 * active identity over them would launder exactly what the read check catches.
 */
export async function saveQueue(
  identity: ClassificationIdentity,
  entries: PendingClassificationChange[],
  now: number = Date.now(),
): Promise<void> {
  const key = queueKey(identity.serverUrl, identity.accountId);
  if (isForgottenKey(key)) {
    // This identity's stores were deliberately cleared while this write was
    // waiting its turn behind another. Writing now would re-create the queue
    // a sign-out or a server change had just deleted, under a key nothing on
    // the device can name any more.
    return;
  }
  const owned = entries.filter((e) => belongsTo(e, identity)).map((e) => clampEntry(e, now));
  if (owned.length === 0) {
    await AsyncStorage.removeItem(key);
    return;
  }
  await AsyncStorage.setItem(key, JSON.stringify(owned));
}

export async function clearQueue(identity: ClassificationIdentity): Promise<void> {
  await AsyncStorage.removeItem(queueKey(identity.serverUrl, identity.accountId));
}

/**
 * Drops the cached project and Tag lists for one identity.
 *
 * Called on every deliberate identity transition **even when the queue is
 * empty**: M-05 never appears in that case, so a sign-out with nothing pending
 * would otherwise leave one account's whole project and Tag vocabulary — the
 * names the person wrote — on the device for the next one.
 */
export async function clearCacheFor(identity: ClassificationIdentity): Promise<void> {
  await AsyncStorage.removeItem(cacheKey(identity.serverUrl, identity.accountId));
}

/** Both stores of one identity, together. Clearing one and forgetting the
 *  other is the documented bug FR-011 exists to prevent. */
export async function clearIdentityStores(identity: ClassificationIdentity): Promise<void> {
  // Tombstoned *before* the delete, not after: a queued write that lands
  // between the two would otherwise slip underneath the clear and put the work
  // straight back. See `forgetIdentityStores`.
  forgetIdentityStores(identity.serverUrl, identity.accountId);
  await AsyncStorage.multiRemove(keysForIdentity(identity.serverUrl, identity.accountId));
}

// ------------------------------------------------------- cross-identity sweep

/**
 * Applies the age rule to every stored classification key, and deletes any key
 * that is not the active identity's once a different identity is signed in
 * (invariant 8b).
 *
 * Run on app start and on every identity change. FR-011's "discarded on a
 * different one" and FR-018's bound become true by construction here, instead
 * of by a read that may never happen.
 *
 * The active identity's *queue* is counted, never emptied: its expiry is
 * surfaced as a notice with the payload retained, which is the only reason the
 * 30-day bound is recoverable from a wrong clock. Its *cache* is dropped when
 * aged — it holds no unsent work and refetches.
 */
export async function sweepAllIdentities(options: SweepOptions): Promise<SweepResult> {
  const { activeKey, now } = options;
  const isExpired = options.isExpired ?? (await loadRetentionRule());
  const activeSuffix = activeKey === null ? null : identitySuffixOf(activeKey);

  const allKeys = await AsyncStorage.getAllKeys();
  const ours = allKeys.filter(isClassificationKey);

  const deletedKeys: string[] = [];
  let foreignEntriesDropped = 0;
  let activeEntriesExpired = 0;

  for (const key of ours) {
    const isActive = activeSuffix !== null && identitySuffixOf(key) === activeSuffix;

    // A different identity has signed in successfully: unreadable is not
    // deleted, so delete it.
    if (!isActive && activeSuffix !== null) {
      deletedKeys.push(key);
      continue;
    }

    const { value } = await readJson(key);

    if (storeOf(key) === "cache") {
      if (!isCachedLists(value) || isExpired(value.fetchedAt, now)) {
        deletedKeys.push(key);
      }
      continue;
    }

    if (!Array.isArray(value)) {
      // Unreadable, and nothing will ever read it again to repair it.
      deletedKeys.push(key);
      continue;
    }

    const entries = (value as unknown[]).filter(isPendingEntry);
    const aged = entries.filter((e) => isExpired(e.lastEditedAt, now));

    if (isActive) {
      activeEntriesExpired += aged.length;
      continue;
    }

    const kept = entries.filter((e) => !isExpired(e.lastEditedAt, now));
    foreignEntriesDropped += entries.length - kept.length;
    if (kept.length === 0) {
      deletedKeys.push(key);
    } else if (kept.length !== (value as unknown[]).length) {
      await AsyncStorage.setItem(key, JSON.stringify(kept));
    }
  }

  if (deletedKeys.length > 0) {
    await AsyncStorage.multiRemove(deletedKeys);
  }

  return {
    scannedKeys: ours.length,
    deletedKeys,
    foreignEntriesDropped,
    activeEntriesExpired,
  };
}
