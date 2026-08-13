/**
 * The classification drain, as the app actually runs it.
 *
 * `drain.test.ts` covers everything the drain *decides* — those are pure
 * functions over a queue and a port, and they are well covered there. What it
 * cannot reach is the hook: the cold read, the two triggers, the single flight
 * between them, and the identity and rollout rules that live in render and in
 * effects. The header of `useClassificationQueue.ts` says that gap is forced
 * ("`mobile/` cannot render a component in a test"). It no longer is —
 * `src/test/fakeBackend.ts` and `@testing-library/react-native` landed on main —
 * so this file closes it, and nothing below duplicates an assertion made there.
 *
 * Three things are real here that are stubbed in `drain.test.ts`:
 *
 * - the **api client**, so an `Idempotency-Key` header, a 409 body's
 *   `detail.resource` and an `X-Correlation-ID` header are asserted on the wire
 *   rather than on a duck-typed throw;
 * - **AsyncStorage**, so "the payload is retained" is a fact about the device
 *   and not about a return value;
 * - the **hook's own lifecycle**, so "a cold start finishes the send" is
 *   asserted end to end instead of inferred from two functions that each pass.
 *
 * Only one device boundary is stood in for: `AppState`, which the RN jest
 * preset already replaces with a mock that never fires. The stand-in below
 * records the handler the hook registered and lets a test deliver the
 * foreground event the device would. Every assertion is then an outcome — what
 * reached the server, what the hook exposes, what is on the device — never that
 * a mock was called.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { AppState, type AppStateStatus } from "react-native";

import { createApiClient } from "@/api/client";
import { uuidNumber } from "@/test/expoCryptoMock";
import {
  FakeHttpError,
  installFakeBackend,
  makeTask,
  type FakeBackend,
  type RouteHandler,
} from "@/test/fakeBackend";

import type { PendingClassificationChange } from "../classificationTypes";
import { SERVER_TIME_KEY } from "../classificationQueue.storage";
import { queueKey, type ClassificationIdentity } from "../storageKeys";
import {
  useClassificationQueue,
  type ClassificationApiPort,
  type ClassificationQueue,
} from "../useClassificationQueue";

const SERVER = "https://api.example.test/api";
const ACCOUNT = "acc-1";
const OTHER_ACCOUNT = "acc-2";
const IDENTITY: ClassificationIdentity = { serverUrl: SERVER, accountId: ACCOUNT };
const OTHER_IDENTITY: ClassificationIdentity = { serverUrl: SERVER, accountId: OTHER_ACCOUNT };

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** The real client, over the fake backend — the same narrow port the task
 *  screen builds in `src/app/task/[id].tsx`. */
const client = createApiClient({ getBaseUrl: () => SERVER });
const api: ClassificationApiPort = {
  getTask: (taskId, signal) => client.getTask(taskId, signal),
  updateTask: (taskId, payload, idempotencyKey) =>
    client.updateTask(taskId, payload, idempotencyKey),
};

// ------------------------------------------------- the foreground trigger

/**
 * `AppState` is a device boundary, and the React Native jest preset already
 * replaces it with a mock whose `addEventListener` records nothing and never
 * fires. This stand-in keeps the handler the hook registered so a test can
 * deliver the event iOS would, and honours `remove()` so an unmounted hook
 * stops hearing it.
 */
const appStateHandlers = new Set<(state: AppStateStatus) => void>();

function emitAppState(state: AppStateStatus): void {
  for (const handler of [...appStateHandlers]) {
    handler(state);
  }
}

/** The app comes back to the foreground. Trigger 1 of 2. */
async function foreground(): Promise<void> {
  await act(async () => {
    emitAppState("active");
  });
}

// --------------------------------------------------------------- fixtures

function ago(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

function queued(overrides: Partial<PendingClassificationChange> = {}): PendingClassificationChange {
  return {
    taskId: "task-1",
    accountId: ACCOUNT,
    serverUrl: SERVER,
    value: { projectId: "proj-q3", tagIds: ["tag-calls"] },
    observedRevision: 4,
    originalValue: { projectId: null, tagIds: [] },
    firstQueuedAt: ago(10 * MINUTE),
    lastEditedAt: ago(10 * MINUTE),
    idempotencyKey: "key-1",
    sendState: "queued",
    ...overrides,
  };
}

/** What the server returns once it has applied the entry above. */
function accepted() {
  return makeTask({ id: "task-1", project_id: "proj-q3", tag_ids: ["tag-calls"], revision: 9 });
}

/** A `fetch` that never reached anyone: no status, so it is retried unchanged. */
function unreachable(): never {
  throw new TypeError("Network request failed");
}

async function seed(
  identity: ClassificationIdentity,
  entries: PendingClassificationChange[],
): Promise<void> {
  await AsyncStorage.setItem(
    queueKey(identity.serverUrl, identity.accountId),
    JSON.stringify(entries),
  );
}

/** What is on the device for one identity, right now. */
async function onDevice(
  identity: ClassificationIdentity,
): Promise<PendingClassificationChange[] | null> {
  const raw = await AsyncStorage.getItem(queueKey(identity.serverUrl, identity.accountId));
  return raw === null ? null : (JSON.parse(raw) as PendingClassificationChange[]);
}

let backend: FakeBackend;

function install(routes: Record<string, RouteHandler>): FakeBackend {
  backend = installFakeBackend(routes);
  return backend;
}

/** Every request the drain made, in order, as `METHOD /path`. */
function traffic(): string[] {
  return backend.calls.map((call) => `${call.method} ${call.path}`);
}

function keysSent(): (string | undefined)[] {
  return backend.callsTo("PATCH", "/tasks/task-1").map((call) => call.headers["Idempotency-Key"]);
}

// ----------------------------------------------------------- the harness

interface QueueProps {
  identity: ClassificationIdentity | null;
  enabled: boolean;
}

interface QueueView {
  result: { current: ClassificationQueue };
  rerender: (props: QueueProps) => Promise<void>;
  /** One entry per time the hook told the caller a pass reached the server —
   *  the screen's cue to refetch (SC-004). */
  refetches: string[];
}

async function renderQueue(props: Partial<QueueProps> = {}): Promise<QueueView> {
  const refetches: string[] = [];
  const view = await renderHook(
    ({ identity, enabled }: QueueProps) =>
      useClassificationQueue({
        identity,
        api,
        enabled,
        onSynced: () => refetches.push("refetch"),
      }),
    { initialProps: { identity: IDENTITY, enabled: true, ...props } },
  );
  return { result: view.result, rerender: view.rerender, refetches };
}

/** The cold read has run: the screen may enqueue from here on. */
async function coldReadDone(view: QueueView): Promise<void> {
  await waitFor(() => expect(view.result.current.ready).toBe(true));
}

beforeEach(async () => {
  await AsyncStorage.clear();
  appStateHandlers.clear();
  jest.spyOn(AppState, "addEventListener").mockImplementation((type, handler) => {
    if (type === "change") {
      appStateHandlers.add(handler);
    }
    return {
      remove: () => {
        appStateHandlers.delete(handler);
      },
    };
  });
});

afterEach(() => {
  jest.restoreAllMocks();
  backend?.restore();
});

describe("006-FR-021 a cold start finishes the send the app was killed in the middle of", () => {
  it("sends the stranded entry under the key it was stranded with, and clears the device", async () => {
    // Force-quit mid-send: `sending` reached the device, the response never did.
    await seed(IDENTITY, [queued({ sendState: "sending", firstSentAt: ago(MINUTE) })]);
    install({ "PATCH /tasks/task-1": () => accepted() });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    const sent = backend.callsTo("PATCH", "/tasks/task-1");
    expect(sent).toHaveLength(1);
    // The same key, so a send that did land replays the stored result instead
    // of applying twice (invariant 6).
    expect(sent[0].headers["Idempotency-Key"]).toBe("key-1");
    expect(sent[0].body).toEqual({
      expected_revision: 4,
      project_id: "proj-q3",
      tag_ids: ["tag-calls"],
    });
    // Nothing is left to send, and nothing is left on the device to re-send.
    expect(await onDevice(IDENTITY)).toBeNull();
    expect(view.result.current.lastSyncedAt).not.toBeNull();
  });

  it("leaves it stranded forever without that reset — the drain skips `sending`", async () => {
    await seed(IDENTITY, [queued({ sendState: "sending", firstSentAt: ago(MINUTE) })]);
    // The route exists, so nothing but invariant 5 can stop the send.
    install({ "PATCH /tasks/task-1": () => accepted() });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    // The evidence that the reset ran on the way in: the entry was picked up at
    // all. Left in `sending`, it is never sent, never conflicts, never errors,
    // and its only terminal outcome is the 30-day drop.
    expect(traffic()).toEqual(["PATCH /tasks/task-1"]);
  });
});

describe("006-FR-017 two triggers, one flight", () => {
  it("sends once when a second trigger arrives while the first send is in flight", async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await seed(IDENTITY, [queued()]);
    install({
      "PATCH /tasks/task-1": async () => {
        await held;
        return accepted();
      },
    });

    const view = await renderQueue();
    // The cold read's drain has the entry in flight and unanswered.
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1));

    // Both remaining triggers fire before the first answer arrives — the
    // ordinary case, since a foreground and a settled request routinely
    // coincide.
    await foreground();
    await act(async () => {
      await view.result.current.drain();
    });

    await act(async () => {
      release();
    });
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1);
    expect(view.refetches).toEqual(["refetch"]);
  });

  it("retries on the next foreground, under the same key, when nobody answered", async () => {
    await seed(IDENTITY, [queued()]);
    install({ "PATCH /tasks/task-1": unreachable });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1));
    // Nothing was lost and nothing was decided: it waits, unchanged.
    expect(view.result.current.queue[0].sendState).toBe("queued");
    expect(view.result.current.queue[0].idempotencyKey).toBe("key-1");

    // Backgrounding is not a trigger; only coming back to the foreground is.
    await act(async () => {
      emitAppState("background");
    });
    expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1);

    backend.route("PATCH /tasks/task-1", () => accepted());
    await foreground();
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    // The retry is a replay of the same attempt, which is what makes it
    // at-most-once inside the server's window.
    expect(keysSent()).toEqual(["key-1", "key-1"]);
  });

  it("006-SC-004 tells the caller to refetch only once the server has answered", async () => {
    await seed(IDENTITY, [queued()]);
    install({ "PATCH /tasks/task-1": unreachable });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1));

    // A pass that reached nobody advances nothing and asks for nothing.
    expect(view.result.current.lastSyncedAt).toBeNull();
    expect(view.refetches).toEqual([]);

    backend.route("PATCH /tasks/task-1", () => accepted());
    await foreground();
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    expect(view.result.current.lastSyncedAt).not.toBeNull();
    expect(view.refetches).toEqual(["refetch"]);
  });
});

describe("006-FR-010 an edit made while a send is in flight is not written over (invariant 5b)", () => {
  /** A request that never answers until the test says so. */
  function heldSend(): { held: Promise<void>; release: () => void } {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    return { held, release };
  }

  /** The person attaches a second Tag while the first request is still out.
   *  `coalesce` makes this a successor entry, because touching the entry in
   *  flight would let its acceptance delete an edit that was never sent. */
  async function attachSecondTag(view: QueueView): Promise<void> {
    await act(async () => {
      await view.result.current.enqueue({
        taskId: "task-1",
        value: { tagIds: ["tag-calls", "tag-home"] },
        observedRevision: 4,
        displayedValue: { projectId: "proj-q3", tagIds: ["tag-calls"] },
      });
    });
  }

  it("sends it after the one in flight, against the revision the server accepted", async () => {
    const first = heldSend();
    await seed(IDENTITY, [queued()]);
    install({
      "PATCH /tasks/task-1": async (call) => {
        if (call.headers["Idempotency-Key"] !== "key-1") {
          return makeTask({
            id: "task-1",
            project_id: "proj-q3",
            tag_ids: ["tag-calls", "tag-home"],
            revision: 10,
          });
        }
        await first.held;
        return accepted();
      },
    });

    const view = await renderQueue();
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1));

    await attachSecondTag(view);
    // Two entries for one task, which invariant 1 permits only here: the edit
    // could not touch the one in flight without its acceptance deleting work
    // that was never sent.
    expect(view.result.current.queue.map((entry) => entry.value.tagIds)).toEqual([
      ["tag-calls"],
      ["tag-calls", "tag-home"],
    ]);

    await act(async () => {
      first.release();
    });
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    expect(keysSent()).toEqual(["key-1", uuidNumber(1)]);
    // 9 is the revision the first send returned. The successor is re-based onto
    // it, so the person's own second edit does not arrive as a stale revision
    // and put a conflict of the app's making in front of them.
    expect(backend.callsTo("PATCH", "/tasks/task-1")[1].body).toEqual({
      expected_revision: 9,
      tag_ids: ["tag-calls", "tag-home"],
    });
    expect(await onDevice(IDENTITY)).toBeNull();
  });

  it("006-FR-009 keeps it on the device when the pass cannot send it yet", async () => {
    const first = heldSend();
    await seed(IDENTITY, [queued()]);
    install({
      "PATCH /tasks/task-1": async (call) => {
        if (call.headers["Idempotency-Key"] !== "key-1") {
          return unreachable();
        }
        await first.held;
        return accepted();
      },
    });

    const view = await renderQueue();
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1));
    await attachSecondTag(view);

    await act(async () => {
      first.release();
    });
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(2));

    // The pass settled the entry it knew about and kept the one it did not.
    // Deleting it here is silent: no request carried it, and FR-007 means no
    // surface ever showed it as pending, so the Tag would simply appear to
    // detach itself some time later.
    expect(view.result.current.pendingFor("task-1")).toMatchObject({
      sendState: "queued",
      observedRevision: 9,
      value: { tagIds: ["tag-calls", "tag-home"] },
    });
    expect(await onDevice(IDENTITY)).toMatchObject([
      { idempotencyKey: uuidNumber(1), value: { tagIds: ["tag-calls", "tag-home"] } },
    ]);
  });

  /**
   * The same edit, but the two writers reach the device out of order.
   *
   * `enqueue` and the drain both persist a *snapshot* they captured before
   * their own await, and nothing serialises them. AsyncStorage is a bridge to
   * native, so its writes settle in whatever order the platform finishes them,
   * and the loser overwrites the winner wholesale. `latest()` repairs the pass's
   * in-memory view after every await; it does nothing for what has already been
   * handed to storage.
   *
   * The visible damage is on the next launch, not this one: invariant 5c revives
   * the resurrected `sending` entry, so a change the server already applied is
   * replayed, and the successor goes back out carrying the revision it was
   * queued with rather than the one the server accepted — a conflict of the
   * app's own making, put in front of a person who did nothing wrong.
   */
  it("006-FR-010 leaves nothing behind when the two writers settle out of order", async () => {
    const first = heldSend();
    await seed(IDENTITY, [queued()]);
    install({
      "PATCH /tasks/task-1": async (call) => {
        if (call.headers["Idempotency-Key"] !== "key-1") {
          return makeTask({
            id: "task-1",
            project_id: "proj-q3",
            tag_ids: ["tag-calls", "tag-home"],
            revision: 10,
          });
        }
        await first.held;
        return accepted();
      },
    });

    const view = await renderQueue();
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1));

    // The device boundary, holding the next write back so the edit's snapshot
    // lands after the pass's. Nothing about the ordering is contrived: two
    // unsynchronised writers to one key settle either way round, and this file
    // may not assert on the half that happens to pass.
    const store = AsyncStorage as unknown as Record<string, unknown>;
    const write = store.setItem as (key: string, value: string) => Promise<void>;
    let holdNext = true;
    store.setItem = async (key: string, value: string): Promise<void> => {
      if (holdNext) {
        holdNext = false;
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      return write.call(AsyncStorage, key, value);
    };

    try {
      await act(async () => {
        const edit = view.result.current.enqueue({
          taskId: "task-1",
          value: { tagIds: ["tag-calls", "tag-home"] },
          observedRevision: 4,
          displayedValue: { projectId: "proj-q3", tagIds: ["tag-calls"] },
        });
        first.release();
        await edit;
        await new Promise((resolve) => setTimeout(resolve, 200));
      });
    } finally {
      store.setItem = write;
    }

    // Both changes reached the server, in order, the second re-based onto the
    // revision the first returned.
    expect(keysSent()).toEqual(["key-1", uuidNumber(1)]);
    expect(view.result.current.queue).toHaveLength(0);
    // So the device must hold nothing. A queue that survives its own completion
    // is re-sent on the next cold start under invariant 5c.
    expect(await onDevice(IDENTITY)).toBeNull();
  });
});

describe("006-FR-008 a task that changed elsewhere becomes the person's decision", () => {
  const revisionConflict = () =>
    new FakeHttpError(
      409,
      // The backend's real 409 body for a stale `expected_revision`. No
      // `reference_id`, so FR-012's id has to come off the header — the path a
      // duck-typed throw cannot exercise.
      {
        message: "Task 'task-1' has newer changes; reload before saving.",
        detail: { resource: "Task", id: "task-1" },
      },
      "corr-42",
    );

  it("006-FR-012 parks it conflicted, with the reason and the correlation id it arrived with", async () => {
    await seed(IDENTITY, [queued()]);
    install({
      "PATCH /tasks/task-1": () => revisionConflict(),
      // Somebody else moved it somewhere this entry did not intend.
      "GET /tasks/task-1": () =>
        makeTask({ id: "task-1", project_id: "proj-archive", tag_ids: [], revision: 11 }),
    });

    const view = await renderQueue();
    await waitFor(() => expect(view.result.current.conflict).toBeDefined());

    const conflict = view.result.current.conflict;
    expect(conflict?.entry.sendState).toBe("conflicted");
    // The reason separates a stale revision from a target deleted elsewhere;
    // the sheet offers different choices for the two.
    expect(conflict?.entry.conflictReason).toBe("stale-revision");
    expect(conflict?.entry.correlationId).toBe("corr-42");
    expect(conflict?.index).toBe(1);
    expect(conflict?.total).toBe(1);

    // The re-read is what makes "already applied" reachable, so it happens
    // before anyone is asked anything.
    expect(traffic()).toEqual(["PATCH /tasks/task-1", "GET /tasks/task-1"]);
    // Nothing was resolved and the footer did not move.
    expect(view.result.current.lastSyncedAt).toBeNull();
    // And it survives the app closing: the sheet returns rather than the
    // question quietly disappearing.
    expect((await onDevice(IDENTITY))?.[0]).toMatchObject({
      sendState: "conflicted",
      conflictReason: "stale-revision",
      value: { projectId: "proj-q3", tagIds: ["tag-calls"] },
    });
  });

  it("006-SC-005 asks rather than deciding when the re-read fails too", async () => {
    await seed(IDENTITY, [queued()]);
    install({
      // Offline again between the two calls — the ordinary way a partial
      // failure happens on a phone.
      "PATCH /tasks/task-1": () => revisionConflict(),
      "GET /tasks/task-1": unreachable,
    });

    const view = await renderQueue();
    await waitFor(() => expect(view.result.current.conflict).toBeDefined());

    // Deciding without the server's value is the unsafe direction, so with no
    // value it asks. Nothing is resolved and nothing is discarded.
    expect(traffic()).toEqual(["PATCH /tasks/task-1", "GET /tasks/task-1"]);
    expect(view.result.current.conflict?.entry.conflictReason).toBe("stale-revision");
    expect(view.result.current.queue[0].value).toEqual({
      projectId: "proj-q3",
      tagIds: ["tag-calls"],
    });
  });

  it("006-SC-005 keep-mine re-sends against the revision the person was shown, under a new key", async () => {
    await seed(IDENTITY, [queued()]);
    install({
      "PATCH /tasks/task-1": () => revisionConflict(),
      "GET /tasks/task-1": () =>
        makeTask({ id: "task-1", project_id: "proj-archive", tag_ids: [], revision: 11 }),
    });

    const view = await renderQueue();
    await waitFor(() => expect(view.result.current.conflict).toBeDefined());

    backend.route("PATCH /tasks/task-1", () => accepted());
    await act(async () => {
      await view.result.current.keepMine(11);
    });
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    const sent = backend.callsTo("PATCH", "/tasks/task-1");
    expect(sent).toHaveLength(2);
    // The resolved payload carries a different `expected_revision`, and the
    // server's request hash covers it — the old key would 409 forever.
    expect(sent[1].body).toMatchObject({ expected_revision: 11 });
    expect(sent[1].headers["Idempotency-Key"]).toBe(uuidNumber(1));
    expect(view.result.current.conflict).toBeUndefined();
  });

  it("006-SC-005 discard-mine drops the entry and sends nothing more", async () => {
    await seed(IDENTITY, [queued()]);
    install({
      "PATCH /tasks/task-1": () => revisionConflict(),
      "GET /tasks/task-1": () =>
        makeTask({ id: "task-1", project_id: "proj-archive", tag_ids: [], revision: 11 }),
    });

    const view = await renderQueue();
    await waitFor(() => expect(view.result.current.conflict).toBeDefined());

    await act(async () => {
      await view.result.current.discardMine(11);
    });

    expect(view.result.current.queue).toHaveLength(0);
    expect(view.result.current.conflict).toBeUndefined();
    expect(await onDevice(IDENTITY)).toBeNull();
    expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1);

    // The sheet is dismissed by the same gesture that answers it, so a second
    // answer can arrive after the question is gone. It must not resurrect the
    // change the person just discarded.
    await act(async () => {
      await view.result.current.keepMine(11);
    });
    expect(view.result.current.queue).toHaveLength(0);
    expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1);
  });
});

describe("006-FR-017 a spent idempotency key is re-minted, never replayed", () => {
  /** The backend's other 409: a stored key arriving with a different request
   *  hash. Only `detail.resource` tells the two apart. */
  const spentKey = () =>
    new FakeHttpError(
      409,
      {
        message: "Idempotency-Key 'key-1' was used for a different request.",
        reference_id: "ref-7",
        detail: { resource: "Idempotency-Key", id: "key-1" },
      },
      "corr-7",
    );

  it("re-queues under a new key instead of asking a person about a client bug", async () => {
    await seed(IDENTITY, [queued()]);
    install({
      "PATCH /tasks/task-1": (call) =>
        call.headers["Idempotency-Key"] === "key-1" ? spentKey() : accepted(),
    });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1));

    const entry = view.result.current.queue[0];
    expect(entry.sendState).toBe("queued");
    expect(entry.idempotencyKey).toBe(uuidNumber(1));
    // A reused key is not a disagreement, so nobody is asked to choose.
    expect(view.result.current.conflict).toBeUndefined();
    // No re-read either: there is nothing about the task to look at.
    expect(traffic()).toEqual(["PATCH /tasks/task-1"]);
  });

  it("so the next trigger sends a different request rather than 409ing forever", async () => {
    await seed(IDENTITY, [queued()]);
    install({
      "PATCH /tasks/task-1": (call) =>
        call.headers["Idempotency-Key"] === "key-1" ? spentKey() : accepted(),
    });

    const view = await renderQueue();
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1));

    await foreground();
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    expect(keysSent()).toEqual(["key-1", uuidNumber(1)]);
    expect(await onDevice(IDENTITY)).toBeNull();
  });
});

describe("006-FR-017 past the replay window the drain looks before it leaps", () => {
  /** First attempted 25 h ago: the server has forgotten the key, so it is no
   *  longer a dedupe token (invariant 10). */
  const aged = () => queued({ firstSentAt: ago(25 * HOUR) });

  it("re-reads first, and drops the entry when the server already holds the value", async () => {
    await seed(IDENTITY, [aged()]);
    install({
      // Somebody else made the same change while this device was away.
      "GET /tasks/task-1": () =>
        makeTask({ id: "task-1", project_id: "proj-q3", tag_ids: ["tag-calls"], revision: 12 }),
    });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    // Nothing was sent blind, and nobody was asked about a disagreement that
    // is not there.
    expect(traffic()).toEqual(["GET /tasks/task-1"]);
    expect(view.result.current.conflict).toBeUndefined();
    expect(view.result.current.lastSyncedAt).not.toBeNull();
    expect(await onDevice(IDENTITY)).toBeNull();
  });

  it("re-presents it against the revision the re-read observed, under a new key", async () => {
    await seed(IDENTITY, [aged()]);
    install({
      // The classification is exactly where the phone left it; the revision
      // moved because somebody edited the title. Nothing of theirs is at stake,
      // so the entry is re-aimed and sent rather than put to the person.
      "GET /tasks/task-1": () =>
        makeTask({ id: "task-1", project_id: null, tag_ids: [], revision: 12 }),
      "PATCH /tasks/task-1": () => accepted(),
    });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    // The order is the whole rule: look, then leap.
    expect(traffic()).toEqual(["GET /tasks/task-1", "PATCH /tasks/task-1"]);
    const sent = backend.callsTo("PATCH", "/tasks/task-1")[0];
    // At-most-once is carried by `expected_revision` out here, not by the key.
    expect(sent.body).toEqual({
      expected_revision: 12,
      project_id: "proj-q3",
      tag_ids: ["tag-calls"],
    });
    expect(sent.headers["Idempotency-Key"]).toBe(uuidNumber(1));
  });

  it("006-FR-008 surfaces the conflict instead when somebody else reclassified it", async () => {
    // Same shape as the test above, one thing different: the re-read finds a
    // classification that is neither what this entry intends nor what the phone
    // last showed. That is somebody else's work, and sending over it is what
    // FR-008 and SC-005 forbid. The whole difference between the two tests is
    // whether anybody else has been here.
    await seed(IDENTITY, [aged()]);
    install({
      "GET /tasks/task-1": () =>
        makeTask({ id: "task-1", project_id: "proj-inbox", tag_ids: ["tag-home"], revision: 12 }),
      "PATCH /tasks/task-1": () => accepted(),
    });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(view.result.current.conflict).toBeDefined());

    // It looked, and then did not leap: no PATCH was ever issued.
    expect(traffic()).toEqual(["GET /tasks/task-1"]);
    expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(0);

    const parked = view.result.current.conflict?.entry;
    expect(parked?.sendState).toBe("conflicted");
    expect(parked?.conflictServerRevision).toBe(12);
    expect(parked?.conflictServerValue).toEqual({
      projectId: "proj-inbox",
      tagIds: ["tag-home"],
    });
    // Still on the device, still unsent, waiting on a person — not discarded
    // and not applied.
    expect(await onDevice(IDENTITY)).toHaveLength(1);
  });
});

describe("006-FR-011 the queue belongs to one identity", () => {
  it("clears it and deletes the old key when a different account signs in", async () => {
    await seed(IDENTITY, [queued()]);
    install({ "PATCH /tasks/task-1": unreachable, "PATCH /tasks/task-2": unreachable });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(view.result.current.queue).toHaveLength(1));

    // The second account's own unsent work, stored as it signs in. It could not
    // have been seeded earlier: while the first account was active the sweep
    // had already deleted every foreign key, which is invariant 8b working.
    await seed(OTHER_IDENTITY, [
      queued({ taskId: "task-2", accountId: OTHER_ACCOUNT, idempotencyKey: "key-2" }),
    ]);
    await view.rerender({ identity: OTHER_IDENTITY, enabled: true });

    await waitFor(() =>
      expect(view.result.current.queue.map((entry) => entry.taskId)).toEqual(["task-2"]),
    );
    // Not migrated, not merged, not readable: discarded.
    expect(await onDevice(IDENTITY)).toBeNull();
  });

  it("006-SC-008 stops reading it when nobody is signed in, without destroying the work", async () => {
    await seed(IDENTITY, [queued()]);
    install({ "PATCH /tasks/task-1": unreachable });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(view.result.current.queue).toHaveLength(1));
    const attempts = backend.callsTo("PATCH", "/tasks/task-1").length;

    // An involuntary session end — a 401 or an offline launch, which the client
    // cannot tell apart by outcome.
    await view.rerender({ identity: null, enabled: true });

    expect(view.result.current.queue).toEqual([]);
    expect(view.result.current.ready).toBe(false);
    await foreground();
    expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(attempts);
    // Nobody chose to end the session, so the unsent change is still there for
    // the next sign-in to the same identity.
    expect(await onDevice(IDENTITY)).toHaveLength(1);
  });
});

describe("006-FR-015 the rollout flag", () => {
  it("shows nothing and drains nothing while it is off, and keeps the work", async () => {
    await seed(IDENTITY, [queued()]);
    install({ "PATCH /tasks/task-1": unreachable });

    const view = await renderQueue();
    await coldReadDone(view);
    await waitFor(() => expect(view.result.current.queue).toHaveLength(1));
    const attempts = backend.callsTo("PATCH", "/tasks/task-1").length;

    await view.rerender({ identity: IDENTITY, enabled: false });

    expect(view.result.current.queue).toEqual([]);
    expect(view.result.current.ready).toBe(false);
    expect(view.result.current.expiredTotal).toBe(0);
    await foreground();
    expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(attempts);
    expect(await onDevice(IDENTITY)).toHaveLength(1);
  });

  it("rehydrates and drains the kept queue when it is turned back on", async () => {
    await seed(IDENTITY, [queued()]);
    install({ "PATCH /tasks/task-1": unreachable });

    const view = await renderQueue({ enabled: false });
    expect(view.result.current.ready).toBe(false);

    backend.route("PATCH /tasks/task-1", () => accepted());
    await view.rerender({ identity: IDENTITY, enabled: true });
    await coldReadDone(view);
    await waitFor(() => expect(view.result.current.queue).toHaveLength(0));

    // The flag being off never read the key, so nothing was sent until it was
    // on — and then the queue that survived went out unchanged.
    expect(keysSent()).toEqual(["key-1"]);
  });
});

describe("006-FR-018 an expired change is surfaced, and its payload is kept (invariant 8a)", () => {
  /** Last edited 31 days ago, and touching only the project. */
  const stale = () =>
    queued({
      value: { projectId: "proj-q3", tagIds: undefined },
      firstQueuedAt: ago(31 * DAY),
      lastEditedAt: ago(31 * DAY),
    });

  it("names the field and what it reverted to, while the same sweep deletes a foreign key", async () => {
    await seed(IDENTITY, [stale()]);
    // Another identity's aged work, which nothing will ever read again.
    await seed(OTHER_IDENTITY, [
      queued({
        taskId: "task-2",
        accountId: OTHER_ACCOUNT,
        idempotencyKey: "key-2",
        lastEditedAt: ago(31 * DAY),
      }),
    ]);
    // The last server `Date` this device saw, so the bound passes against both
    // clocks rather than the device's alone.
    await AsyncStorage.setItem(SERVER_TIME_KEY, String(Date.now() - HOUR));
    install({ "PATCH /tasks/task-1": () => accepted() });

    const view = await renderQueue();
    await coldReadDone(view);

    expect(view.result.current.droppedThisLaunch).toBe(1);
    expect(view.result.current.expiredTotal).toBe(1);
    // FR-007 removed every per-change marker, so a bare count would leave the
    // value looking as though it changed back on its own.
    expect(
      view.result.current.expiredNoticeFor("task-1", {
        projectId: "proj-onboarding",
        tagIds: [],
      }),
    ).toEqual({
      taskId: "task-1",
      lastEditedAt: expect.any(String),
      fields: [{ field: "project", dropped: "proj-q3", revertedTo: "proj-onboarding" }],
    });
    // A notice, not live work: the row shows the server's value again and
    // nothing is sent.
    expect(view.result.current.pendingFor("task-1")).toBeUndefined();
    expect(traffic()).toEqual([]);

    // Invariant 8a. The entry-level rule RETAINS: the payload is still on the
    // device after the pass that expired it, so a device clock that jumped
    // forward is recoverable rather than terminal.
    const kept = await onDevice(IDENTITY);
    expect(kept).toHaveLength(1);
    expect(kept?.[0]).toMatchObject({
      sendState: "expired",
      value: { projectId: "proj-q3" },
    });
    // The key-level rule DELETES, and only reaches keys that are not the
    // active identity's.
    expect(await onDevice(OTHER_IDENTITY)).toBeNull();

    // The footer starts from the persisted server clock, never the device's.
    expect(view.result.current.lastSyncedAt).not.toBeNull();
  });

  it("drops the payload only once the person has dismissed the notice", async () => {
    await seed(IDENTITY, [stale()]);
    install({ "PATCH /tasks/task-1": () => accepted() });

    const view = await renderQueue();
    await waitFor(() => expect(view.result.current.expiredTotal).toBe(1));

    await act(async () => {
      await view.result.current.dismissExpiredNotice("task-1");
    });

    expect(view.result.current.expiredTotal).toBe(0);
    expect(view.result.current.expiredNoticeFor("task-1")).toBeNull();
    expect(await onDevice(IDENTITY)).toBeNull();
  });
});

describe("006-FR-006 an edit made while online does not wait for a trigger", () => {
  it("sends it as soon as it is enqueued, carrying only the field it touched", async () => {
    install({ "PATCH /tasks/task-1": () => accepted() });

    const view = await renderQueue();
    await coldReadDone(view);

    await act(async () => {
      await view.result.current.enqueue({
        taskId: "task-1",
        value: { projectId: "proj-q3" },
        observedRevision: 4,
        displayedValue: { projectId: null, tagIds: [] },
      });
    });

    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1));
    const sent = backend.callsTo("PATCH", "/tasks/task-1")[0];
    // Tags were never part of this change, so `tag_ids` is absent rather than
    // sent as a clear.
    expect(sent.body).toEqual({ expected_revision: 4, project_id: "proj-q3" });
    expect(sent.headers["Idempotency-Key"]).toBe(uuidNumber(1));
    expect(view.result.current.queue).toHaveLength(0);
  });

  it("006-FR-009 keeps it, and still shows it as made, when the server cannot be reached", async () => {
    install({ "PATCH /tasks/task-1": unreachable });

    const view = await renderQueue();
    await coldReadDone(view);

    await act(async () => {
      await view.result.current.enqueue({
        taskId: "task-1",
        value: { projectId: "proj-q3" },
        observedRevision: 4,
        displayedValue: { projectId: null, tagIds: [] },
      });
    });

    // FR-007: the change is shown as made, with no marker saying it is unsent.
    expect(view.result.current.pendingFor("task-1")).toMatchObject({
      sendState: "queued",
      value: { projectId: "proj-q3" },
    });
    // FR-009: and it is on the device, so closing the app does not lose it.
    expect(await onDevice(IDENTITY)).toMatchObject([
      { taskId: "task-1", sendState: "queued", value: { projectId: "proj-q3" } },
    ]);
  });
});

describe("006-SC-007 nothing is written that cannot be attributed to an identity", () => {
  it("drops an edit made with nobody signed in rather than guessing a key", async () => {
    install({});

    const view = await renderQueue({ identity: null });
    await act(async () => {
      await view.result.current.enqueue({
        taskId: "task-1",
        value: { projectId: "proj-q3" },
        observedRevision: 4,
        displayedValue: { projectId: null, tagIds: [] },
      });
      // The sheet cannot be open with no queue, but neither answer may write
      // anything if it somehow is.
      await view.result.current.discardMine(11);
    });

    expect(view.result.current.queue).toEqual([]);
    // An empty half of the key would pool every account into one store, so the
    // only safe answer is to write nothing at all.
    expect(await onDevice(IDENTITY)).toBeNull();
    expect(backend.calls).toEqual([]);
  });

  it("never reads or sends the account that signed in while a pass was in flight", async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await seed(IDENTITY, [queued()]);
    install({
      "PATCH /tasks/task-1": async () => {
        await held;
        return accepted();
      },
      "PATCH /tasks/task-2": unreachable,
    });

    const view = await renderQueue();
    await waitFor(() => expect(backend.callsTo("PATCH", "/tasks/task-1")).toHaveLength(1));

    // Somebody else signs in while the first account's request is still out.
    await seed(OTHER_IDENTITY, [
      queued({ taskId: "task-2", accountId: OTHER_ACCOUNT, idempotencyKey: "key-2" }),
    ]);
    await view.rerender({ identity: OTHER_IDENTITY, enabled: true });
    await waitFor(() =>
      expect(view.result.current.queue.map((entry) => entry.taskId)).toEqual(["task-2"]),
    );

    await act(async () => {
      release();
    });
    await waitFor(() => expect(view.refetches).toEqual(["refetch"]));

    // The second account's own drain never ran — one pass at a time, and the
    // first account's was holding it — so the only thing that could have sent
    // task-2 is a pass reaching into a queue that stopped being its own.
    expect(backend.callsTo("PATCH", "/tasks/task-2")).toEqual([]);
    // And what is on screen is still the account that is signed in.
    expect(view.result.current.queue.map((entry) => entry.taskId)).toEqual(["task-2"]);
    expect(await onDevice(OTHER_IDENTITY)).toMatchObject([{ taskId: "task-2" }]);
  });

  it("discards a cold read that only finishes after somebody else has signed in", async () => {
    await seed(IDENTITY, [queued()]);
    await seed(OTHER_IDENTITY, [
      queued({ taskId: "task-2", accountId: OTHER_ACCOUNT, idempotencyKey: "key-2" }),
    ]);
    install({ "PATCH /tasks/task-1": unreachable, "PATCH /tasks/task-2": unreachable });

    // Hold the first account's cold read at its very first storage call — a
    // slow device, and the window in which the person signs in as somebody
    // else. Only the first read is held; the second account's runs normally.
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const readKeys = AsyncStorage.getAllKeys.bind(AsyncStorage);
    jest.spyOn(AsyncStorage, "getAllKeys").mockImplementationOnce(async () => {
      await held;
      return readKeys();
    });

    const view = await renderQueue();
    await view.rerender({ identity: OTHER_IDENTITY, enabled: true });
    await waitFor(() =>
      expect(view.result.current.queue.map((entry) => entry.taskId)).toEqual(["task-2"]),
    );

    await act(async () => {
      release();
    });

    // The first account's entries land late and go on the floor: putting them
    // on screen now would show one account another's unsent work.
    expect(view.result.current.queue.map((entry) => entry.taskId)).toEqual(["task-2"]);
  });
});
