/**
 * 006-FR-006 / 006-FR-011 / 006-FR-018 — the cached project and Tag lists.
 *
 * The store is injected as an AsyncStorage-shaped interface and the key as a
 * plain string, so nothing here touches the device and no test depends on the
 * key derivation that lives elsewhere.
 *
 * The clearing test is the one that matters most: M-05 never appears with an
 * empty queue (design.md), so a sign-out with nothing pending would otherwise
 * leave one account's whole project and Tag vocabulary on the device for the
 * next person — the literal thing FR-011 exists to prevent.
 */

import type { CachedClassificationLists } from "../classificationTypes";
import {
  clearClassificationCache,
  isCacheExpired,
  readClassificationCache,
  writeClassificationCache,
  type ClassificationCacheStore,
} from "../classificationCache";

const NOW = Date.parse("2026-08-11T12:00:00.000Z");
const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const PREFIX = "bb.classificationCache.";
const KEY_A = `${PREFIX}https%3A%2F%2Fapi.example.test.user_a`;
const KEY_B = `${PREFIX}https%3A%2F%2Fapi.example.test.user_b`;

const LISTS: CachedClassificationLists = {
  projects: [
    { id: "project_1", name: "Q3 Launch" },
    { id: "project_2", name: "Therapy — homework" },
  ],
  tags: [
    { id: "tag_1", name: "home" },
    { id: "tag_2", name: "deep work" },
  ],
  fetchedAt: new Date(NOW - 5 * MINUTE).toISOString(),
};

interface MemoryStore extends ClassificationCacheStore {
  readonly items: Map<string, string>;
}

/** An in-memory stand-in for AsyncStorage. */
function memoryStore(seed: Record<string, string> = {}): MemoryStore {
  const items = new Map<string, string>(Object.entries(seed));
  return {
    items,
    getItem: async (key) => items.get(key) ?? null,
    setItem: async (key, value) => {
      items.set(key, value);
    },
    removeItem: async (key) => {
      items.delete(key);
    },
  };
}

const stored = (lists: Partial<CachedClassificationLists>): string => JSON.stringify(lists);

describe("006-FR-006 the pickers work after a cold start with no connection", () => {
  it("round-trips the lists the person would otherwise have to be online to see", async () => {
    const store = memoryStore();
    await writeClassificationCache({ store, key: KEY_A, lists: LISTS, now: NOW });

    // A cold start: nothing in memory, only what the device holds.
    const coldStore = memoryStore(Object.fromEntries(store.items));
    expect(await readClassificationCache({ store: coldStore, key: KEY_A, now: NOW })).toEqual(LISTS);
  });

  it("keeps the names byte-for-byte, including punctuation the person typed", async () => {
    const store = memoryStore();
    await writeClassificationCache({ store, key: KEY_A, lists: LISTS, now: NOW });
    const read = await readClassificationCache({ store, key: KEY_A, now: NOW });
    expect(read?.projects[1].name).toBe("Therapy — homework");
    expect(read?.tags.map((tag) => tag.name)).toEqual(["home", "deep work"]);
  });

  it("returns null when this device has never fetched, so M-02 can say exactly that", async () => {
    const store = memoryStore();
    expect(await readClassificationCache({ store, key: KEY_A, now: NOW })).toBeNull();
  });

  it("reads only its own key: another identity's cache is not a fallback", async () => {
    const store = memoryStore({ [KEY_B]: stored(LISTS) });
    expect(await readClassificationCache({ store, key: KEY_A, now: NOW })).toBeNull();
  });

  it.each<[string, string]>([
    ["a truncated write", '{"projects":[{"id":"p1","na'],
    ["a value that is not an object", '"nope"'],
    ["projects missing", stored({ tags: [], fetchedAt: LISTS.fetchedAt })],
    ["projects not an array", '{"projects":{},"tags":[],"fetchedAt":"2026-08-11T11:55:00.000Z"}'],
    ["an entry with no name", '{"projects":[{"id":"p1"}],"tags":[],"fetchedAt":"2026-08-11T11:55:00.000Z"}'],
    ["fetchedAt missing", stored({ projects: [], tags: [] })],
  ])("discards %s rather than handing a picker half a list", async (_why, value) => {
    const store = memoryStore({ [KEY_A]: value });
    expect(await readClassificationCache({ store, key: KEY_A, now: NOW })).toBeNull();
    expect(store.items.has(KEY_A)).toBe(false);
  });
});

describe("006-FR-011 a deliberate identity transition clears the cache", () => {
  it("clears it even when the queue is empty and M-05 therefore never appeared", async () => {
    // Sign-out with nothing pending: no warning is shown, and this is the only
    // thing standing between one account's vocabulary and the next person.
    const store = memoryStore({ [KEY_A]: stored(LISTS) });
    await clearClassificationCache({ store, key: KEY_A });
    expect(store.items.has(KEY_A)).toBe(false);
    expect(await readClassificationCache({ store, key: KEY_A, now: NOW })).toBeNull();
  });

  it("is a deletion, not a filter: nothing of it is left to be read back", async () => {
    const store = memoryStore({ [KEY_A]: stored(LISTS) });
    await clearClassificationCache({ store, key: KEY_A });
    expect([...store.items.values()].join("")).not.toContain("Therapy");
  });

  it("is unbothered by a cache that was never written", async () => {
    const store = memoryStore();
    await expect(clearClassificationCache({ store, key: KEY_A })).resolves.toBeUndefined();
  });

  it("touches only the key it was given: another identity's cache is not its business", async () => {
    const store = memoryStore({
      [KEY_A]: stored(LISTS),
      [KEY_B]: stored(LISTS),
      "bb.serverUrl": "https://api.example.test",
    });
    await clearClassificationCache({ store, key: KEY_A });
    expect([...store.items.keys()].sort()).toEqual([KEY_B, "bb.serverUrl"].sort());
  });
});

describe("006-FR-018 the 30-day bound runs from fetchedAt", () => {
  it.each([
    { why: "written a minute ago", age: MINUTE, expired: false },
    { why: "one hour short of the bound", age: 30 * DAY - HOUR, expired: false },
    { why: "one minute short of the bound", age: 30 * DAY - MINUTE, expired: false },
    { why: "the bound exactly, which is not yet past it", age: 30 * DAY, expired: false },
    { why: "a minute past the bound", age: 30 * DAY + MINUTE, expired: true },
    { why: "a year past the bound", age: 365 * DAY, expired: true },
  ])("$why: expired = $expired", ({ age, expired }) => {
    expect(isCacheExpired(new Date(NOW - age).toISOString(), NOW)).toBe(expired);
  });

  it("29 days and 23 hours is still read, so the picker keeps working", async () => {
    const fetchedAt = new Date(NOW - (30 * DAY - HOUR)).toISOString();
    const store = memoryStore({ [KEY_A]: stored({ ...LISTS, fetchedAt }) });
    expect(await readClassificationCache({ store, key: KEY_A, now: NOW })).not.toBeNull();
    expect(store.items.has(KEY_A)).toBe(true);
  });

  it("a minute past 30 days is not returned, and is deleted rather than left behind", async () => {
    const fetchedAt = new Date(NOW - (30 * DAY + MINUTE)).toISOString();
    const store = memoryStore({ [KEY_A]: stored({ ...LISTS, fetchedAt }) });
    expect(await readClassificationCache({ store, key: KEY_A, now: NOW })).toBeNull();
    expect(store.items.has(KEY_A)).toBe(false);
  });

  it("honours an injected rule, so the read path and the sweep can share one test", async () => {
    // `loadRetentionRule()` in classificationQueue.storage.ts binds the last
    // observed server `Date` into the bound, so a device clock that jumped
    // forward cannot condemn a store on its own (FR-018).
    const fetchedAt = new Date(NOW - 40 * DAY).toISOString();
    const store = memoryStore({ [KEY_A]: stored({ ...LISTS, fetchedAt }) });
    const serverSaysItIsFine = jest.fn().mockReturnValue(false);

    const read = await readClassificationCache({
      store,
      key: KEY_A,
      now: NOW,
      isExpired: serverSaysItIsFine,
    });

    expect(serverSaysItIsFine).toHaveBeenCalledWith(fetchedAt, NOW);
    expect(read?.fetchedAt).toBe(fetchedAt);
    expect(store.items.has(KEY_A)).toBe(true);
  });

  it("an injected rule that condemns the cache still deletes it", async () => {
    const store = memoryStore({ [KEY_A]: stored(LISTS) });
    const read = await readClassificationCache({
      store,
      key: KEY_A,
      now: NOW,
      isExpired: () => true,
    });
    expect(read).toBeNull();
    expect(store.items.has(KEY_A)).toBe(false);
  });

  it("clamps a fetchedAt written by a clock that was ahead, so it cannot become immortal", async () => {
    // The same guard the queue applies at write time (data-model invariant 8):
    // a timestamp in the future is stored as now.
    const store = memoryStore();
    await writeClassificationCache({
      store,
      key: KEY_A,
      lists: { ...LISTS, fetchedAt: new Date(NOW + 10 * DAY).toISOString() },
      now: NOW,
    });
    const written = await readClassificationCache({ store, key: KEY_A, now: NOW });
    expect(written?.fetchedAt).toBe(new Date(NOW).toISOString());
    expect(await readClassificationCache({ store, key: KEY_A, now: NOW + 31 * DAY })).toBeNull();
  });

  it("treats an unparseable fetchedAt as expired rather than as ageless", () => {
    expect(isCacheExpired("whenever", NOW)).toBe(true);
    expect(isCacheExpired("", NOW)).toBe(true);
  });
});
