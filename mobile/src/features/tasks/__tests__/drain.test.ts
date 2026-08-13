/**
 * 006-FR-021 / 006-FR-017 / 006-FR-008 / 006-FR-018 — the drain orchestration.
 *
 * The drain's decisions live in pure functions over the queue, and this file
 * tests those rather than the hook that calls them — a rule that lives inside
 * a `useEffect` is hard to pin, and pushing it out is what makes it testable
 * at all.
 *
 * That split was originally forced: when this was written `mobile/` had no way
 * to render a component in a test. It does now, and the screens that call this
 * hook have their own render tests. The split stayed because it is the better
 * shape, not because it is the only one available.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

import type { PendingClassificationChange } from "../classificationTypes";
import { RETENTION_MS, SERVER_REPLAY_WINDOW_MS } from "../classificationTypes";
import { isBeyondRetention, loadQueue, sweepAllIdentities } from "../classificationQueue.storage";
import { resetInterrupted } from "../classificationQueue";
import { queueKey } from "../storageKeys";
import {
  buildUpdatePayload,
  countExpired,
  describeExpiredChange,
  drainQueue,
  effectiveClassification,
  hydrateQueue,
  mergePassResult,
  planDrainStep,
  resolveConflictDiscardMine,
  resolveConflictKeepMine,
  resolveRereadOutcome,
  resolveSendRejection,
  resolveSendSuccess,
  selectPendingConflict,
  shouldRereadAfterRejection,
  sweepActiveKey,
  type DrainPort,
  type ServerTaskState,
} from "../useClassificationQueue";

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
      multiSet: jest.fn(async (pairs: readonly (readonly [string, string])[]) => {
        for (const [key, value] of pairs) {
          store.set(key, value);
        }
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

const SERVER = "https://api.example.test/api";
const ACCOUNT = "acc-1";
const IDENTITY = { serverUrl: SERVER, accountId: ACCOUNT };

const OTHER_SERVER = "http://192.168.1.10:8000/api";
const OTHER_ACCOUNT = "acc-2";

const NOW = Date.parse("2026-08-11T12:00:00.000Z");
const MINUTE = 60_000;

function iso(at: number): string {
  return new Date(at).toISOString();
}

function entry(overrides: Partial<PendingClassificationChange> = {}): PendingClassificationChange {
  return {
    taskId: "task-1",
    accountId: ACCOUNT,
    serverUrl: SERVER,
    value: { projectId: "proj-q3", tagIds: ["tag-calls"] },
    observedRevision: 4,
    originalValue: { projectId: null, tagIds: [] },
    firstQueuedAt: iso(NOW - 10 * MINUTE),
    lastEditedAt: iso(NOW - 10 * MINUTE),
    idempotencyKey: "key-1",
    sendState: "queued",
    ...overrides,
  };
}

/** An `ApiError`-shaped throw, duck-typed exactly as the real client's is. */
function apiError(status: number, detail?: { resource: string; id: string }) {
  return {
    name: "ApiError",
    message: "Conflict",
    status,
    correlationId: "corr-1",
    payload: {
      message: "Task 'task-1' has newer changes; reload before saving.",
      reference_id: "ref-1",
      ...(detail ? { detail } : {}),
    },
  };
}

interface Recorder {
  port: DrainPort;
  sent: { taskId: string; idempotencyKey: string; payload: unknown }[];
  reread: string[];
}

function recorder(options: {
  send?: (request: { taskId: string; idempotencyKey: string }) => Promise<ServerTaskState>;
  reread?: (taskId: string) => Promise<ServerTaskState>;
  now?: number;
} = {}): Recorder {
  const sent: Recorder["sent"] = [];
  const reread: string[] = [];
  let minted = 0;
  const port: DrainPort = {
    now: () => options.now ?? NOW,
    mintKey: () => `minted-${++minted}`,
    async send(request) {
      sent.push({ ...request });
      if (options.send) {
        return options.send(request);
      }
      return { revision: 9, projectId: "proj-q3", tagIds: ["tag-calls"] };
    },
    async reread(taskId) {
      reread.push(taskId);
      if (options.reread) {
        return options.reread(taskId);
      }
      return { revision: 9, projectId: null, tagIds: [] };
    },
  };
  return { port, sent, reread };
}

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe("006-FR-021 a cold read revives a send the app was killed in the middle of", () => {
  it("resets `sending` to `queued`, so the ordinary drain picks the entry up", () => {
    const stored = [entry({ sendState: "sending", firstSentAt: iso(NOW - MINUTE) })];

    const hydrated = hydrateQueue(stored, NOW);

    expect(hydrated.queue[0].sendState).toBe("queued");
    expect(hydrated.queue[0].idempotencyKey).toBe("key-1");
  });

  it("is what makes it drainable at all — the stored queue on its own yields nothing", () => {
    const stored = [entry({ sendState: "sending", firstSentAt: iso(NOW - MINUTE) })];

    // Invariant 5 skips anything in flight, so without the reset this entry is
    // stranded until FR-018 drops it 30 days later with nothing having told the
    // person it was pending.
    expect(planDrainStep(stored, NOW).kind).toBe("idle");
    expect(planDrainStep(hydrateQueue(stored, NOW).queue, NOW).kind).toBe("send");
  });

  it("keeps the key, so a send that did land replays rather than applying twice", () => {
    const stored = [entry({ sendState: "sending", firstSentAt: iso(NOW - MINUTE) })];
    const step = planDrainStep(hydrateQueue(stored, NOW).queue, NOW);

    expect(step.kind).toBe("send");
    if (step.kind !== "send") throw new Error("unreachable");
    expect(step.request.idempotencyKey).toBe("key-1");
  });
});

describe("006-FR-017 at most one send of one entry is ever in flight", () => {
  it("selects an entry, then nothing more for that task until the send settles", () => {
    const queue = [entry()];

    const first = planDrainStep(queue, NOW);
    expect(first.kind).toBe("send");
    // The second trigger — foreground and after-a-success both fire — reads the
    // queue the first one persisted.
    expect(planDrainStep(first.queue, NOW).kind).toBe("idle");
  });

  it("sends nothing when another trigger already marked the entry `sending`", async () => {
    const rec = recorder();

    const result = await drainQueue([entry({ sendState: "sending" })], rec.port);

    expect(rec.sent).toHaveLength(0);
    expect(result.stoppedBecause).toBe("drained");
  });

  it("makes exactly one call to the sender for one queued entry", async () => {
    const rec = recorder();

    await drainQueue([entry()], rec.port);

    expect(rec.sent).toHaveLength(1);
    expect(rec.sent[0].idempotencyKey).toBe("key-1");
  });

  it("stamps firstSentAt on the first attempt only — invariant 10 measures from it", () => {
    const already = iso(NOW - 3 * MINUTE);
    const step = planDrainStep([entry({ firstSentAt: already })], NOW);

    expect(step.queue[0].firstSentAt).toBe(already);
    expect(planDrainStep([entry()], NOW).queue[0].firstSentAt).toBe(iso(NOW));
  });

  it("removes the entry and advances last-synced once the server accepts it", async () => {
    const rec = recorder();

    const result = await drainQueue([entry()], rec.port);

    expect(result.queue).toHaveLength(0);
    expect(result.settled).toBe(1);
    expect(result.lastSyncedAt).toBe(iso(NOW));
  });

  it("006-FR-010 re-bases an edit made while the entry was in flight (invariant 5b)", () => {
    const sending = entry({ sendState: "sending" });
    // The successor: its own key, its own payload, still carrying the revision
    // it was made against — which the acceptance now supersedes.
    const successor = entry({
      idempotencyKey: "key-2",
      value: { projectId: "proj-later", tagIds: undefined },
      firstQueuedAt: iso(NOW - MINUTE),
    });

    const resolution = resolveSendSuccess([sending, successor], sending, {
      revision: 9,
      projectId: "proj-q3",
      tagIds: ["tag-calls"],
    });

    expect(resolution.queue).toHaveLength(1);
    expect(resolution.queue[0].idempotencyKey).toBe("key-2");
    expect(resolution.queue[0].observedRevision).toBe(9);
  });

  it("006-FR-017 does not send the successor while its predecessor is in flight", () => {
    const queue = [
      entry({ sendState: "sending" }),
      entry({ idempotencyKey: "key-2", firstQueuedAt: iso(NOW - MINUTE) }),
    ];

    expect(planDrainStep(queue, NOW).kind).toBe("idle");
  });
});

describe("006-FR-010 a pass decides against the queue the device holds now (invariant 5b)", () => {
  /**
   * The successor `coalesce` appends while the predecessor is in flight: its
   * own key, its own payload, and the revision the person was looking at.
   */
  const successor = (): PendingClassificationChange =>
    entry({
      idempotencyKey: "key-2",
      value: { projectId: undefined, tagIds: ["tag-calls", "tag-home"] },
      firstQueuedAt: iso(NOW - MINUTE),
      lastEditedAt: iso(NOW - MINUTE),
    });

  /**
   * A device the pass does not own. `persist` writes to it, `latest` reads it,
   * and the edit made below appears in it and nowhere else — which is the whole
   * point: a pass that keeps deciding against the snapshot it started from
   * writes that edit back out of existence, and FR-007 guarantees no surface
   * ever said it was pending.
   */
  function deviceHolding(initial: PendingClassificationChange[]) {
    const state = { queue: initial };
    return {
      state,
      wire: (port: DrainPort): DrainPort => ({
        ...port,
        latest: () => state.queue,
        persist: async (queue) => {
          state.queue = [...queue];
        },
      }),
    };
  }

  it("adopts an edit made while the request was out, and re-bases it on the accepted revision", async () => {
    const device = deviceHolding([entry()]);
    const rec = recorder({
      send: async ({ idempotencyKey }) => {
        if (idempotencyKey === "key-1") {
          // The person edits the same task while this request is in flight.
          device.state.queue = [...device.state.queue, successor()];
        }
        return { revision: 9, projectId: "proj-q3", tagIds: ["tag-calls"] };
      },
    });

    const result = await drainQueue([entry()], device.wire(rec.port));

    // Sent rather than deleted — and against the revision the first send
    // returned, so the person's own second edit does not land in a conflict of
    // the app's making (invariant 5b's second half).
    expect(rec.sent.map((call) => call.idempotencyKey)).toEqual(["key-1", "key-2"]);
    expect(rec.sent[1].payload).toEqual({
      expected_revision: 9,
      tag_ids: ["tag-calls", "tag-home"],
    });
    expect(result.queue).toHaveLength(0);
    expect(device.state.queue).toHaveLength(0);
  });

  it("leaves it on the device when the pass cannot send it yet", async () => {
    const device = deviceHolding([entry()]);
    const rec = recorder({
      send: async ({ idempotencyKey }) => {
        if (idempotencyKey === "key-1") {
          device.state.queue = [...device.state.queue, successor()];
          return { revision: 9, projectId: "proj-q3", tagIds: ["tag-calls"] };
        }
        throw new TypeError("Network request failed");
      },
    });

    const result = await drainQueue([entry()], device.wire(rec.port));

    // The pass settled the entry it knew about and kept the one it did not.
    expect(result.stoppedBecause).toBe("retry-later");
    expect(device.state.queue).toHaveLength(1);
    expect(device.state.queue[0]).toMatchObject({
      idempotencyKey: "key-2",
      sendState: "queued",
      observedRevision: 9,
      value: { tagIds: ["tag-calls", "tag-home"] },
    });
  });

  describe("and the edit lands after the pass's last look", () => {
    /**
     * `latest` is called after every await, and the last one is still one
     * microtask short of the caller writing the result back. `enqueue` writes
     * the queue synchronously, so an edit made in that gap is present when the
     * result is written and absent from the result — assigning deletes it.
     */
    it("keeps an entry the pass never saw", () => {
      const settled = entry({ idempotencyKey: "key-1" });
      const successor = entry({ idempotencyKey: "key-2" });

      // The pass accepted key-1 and returned an empty queue; key-2 arrived
      // afterwards and exists only in the live queue.
      const merged = mergePassResult([], ["key-1"], [successor]);

      expect(merged).toEqual([successor]);
      expect(merged).not.toContainEqual(settled);
    });

    it("does not resurrect an entry the pass settled", () => {
      const settled = entry({ idempotencyKey: "key-1" });

      // The live queue still shows it only because the writer that produced it
      // read the queue before the acceptance landed. The pass decided it.
      expect(mergePassResult([], ["key-1"], [settled])).toEqual([]);
    });

    it("prefers the pass's own copy of an entry it decided", () => {
      // Re-presented: same entry, new key, and the pass's version is the one
      // carrying the revision the server just reported.
      const represented = entry({ idempotencyKey: "key-9", observedRevision: 11 });
      const stale = entry({ idempotencyKey: "key-9", observedRevision: 4 });

      expect(mergePassResult([represented], ["key-1"], [stale])).toEqual([represented]);
    });

    it("is the identity when nothing moved underneath it", () => {
      const parked = entry({ sendState: "conflicted" });

      expect(mergePassResult([parked], ["key-1"], [parked])).toEqual([parked]);
    });
  });

  it("keeps its own view when the caller can no longer vouch for the device's", async () => {
    // `latest` returning undefined is the caller saying the queue on the device
    // is no longer the one this pass started under — another identity has
    // signed in. Adopting it would send one account's work under another's.
    const rec = recorder();
    const port: DrainPort = { ...rec.port, latest: () => undefined };

    const result = await drainQueue([entry()], port);

    expect(rec.sent.map((call) => call.idempotencyKey)).toEqual(["key-1"]);
    expect(result.queue).toHaveLength(0);
    expect(result.settled).toBe(1);
  });
});

describe("006-FR-001 / 006-FR-003 the request carries the intended net effect", () => {
  it("sends an explicit null to clear a project, which is a supported outcome", () => {
    const payload = buildUpdatePayload(entry({ value: { projectId: null, tagIds: undefined } }));

    expect(payload).toEqual({ expected_revision: 4, project_id: null });
    expect("tag_ids" in payload).toBe(false);
  });

  it("omits a field the change never touched, so `undefined` is not sent as a clear", () => {
    const payload = buildUpdatePayload(
      entry({ value: { projectId: undefined, tagIds: ["tag-a", "tag-b"] } }),
    );

    expect(payload).toEqual({ expected_revision: 4, tag_ids: ["tag-a", "tag-b"] });
    expect("project_id" in payload).toBe(false);
  });

  it("006-FR-002 attaches Tags as the whole intended set, never as a delta", () => {
    const attached = buildUpdatePayload(
      entry({ value: { projectId: undefined, tagIds: ["tag-home", "tag-deep"] } }),
    );
    // Detaching one Tag is the same shape: the set that should remain.
    const detached = buildUpdatePayload(
      entry({ value: { projectId: undefined, tagIds: ["tag-home"] } }),
    );

    expect(attached.tag_ids).toEqual(["tag-home", "tag-deep"]);
    expect(detached.tag_ids).toEqual(["tag-home"]);
  });

  it("006-FR-002 shows a detach as made, leaving the other Tag attached", () => {
    const shown = effectiveClassification(
      { projectId: "proj-inbox", tagIds: ["tag-home", "tag-deep"] },
      entry({ value: { projectId: undefined, tagIds: ["tag-home"] } }),
    );

    expect(shown.tagIds).toEqual(["tag-home"]);
    expect(shown.projectId).toBe("proj-inbox");
  });

  it("006-SC-002 sends exactly the entry's net effect and nothing else", () => {
    // The client half of "the server holds exactly what the phone sent". The
    // server half is asserted for real in mobile/integration/run.ts, which the
    // coverage script cannot see because its path carries no `test` — so the
    // id is named here too rather than silently going untraced.
    //
    // `extra="forbid"` on the backend models means a stray key is a 422, and a
    // *missing* key is worse: it reads as "leave this field alone".
    const payload = buildUpdatePayload(
      entry({ value: { projectId: "proj-q3", tagIds: ["tag-home"] } }),
    );

    expect(Object.keys(payload).sort()).toEqual(["expected_revision", "project_id", "tag_ids"]);
    expect(payload).toEqual({
      expected_revision: 4,
      project_id: "proj-q3",
      tag_ids: ["tag-home"],
    });
  });

  it("006-SC-002 copies the Tag set, so a later edit cannot mutate a request in flight", () => {
    const tagIds = ["tag-home"];
    const payload = buildUpdatePayload(entry({ value: { projectId: undefined, tagIds } }));

    tagIds.push("tag-deep");

    expect(payload.tag_ids).toEqual(["tag-home"]);
  });
});

describe("006-FR-017 the idempotency 409 is broken out of its loop", () => {
  const rejection = apiError(409, { resource: "Idempotency-Key", id: "key-1" });

  it("returns the entry to `queued` under a NEW key rather than replaying the rejected one", () => {
    const sending = entry({ sendState: "sending" });
    const rec = recorder();

    const resolution = resolveSendRejection({
      queue: [sending],
      entry: sending,
      error: rejection,
      mintKey: rec.port.mintKey,
    });

    expect(resolution.queue[0].sendState).toBe("queued");
    expect(resolution.queue[0].idempotencyKey).not.toBe("key-1");
  });

  it("so the next attempt is a different request — the same one 409s forever", async () => {
    let attempts = 0;
    const rec = recorder({
      send: async ({ idempotencyKey }) => {
        attempts += 1;
        if (idempotencyKey === "key-1") {
          throw rejection;
        }
        return { revision: 9, projectId: "proj-q3", tagIds: ["tag-calls"] };
      },
    });

    const first = await drainQueue([entry()], rec.port);
    expect(first.queue[0].idempotencyKey).not.toBe("key-1");

    const second = await drainQueue(first.queue, rec.port);
    expect(second.queue).toHaveLength(0);
    expect(attempts).toBe(2);
  });

  it("006-FR-012 surfaces it with the correlation id, because it is a client bug", () => {
    const sending = entry({ sendState: "sending" });
    const rec = recorder();

    const resolution = resolveSendRejection({
      queue: [sending],
      entry: sending,
      error: rejection,
      mintKey: rec.port.mintKey,
    });

    expect(resolution.decision?.surfaceToPerson).toBe(true);
    expect(resolution.decision?.correlationId).toBe("ref-1");
  });

  it("never asks a person about it — a reused key is not a disagreement", () => {
    const sending = entry({ sendState: "sending" });
    const rec = recorder();

    const resolution = resolveSendRejection({
      queue: [sending],
      entry: sending,
      error: rejection,
      mintKey: rec.port.mintKey,
    });

    expect(selectPendingConflict(resolution.queue)).toBeUndefined();
  });
});

describe("006-FR-008 a stale revision is the person's decision and nobody else's", () => {
  const staleRevision = apiError(409, { resource: "Task", id: "task-1" });

  it("re-reads before prompting, so `already applied` can be reached at all", () => {
    expect(shouldRereadAfterRejection(staleRevision)).toBe(true);
    expect(shouldRereadAfterRejection(apiError(500))).toBe(false);
  });

  it("parks the entry `conflicted` and stops the pass", async () => {
    const rec = recorder({
      send: async () => {
        throw staleRevision;
      },
      reread: async () => ({ revision: 11, projectId: "proj-archive", tagIds: [] }),
    });

    const result = await drainQueue([entry()], rec.port);

    expect(result.queue[0].sendState).toBe("conflicted");
    expect(result.stoppedBecause).toBe("conflict");
  });

  it("names one conflict at a time for the sheet, oldest first", () => {
    const queue = [
      entry({ taskId: "task-2", idempotencyKey: "key-2", sendState: "conflicted", firstQueuedAt: iso(NOW - MINUTE) }),
      entry({ sendState: "conflicted" }),
    ];

    const pending = selectPendingConflict(queue);

    expect(pending?.entry.taskId).toBe("task-1");
    expect(pending?.index).toBe(1);
    expect(pending?.total).toBe(2);
  });

  it("006-SC-005 resolves nothing on its own: neither choice is taken for the person", async () => {
    const rec = recorder({
      send: async () => {
        throw staleRevision;
      },
      reread: async () => ({ revision: 11, projectId: "proj-archive", tagIds: [] }),
    });

    const result = await drainQueue([entry()], rec.port);

    expect(result.queue).toHaveLength(1);
    expect(result.queue[0].value).toEqual({ projectId: "proj-q3", tagIds: ["tag-calls"] });
  });

  it("keep-mine re-queues against the current revision with a new key", () => {
    const conflicted = entry({ sendState: "conflicted" });

    const queue = resolveConflictKeepMine([conflicted], conflicted, 11, recorder().port.mintKey);

    expect(queue[0].sendState).toBe("queued");
    expect(queue[0].observedRevision).toBe(11);
    expect(queue[0].idempotencyKey).not.toBe("key-1");
  });

  it("keep-mine does not refresh lastEditedAt, or a retry loop outlives FR-018", () => {
    const conflicted = entry({ sendState: "conflicted" });

    const queue = resolveConflictKeepMine([conflicted], conflicted, 11, recorder().port.mintKey);

    expect(queue[0].lastEditedAt).toBe(conflicted.lastEditedAt);
  });

  it("discard-mine drops the entry and leaves nothing of theirs pending", () => {
    const conflicted = entry({ sendState: "conflicted" });

    expect(resolveConflictDiscardMine([conflicted], conflicted, 11)).toHaveLength(0);
  });

  it("006-SC-005 exception: no prompt when the server already holds what was intended", async () => {
    const rec = recorder({
      send: async () => {
        throw staleRevision;
      },
      // Somebody else made the same change.
      reread: async () => ({ revision: 11, projectId: "proj-q3", tagIds: ["tag-calls"] }),
    });

    const result = await drainQueue([entry()], rec.port);

    expect(result.queue).toHaveLength(0);
    expect(result.lastSyncedAt).toBe(iso(NOW));
    expect(selectPendingConflict(result.queue)).toBeUndefined();
  });
});

describe("006-SC-003 a server that cannot be reached loses nothing", () => {
  it("keeps the entry queued under the same key — the retry must be a replay", async () => {
    const rec = recorder({
      send: async () => {
        // What `fetch` throws with no connection: no status at all.
        throw new TypeError("Network request failed");
      },
    });

    const result = await drainQueue([entry()], rec.port);

    expect(result.queue).toHaveLength(1);
    expect(result.queue[0].sendState).toBe("queued");
    expect(result.queue[0].idempotencyKey).toBe("key-1");
    expect(result.stoppedBecause).toBe("retry-later");
    expect(result.lastSyncedAt).toBeUndefined();
  });
});

describe("006-FR-017 past the replay window the drain looks before it leaps", () => {
  const aged = () =>
    entry({ firstSentAt: iso(NOW - SERVER_REPLAY_WINDOW_MS - MINUTE), sendState: "queued" });

  it("plans a re-read rather than a blind retry", () => {
    const step = planDrainStep([aged()], NOW);

    expect(step.kind).toBe("reread");
  });

  it("still sends directly while the key is inside the window", () => {
    const step = planDrainStep([entry({ firstSentAt: iso(NOW - SERVER_REPLAY_WINDOW_MS + MINUTE) })], NOW);

    expect(step.kind).toBe("send");
  });

  it("drops the entry with no prompt when the server already holds the intended value", async () => {
    const rec = recorder({
      reread: async () => ({ revision: 12, projectId: "proj-q3", tagIds: ["tag-calls"] }),
    });

    const result = await drainQueue([aged()], rec.port);

    expect(rec.reread).toEqual(["task-1"]);
    expect(rec.sent).toHaveLength(0);
    expect(result.queue).toHaveLength(0);
    expect(result.lastSyncedAt).toBe(iso(NOW));
  });

  it("re-presents against the current revision with a new key and a refreshed original", () => {
    // Only the project is being changed, and the project is exactly where the
    // phone left it — so nothing of anybody else's is at stake and this is a
    // plain resend, not a disagreement. Somebody did move the Tags, which is
    // why the revision advanced; the refreshed original picks that up, so a
    // later prompt diffs against what the server holds rather than a value up
    // to 30 days stale.
    const sending = {
      ...aged(),
      sendState: "sending" as const,
      value: { projectId: "proj-q3", tagIds: undefined },
    };
    const server: ServerTaskState = { revision: 12, projectId: null, tagIds: ["tag-home"] };

    const resolution = resolveRereadOutcome({
      queue: [sending],
      entry: sending,
      task: server,
      mintKey: recorder().port.mintKey,
    });

    const next = resolution.queue[0];
    expect(next.sendState).toBe("queued");
    expect(next.observedRevision).toBe(12);
    expect(next.originalValue).toEqual({ projectId: null, tagIds: ["tag-home"] });
    expect(next.idempotencyKey).not.toBe("key-1");
    // A fresh key gets its own replay window, or the very next step re-reads again.
    expect(next.firstSentAt).toBeUndefined();
  });

  it("then sends it, carrying the revision the re-read observed", async () => {
    const rec = recorder({
      // The classification is untouched — somebody edited the title. The
      // revision moved, nobody else's classification did, so the entry is
      // simply re-aimed and sent.
      reread: async () => ({ revision: 12, projectId: null, tagIds: [] }),
      send: async () => ({ revision: 13, projectId: "proj-q3", tagIds: ["tag-calls"] }),
    });

    const result = await drainQueue([aged()], rec.port);

    expect(rec.sent).toHaveLength(1);
    expect(rec.sent[0].payload).toEqual({
      expected_revision: 12,
      project_id: "proj-q3",
      tag_ids: ["tag-calls"],
    });
    expect(rec.sent[0].idempotencyKey).not.toBe("key-1");
    expect(result.queue).toHaveLength(0);
  });

  it("006-FR-008 asks instead, when the re-read finds somebody else's value", async () => {
    // The branch that did not exist. Re-presenting rebases `observedRevision`
    // onto the revision just read, so the send that follows CANNOT 409 — and
    // the 409 is the only thing that ever opens M-04. An entry attempted once,
    // left more than 24h, on a task somebody else reclassified meanwhile,
    // therefore overwrote their work in silence. FR-008 says the person
    // decides; SC-005 says zero classifications are overwritten silently.
    const rec = recorder({
      reread: async () => ({ revision: 12, projectId: "proj-inbox", tagIds: ["tag-home"] }),
      send: async () => ({ revision: 13, projectId: "proj-q3", tagIds: ["tag-calls"] }),
    });

    const result = await drainQueue([aged()], rec.port);

    // Nothing went out. The pass stops and hands the question over.
    expect(rec.sent).toHaveLength(0);
    expect(result.stoppedBecause).toBe("conflict");

    const parked = result.queue[0];
    expect(parked.sendState).toBe("conflicted");
    expect(parked.conflictReason).toBe("stale-revision");
    // Both halves of M-04's third row, from the read that found the divergence.
    expect(parked.conflictServerRevision).toBe(12);
    expect(parked.conflictServerValue).toEqual({
      projectId: "proj-inbox",
      tagIds: ["tag-home"],
    });
    // NOT refreshed. It is what the phone showed, and M-04's first row says so
    // in those words; overwriting it with the server's value would leave the
    // person choosing between two copies of their opponent's answer.
    expect(parked.originalValue).toEqual({ projectId: null, tagIds: [] });
  });

  it("006-FR-008 resends without asking when the edit somebody else made cannot collide", async () => {
    // The scope rule, stated as behaviour: this entry sets only the project,
    // and only the Tags moved. Prompting would ask a person to arbitrate a
    // disagreement that does not exist, so it sends.
    const projectOnly = entry({
      firstSentAt: iso(NOW - SERVER_REPLAY_WINDOW_MS - MINUTE),
      sendState: "queued",
      value: { projectId: "proj-q3", tagIds: undefined },
    });
    const rec = recorder({
      reread: async () => ({ revision: 12, projectId: null, tagIds: ["tag-home"] }),
      send: async () => ({ revision: 13, projectId: "proj-q3", tagIds: ["tag-home"] }),
    });

    const result = await drainQueue([projectOnly], rec.port);

    expect(rec.sent).toHaveLength(1);
    expect(rec.sent[0].payload).toEqual({ expected_revision: 12, project_id: "proj-q3" });
    expect(result.queue).toHaveLength(0);
  });

  it("keeps the entry when the re-read itself fails — nothing was sent", async () => {
    const rec = recorder({
      reread: async () => {
        throw new TypeError("Network request failed");
      },
    });

    const result = await drainQueue([aged()], rec.port);

    expect(result.queue).toHaveLength(1);
    expect(result.queue[0].sendState).toBe("queued");
    expect(result.queue[0].idempotencyKey).toBe("key-1");
  });
});

describe("006-FR-018 the entry rule and the key rule must not overlap (invariant 8a)", () => {
  it("moves an aged entry to `expired` and keeps its payload for the notice", () => {
    const old = entry({ lastEditedAt: iso(NOW - RETENTION_MS - MINUTE) });

    const hydrated = hydrateQueue([old], NOW);

    expect(hydrated.queue[0].sendState).toBe("expired");
    expect(hydrated.queue[0].value).toEqual({ projectId: "proj-q3", tagIds: ["tag-calls"] });
    expect(hydrated.droppedCount).toBe(1);
  });

  it("never sends an expired entry — it is a notice awaiting dismissal", () => {
    const old = entry({ lastEditedAt: iso(NOW - RETENTION_MS - MINUTE) });

    expect(planDrainStep(hydrateQueue([old], NOW).queue, NOW).kind).toBe("idle");
  });

  it("keeps the active identity's aged entries on the device while deleting a foreign key", async () => {
    const mine = entry({ lastEditedAt: iso(NOW - RETENTION_MS - MINUTE) });
    const theirs = entry({
      accountId: OTHER_ACCOUNT,
      serverUrl: OTHER_SERVER,
      lastEditedAt: iso(NOW - RETENTION_MS - MINUTE),
    });
    await AsyncStorage.setItem(queueKey(SERVER, ACCOUNT), JSON.stringify([mine]));
    await AsyncStorage.setItem(queueKey(OTHER_SERVER, OTHER_ACCOUNT), JSON.stringify([theirs]));

    const result = await sweepAllIdentities({
      activeKey: sweepActiveKey(IDENTITY),
      now: NOW,
      isExpired: (timestamp, now) => isBeyondRetention(timestamp, now),
    });

    expect(result.deletedKeys).toEqual([queueKey(OTHER_SERVER, OTHER_ACCOUNT)]);
    expect(result.activeEntriesExpired).toBe(1);

    // The payload survives the sweep and is only then moved to `expired` —
    // FR-018's "retains the payload until dismissed", end to end.
    const loaded = await loadQueue(IDENTITY, { resetInterrupted });
    expect(hydrateQueue(loaded, NOW).queue[0].value).toEqual({
      projectId: "proj-q3",
      tagIds: ["tag-calls"],
    });
  });

  it("would destroy them if the sweep were handed no active key — hence sweepActiveKey", async () => {
    const mine = entry({ lastEditedAt: iso(NOW - RETENTION_MS - MINUTE) });
    await AsyncStorage.setItem(queueKey(SERVER, ACCOUNT), JSON.stringify([mine]));

    // The wrong wiring, asserted so the guard is a regression test rather than
    // a comment: with no active key every key is foreign, and the *deleting*
    // rule reaches the active identity's own unsent work.
    await sweepAllIdentities({
      activeKey: null,
      now: NOW,
      isExpired: (timestamp, now) => isBeyondRetention(timestamp, now),
    });
    expect(await loadQueue(IDENTITY, { resetInterrupted })).toHaveLength(0);

    expect(sweepActiveKey(IDENTITY)).toBe(queueKey(SERVER, ACCOUNT));
    expect(sweepActiveKey(null)).toBeNull();
  });
});

describe("006-SC-003 an expired change is named, not counted", () => {
  it("says which field was dropped and what the row shows now", () => {
    const old = entry({
      value: { projectId: "proj-q3", tagIds: undefined },
      lastEditedAt: iso(NOW - RETENTION_MS - MINUTE),
    });
    const [expired] = hydrateQueue([old], NOW).queue;

    const notice = describeExpiredChange(expired, { projectId: "proj-onboarding", tagIds: [] });

    expect(notice?.fields).toEqual([
      { field: "project", dropped: "proj-q3", revertedTo: "proj-onboarding" },
    ]);
    expect(notice?.lastEditedAt).toBe(old.lastEditedAt);
  });

  it("names Tags as a set, and both fields when the entry touched both", () => {
    const old = entry({
      value: { projectId: null, tagIds: ["tag-calls"] },
      lastEditedAt: iso(NOW - RETENTION_MS - MINUTE),
    });
    const [expired] = hydrateQueue([old], NOW).queue;

    const notice = describeExpiredChange(expired, { projectId: "proj-a", tagIds: ["tag-home"] });

    expect(notice?.fields).toEqual([
      { field: "project", dropped: null, revertedTo: "proj-a" },
      { field: "tags", dropped: ["tag-calls"], revertedTo: ["tag-home"] },
    ]);
  });

  it("falls back to what the device last displayed when the server value is unknown", () => {
    const old = entry({
      originalValue: { projectId: "proj-inbox", tagIds: [] },
      value: { projectId: "proj-q3", tagIds: undefined },
      lastEditedAt: iso(NOW - RETENTION_MS - MINUTE),
    });
    const [expired] = hydrateQueue([old], NOW).queue;

    expect(describeExpiredChange(expired)?.fields).toEqual([
      { field: "project", dropped: "proj-q3", revertedTo: "proj-inbox" },
    ]);
  });

  it("says nothing about an entry that has not expired", () => {
    expect(describeExpiredChange(entry())).toBeNull();
  });

  it("counts the account-level total for the dismiss-once notice", () => {
    const old = { lastEditedAt: iso(NOW - RETENTION_MS - MINUTE) };
    const hydrated = hydrateQueue(
      [entry(old), entry({ ...old, taskId: "task-2", idempotencyKey: "key-2" }), entry({ taskId: "task-3", idempotencyKey: "key-3" })],
      NOW,
    );

    expect(countExpired(hydrated.queue)).toBe(2);
  });
});

describe("006-FR-007 a queued change is shown as made, with no per-change marker", () => {
  it("shows the queued value over the server's", () => {
    const shown = effectiveClassification(
      { projectId: "proj-inbox", tagIds: [] },
      entry({ value: { projectId: "proj-q3", tagIds: ["tag-calls"] } }),
    );

    expect(shown).toEqual({ projectId: "proj-q3", tagIds: ["tag-calls"] });
  });

  it("leaves a field the change never touched showing the server's value", () => {
    const shown = effectiveClassification(
      { projectId: "proj-inbox", tagIds: ["tag-home"] },
      entry({ value: { projectId: null, tagIds: undefined } }),
    );

    expect(shown).toEqual({ projectId: null, tagIds: ["tag-home"] });
  });

  it("006-FR-018 shows the server's value again once the entry has expired", () => {
    const shown = effectiveClassification(
      { projectId: "proj-onboarding", tagIds: [] },
      entry({ sendState: "expired" }),
    );

    expect(shown).toEqual({ projectId: "proj-onboarding", tagIds: [] });
  });

  it("is the server's own value when nothing is queued", () => {
    expect(effectiveClassification({ projectId: null, tagIds: ["tag-home"] }, undefined)).toEqual({
      projectId: null,
      tagIds: ["tag-home"],
    });
  });
});
