/**
 * The device-local classification queue reducer — feature 006.
 *
 * Pure and total: every function takes the queue and returns a new one, and
 * nothing here reads a clock, a store or a random source. `now` is always an
 * argument and the idempotency-key minter is injected, because the 30-day
 * bound of FR-018 and the key lifecycle of FR-017 are otherwise untestable —
 * `mobile/` has no fake-timer precedent.
 *
 * The invariants implemented here are numbered in
 * `specs/006-mobile-task-classification/data-model.md`; the numbers in the
 * comments below refer to that list.
 *
 * Production wiring passes `newIdempotencyKey` from `src/utils/ids.ts` as
 * `mintKey`; this module deliberately does not import it, so the reducer never
 * pulls a native module into a unit test.
 */

import type {
  ClassificationValue,
  IdentityEventKind,
  PendingClassificationChange,
  QueueDisposition,
  SendState,
} from "./classificationTypes";
import { RETENTION_MS, SERVER_REPLAY_WINDOW_MS } from "./classificationTypes";

/** Epoch milliseconds. Callers pass `Date.now()`; this module never calls it. */
export type Millis = number;

/**
 * One edit by the person, before it becomes — or joins — a queue entry.
 *
 * `value` is partial on purpose: an omitted (or `undefined`) field is untouched
 * by this edit, while `projectId: null` deliberately clears the project. The
 * distinction is load-bearing (FR-001) and survives into the stored entry.
 */
export interface ClassificationEdit {
  taskId: string;
  accountId: string;
  serverUrl: string;
  value: Partial<ClassificationValue>;
  /** The task revision the person was looking at. Used only when this edit
   *  opens a new entry — invariant 2 forbids refreshing it on a coalesce. */
  observedRevision: number;
  /** What the device was displaying when this edit was made. Becomes
   *  `originalValue` when this edit opens a new entry; invariant 7 forbids
   *  refreshing it afterwards. */
  displayedValue: { projectId: string | null; tagIds: string[] };
}

export type MintIdempotencyKey = () => string;

/** Why the server refused a send. Only a stale revision is the person's
 *  question to answer (FR-008); anything else is retried. */
export type RejectionKind = "revision-conflict" | "other";

export interface QueueIdentity {
  accountId: string;
  serverUrl: string;
}

export interface IdentityEvent {
  storedIdentity: QueueIdentity;
  incomingIdentity: QueueIdentity;
  kind: IdentityEventKind;
}

/**
 * `kept` and `expired` together are the queue to persist — an expired entry
 * keeps its payload until the person dismisses the notice (FR-018), so it is
 * not deleted here. `expired` therefore includes entries that expired on an
 * earlier sweep, while `droppedCount` counts only the ones that expired on
 * this one, which is the number worth announcing.
 */
export interface QueueExpiryResult {
  kept: PendingClassificationChange[];
  expired: PendingClassificationChange[];
  droppedCount: number;
}

/** States an incoming edit may merge into. `sending` is excluded by invariant
 *  5b (it gets a successor instead) and `expired` by FR-018 — an expired entry
 *  is a notice awaiting dismissal, not live work. */
const COALESCABLE: readonly SendState[] = ["queued", "conflicted"];

/**
 * Invariant 8's first guard: a timestamp ahead of `now` is stored as `now`.
 *
 * Without it, a clock that was ahead when the entry was written makes
 * `now - lastEditedAt` negative and the 30-day bound never fires — on exactly
 * the entries whose timestamps are least trustworthy. An unreadable timestamp
 * is treated the same way rather than as infinitely old: the failure mode of
 * this function must never be "destroy the person's work".
 */
function clampTimestamp(value: string, now: Millis): string {
  const at = Date.parse(value);
  if (!Number.isFinite(at) || at > now) return new Date(now).toISOString();
  return value;
}

function sameTagSet(left: readonly string[], right: readonly string[]): boolean {
  const a = new Set(left);
  const b = new Set(right);
  if (a.size !== b.size) return false;
  for (const tag of a) {
    if (!b.has(tag)) return false;
  }
  return true;
}

/** Payload equality, which decides whether the idempotency key survives
 *  (invariant 6). Tags are a set, so order alone is not a change. */
function sameValue(left: ClassificationValue, right: ClassificationValue): boolean {
  if (left.projectId !== right.projectId) return false;
  if (left.tagIds === undefined || right.tagIds === undefined) {
    return left.tagIds === right.tagIds;
  }
  return sameTagSet(left.tagIds, right.tagIds);
}

/**
 * Invariant 3: a net effect equal to where the person started is not a change.
 * A tag added and then removed leaves no trace, and an entry that would send a
 * no-op is dropped instead of sent.
 *
 * The baseline is `originalValue` — what the device last displayed (invariant
 * 9), which is the device's only offline knowledge of what the server holds.
 */
function isNoOp(
  value: ClassificationValue,
  original: { projectId: string | null; tagIds: string[] },
): boolean {
  const projectSettled = value.projectId === undefined || value.projectId === original.projectId;
  const tagsSettled = value.tagIds === undefined || sameTagSet(value.tagIds, original.tagIds);
  return projectSettled && tagsSettled;
}

/** Merges an edit over an entry field by field. The result is the whole
 *  intended value, never a delta — coalescing a delta stream is where a queue
 *  loses data (FR-010). */
function mergeValue(base: ClassificationValue, edit: Partial<ClassificationValue>): ClassificationValue {
  return {
    projectId: edit.projectId !== undefined ? edit.projectId : base.projectId,
    tagIds: edit.tagIds !== undefined ? [...edit.tagIds] : base.tagIds,
  };
}

/**
 * FR-010. Folds one edit into the queue and returns the net effect.
 *
 * Three outcomes, in the order they are decided:
 *  - the edit merges into the task's live entry (`queued` or `conflicted`);
 *  - the merged value equals where the person started, so the entry is dropped
 *    rather than sent as a no-op;
 *  - the task's only entry is in flight, so the edit becomes a *successor*
 *    entry with its own fresh key (invariant 5b) — mutating the in-flight one
 *    would let its acceptance delete an edit that was never sent.
 */
export function coalesce(
  queue: readonly PendingClassificationChange[],
  edit: ClassificationEdit,
  now: Millis,
  mintKey: MintIdempotencyKey,
): PendingClassificationChange[] {
  const nowIso = new Date(now).toISOString();
  const existing = queue.find(
    (entry) => entry.taskId === edit.taskId && COALESCABLE.includes(entry.sendState),
  );

  if (!existing) {
    const originalValue = {
      projectId: edit.displayedValue.projectId,
      tagIds: [...edit.displayedValue.tagIds],
    };
    const value = mergeValue({ projectId: undefined, tagIds: undefined }, edit.value);
    if (isNoOp(value, originalValue)) return [...queue];

    return [
      ...queue,
      {
        taskId: edit.taskId,
        accountId: edit.accountId,
        serverUrl: edit.serverUrl,
        value,
        observedRevision: edit.observedRevision,
        originalValue,
        firstQueuedAt: nowIso,
        lastEditedAt: nowIso,
        idempotencyKey: mintKey(),
        sendState: "queued",
      },
    ];
  }

  const value = mergeValue(existing.value, edit.value);
  if (isNoOp(value, existing.originalValue)) {
    return queue.filter((entry) => entry !== existing);
  }

  // `observedRevision` and `originalValue` are captured once (invariants 2 and
  // 7): refreshing either would quietly swallow a concurrent edit, or rewrite
  // where the person started to wherever they have got to.
  const updated: PendingClassificationChange = {
    ...existing,
    value,
    firstQueuedAt: clampTimestamp(existing.firstQueuedAt, now),
    lastEditedAt: nowIso,
    idempotencyKey: sameValue(value, existing.value) ? existing.idempotencyKey : mintKey(),
  };
  return queue.map((entry) => (entry === existing ? updated : entry));
}

/**
 * FR-017 single flight. Returns the next entry to send, or `undefined`.
 *
 * An entry in `sending` is never returned, and neither is another entry for
 * the same task — a successor sent while its predecessor is in flight would
 * race it, and its `observedRevision` is only correct once the predecessor
 * settles. `conflicted` waits for the person's answer; `expired` waits for a
 * dismissal. Oldest first, so a predecessor always goes before its successor.
 */
export function selectDrainable(
  queue: readonly PendingClassificationChange[],
): PendingClassificationChange | undefined {
  const inFlight = new Set(
    queue.filter((entry) => entry.sendState === "sending").map((entry) => entry.taskId),
  );
  return queue
    .filter((entry) => entry.sendState === "queued" && !inFlight.has(entry.taskId))
    .sort((a, b) => Date.parse(a.firstQueuedAt) - Date.parse(b.firstQueuedAt))[0];
}

function transition(
  queue: readonly PendingClassificationChange[],
  idempotencyKey: string,
  change: (entry: PendingClassificationChange) => PendingClassificationChange,
): PendingClassificationChange[] {
  return queue.map((entry) =>
    // An expired entry is a notice, never resurrected by a send that settles
    // late (FR-018).
    entry.idempotencyKey === idempotencyKey && entry.sendState !== "expired"
      ? change(entry)
      : entry,
  );
}

/**
 * Takes an entry in flight. `firstSentAt` is stamped on the *first* attempt
 * only, because invariant 10 measures the server's replay window from it.
 *
 * A no-op on an entry that is not `queued`: this is the guard that makes a
 * second drain trigger skip rather than duplicate (FR-017).
 */
export function markSending(
  queue: readonly PendingClassificationChange[],
  idempotencyKey: string,
  now: Millis,
): PendingClassificationChange[] {
  return transition(queue, idempotencyKey, (entry) =>
    entry.sendState === "queued"
      ? {
          ...entry,
          sendState: "sending",
          firstSentAt: entry.firstSentAt ?? new Date(now).toISOString(),
        }
      : entry,
  );
}

/**
 * The server applied the change: the entry is removed and any successor for
 * the same task is re-based onto the revision the server returned (invariant
 * 5b). `originalValue` is left alone — the successor started from what the
 * predecessor intended, which is what the server now holds.
 */
export function applyAccepted(
  queue: readonly PendingClassificationChange[],
  idempotencyKey: string,
  acceptedRevision: number,
): PendingClassificationChange[] {
  const accepted = queue.find(
    (entry) => entry.idempotencyKey === idempotencyKey && entry.sendState !== "expired",
  );
  if (!accepted) return [...queue];

  return queue
    .filter((entry) => entry !== accepted)
    .map((entry) =>
      entry.taskId === accepted.taskId && entry.sendState === "queued"
        ? { ...entry, observedRevision: acceptedRevision }
        : entry,
    );
}

/**
 * The server refused the send. A stale revision becomes `conflicted` so the
 * person is asked (FR-008); anything else returns to `queued` for a retry with
 * the error surfaced by the caller.
 *
 * `lastEditedAt` deliberately does not move: only a person's edit refreshes
 * it, or a retry loop would keep an entry alive past FR-018's bound forever.
 */
export function applyRejected(
  queue: readonly PendingClassificationChange[],
  idempotencyKey: string,
  kind: RejectionKind,
): PendingClassificationChange[] {
  return transition(queue, idempotencyKey, (entry) => ({
    ...entry,
    sendState: kind === "revision-conflict" ? "conflicted" : "queued",
  }));
}

/**
 * The request timed out or lost its connection, so it may already have been
 * applied. The entry returns to `queued` with the **same** idempotency key —
 * that is what makes the retry a replay rather than a second application,
 * inside the server's 24-hour window (invariant 10 covers the rest).
 */
export function applyTimeout(
  queue: readonly PendingClassificationChange[],
  idempotencyKey: string,
): PendingClassificationChange[] {
  return transition(queue, idempotencyKey, (entry) => ({ ...entry, sendState: "queued" }));
}

/**
 * FR-021, invariant 5c. `sending` is a liveness marker for the running
 * process, never authoritative across a restart: on a cold read every entry
 * found in it is reset to `queued` before any drain runs.
 *
 * Without this an app kill mid-send strands the entry forever — invariant 5
 * makes every later drain skip it, so it is never sent, never conflicts, never
 * errors, and its only terminal outcome is the 30-day drop. The key is kept so
 * the re-send replays the stored result if the original did land.
 */
export function resetInterrupted(
  queue: readonly PendingClassificationChange[],
): PendingClassificationChange[] {
  return queue.map((entry) =>
    entry.sendState === "sending" ? { ...entry, sendState: "queued" } : entry,
  );
}

/**
 * FR-018, invariant 8. Expiry runs from `lastEditedAt` — running it from the
 * first edit would destroy a change made yesterday because an earlier one to
 * the same task was old — and is evaluated on read, since a background timer
 * in an app that is usually not running mostly does not fire.
 *
 * Three guards, because this is the only path in the feature that destroys the
 * person's work without asking, keyed on a clock the person can set:
 *  - timestamps are clamped, so a clock that was ahead cannot make an entry
 *    immortal (and the clamped value is returned, so it persists);
 *  - when `serverNow` (the last server `Date` header seen) is supplied the
 *    bound must pass against it too, so a device clock jumped forward cannot
 *    delete a queue on its own;
 *  - an expired entry retains its payload until the person dismisses the
 *    notice, so a clock error is recoverable rather than terminal.
 */
export function expireQueue(
  entries: readonly PendingClassificationChange[],
  now: Millis,
  serverNow?: Millis,
): QueueExpiryResult {
  const kept: PendingClassificationChange[] = [];
  const expired: PendingClassificationChange[] = [];
  let droppedCount = 0;

  for (const entry of entries) {
    const clamped: PendingClassificationChange = {
      ...entry,
      firstQueuedAt: clampTimestamp(entry.firstQueuedAt, now),
      lastEditedAt: clampTimestamp(entry.lastEditedAt, now),
    };

    if (clamped.sendState === "expired") {
      expired.push(clamped);
      continue;
    }

    const editedAt = Date.parse(clamped.lastEditedAt);
    const byDeviceClock = now - editedAt >= RETENTION_MS;
    const byServerClock = serverNow === undefined || serverNow - editedAt >= RETENTION_MS;

    if (byDeviceClock && byServerClock) {
      expired.push({ ...clamped, sendState: "expired" });
      droppedCount += 1;
    } else {
      kept.push(clamped);
    }
  }

  return { kept, expired, droppedCount };
}

/** FR-018. Drops an expired entry once the person has been told what was
 *  dropped and what it reverted to. Live entries for the same task — an edit
 *  made after the expiry — are untouched. */
export function dismissExpired(
  queue: readonly PendingClassificationChange[],
  taskId: string,
): PendingClassificationChange[] {
  return queue.filter((entry) => !(entry.taskId === taskId && entry.sendState === "expired"));
}

/**
 * FR-011 / SC-008. What happens to unsent work when a session ends.
 *
 * A session ending without anyone choosing it must not discard the work: the
 * client cannot tell an expired token from an offline launch by outcome, and
 * discarding on that path would destroy the queue on exactly the path the
 * feature exists for. A deliberate transition always warns first and then
 * discards — including back to the same identity, because the person asked to
 * leave and the warning is what FR-011 requires before their work goes.
 *
 * Call this only when a stored queue exists; both identities are required so
 * the answer never has to guess which side is missing.
 */
export function resolveQueueOnIdentityEvent({
  storedIdentity,
  incomingIdentity,
  kind,
}: IdentityEvent): QueueDisposition {
  if (kind === "deliberate") return "warn-then-discard";
  const sameIdentity =
    storedIdentity.accountId === incomingIdentity.accountId &&
    storedIdentity.serverUrl === incomingIdentity.serverUrl;
  return sameIdentity ? "keep" : "discard";
}

/**
 * Invariant 10. Past `firstSentAt + SERVER_REPLAY_WINDOW_MS` the server has
 * forgotten the idempotency key, so the entry may no longer be retried blind:
 * the drain must re-read the task first, then drop the entry if the server
 * already holds the intended value or re-present it against the current
 * revision with a new key.
 *
 * At-most-once is carried by the key inside the window and by
 * `expected_revision` outside it.
 */
export function needsRereadBeforeSend(
  entry: PendingClassificationChange,
  now: Millis,
): boolean {
  if (entry.firstSentAt === undefined) return false;
  const sentAt = Date.parse(entry.firstSentAt);
  // Sent, but at an unreadable time: the one answer that is never wrong is to
  // look before leaping.
  if (!Number.isFinite(sentAt)) return true;
  return now - Math.min(sentAt, now) >= SERVER_REPLAY_WINDOW_MS;
}
