import {
  applyAccepted,
  applyRejected,
  applyTimeout,
  coalesce,
  dismissExpired,
  expireQueue,
  markSending,
  needsRereadBeforeSend,
  resetInterrupted,
  resolveQueueOnIdentityEvent,
  selectDrainable,
} from "../classificationQueue";
import type { ClassificationEdit } from "../classificationQueue";
import type { PendingClassificationChange } from "../classificationTypes";

// The reducer for specs/006-mobile-task-classification/data-model.md. Every
// bound below is written as a literal rather than imported from the module it
// checks: importing RETENTION_MS to assert RETENTION_MS proves nothing.

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Fixed clock. No module here reads Date.now(); `now` is always an argument. */
const T0 = Date.parse("2026-08-11T12:00:00.000Z");

const iso = (at: number): string => new Date(at).toISOString();

/** Deterministic stand-in for `newIdempotencyKey` (src/utils/ids.ts). */
function keyMinter(): () => string {
  let issued = 0;
  return () => `minted-${++issued}`;
}

function edit(overrides: Partial<ClassificationEdit> = {}): ClassificationEdit {
  return {
    taskId: "task-1",
    accountId: "acct-1",
    serverUrl: "https://bb.example",
    value: {},
    observedRevision: 3,
    displayedValue: { projectId: "p-old", tagIds: ["t-1"] },
    ...overrides,
  };
}

function entry(overrides: Partial<PendingClassificationChange> = {}): PendingClassificationChange {
  return {
    taskId: "task-1",
    accountId: "acct-1",
    serverUrl: "https://bb.example",
    value: { projectId: "p-new", tagIds: undefined },
    observedRevision: 3,
    originalValue: { projectId: "p-old", tagIds: ["t-1"] },
    firstQueuedAt: iso(T0 - HOUR),
    lastEditedAt: iso(T0 - HOUR),
    idempotencyKey: "key-existing",
    sendState: "queued",
    ...overrides,
  };
}

describe("coalesce", () => {
  it("006-FR-010 opens one queued entry for a change against what the device displays", () => {
    const queue = coalesce([], edit({ value: { projectId: "p-new" } }), T0, keyMinter());

    expect(queue).toHaveLength(1);
    expect(queue[0]).toMatchObject({
      taskId: "task-1",
      accountId: "acct-1",
      serverUrl: "https://bb.example",
      observedRevision: 3,
      sendState: "queued",
      idempotencyKey: "minted-1",
      firstQueuedAt: iso(T0),
      lastEditedAt: iso(T0),
    });
    expect(queue[0].value.projectId).toBe("p-new");
    expect(queue[0].originalValue).toEqual({ projectId: "p-old", tagIds: ["t-1"] });
  });

  it("006-FR-010 keeps at most one non-sending entry per task", () => {
    const mint = keyMinter();
    let queue = coalesce([], edit({ value: { projectId: "p-a" } }), T0, mint);
    queue = coalesce(queue, edit({ value: { projectId: "p-b" } }), T0 + MINUTE, mint);

    expect(queue).toHaveLength(1);
    expect(queue[0].value.projectId).toBe("p-b");
  });

  it("006-FR-010 coalesces to the net effect rather than a replay log", () => {
    const mint = keyMinter();
    let queue = coalesce([], edit({ value: { projectId: "p-a" } }), T0, mint);
    queue = coalesce(queue, edit({ value: { tagIds: ["t-1", "t-2"] } }), T0 + MINUTE, mint);

    expect(queue).toHaveLength(1);
    expect(queue[0].value).toEqual({ projectId: "p-a", tagIds: ["t-1", "t-2"] });
  });

  it("006-FR-010 leaves no trace of a tag added and then removed before the drain", () => {
    const mint = keyMinter();
    let queue = coalesce([], edit({ value: { tagIds: ["t-1", "t-2"] } }), T0, mint);
    expect(queue).toHaveLength(1);

    queue = coalesce(queue, edit({ value: { tagIds: ["t-1"] } }), T0 + MINUTE, mint);
    expect(queue).toEqual([]);
  });

  it("006-FR-010 drops an entry whose net value equals the server's instead of sending a no-op", () => {
    const mint = keyMinter();
    let queue = coalesce([], edit({ value: { projectId: "p-new" } }), T0, mint);
    queue = coalesce(queue, edit({ value: { projectId: "p-old" } }), T0 + MINUTE, mint);

    expect(queue).toEqual([]);
  });

  it("006-FR-010 never opens an entry for a change that matches what is already displayed", () => {
    const queue = coalesce([], edit({ value: { projectId: "p-old" } }), T0, keyMinter());

    expect(queue).toEqual([]);
  });

  it("006-FR-010 compares tag sets by membership, not by order, when deciding a no-op", () => {
    const queue = coalesce(
      [],
      edit({
        value: { tagIds: ["t-2", "t-1"] },
        displayedValue: { projectId: null, tagIds: ["t-1", "t-2"] },
      }),
      T0,
      keyMinter(),
    );

    expect(queue).toEqual([]);
  });

  it("006-FR-010 distinguishes a deliberate null clear from an untouched field", () => {
    const queue = coalesce([], edit({ value: { projectId: null } }), T0, keyMinter());

    expect(queue).toHaveLength(1);
    expect(queue[0].value.projectId).toBeNull();
    expect(queue[0].value.tagIds).toBeUndefined();
  });

  it("006-FR-010 captures observedRevision once and never refreshes it on coalescing", () => {
    const mint = keyMinter();
    let queue = coalesce([], edit({ value: { projectId: "p-a" }, observedRevision: 3 }), T0, mint);
    queue = coalesce(
      queue,
      edit({ value: { projectId: "p-b" }, observedRevision: 9 }),
      T0 + MINUTE,
      mint,
    );

    expect(queue[0].observedRevision).toBe(3);
  });

  it("006-FR-010 captures originalValue once and leaves it unchanged after N coalesces including a null clear", () => {
    const mint = keyMinter();
    let queue = coalesce([], edit({ value: { projectId: "p-a" } }), T0, mint);
    queue = coalesce(
      queue,
      edit({
        value: { tagIds: ["t-1", "t-9"] },
        displayedValue: { projectId: "p-a", tagIds: ["t-1"] },
      }),
      T0 + MINUTE,
      mint,
    );
    queue = coalesce(
      queue,
      edit({
        value: { projectId: null },
        displayedValue: { projectId: "p-a", tagIds: ["t-1", "t-9"] },
      }),
      T0 + 2 * MINUTE,
      mint,
    );

    expect(queue).toHaveLength(1);
    expect(queue[0].originalValue).toEqual({ projectId: "p-old", tagIds: ["t-1"] });
    expect(queue[0].value).toEqual({ projectId: null, tagIds: ["t-1", "t-9"] });
  });

  it("006-FR-010 holds firstQueuedAt immutable while lastEditedAt moves", () => {
    const mint = keyMinter();
    let queue = coalesce([], edit({ value: { projectId: "p-a" } }), T0, mint);
    queue = coalesce(queue, edit({ value: { projectId: "p-b" } }), T0 + 3 * HOUR, mint);

    expect(queue[0].firstQueuedAt).toBe(iso(T0));
    expect(queue[0].lastEditedAt).toBe(iso(T0 + 3 * HOUR));
  });

  it("006-FR-018 clamps a firstQueuedAt written while the clock was ahead down to now", () => {
    const ahead = entry({ firstQueuedAt: iso(T0 + 40 * DAY), lastEditedAt: iso(T0 + 40 * DAY) });
    const queue = coalesce([ahead], edit({ value: { projectId: "p-b" } }), T0, keyMinter());

    expect(queue[0].firstQueuedAt).toBe(iso(T0));
    expect(queue[0].lastEditedAt).toBe(iso(T0));
  });

  it("006-FR-010 coalesces into a conflicted entry rather than opening a second one", () => {
    const conflicted = entry({ sendState: "conflicted" });
    const queue = coalesce([conflicted], edit({ value: { projectId: "p-b" } }), T0, keyMinter());

    expect(queue).toHaveLength(1);
    expect(queue[0].sendState).toBe("conflicted");
    expect(queue[0].value.projectId).toBe("p-b");
  });

  it("006-FR-018 leaves an expired entry's notice standing and opens a fresh entry beside it", () => {
    const expired = entry({ sendState: "expired", idempotencyKey: "key-expired" });
    const queue = coalesce([expired], edit({ value: { projectId: "p-b" } }), T0, keyMinter());

    expect(queue).toHaveLength(2);
    expect(queue.map((e) => e.sendState).sort()).toEqual(["expired", "queued"]);
    expect(queue.find((e) => e.sendState === "expired")).toEqual(expired);
  });

  it("006-FR-010 leaves other tasks' entries alone", () => {
    const other = entry({ taskId: "task-2", idempotencyKey: "key-other" });
    const queue = coalesce([other], edit({ value: { projectId: "p-b" } }), T0, keyMinter());

    expect(queue).toHaveLength(2);
    expect(queue[0]).toBe(other);
  });

  it("006-FR-010 does not mutate the caller's queue or entries", () => {
    const original = entry();
    const queue = [original];
    coalesce(queue, edit({ value: { projectId: "p-b" } }), T0 + HOUR, keyMinter());

    expect(queue).toHaveLength(1);
    expect(original.value.projectId).toBe("p-new");
    expect(original.lastEditedAt).toBe(iso(T0 - HOUR));
  });

  it("006-FR-010 copies the caller's tag array instead of aliasing it", () => {
    const tagIds = ["t-1", "t-2"];
    const queue = coalesce([], edit({ value: { tagIds } }), T0, keyMinter());
    tagIds.push("t-3");

    expect(queue[0].value.tagIds).toEqual(["t-1", "t-2"]);
  });
});

describe("coalesce while an entry is sending", () => {
  const inFlight = entry({
    sendState: "sending",
    value: { projectId: "p-inflight", tagIds: undefined },
    idempotencyKey: "key-inflight",
    firstSentAt: iso(T0 - MINUTE),
  });

  it("006-FR-017 creates a successor entry instead of touching the entry in flight", () => {
    const queue = coalesce(
      [inFlight],
      edit({
        value: { tagIds: ["t-1", "t-2"] },
        displayedValue: { projectId: "p-inflight", tagIds: ["t-1"] },
      }),
      T0,
      keyMinter(),
    );

    expect(queue).toHaveLength(2);
    expect(queue[0]).toBe(inFlight);
    expect(queue[1].sendState).toBe("queued");
    expect(queue[1].value.tagIds).toEqual(["t-1", "t-2"]);
  });

  it("006-FR-017 gives the successor its own fresh idempotency key", () => {
    const queue = coalesce(
      [inFlight],
      edit({
        value: { tagIds: ["t-1", "t-2"] },
        displayedValue: { projectId: "p-inflight", tagIds: ["t-1"] },
      }),
      T0,
      keyMinter(),
    );

    expect(queue[1].idempotencyKey).toBe("minted-1");
    expect(queue[1].idempotencyKey).not.toBe(inFlight.idempotencyKey);
  });

  it("006-FR-010 coalesces a later edit into the successor, never into the entry in flight", () => {
    const mint = keyMinter();
    let queue = coalesce(
      [inFlight],
      edit({
        value: { tagIds: ["t-1", "t-2"] },
        displayedValue: { projectId: "p-inflight", tagIds: ["t-1"] },
      }),
      T0,
      mint,
    );
    queue = coalesce(
      queue,
      edit({
        value: { tagIds: ["t-1", "t-2", "t-3"] },
        displayedValue: { projectId: "p-inflight", tagIds: ["t-1", "t-2"] },
      }),
      T0 + MINUTE,
      mint,
    );

    expect(queue).toHaveLength(2);
    expect(queue[0]).toBe(inFlight);
    expect(queue[1].value.tagIds).toEqual(["t-1", "t-2", "t-3"]);
  });

  it("006-FR-017 does not let the in-flight acceptance remove work that was never sent", () => {
    const successor = coalesce(
      [inFlight],
      edit({
        value: { tagIds: ["t-1", "t-2"] },
        displayedValue: { projectId: "p-inflight", tagIds: ["t-1"] },
      }),
      T0,
      keyMinter(),
    );

    const settled = applyAccepted(successor, "key-inflight", 8);

    expect(settled).toHaveLength(1);
    expect(settled[0].value.tagIds).toEqual(["t-1", "t-2"]);
    expect(settled[0].sendState).toBe("queued");
    expect(settled[0].observedRevision).toBe(8);
  });
});

describe("idempotency key lifecycle", () => {
  it("006-FR-017 keeps the key byte-identical across a retry of an unchanged payload", () => {
    const queue = [entry({ idempotencyKey: "key-stable" })];
    const sending = markSending(queue, "key-stable", T0);
    const retried = applyTimeout(sending, "key-stable");

    expect(retried[0].idempotencyKey).toBe("key-stable");
    expect(retried[0].sendState).toBe("queued");
  });

  it("006-FR-017 keeps the key when coalescing does not alter the payload", () => {
    const queue = coalesce(
      [entry({ idempotencyKey: "key-stable" })],
      edit({ value: { projectId: "p-new" } }),
      T0,
      keyMinter(),
    );

    expect(queue[0].idempotencyKey).toBe("key-stable");
    expect(queue[0].lastEditedAt).toBe(iso(T0));
  });

  it("006-FR-017 re-mints the key when coalescing alters projectId", () => {
    const queue = coalesce(
      [entry({ idempotencyKey: "key-stable" })],
      edit({ value: { projectId: "p-other" } }),
      T0,
      keyMinter(),
    );

    expect(queue[0].idempotencyKey).toBe("minted-1");
  });

  it("006-FR-017 re-mints the key when coalescing alters tagIds", () => {
    const queue = coalesce(
      [entry({ value: { projectId: undefined, tagIds: ["t-9"] }, idempotencyKey: "key-stable" })],
      edit({ value: { tagIds: ["t-9", "t-8"] } }),
      T0,
      keyMinter(),
    );

    expect(queue[0].idempotencyKey).toBe("minted-1");
  });

  it("006-FR-017 does not re-mint for a tag set that differs only in order", () => {
    const queue = coalesce(
      [
        entry({
          value: { projectId: undefined, tagIds: ["t-8", "t-9"] },
          idempotencyKey: "key-stable",
        }),
      ],
      edit({ value: { tagIds: ["t-9", "t-8"] } }),
      T0,
      keyMinter(),
    );

    expect(queue[0].idempotencyKey).toBe("key-stable");
  });
});

describe("selectDrainable", () => {
  it("006-FR-017 never returns an entry that is sending", () => {
    const queue = [entry({ sendState: "sending" })];

    expect(selectDrainable(queue)).toBeUndefined();
  });

  it("006-FR-017 never returns a conflicted or an expired entry", () => {
    const queue = [
      entry({ taskId: "task-1", sendState: "conflicted", idempotencyKey: "key-conflicted" }),
      entry({ taskId: "task-2", sendState: "expired", idempotencyKey: "key-expired" }),
    ];

    expect(selectDrainable(queue)).toBeUndefined();
  });

  it("006-FR-017 does not return a queued successor while its predecessor is in flight", () => {
    const queue = [
      entry({ sendState: "sending", idempotencyKey: "key-inflight" }),
      entry({ sendState: "queued", idempotencyKey: "key-successor" }),
    ];

    expect(selectDrainable(queue)).toBeUndefined();
  });

  it("006-FR-017 still drains another task while one task is in flight", () => {
    const queue = [
      entry({ sendState: "sending", idempotencyKey: "key-inflight" }),
      entry({ taskId: "task-2", idempotencyKey: "key-other" }),
    ];

    expect(selectDrainable(queue)?.idempotencyKey).toBe("key-other");
  });

  it("006-FR-017 returns the oldest queued entry first", () => {
    const queue = [
      entry({ taskId: "task-2", firstQueuedAt: iso(T0 - HOUR), idempotencyKey: "key-newer" }),
      entry({ taskId: "task-3", firstQueuedAt: iso(T0 - DAY), idempotencyKey: "key-older" }),
    ];

    expect(selectDrainable(queue)?.idempotencyKey).toBe("key-older");
  });

  it("006-FR-017 lets two drain triggers make exactly one call to an injected sender", () => {
    let queue = [entry({ idempotencyKey: "key-once" })];
    const sent: string[] = [];
    const drain = (): void => {
      const next = selectDrainable(queue);
      if (!next) return;
      queue = markSending(queue, next.idempotencyKey, T0);
      sent.push(next.idempotencyKey);
    };

    drain();
    drain();

    expect(sent).toEqual(["key-once"]);
  });

  it("006-FR-017 does not mutate the caller's queue order", () => {
    const queue = [
      entry({ taskId: "task-2", firstQueuedAt: iso(T0 - HOUR), idempotencyKey: "key-newer" }),
      entry({ taskId: "task-3", firstQueuedAt: iso(T0 - DAY), idempotencyKey: "key-older" }),
    ];
    selectDrainable(queue);

    expect(queue[0].idempotencyKey).toBe("key-newer");
  });
});

describe("send transitions", () => {
  it("006-FR-017 markSending stamps firstSentAt on the first attempt only", () => {
    const first = markSending([entry()], "key-existing", T0);
    expect(first[0].sendState).toBe("sending");
    expect(first[0].firstSentAt).toBe(iso(T0));

    const retried = applyTimeout(first, "key-existing");
    const second = markSending(retried, "key-existing", T0 + 5 * HOUR);
    expect(second[0].firstSentAt).toBe(iso(T0));
  });

  it("006-FR-017 markSending is a no-op on an entry that is already sending", () => {
    const queue = [entry({ sendState: "sending", firstSentAt: iso(T0 - MINUTE) })];
    const again = markSending(queue, "key-existing", T0);

    expect(again[0].firstSentAt).toBe(iso(T0 - MINUTE));
  });

  it("006-FR-008 applyRejected on a stale revision moves the entry to conflicted", () => {
    const queue = markSending([entry()], "key-existing", T0);
    const rejected = applyRejected(queue, "key-existing", "revision-conflict");

    expect(rejected[0].sendState).toBe("conflicted");
    expect(rejected[0].idempotencyKey).toBe("key-existing");
  });

  it("006-FR-017 applyRejected for any other reason returns the entry to queued", () => {
    const queue = markSending([entry()], "key-existing", T0);
    const rejected = applyRejected(queue, "key-existing", "other");

    expect(rejected[0].sendState).toBe("queued");
  });

  it("006-FR-010 captures when the device last read the task, so the prompt can date it", () => {
    // Without this the conflict sheet either omits the age or back-fills it
    // from firstQueuedAt, which would claim the phone's knowledge is minutes
    // old when it may be weeks old — the precise falsehood the labelled row
    // exists to prevent.
    const q = coalesce([], edit({ value: { projectId: "p-new" }, displayedAt: "2026-07-20T00:00:00.000Z" }), T0, () => "k1");

    expect(q[0].observedAt).toBe("2026-07-20T00:00:00.000Z");
  });

  it("006-FR-010 omits the observation time rather than inventing one", () => {
    const q = coalesce([], edit({ value: { projectId: "p-new" } }), T0, () => "k1");

    expect(q[0].observedAt).toBeUndefined();
  });

  it("006-FR-017 applyRejected re-mints the key on an Idempotency-Key conflict", () => {
    // The backend returns 409 for two unrelated things. Returning to `queued`
    // with the same key after a key conflict sends a byte-identical request,
    // gets the same 409, and loops until FR-018 drops the entry 30 days later
    // with nothing having told the person. This is the spec-review defect
    // reappearing at the reducer/decision seam.
    const queue = markSending([entry()], "key-existing", T0);
    const rejected = applyRejected(
      queue,
      "key-existing",
      "idempotency-key-conflict",
      () => "key-fresh",
    );

    expect(rejected[0].sendState).toBe("queued");
    expect(rejected[0].idempotencyKey).toBe("key-fresh");
  });

  it("006-FR-017 applyRejected stops rather than loops when no minter is given", () => {
    // A caller that forgets the minter gets a stuck entry a person can see,
    // never a drain silently spinning on a request that cannot succeed.
    const queue = markSending([entry()], "key-existing", T0);
    const rejected = applyRejected(queue, "key-existing", "idempotency-key-conflict");

    expect(rejected[0].sendState).toBe("conflicted");
    expect(rejected[0].idempotencyKey).toBe("key-existing");
  });

  it("006-FR-017 applyTimeout returns the entry to queued for another try", () => {
    const queue = markSending([entry()], "key-existing", T0);
    const timed = applyTimeout(queue, "key-existing");

    expect(timed[0].sendState).toBe("queued");
    expect(timed[0].idempotencyKey).toBe("key-existing");
  });

  it("006-FR-018 a failed send does not extend the entry's life by moving lastEditedAt", () => {
    const queue = markSending([entry()], "key-existing", T0);
    const timed = applyTimeout(queue, "key-existing");
    const rejected = applyRejected(timed, "key-existing", "other");

    expect(rejected[0].lastEditedAt).toBe(iso(T0 - HOUR));
  });

  it("006-FR-017 applyAccepted removes the entry", () => {
    const queue = markSending([entry()], "key-existing", T0);

    expect(applyAccepted(queue, "key-existing", 4)).toEqual([]);
  });

  it("006-FR-017 leaves the queue alone for a key it does not hold", () => {
    const queue = [entry()];

    expect(applyAccepted(queue, "key-unknown", 4)).toEqual(queue);
    expect(applyTimeout(queue, "key-unknown")).toEqual(queue);
    expect(applyRejected(queue, "key-unknown", "other")).toEqual(queue);
    expect(markSending(queue, "key-unknown", T0)).toEqual(queue);
  });

  it("006-FR-018 never resurrects an expired entry through a settled send", () => {
    const expired = entry({ sendState: "expired", idempotencyKey: "key-expired" });

    expect(applyTimeout([expired], "key-expired")[0].sendState).toBe("expired");
    expect(applyRejected([expired], "key-expired", "other")[0].sendState).toBe("expired");
    expect(markSending([expired], "key-expired", T0)[0].sendState).toBe("expired");
  });
});

describe("resetInterrupted", () => {
  it("006-FR-021 resets an entry read as sending back to queued", () => {
    const queue = resetInterrupted([entry({ sendState: "sending" })]);

    expect(queue[0].sendState).toBe("queued");
  });

  it("006-FR-021 makes an interrupted entry drainable again on the next cold read", () => {
    const stranded = [entry({ sendState: "sending", idempotencyKey: "key-stranded" })];
    expect(selectDrainable(stranded)).toBeUndefined();

    const revived = resetInterrupted(stranded);

    expect(selectDrainable(revived)?.idempotencyKey).toBe("key-stranded");
  });

  it("006-FR-021 keeps the same idempotency key so the server replays rather than re-applies", () => {
    const queue = resetInterrupted([
      entry({ sendState: "sending", idempotencyKey: "key-stranded" }),
    ]);

    expect(queue[0].idempotencyKey).toBe("key-stranded");
  });

  it("006-FR-021 preserves firstSentAt so the replay window is still measured from the first attempt", () => {
    const queue = resetInterrupted([
      entry({ sendState: "sending", firstSentAt: iso(T0 - 20 * HOUR) }),
    ]);

    expect(queue[0].firstSentAt).toBe(iso(T0 - 20 * HOUR));
  });

  it("006-FR-021 leaves queued, conflicted and expired entries untouched", () => {
    const queue = [
      entry({ taskId: "task-1", sendState: "queued" }),
      entry({ taskId: "task-2", sendState: "conflicted" }),
      entry({ taskId: "task-3", sendState: "expired" }),
    ];

    expect(resetInterrupted(queue).map((e) => e.sendState)).toEqual([
      "queued",
      "conflicted",
      "expired",
    ]);
  });

  it("006-FR-021 does not mutate the caller's entries", () => {
    const stranded = entry({ sendState: "sending" });
    resetInterrupted([stranded]);

    expect(stranded.sendState).toBe("sending");
  });
});

describe("expireQueue", () => {
  it("006-FR-018 keeps an entry last edited 29 days and 23 hours ago", () => {
    const fresh = entry({
      firstQueuedAt: iso(T0 - 60 * DAY),
      lastEditedAt: iso(T0 - (29 * DAY + 23 * HOUR)),
    });
    const result = expireQueue([fresh], T0);

    expect(result.kept).toHaveLength(1);
    expect(result.expired).toEqual([]);
    expect(result.droppedCount).toBe(0);
  });

  it("006-FR-018 expires an entry last edited 30 days and 1 minute ago", () => {
    const stale = entry({ lastEditedAt: iso(T0 - (30 * DAY + MINUTE)) });
    const result = expireQueue([stale], T0);

    expect(result.kept).toEqual([]);
    expect(result.expired).toHaveLength(1);
    expect(result.expired[0].sendState).toBe("expired");
    expect(result.droppedCount).toBe(1);
  });

  it("006-FR-018 expires at exactly 30 days", () => {
    const result = expireQueue([entry({ lastEditedAt: iso(T0 - 30 * DAY) })], T0);

    expect(result.droppedCount).toBe(1);
  });

  it("006-FR-018 runs the bound from lastEditedAt, not from firstQueuedAt", () => {
    const edited = entry({
      firstQueuedAt: iso(T0 - 90 * DAY),
      lastEditedAt: iso(T0 - MINUTE),
    });

    expect(expireQueue([edited], T0).kept).toHaveLength(1);
  });

  it("006-FR-018 retains the payload of an expired entry rather than deleting it", () => {
    const stale = entry({
      value: { projectId: "p-new", tagIds: ["t-1", "t-2"] },
      lastEditedAt: iso(T0 - 31 * DAY),
    });
    const result = expireQueue([stale], T0);

    expect(result.expired[0]).toMatchObject({
      taskId: "task-1",
      value: { projectId: "p-new", tagIds: ["t-1", "t-2"] },
      originalValue: { projectId: "p-old", tagIds: ["t-1"] },
      idempotencyKey: "key-existing",
    });
  });

  it("006-FR-018 returns the dropped count rather than swallowing it", () => {
    const entries = [
      entry({ taskId: "task-1", lastEditedAt: iso(T0 - 31 * DAY) }),
      entry({ taskId: "task-2", lastEditedAt: iso(T0 - 40 * DAY) }),
      entry({ taskId: "task-3", lastEditedAt: iso(T0 - HOUR) }),
    ];
    const result = expireQueue(entries, T0);

    expect(result.droppedCount).toBe(2);
    expect(result.kept.map((e) => e.taskId)).toEqual(["task-3"]);
    expect(result.expired.map((e) => e.taskId)).toEqual(["task-1", "task-2"]);
  });

  it("006-FR-018 does not count again an entry that expired on an earlier sweep", () => {
    const already = entry({ sendState: "expired", lastEditedAt: iso(T0 - 40 * DAY) });
    const result = expireQueue([already], T0);

    expect(result.droppedCount).toBe(0);
    expect(result.expired).toHaveLength(1);
    expect(result.kept).toEqual([]);
  });

  it("006-FR-018 clamps a future lastEditedAt to now rather than letting the entry become immortal", () => {
    const ahead = entry({
      firstQueuedAt: iso(T0 + 400 * DAY),
      lastEditedAt: iso(T0 + 400 * DAY),
    });
    const result = expireQueue([ahead], T0);

    expect(result.kept[0].lastEditedAt).toBe(iso(T0));
    expect(result.kept[0].firstQueuedAt).toBe(iso(T0));
    expect(result.droppedCount).toBe(0);

    const later = expireQueue(result.kept, T0 + 31 * DAY);
    expect(later.droppedCount).toBe(1);
  });

  it("006-FR-018 does not expire on a device clock alone when the last server time disagrees", () => {
    const stale = entry({ lastEditedAt: iso(T0 - HOUR) });
    const jumped = T0 + 400 * DAY;
    const result = expireQueue([stale], jumped, T0);

    expect(result.droppedCount).toBe(0);
    expect(result.kept).toHaveLength(1);
  });

  it("006-FR-018 expires when the device and the last server time agree the entry is old", () => {
    const stale = entry({ lastEditedAt: iso(T0 - 31 * DAY) });
    const result = expireQueue([stale], T0, T0 - MINUTE);

    expect(result.droppedCount).toBe(1);
  });

  it("006-FR-018 treats an unreadable timestamp as now rather than destroying the work", () => {
    const broken = entry({ lastEditedAt: "not-a-timestamp" });
    const result = expireQueue([broken], T0);

    expect(result.droppedCount).toBe(0);
    expect(result.kept[0].lastEditedAt).toBe(iso(T0));
  });

  it("006-FR-018 does not mutate the caller's entries", () => {
    const stale = entry({ lastEditedAt: iso(T0 - 31 * DAY) });
    expireQueue([stale], T0);

    expect(stale.sendState).toBe("queued");
  });
});

describe("dismissExpired", () => {
  it("006-FR-018 removes an expired entry once the person has been told", () => {
    const queue = [entry({ sendState: "expired" })];

    expect(dismissExpired(queue, "task-1")).toEqual([]);
  });

  it("006-FR-018 leaves a live entry for the same task alone", () => {
    const queue = [
      entry({ sendState: "expired", idempotencyKey: "key-expired" }),
      entry({ sendState: "queued", idempotencyKey: "key-live" }),
    ];
    const remaining = dismissExpired(queue, "task-1");

    expect(remaining).toHaveLength(1);
    expect(remaining[0].idempotencyKey).toBe("key-live");
  });

  it("006-FR-018 leaves another task's expired notice standing", () => {
    const other = entry({ taskId: "task-2", sendState: "expired" });

    expect(dismissExpired([other], "task-1")).toEqual([other]);
  });
});

describe("resolveQueueOnIdentityEvent", () => {
  const stored = { accountId: "acct-1", serverUrl: "https://bb.example" };

  it("006-FR-011 keeps unsent work when a session ends on its own and the same identity returns", () => {
    expect(
      resolveQueueOnIdentityEvent({
        storedIdentity: stored,
        incomingIdentity: { ...stored },
        kind: "involuntary",
      }),
    ).toBe("keep");
  });

  it("006-SC-008 discards the queue when a different identity arrives after an involuntary end", () => {
    expect(
      resolveQueueOnIdentityEvent({
        storedIdentity: stored,
        incomingIdentity: { accountId: "acct-2", serverUrl: "https://bb.example" },
        kind: "involuntary",
      }),
    ).toBe("discard");
  });

  it("006-FR-011 warns before discarding on a deliberate transition to the same identity", () => {
    expect(
      resolveQueueOnIdentityEvent({
        storedIdentity: stored,
        incomingIdentity: { ...stored },
        kind: "deliberate",
      }),
    ).toBe("warn-then-discard");
  });

  it("006-FR-011 warns before discarding on a deliberate transition to a different identity", () => {
    expect(
      resolveQueueOnIdentityEvent({
        storedIdentity: stored,
        incomingIdentity: { accountId: "acct-2", serverUrl: "https://other.example" },
        kind: "deliberate",
      }),
    ).toBe("warn-then-discard");
  });

  it("006-SC-008 treats the same account on a different server as a different identity", () => {
    expect(
      resolveQueueOnIdentityEvent({
        storedIdentity: stored,
        incomingIdentity: { accountId: "acct-1", serverUrl: "https://other.example" },
        kind: "involuntary",
      }),
    ).toBe("discard");
  });
});

describe("needsRereadBeforeSend", () => {
  it("006-FR-017 does not require a reread for an entry that was never sent", () => {
    expect(needsRereadBeforeSend(entry(), T0)).toBe(false);
  });

  it("006-FR-017 does not require a reread just inside the server's replay window", () => {
    const sent = entry({ firstSentAt: iso(T0 - (24 * HOUR - MINUTE)) });

    expect(needsRereadBeforeSend(sent, T0)).toBe(false);
  });

  it("006-FR-017 requires a reread once the server's 24 hour replay window has closed", () => {
    const sent = entry({ firstSentAt: iso(T0 - (24 * HOUR + MINUTE)) });

    expect(needsRereadBeforeSend(sent, T0)).toBe(true);
  });

  it("006-FR-017 requires a reread at exactly the replay window boundary", () => {
    const sent = entry({ firstSentAt: iso(T0 - 24 * HOUR) });

    expect(needsRereadBeforeSend(sent, T0)).toBe(true);
  });

  it("006-FR-017 clamps a firstSentAt in the future rather than trusting it", () => {
    const sent = entry({ firstSentAt: iso(T0 + 400 * DAY) });

    expect(needsRereadBeforeSend(sent, T0)).toBe(false);
  });

  it("006-FR-017 requires a reread when the entry was sent at an unreadable time", () => {
    const sent = entry({ firstSentAt: "not-a-timestamp" });

    expect(needsRereadBeforeSend(sent, T0)).toBe(true);
  });
});
