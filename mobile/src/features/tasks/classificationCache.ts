/**
 * FR-006 / FR-011 / FR-018 — the cached project and Tag lists.
 *
 * The pickers must work after a cold start with no connection (SC-009), so the
 * last lists the device saw are persisted. This store holds **names the person
 * wrote**, where the queue holds only ids, and project and Tag names routinely
 * carry the most disclosing content in a GTD system. Its lifetime rules are
 * therefore its own, not an afterthought of the queue's:
 *
 * - **Cleared on every deliberate identity transition, even when the queue is
 *   empty.** M-05 never appears with an empty queue (design.md), so a sign-out
 *   with nothing pending shows no warning at all — and without this clear it
 *   would leave one account's whole vocabulary on the device for the next
 *   person, which is the literal thing FR-011 exists to prevent.
 * - **The 30-day bound of FR-018 runs from `fetchedAt`**, and a read that finds
 *   an expired or unreadable blob deletes it rather than leaving it behind.
 *   That covers the active identity only; every *other* stored identity is
 *   reached by the cross-identity sweep — see the note at the end.
 *
 * The storage key is an argument, not an import, so nothing here depends on how
 * identity is encoded. The store is an AsyncStorage-shaped interface for the
 * same reason — and so the whole module tests in memory.
 *
 * Unlike the queue, an expired cache is deleted rather than retained: it is a
 * copy of server state with nothing of the person's in it to recover, so
 * FR-018's "retain the payload" guard has nothing to protect here.
 *
 * The cross-identity sweep of invariant 8b is *not* here. It has to walk both
 * prefixes in one pass over `getAllKeys()`, so it lives with the queue's
 * storage adapter (`classificationQueue.storage.ts`, `sweepAllIdentities`);
 * a second sweep of one prefix would be a competing copy of one rule. Pass that
 * module's `loadRetentionRule()` in as `isExpired` below to keep the read path
 * and the sweep applying the same test, server-clock cross-check included.
 */

import { RETENTION_MS, type CachedClassificationLists } from "./classificationTypes";
import { toEpochMs, type Instant } from "./syncStatus";

/** The slice of AsyncStorage this module needs. */
export interface ClassificationCacheStore {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
}

/**
 * The retention test, so the read path can be handed the same rule the sweep
 * uses — the one with the last observed server time bound into it, which is
 * what stops a device clock deciding on its own (FR-018).
 */
export type CacheRetentionRule = (fetchedAt: string, now: number) => boolean;

function parseEntities(value: unknown): { id: string; name: string }[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const entities: { id: string; name: string }[] = [];
  for (const item of value) {
    if (typeof item !== "object" || item === null) {
      return null;
    }
    const { id, name } = item as { id?: unknown; name?: unknown };
    if (typeof id !== "string" || typeof name !== "string") {
      return null;
    }
    entities.push({ id, name });
  }
  return entities;
}

/**
 * The stored blob, or `null` when it is not a whole, well-formed cache.
 *
 * Half a list is worse than no list: the picker would show a shortened
 * vocabulary as though it were complete, and the person would create a
 * duplicate of something they already have.
 */
function parseLists(raw: string): CachedClassificationLists | null {
  let decoded: unknown;
  try {
    decoded = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof decoded !== "object" || decoded === null || Array.isArray(decoded)) {
    return null;
  }
  const { projects, tags, fetchedAt } = decoded as {
    projects?: unknown;
    tags?: unknown;
    fetchedAt?: unknown;
  };
  const parsedProjects = parseEntities(projects);
  const parsedTags = parseEntities(tags);
  if (parsedProjects === null || parsedTags === null || typeof fetchedAt !== "string") {
    return null;
  }
  return { projects: parsedProjects, tags: parsedTags, fetchedAt };
}

/**
 * FR-018's 30-day bound, measured from `fetchedAt`.
 *
 * A `fetchedAt` that does not parse counts as expired: an unreadable timestamp
 * is not evidence of freshness, and treating it as ageless is how a store
 * becomes the one thing in the product with no retention bound.
 */
export function isCacheExpired(fetchedAt: string, now: Instant): boolean {
  const fetched = toEpochMs(fetchedAt);
  const current = toEpochMs(now);
  if (fetched === null || current === null) {
    return true;
  }
  return current - fetched > RETENTION_MS;
}

function applyRetention(fetchedAt: string, now: Instant, rule?: CacheRetentionRule): boolean {
  if (rule === undefined) {
    return isCacheExpired(fetchedAt, now);
  }
  const current = toEpochMs(now);
  // A `now` that carries no time cannot bound anything, and an unbounded store
  // is the one thing FR-018 forbids.
  return current === null || rule(fetchedAt, current);
}

/**
 * Persist the lists, returning exactly what was stored.
 *
 * `fetchedAt` is clamped to `now`: a device clock that was ahead when the write
 * happened would otherwise put the age permanently out of reach of the bound —
 * the same guard the queue applies to its own timestamps (invariant 8). Only
 * `id` and `name` are kept, so nothing else the server sent comes to rest on
 * the device.
 */
export async function writeClassificationCache(options: {
  store: ClassificationCacheStore;
  key: string;
  lists: CachedClassificationLists;
  now: Instant;
}): Promise<CachedClassificationLists> {
  const { store, key, lists, now } = options;
  const current = toEpochMs(now);
  const fetched = toEpochMs(lists.fetchedAt);
  let fetchedAt = lists.fetchedAt;
  if (current !== null && (fetched === null || fetched > current)) {
    fetchedAt = new Date(current).toISOString();
  }

  const stored: CachedClassificationLists = {
    projects: lists.projects.map((project) => ({ id: project.id, name: project.name })),
    tags: lists.tags.map((tag) => ({ id: tag.id, name: tag.name })),
    fetchedAt,
  };
  await store.setItem(key, JSON.stringify(stored));
  return stored;
}

/**
 * The lists this identity last saw, or `null` when there are none to show —
 * which is M-02/M-03's "offline, never fetched" state, stated plainly rather
 * than rendered as "no projects yet".
 *
 * A malformed or expired blob is deleted on the way out, so a store nobody can
 * read does not sit on the device until the next sweep.
 */
export async function readClassificationCache(options: {
  store: ClassificationCacheStore;
  key: string;
  now: Instant;
  /** Defaults to the plain 30 days from `fetchedAt`. */
  isExpired?: CacheRetentionRule;
}): Promise<CachedClassificationLists | null> {
  const { store, key, now, isExpired } = options;
  const raw = await store.getItem(key);
  if (raw === null) {
    return null;
  }
  const lists = parseLists(raw);
  if (lists === null || applyRetention(lists.fetchedAt, now, isExpired)) {
    await store.removeItem(key);
    return null;
  }
  return lists;
}

/**
 * FR-011 — the deliberate identity transition (sign-out, account change,
 * server change).
 *
 * Deliberately takes no queue: this runs whether or not anything was pending,
 * because M-05 is shown only for a non-empty queue and the vocabulary has to go
 * either way.
 */
export async function clearClassificationCache(options: {
  store: ClassificationCacheStore;
  key: string;
}): Promise<void> {
  await options.store.removeItem(options.key);
}
