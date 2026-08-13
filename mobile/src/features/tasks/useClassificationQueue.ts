/**
 * The drain — feature 006, T050 and T068.
 *
 * Two triggers send queued classification changes: the app coming to the
 * foreground, and the settling of a request that succeeded. Everything either
 * trigger *decides* lives in the exported pure functions at the top of this
 * file; the hook at the bottom is wiring, and holds no rule of its own.
 *
 * That split is forced rather than stylistic. `mobile/` cannot render a
 * component in a test, so a rule that lives inside a `useEffect` has no
 * evidence at all — `__tests__/drain.test.ts` covers every function above the
 * hook, and the hook's own evidence is typecheck, Metro bundle and the numbered
 * `quickstart.md` steps.
 *
 * Nothing here reads the clock or mints a key on its own: `now` and `mintKey`
 * are always arguments (plan.md's clock rule), and the hook passes
 * `Date.now` and `newIdempotencyKey`.
 *
 * The five seams this file owns, each with its data-model invariant:
 *
 * - **5b / FR-010** — a pass decides against the queue the device holds *now*,
 *   never the snapshot it started from. An edit made while a request is in
 *   flight is a successor entry that exists only on the device; a pass that
 *   writes its own snapshot back deletes it, and FR-007 guarantees no surface
 *   ever said it was pending. `DrainPort.latest` is that re-read.
 * - **5c / FR-021** — a cold read resets `sending` to `queued` *before* any
 *   drain, or invariant 5 makes every later drain skip an entry that was in
 *   flight when the app was killed.
 * - **6 / FR-017** — a 409 on the idempotency key is a spent key, not a
 *   disagreement. It must be re-minted; replaying it 409s forever.
 * - **8a / FR-018** — the entry-level bound (`expireQueue`) *retains* the
 *   payload; the key-level sweep *deletes*. `sweepActiveKey` is what keeps the
 *   deleting rule off the active identity's unsent work.
 * - **10 / FR-017** — past the server's 24 h replay window the key is no longer
 *   a dedupe token, so the entry may not be retried blind: re-read first, then
 *   drop it or re-present it against the current revision.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";

import type { TaskResponse, TaskUpdateRequest } from "../../api/types";
import { newIdempotencyKey } from "../../utils/ids";
import {
  applyAccepted,
  applyRejected,
  applyTimeout,
  coalesce,
  expireQueue,
  dismissExpired,
  markSending,
  needsRereadBeforeSend,
  resetInterrupted,
  selectDrainable,
  type ClassificationEdit,
  type Millis,
  type MintIdempotencyKey,
} from "./classificationQueue";
import {
  loadQueue,
  loadServerTime,
  saveQueue,
  sweepAllIdentities,
} from "./classificationQueue.storage";
import type { PendingClassificationChange } from "./classificationTypes";
import {
  decideOnRejection,
  rejectionFromError,
  serverHoldsIntendedValue,
  serverStillHoldsOriginal,
  type ClassificationState,
  type ConflictDecision,
} from "./conflictDecision";
import {
  identityStoreGeneration,
  queueKey,
  type ClassificationIdentity,
} from "./storageKeys";

// ------------------------------------------------------------------ contracts

/** A task's classification as the server holds it, with the revision that
 *  proves it. The drain never needs the rest of a `TaskResponse`. */
export interface ServerTaskState {
  revision: number;
  projectId: string | null;
  tagIds: string[];
}

export function serverStateOf(task: TaskResponse): ServerTaskState {
  return { revision: task.revision, projectId: task.project_id, tagIds: [...task.tag_ids] };
}

export interface DrainRequest {
  taskId: string;
  payload: TaskUpdateRequest;
  idempotencyKey: string;
}

/**
 * Everything the drain needs from the outside world, injected.
 *
 * A port rather than the API client itself: the pass is then a pure function of
 * its inputs and a set of fakes, which is the only way any of this is testable
 * in `mobile/`.
 */
export interface DrainPort {
  now(): Millis;
  mintKey: MintIdempotencyKey;
  send(request: DrainRequest): Promise<ServerTaskState>;
  reread(taskId: string): Promise<ServerTaskState>;
  /** Called before and after every attempt. The `sending` marker has to reach
   *  storage before the request goes out, or a kill mid-send loses the fact
   *  that an attempt happened at all. */
  persist?(queue: PendingClassificationChange[]): Promise<void>;
  /**
   * The queue as the device holds it *now*, or `undefined` when the caller can
   * no longer vouch for it — another identity has signed in, and one account's
   * queue may never be read, shown or sent under another's (SC-007).
   *
   * A pass owns one entry's outcome, never the whole queue. It can be awaiting
   * the server for the length of a request timeout, and an edit made in that
   * window lives here and nowhere else: `coalesce` appends it as a successor
   * (invariant 5b) precisely so the acceptance of the entry in flight cannot
   * delete it. Omitting this leaves the pass deciding against the snapshot it
   * started from, which writes that successor back out of existence — silently,
   * because FR-007 means no surface ever said it was pending.
   */
  latest?(): readonly PendingClassificationChange[] | undefined;

  /**
   * Whether the pass still speaks for the identity it started under. Absent
   * means "always", for the callers that have no identity to lose.
   *
   * `latest` and `persist` protect what the pass *reads and writes on the
   * device*; this protects what it *sends*. They are not the same guarantee.
   * The api client resolves its base URL from `currentServerUrl()` and carries
   * whatever cookie the app now holds, so a pass that keeps stepping after
   * somebody else has signed in issues account A's mutations against account
   * B's session — over the wire, against real data, which is precisely what
   * SC-007 forbids. Isolating A's *storage* while still sending A's writes
   * under B is the worst of both.
   */
  owned?(): boolean;
}

/** What the drain must do next with one entry. */
export type DrainStep =
  | { kind: "idle"; queue: PendingClassificationChange[] }
  | { kind: "reread"; queue: PendingClassificationChange[]; entry: PendingClassificationChange }
  | {
      kind: "send";
      queue: PendingClassificationChange[];
      entry: PendingClassificationChange;
      request: DrainRequest;
    };

export interface DrainResolution {
  kind: "accepted" | "already-applied" | "re-presented" | "conflicted" | "retry" | "error";
  queue: PendingClassificationChange[];
  /** SC-004: the footer advances whenever the server answered. */
  advanceLastSynced: boolean;
  /** Whether the pass may move on to the next entry. */
  continueDraining: boolean;
  /** Present for every rejection. FR-012's correlation id travels on it. */
  decision?: ConflictDecision;
}

export type DrainStop =
  | "drained"
  | "conflict"
  | "retry-later"
  | "error"
  | "limit"
  /** Somebody else signed in mid-pass. Nothing further may be sent. */
  | "disowned";

export interface DrainPassResult {
  queue: PendingClassificationChange[];
  /** Entries the server accepted, or already held. */
  settled: number;
  lastSyncedAt?: string;
  stoppedBecause: DrainStop;
  /** Newest last. Everything the person may need to be told about. */
  decisions: ConflictDecision[];
  /**
   * Every idempotency key this pass ever held, including the ones it removed
   * and the ones it re-minted away from.
   *
   * `queue` alone cannot say whether a key missing from it was *settled* or
   * simply never seen, and those need opposite treatment when the result is
   * written back over a queue that has moved on — see `mergePassResult`.
   */
  decidedKeys: string[];
}

/**
 * A bound on one pass, so no state of the queue can spin the device.
 *
 * Every step either settles an entry or stops the pass, so the bound is not
 * reachable by design — it exists because "not reachable by design" is exactly
 * what was said about the two loops this feature has already had.
 */
export const MAX_DRAIN_STEPS = 25;

// ------------------------------------------------------------------- the plan

/**
 * The request body for one entry.
 *
 * A field the change never touched is **omitted**, and a deliberate clear is
 * sent as an explicit `null` (FR-001, FR-003). The backend's models are
 * `extra="forbid"`, so nothing else may appear here.
 */
export function buildUpdatePayload(entry: PendingClassificationChange): TaskUpdateRequest {
  const payload: TaskUpdateRequest = { expected_revision: entry.observedRevision };
  if (entry.value.projectId !== undefined) {
    payload.project_id = entry.value.projectId;
  }
  if (entry.value.tagIds !== undefined) {
    payload.tag_ids = [...entry.value.tagIds];
  }
  return payload;
}

/**
 * Picks the next entry and takes it in flight, or reports that there is
 * nothing to do.
 *
 * The returned queue already carries the `sending` marker, so a second trigger
 * handed that queue sees the entry in flight and skips it — which is the whole
 * of FR-017's single flight. The caller must persist the returned queue before
 * the request goes out.
 */
export function planDrainStep(
  queue: readonly PendingClassificationChange[],
  now: Millis,
): DrainStep {
  const entry = selectDrainable(queue);
  if (!entry) {
    return { kind: "idle", queue: [...queue] };
  }

  const next = markSending(queue, entry.idempotencyKey, now);
  const marked = next.find((candidate) => candidate.idempotencyKey === entry.idempotencyKey) ?? entry;

  if (needsRereadBeforeSend(entry, now)) {
    // Invariant 10: the server has forgotten this key, so the key no longer
    // makes a retry a replay. Look before leaping.
    return { kind: "reread", queue: next, entry: marked };
  }

  return {
    kind: "send",
    queue: next,
    entry: marked,
    request: {
      taskId: marked.taskId,
      payload: buildUpdatePayload(marked),
      idempotencyKey: marked.idempotencyKey,
    },
  };
}

/**
 * Is this rejection worth a re-read before anyone is asked anything?
 *
 * Only a 409 on the *task*. Without the re-read, design.md's "already applied"
 * state is unreachable and a person is prompted to choose between two values
 * that happen to be the same one — the disagreement the sheet exists for is
 * not actually there.
 */
export function shouldRereadAfterRejection(error: unknown): boolean {
  const rejection = rejectionFromError(error);
  return rejection.status === 409 && rejection.detail?.resource === "Task";
}

// --------------------------------------------------------------- the outcomes

/** The server applied it: the entry goes, and any successor edit made while it
 *  was in flight is re-based onto the revision the server returned (5b). */
export function resolveSendSuccess(
  queue: readonly PendingClassificationChange[],
  entry: PendingClassificationChange,
  task: ServerTaskState,
): DrainResolution {
  return {
    kind: "accepted",
    queue: applyAccepted(queue, entry.idempotencyKey, task.revision),
    advanceLastSynced: true,
    continueDraining: true,
  };
}

export interface SendRejectionInput {
  queue: readonly PendingClassificationChange[];
  entry: PendingClassificationChange;
  error: unknown;
  mintKey: MintIdempotencyKey;
  /** The task as a re-read found it, when one was made. Supplying it is what
   *  lets a rejection resolve as "already applied" instead of a prompt. */
  serverTask?: ServerTaskState | null;
}

/**
 * What a failed attempt means, and what happens to the entry.
 *
 * The decision itself belongs to `conflictDecision.ts`; this maps it onto the
 * queue. The load-bearing line is the last one: when the decision says the key
 * may not be reused, a new one is **minted here**. Omitting the minter parks the
 * entry as `conflicted` — safe, but it asks a person about a client bug, and
 * reusing the key instead would send the identical request forever.
 */
export function resolveSendRejection({
  queue,
  entry,
  error,
  mintKey,
  serverTask,
}: SendRejectionInput): DrainResolution {
  const rejection = rejectionFromError(error);
  const serverState: ClassificationState | undefined = serverTask
    ? { projectId: serverTask.projectId, tagIds: serverTask.tagIds }
    : undefined;
  const decision = decideOnRejection({ rejection, entry, serverState });

  if (decision.nextSendState === "removed") {
    return {
      kind: "already-applied",
      // The server holds exactly what this entry intended, so its successors
      // start from there too.
      queue: applyAccepted(
        queue,
        entry.idempotencyKey,
        serverTask?.revision ?? entry.observedRevision,
      ),
      advanceLastSynced: true,
      continueDraining: true,
      decision,
    };
  }

  if (decision.nextSendState === "conflicted") {
    return {
      // `revision-conflict` is the reducer's word for "park it and ask"; a
      // deleted task (404) parks the same way for the same reason.
      // The reason rides onto the entry: `conflicted` alone cannot tell a
      // stale revision from a target deleted elsewhere, and the sheet needs
      // that to avoid offering "Keep mine, replace theirs" for a task that no
      // longer exists.
      queue: applyRejected(queue, entry.idempotencyKey, "revision-conflict", undefined, {
        reason: decision.reason,
        correlationId: decision.correlationId,
        // What the re-read saw, kept because it is the only revision the
        // resolution can be aimed at — see `conflictServerRevision` — and the
        // only values on the device that are the server's own, which is what
        // M-04's third row states and what the choice turns on.
        ...(serverTask
          ? {
              serverRevision: serverTask.revision,
              serverValue: { projectId: serverTask.projectId, tagIds: [...serverTask.tagIds] },
            }
          : {}),
      }),
      kind: decision.kind === "prompt" ? "conflicted" : "error",
      advanceLastSynced: false,
      continueDraining: false,
      decision,
    };
  }

  if (decision.reuseIdempotencyKey) {
    // Timeout, lost connection, 5xx, 401: the write may already have landed, so
    // the same key goes back out. That is what makes the retry at-most-once.
    return {
      kind: "retry",
      queue: applyTimeout(queue, entry.idempotencyKey),
      advanceLastSynced: false,
      continueDraining: false,
      decision,
    };
  }

  return {
    kind: "error",
    queue: applyRejected(queue, entry.idempotencyKey, "idempotency-key-conflict", mintKey, {
      reason: decision.reason,
      correlationId: decision.correlationId,
    }),
    advanceLastSynced: false,
    continueDraining: false,
    decision,
  };
}

export interface RereadInput {
  queue: readonly PendingClassificationChange[];
  entry: PendingClassificationChange;
  task: ServerTaskState;
  mintKey: MintIdempotencyKey;
}

/**
 * Invariant 10, the half that runs *before* a send.
 *
 * Past the replay window the entry is either already unnecessary or must be
 * re-aimed:
 *
 * - the server already holds what it intended → drop it, advance last-synced,
 *   and ask nobody anything. This is the one explicit exception to SC-005:
 *   nothing is overwritten and nothing is discarded, so there is no decision to
 *   put to a person and inventing one would be noise.
 * - the server still holds what the phone last showed → nobody else has been
 *   here, so this is a plain resend. Re-present it against the revision just
 *   observed, with a new key and a refreshed `originalValue`. Refreshing the
 *   original is the single sanctioned exception to invariant 7, and it is sound
 *   precisely because the device has *just* read the server: the conflict
 *   prompt would otherwise diff against a value up to 30 days stale and name
 *   the wrong disagreement.
 * - the server holds a **third** value → somebody else moved a field this
 *   change is about, and FR-008 says the person decides. Park it for M-04.
 *
 * That third branch did not exist, and its absence was a silent overwrite on a
 * path where the device had the evidence in hand. Re-presenting rebases
 * `observedRevision` onto the revision just read, so the send that follows
 * cannot 409 — and the 409 is the only thing that would ever have opened the
 * sheet. An entry attempted once, left more than 24h (FR-018 permits 30 days),
 * on a task somebody else reclassified meanwhile, therefore overwrote their
 * work without a word: FR-008's "MUST NOT decide for them" and SC-005's "zero
 * classifications are overwritten or discarded silently", both, on the one path
 * where asking was free. The comment above this function reasoned about "the
 * conflict prompt" while the code guaranteed it could not fire.
 *
 * `lastEditedAt` deliberately does not move — a re-present is not an edit, and
 * refreshing it would keep an entry alive past FR-018's bound forever.
 */
export function resolveRereadOutcome({
  queue,
  entry,
  task,
  mintKey,
}: RereadInput): DrainResolution {
  const serverState: ClassificationState = { projectId: task.projectId, tagIds: task.tagIds };

  if (serverHoldsIntendedValue(entry.value, serverState)) {
    return {
      kind: "already-applied",
      queue: applyAccepted(queue, entry.idempotencyKey, task.revision),
      advanceLastSynced: true,
      continueDraining: true,
    };
  }

  if (!serverStillHoldsOriginal(entry.value, entry.originalValue, serverState)) {
    return {
      kind: "conflicted",
      // The same parking the 409 path uses, for the same reason and with the
      // same evidence: the revision aims a resolution, the values are what it
      // is about, and neither is recorded anywhere else on the device.
      //
      // `originalValue` is pointedly NOT refreshed on this branch. It is what
      // the phone showed, M-04's first row states it as exactly that, and
      // replacing it with the server's value collapses the three-way choice
      // into a two-way one in which the person's own starting point has
      // quietly become their opponent's.
      queue: applyRejected(queue, entry.idempotencyKey, "revision-conflict", undefined, {
        reason: "stale-revision",
        serverRevision: task.revision,
        serverValue: { projectId: serverState.projectId, tagIds: [...serverState.tagIds] },
      }),
      // False, as on the 409 path: a conflicted pass settles nothing, and a
      // footer reading "synced just now" over an unanswered question overstates
      // what the device actually knows.
      advanceLastSynced: false,
      continueDraining: false,
    };
  }

  const represented = queue.map((candidate) =>
    candidate.idempotencyKey === entry.idempotencyKey && candidate.sendState !== "expired"
      ? {
          ...candidate,
          sendState: "queued" as const,
          observedRevision: task.revision,
          originalValue: { projectId: task.projectId, tagIds: [...task.tagIds] },
          idempotencyKey: mintKey(),
          // A fresh key opens a fresh replay window, so the next step sends
          // rather than re-reading again.
          firstSentAt: undefined,
        }
      : candidate,
  );

  return {
    kind: "re-presented",
    queue: represented,
    advanceLastSynced: true,
    continueDraining: true,
  };
}

function stopReasonFor(resolution: DrainResolution): DrainStop {
  if (resolution.kind === "conflicted") {
    return "conflict";
  }
  return resolution.kind === "retry" ? "retry-later" : "error";
}

/**
 * One drain pass: send what can be sent, stop at the first thing that needs
 * someone or something else.
 *
 * The pass is sequential on purpose. Two entries in flight at once is not
 * forbidden by invariant 5 — which is per entry — but it doubles the ways a
 * half-drained queue can be observed for no gain on a queue that is almost
 * always one or two entries long.
 */
export async function drainQueue(
  queue: readonly PendingClassificationChange[],
  port: DrainPort,
): Promise<DrainPassResult> {
  let current: PendingClassificationChange[] = [...queue];
  let settled = 0;
  let lastSyncedAt: string | undefined;
  const decisions: ConflictDecision[] = [];

  /** Every key this pass has had in hand, so the caller can tell an entry this
   *  pass settled from one it never saw (`mergePassResult`). */
  const decided = new Set<string>();
  const remember = (entries: readonly PendingClassificationChange[]): void => {
    for (const entry of entries) {
      decided.add(entry.idempotencyKey);
    }
  };
  remember(current);

  /**
   * Re-reads the queue from the device, and is called after **every** await
   * below. That is invariant 5b at this layer.
   *
   * A pass owns one entry's outcome, never the whole queue. While it waits on
   * the server — up to a request timeout — an edit to the same task becomes a
   * successor entry (`coalesce`) that exists only in the live queue. Resolving
   * against the snapshot instead of the live queue therefore produces a queue
   * with that successor missing, and the write straight afterwards makes the
   * deletion permanent. Nothing surfaces it: no request ever carried the edit,
   * and FR-007 means no marker ever said it was pending.
   *
   * Adopting *before* the resolution rather than merging after it is what makes
   * the successor land as well as survive: `applyAccepted` can only re-base an
   * entry it can see, and a successor still carrying the revision from before
   * the acceptance would 409 on its own turn.
   */
  const adopt = (known: PendingClassificationChange[]): PendingClassificationChange[] => {
    const live = port.latest?.();
    const next = live === undefined ? known : [...live];
    remember(next);
    return next;
  };

  const commit = async (
    next: PendingClassificationChange[],
  ): Promise<PendingClassificationChange[]> => {
    await port.persist?.(next);
    return adopt(next);
  };

  /** Absent means the caller has no identity that can be taken from it. */
  const owned = (): boolean => port.owned?.() ?? true;

  const stop = (
    queue: PendingClassificationChange[],
    stoppedBecause: DrainStop,
  ): DrainPassResult => ({
    queue,
    settled,
    lastSyncedAt,
    stoppedBecause,
    decisions,
    decidedKeys: [...decided],
  });

  for (let step = 0; step < MAX_DRAIN_STEPS; step += 1) {
    if (!owned()) {
      // Checked at the head of every iteration, so no request is ever *issued*
      // under an identity that has been replaced. An iteration already under
      // way still finishes its own entry — that outcome is unambiguously this
      // pass's work, and abandoning it mid-flight is what would lose it.
      return stop(current, "disowned");
    }

    const plan = planDrainStep(current, port.now());
    if (plan.kind === "idle") {
      return stop(plan.queue, "drained");
    }

    // The `sending` marker must be on the device before the request leaves, or
    // a kill mid-send leaves no trace that an attempt was ever made.
    current = await commit(plan.queue);

    // And again here, because `commit` is an await. The head-of-iteration check
    // has already passed by the time that storage write resumes, so an identity
    // change landing inside it would let the *first* request of this step go
    // out under the new session — the rejection-path check below only guards
    // the optional second one. Every request this pass issues is now preceded
    // by a check with no await between the two.
    if (!owned()) {
      return stop(current, "disowned");
    }

    let resolution: DrainResolution;
    if (plan.kind === "reread") {
      try {
        // Bound to a name rather than awaited inside the call: the queue has to
        // be re-read *after* the request settles, not before it went out.
        const task = await port.reread(plan.entry.taskId);
        current = adopt(current);
        resolution = resolveRereadOutcome({
          queue: current,
          entry: plan.entry,
          task,
          mintKey: port.mintKey,
        });
      } catch (error) {
        // Nothing was sent, so the ordinary rejection rules apply: unreachable
        // goes back to `queued` with the same key and waits.
        current = adopt(current);
        resolution = resolveSendRejection({
          queue: current,
          entry: plan.entry,
          error,
          mintKey: port.mintKey,
        });
      }
    } else {
      try {
        const task = await port.send(plan.request);
        current = adopt(current);
        resolution = resolveSendSuccess(current, plan.entry, task);
      } catch (error) {
        let serverTask: ServerTaskState | null = null;
        // `owned()` again, because this is a *second* request in the same
        // iteration and the identity can have changed during the first. A
        // re-read issued now would ask the new session about the old account's
        // task and answer the conflict with whatever it said.
        if (shouldRereadAfterRejection(error) && owned()) {
          try {
            serverTask = await port.reread(plan.entry.taskId);
          } catch {
            // Offline again between the two calls. Deciding without the server's
            // value prompts, which is the safe direction: it asks rather than
            // resolving anything on its own.
            serverTask = null;
          }
        }
        current = adopt(current);
        resolution = resolveSendRejection({
          queue: current,
          entry: plan.entry,
          error,
          mintKey: port.mintKey,
          serverTask,
        });
      }
    }

    remember(resolution.queue);
    current = await commit(resolution.queue);
    if (resolution.decision) {
      decisions.push(resolution.decision);
    }
    if (resolution.advanceLastSynced) {
      lastSyncedAt = new Date(port.now()).toISOString();
    }
    if (resolution.kind === "accepted" || resolution.kind === "already-applied") {
      settled += 1;
    }
    if (!resolution.continueDraining) {
      return stop(current, stopReasonFor(resolution));
    }
  }

  return stop(current, "limit");
}

/**
 * Reconciles a finished pass with the queue the device holds now — invariant
 * 5b, at the one seam `DrainPort.latest` cannot reach.
 *
 * `latest` repairs the pass's view after every await, so the result speaks for
 * every entry the pass saw. It cannot speak for one queued *after* its last
 * adoption: the pass resolving, returning, and its caller writing the result
 * back are separated by a microtask, and `enqueue` writes the queue
 * synchronously. Assigning the result over that is the same deletion `latest`
 * exists to prevent, arriving through the back door — silent, because no
 * request ever carried the edit and FR-007 means no surface said it was
 * pending.
 *
 * Identity is the idempotency key, which is what every transition in
 * `classificationQueue.ts` already keys off. `decidedKeys` is what makes the
 * merge safe in both directions: a key the pass held and removed was *settled*
 * and must not come back, while a key it never saw is a concurrent successor
 * and must survive. Without it the two are indistinguishable, and a merge that
 * keeps everything missing from the result resurrects every accepted entry.
 */
export function mergePassResult(
  result: readonly PendingClassificationChange[],
  decidedKeys: readonly string[],
  live: readonly PendingClassificationChange[],
): PendingClassificationChange[] {
  const decided = new Set(decidedKeys);
  const resolved = new Set(result.map((entry) => entry.idempotencyKey));
  const successors = live.filter(
    (entry) => !resolved.has(entry.idempotencyKey) && !decided.has(entry.idempotencyKey),
  );
  // Appended, not spliced: `selectDrainable` orders by `firstQueuedAt`, and a
  // successor is by construction younger than everything the pass decided.
  return successors.length === 0 ? [...result] : [...result, ...successors];
}

// ------------------------------------------------------- reading the queue in

export interface HydratedQueue {
  /** Everything to persist: live entries and expired notices together. */
  queue: PendingClassificationChange[];
  expired: PendingClassificationChange[];
  /** Entries that expired on *this* read — the number worth announcing. */
  droppedCount: number;
}

/**
 * A cold read, in the order the two rules have to run in.
 *
 * `resetInterrupted` first (invariant 5c): `sending` is a liveness marker for a
 * process that is no longer running, and leaving it set means every later drain
 * skips the entry — never sent, never conflicted, never surfaced, dropped 30
 * days later by a rule the person was never shown.
 *
 * Then `expireQueue` (invariant 8), which moves an aged entry to `expired`
 * **retaining its payload** so a wrong device clock stays recoverable.
 */
export function hydrateQueue(
  stored: readonly PendingClassificationChange[],
  now: Millis,
  serverNow?: Millis,
): HydratedQueue {
  const revived = resetInterrupted(stored);
  const { kept, expired, droppedCount } = expireQueue(revived, now, serverNow);
  return { queue: [...kept, ...expired], expired, droppedCount };
}

/**
 * The key the cross-identity sweep must treat as protected — invariant 8a.
 *
 * The sweep *deletes*; `expireQueue` *retains*. The sweep only knows to leave
 * the active identity's queue alone if it is told which key that is, and
 * handing it `null` while somebody is signed in makes every key foreign,
 * including this one — which destroys the payload FR-018 promises is retained
 * until the person dismisses the notice, and then tells them a count for work
 * they can no longer recover.
 *
 * The two stores of one identity share a suffix, so either key protects both.
 */
export function sweepActiveKey(identity: ClassificationIdentity | null): string | null {
  return identity ? queueKey(identity.serverUrl, identity.accountId) : null;
}

// ------------------------------------------------------ what the screen needs

export interface PendingConflict {
  entry: PendingClassificationChange;
  /** 1-based, for M-04's "1 of 3". */
  index: number;
  total: number;
}

/** One conflict at a time, oldest first (M-04, "partial failure"). */
export function selectPendingConflict(
  queue: readonly PendingClassificationChange[],
): PendingConflict | undefined {
  const conflicted = queue
    .filter((entry) => entry.sendState === "conflicted")
    .sort((a, b) => Date.parse(a.firstQueuedAt) - Date.parse(b.firstQueuedAt));
  return conflicted.length === 0
    ? undefined
    : { entry: conflicted[0], index: 1, total: conflicted.length };
}

/** The live entry for a task, if any. An expired one is a notice, not a value. */
export function pendingEntryFor(
  queue: readonly PendingClassificationChange[],
  taskId: string,
): PendingClassificationChange | undefined {
  return queue.find((entry) => entry.taskId === taskId && entry.sendState !== "expired");
}

/**
 * FR-007. What the row shows: the queued value if there is one, the server's
 * otherwise, and no marker either way. A person is never asked to reconcile
 * per-field sync bookkeeping — that is the app's problem.
 *
 * An `expired` entry deliberately falls through to the server's value: the
 * change is gone, and the notice of FR-018 is what says so.
 */
export function effectiveClassification(
  server: ClassificationState,
  entry: PendingClassificationChange | undefined,
): ClassificationState {
  if (!entry || entry.sendState === "expired") {
    return { projectId: server.projectId, tagIds: [...server.tagIds] };
  }
  return {
    projectId: entry.value.projectId !== undefined ? entry.value.projectId : server.projectId,
    tagIds: entry.value.tagIds !== undefined ? [...entry.value.tagIds] : [...server.tagIds],
  };
}

export type ClassificationField = "project" | "tags";

export type ExpiredFieldNotice =
  | { field: "project"; dropped: string | null; revertedTo: string | null }
  | { field: "tags"; dropped: string[]; revertedTo: string[] };

export interface ExpiredChangeNotice {
  taskId: string;
  /** "from 31 days ago" is rendered from this. */
  lastEditedAt: string;
  fields: ExpiredFieldNotice[];
}

/**
 * FR-018 / SC-003 — what the person is told when a change is dropped.
 *
 * Ids, not names: resolving names needs the picker lists and belongs to the
 * screen. What matters here is that the notice can name **which field and what
 * it reverted to**. A bare count is not enough for work no surface in the app
 * has ever shown as pending — FR-007 removed every per-change marker, so
 * without this the value simply appears to change back on its own.
 *
 * `serverState` is the value the row shows now. With none supplied it falls
 * back to what the device last displayed, which is the device's only offline
 * knowledge of the server and is labelled as such wherever it is rendered.
 */
export function describeExpiredChange(
  entry: PendingClassificationChange,
  serverState?: ClassificationState | null,
): ExpiredChangeNotice | null {
  if (entry.sendState !== "expired") {
    return null;
  }
  const current = serverState ?? entry.originalValue;
  const fields: ExpiredFieldNotice[] = [];
  if (entry.value.projectId !== undefined) {
    fields.push({ field: "project", dropped: entry.value.projectId, revertedTo: current.projectId });
  }
  if (entry.value.tagIds !== undefined) {
    fields.push({ field: "tags", dropped: [...entry.value.tagIds], revertedTo: [...current.tagIds] });
  }
  return fields.length === 0
    ? null
    : { taskId: entry.taskId, lastEditedAt: entry.lastEditedAt, fields };
}

/** The account-level total for the dismiss-once notice (FR-018). */
export function countExpired(queue: readonly PendingClassificationChange[]): number {
  return queue.filter((entry) => entry.sendState === "expired").length;
}

// --------------------------------------------------- resolving one conflict

/**
 * "Keep mine, replace theirs" (M-04).
 *
 * The revision the server just reported, and a **new key**: the resolved
 * payload carries a different `expected_revision`, and the server's request
 * hash covers it, so replaying the old key would 409 forever (invariant 6).
 * `lastEditedAt` does not move — the person chose, they did not edit, and
 * refreshing it would let a conflict loop outlive FR-018's bound.
 */
export function resolveConflictKeepMine(
  queue: readonly PendingClassificationChange[],
  entry: PendingClassificationChange,
  serverRevision: number,
  mintKey: MintIdempotencyKey,
): PendingClassificationChange[] {
  return queue.map((candidate) =>
    candidate.idempotencyKey === entry.idempotencyKey && candidate.sendState === "conflicted"
      ? {
          ...candidate,
          sendState: "queued" as const,
          observedRevision: serverRevision,
          idempotencyKey: mintKey(),
          firstSentAt: undefined,
        }
      : candidate,
  );
}

/**
 * The revision a resolution must be aimed at.
 *
 * The entry's own is what the 409's re-read **saw**. The fallback is the
 * screen's copy of the task, which nothing refreshes when a pass ends in a
 * conflict — a conflicted pass settles nothing, so `onSynced` never fires. So
 * preferring the fallback aims the retry at the revision the server has
 * already rejected once, and goes on doing so: the same 409, the same sheet,
 * for ever. It is used only when no re-read could be made at all.
 */
export function resolutionRevision(
  entry: PendingClassificationChange,
  fallback: number,
): number {
  return entry.conflictServerRevision ?? fallback;
}

/**
 * What M-04 states the server holds now.
 *
 * The same argument as `resolutionRevision`, applied to the values rather than
 * the revision, because the two are read from one re-read and the sheet must
 * not describe the server from two different moments. The fallback is the
 * screen's copy of the task, which nothing refreshes when a pass ends in a
 * conflict — so preferring it names whatever that copy was loaded with, which
 * on the path this exists for is a value the server had already stopped
 * holding. It is used only for an entry parked with no re-read at all,
 * including one parked before the field existed, where the screen's copy is
 * the only server value the device has.
 */
export function conflictServerState(
  entry: PendingClassificationChange,
  fallback: ServerTaskState,
): ServerTaskState {
  const value = entry.conflictServerValue;
  if (value === undefined) {
    return fallback;
  }
  return {
    revision: entry.conflictServerRevision ?? fallback.revision,
    projectId: value.projectId,
    tagIds: [...value.tagIds],
  };
}

/** "Discard mine, keep the server's" (M-04). The entry goes, and a successor
 *  edit made while it was in flight starts from the server's revision. */
export function resolveConflictDiscardMine(
  queue: readonly PendingClassificationChange[],
  entry: PendingClassificationChange,
  serverRevision: number,
): PendingClassificationChange[] {
  return applyAccepted(queue, entry.idempotencyKey, serverRevision);
}

// ------------------------------------------------------------------- the hook

/** The slice of the API client the drain uses. Narrow on purpose: the hook
 *  takes it as an argument, so nothing here imports the session. */
export interface ClassificationApiPort {
  getTask(taskId: string, signal?: AbortSignal): Promise<TaskResponse>;
  updateTask(
    taskId: string,
    payload: TaskUpdateRequest,
    idempotencyKey: string,
  ): Promise<TaskResponse>;
}

export interface UseClassificationQueueOptions {
  /** Both halves of the storage key, resolved from persisted state so a cold
   *  start with no connection can still name it. `null` when nobody is signed
   *  in — the queue is then neither read nor written. */
  identity: ClassificationIdentity | null;
  api: ClassificationApiPort;
  /** The rollout flag (FR-015). Off means the queue is not even rehydrated. */
  enabled?: boolean;
  /** Called after a pass that changed anything on the server, so the caller can
   *  refetch. This is also the "after a successful request" drain trigger's
   *  other half. */
  onSynced?: () => void;
}

export interface ClassificationQueue {
  /** Everything stored for this identity, live entries and expired notices. */
  queue: PendingClassificationChange[];
  /** False until the cold read has run; the screen must not enqueue before it,
   *  or the first edit would be written over a queue it never read. */
  ready: boolean;
  /** True when that read failed rather than not having finished. `ready` stays
   *  false either way — the queue is still unknown, and an edit made now would
   *  still overwrite it — but a failure is not a wait, and the screen says so
   *  instead of promising an arrival that is not coming. */
  readFailed: boolean;
  /** SC-004. Null until this device has seen the server answer. */
  lastSyncedAt: string | null;
  /** M-04, one at a time. */
  conflict: PendingConflict | undefined;
  /** FR-018's account-level total, for the dismiss-once notice. */
  expiredTotal: number;
  /** Entries that expired on the most recent cold read. */
  droppedThisLaunch: number;
  pendingFor(taskId: string): PendingClassificationChange | undefined;
  expiredNoticeFor(taskId: string, server?: ClassificationState | null): ExpiredChangeNotice | null;
  enqueue(edit: Omit<ClassificationEdit, "accountId" | "serverUrl">): Promise<void>;
  drain(): Promise<void>;
  keepMine(serverRevision: number): Promise<void>;
  discardMine(serverRevision: number): Promise<void>;
  dismissExpiredNotice(taskId: string): Promise<void>;
}

const EMPTY: PendingClassificationChange[] = [];

export function useClassificationQueue(
  options: UseClassificationQueueOptions,
): ClassificationQueue {
  const { identity, api, enabled = true, onSynced } = options;
  const [queue, setQueue] = useState<PendingClassificationChange[]>(EMPTY);
  const [ready, setReady] = useState(false);
  const [readFailed, setReadFailed] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [droppedThisLaunch, setDroppedThisLaunch] = useState(0);

  const queueRef = useRef<PendingClassificationChange[]>(EMPTY);
  const identityRef = useRef<ClassificationIdentity | null>(null);
  // Written in an effect, not during render: mutating a ref while rendering is
  // not safe under concurrent rendering, which is what `react-hooks/refs`
  // guards. These exist only to keep the drain from closing over a stale api
  // or callback, and the drain never runs during render.
  const apiRef = useRef(api);
  const onSyncedRef = useRef(onSynced);
  useEffect(() => {
    apiRef.current = api;
    onSyncedRef.current = onSynced;
  });
  /** One pass at a time. The queue's own `sending` marker is what makes a
   *  concurrent send impossible; this only stops two passes interleaving their
   *  writes to the same key. */
  const drainingRef = useRef(false);

  const serverUrl = identity?.serverUrl ?? null;
  const accountId = identity?.accountId ?? null;

  /**
   * Device writes, in order, each persisting the queue the device holds *at the
   * moment it runs* rather than the snapshot its caller captured.
   *
   * Two writers share this key — `enqueue` and the drain's `persist` — and both
   * used to hand `saveQueue` an array captured before their own await. Nothing
   * serialised them, and AsyncStorage is a bridge to native, so the two settle
   * in whatever order the platform finishes them. The loser overwrote the
   * winner wholesale: a completed pass could be replaced on the device by a
   * queue whose entries the server had already applied, and invariant 5c then
   * revived and replayed them on the next launch, the successor among them
   * carrying the revision it was queued with rather than the one that was
   * accepted — a conflict of the app's own making.
   *
   * `snapshot` is for the one caller that must not read the live queue: a pass
   * whose identity has since been replaced may still finish its own entry into
   * its own key, but `queueRef` now belongs to somebody else (SC-007).
   */
  const writeChainRef = useRef<Promise<unknown>>(Promise.resolve());

  const persistLive = useCallback(
    (
      active: ClassificationIdentity,
      snapshot?: PendingClassificationChange[],
      /** The generation of the *operation* this write belongs to, when that
       *  operation is longer-lived than the write — a drain pass, whose request
       *  may have been in flight across a whole sign-out. Omitted by callers
       *  that are themselves the operation, like a single enqueue. */
      passGeneration?: number,
    ): Promise<void> => {
      // Captured now, used only as the floor if the ref stops being `active`'s
      // before this write's turn comes.
      const scheduled = snapshot ?? queueRef.current;
      // What matters is not whether this identity has ever been forgotten, but
      // whether it was forgotten after the operation this write belongs to
      // began. For a lone enqueue that is now; for a drain pass it is when the
      // pass started, which is why it may be passed in — see below.
      const generation =
        passGeneration ?? identityStoreGeneration(active.serverUrl, active.accountId);
      const write = writeChainRef.current.then(() => {
        // `queueRef` is read late on purpose — that is what makes a write that
        // waited behind another persist what the device holds *now*. But the
        // identity-change effect sets `queueRef.current = EMPTY` the moment an
        // identity goes away, and a 401 does exactly that. A write for A still
        // queued at that instant would then call `saveQueue(A, [])` and delete
        // A's persisted queue — the unsent work FR-011 keeps *specifically*
        // through an involuntary end, destroyed by the mechanism meant to stop
        // writes clobbering each other. Read live only while the ref is still
        // A's; otherwise it says nothing about A at all.
        const live = identityRef.current === active ? queueRef.current : scheduled;
        return saveQueue(active, snapshot ?? live, Date.now(), generation);
      });
      // The chain must survive a failed write, or one rejected save would strand
      // every later one behind it. The caller still sees its own rejection.
      writeChainRef.current = write.catch(() => undefined);
      return write;
    },
    [],
  );

  const commit = useCallback(
    async (next: PendingClassificationChange[]) => {
      queueRef.current = next;
      setQueue(next);
      const active = identityRef.current;
      if (active) {
        await persistLive(active);
      }
    },
    [persistLive],
  );

  const drain = useCallback(async () => {
    const active = identityRef.current;
    if (!active || drainingRef.current) {
      return;
    }
    drainingRef.current = true;
    try {
      // A pass speaks only for the identity it started under. Once somebody
      // else has signed in, the queue on the device is no longer this pass's to
      // read, show or send (SC-007); it may still finish its own entry into its
      // own key, which is the one thing that is unambiguously its work.
      const owns = (): boolean => identityRef.current === active;

      // Captured once, here, and used for every write this pass makes.
      //
      // Reading it per-write reads it when the write is *scheduled*, and a pass
      // whose request was in flight across a sign-out schedules its writes
      // afterwards — by which time the counter has already moved and, if the
      // same account signed back in, the pass captures the NEW generation and
      // sails through its own fence. Its stale successful result then deletes
      // the new session's queue; its stale failure resurrects the one the
      // sign-out discarded. The fence has to be stamped when the pass begins,
      // because the pass is the thing being fenced.
      const passGeneration = identityStoreGeneration(active.serverUrl, active.accountId);

      // `MAX_DRAIN_STEPS` bounds one *pass*, not the queue. An offline triage
      // session can leave far more than that behind, and a pass that stopped on
      // the cap simply returned with the rest still queued: nothing read
      // `stoppedBecause`, and the lock this pass holds is exactly what stops
      // the "after a successful request" trigger from starting another. The
      // 26th change then waited for an unrelated edit or a foreground
      // transition — on a queue whose whole purpose is to drain itself.
      //
      // Continued only while the cap was reached *and* the pass settled
      // something, so every turn strictly shortens the queue. Without that
      // second condition a queue of 25 permanently-retryable entries would spin
      // here for ever.
      for (;;) {
        const result = await drainQueue(queueRef.current, {
          now: () => Date.now(),
          mintKey: newIdempotencyKey,
          send: async ({ taskId, payload, idempotencyKey }) =>
            serverStateOf(await apiRef.current.updateTask(taskId, payload, idempotencyKey)),
          reread: async (taskId) => serverStateOf(await apiRef.current.getTask(taskId)),
          // Where an edit made while a request was in flight lives, and until
          // the pass adopts it, the only place it lives (invariant 5b).
          latest: () => (owns() ? queueRef.current : undefined),
          // What stops the pass *sending* under somebody else's session, which
          // `latest` and `persist` do not cover — they scope storage, not the
          // wire.
          owned: owns,
          persist: async (next) => {
            if (owns()) {
              // Before the storage write, and synchronously: an `enqueue`
              // racing this one must coalesce onto the marker this pass has
              // just set, not onto the queue as it was before the attempt.
              queueRef.current = next;
              setQueue(next);
              await persistLive(active, undefined, passGeneration);
              return;
            }
            await persistLive(active, next, passGeneration);
          },
        });
        if (owns()) {
          // The pass adopted the device's queue after every await, so this is
          // the live queue and not the snapshot it started from. Assigning the
          // snapshot is what deleted an edit made during a send.
          //
          // Merged rather than assigned, because "after every await" stops one
          // microtask short of here: the pass returning and this line running
          // are separated by one, and `enqueue` writes `queueRef` synchronously.
          const merged = mergePassResult(result.queue, result.decidedKeys, queueRef.current);
          queueRef.current = merged;
          setQueue(merged);
          // The pass's own last write went out before this merge existed, so
          // the device would otherwise keep a queue this line has superseded.
          await persistLive(active, undefined, passGeneration);
        }
        if (result.lastSyncedAt) {
          setLastSyncedAt(result.lastSyncedAt);
        }
        if (result.settled > 0) {
          onSyncedRef.current?.();
        }
        if (result.stoppedBecause !== "limit" || result.settled === 0 || !owns()) {
          return;
        }
      }
    } finally {
      drainingRef.current = false;
    }
  }, [persistLive]);

  // The cold read, and the drain trigger that follows it. Runs again on every
  // identity change: the key changes with it, and nothing of one identity's is
  // ever read under another (FR-011, SC-007).
  // Clearing the queue when the feature is off or the identity is unknown is a
  // derivation from props, so it happens during render. In an effect it would
  // cascade a render on every tick of a disabled hook.
  const inactive = !enabled || !serverUrl || !accountId;
  const [wasInactive, setWasInactive] = useState(inactive);
  if (wasInactive !== inactive) {
    setWasInactive(inactive);
    if (inactive) {
      setQueue(EMPTY);
      setReady(false);
      // A queue that is not read at all has not failed to be read: M-01c and a
      // signed-out screen carry no rows, so there is nothing to explain.
      setReadFailed(false);
    }
  }

  useEffect(() => {
    if (!enabled || !serverUrl || !accountId) {
      identityRef.current = null;
      queueRef.current = EMPTY;
      return;
    }
    const active: ClassificationIdentity = { serverUrl, accountId };
    identityRef.current = active;
    let cancelled = false;

    (async () => {
      // The guard runs before every write, not only before the state update.
      // These are destructive: a cold read for identity A that resumes after B
      // has signed in would sweep with A's key active and delete B's live
      // queue — the current person's unsent work, destroyed by a stale read of
      // somebody else's. `cancelled` protecting only the React state below is
      // not enough, because the damage is on the device.
      const stale = () => cancelled || identityRef.current !== active;
      if (stale()) {
        return;
      }
      try {
        // Invariant 8b, with 8a's guard: the sweep deletes foreign keys and
        // this identity's aged *cache*, and must be told which key is active or
        // it deletes this identity's unsent work too.
        await sweepAllIdentities({ activeKey: sweepActiveKey(active), now: Date.now() });
        if (stale()) {
          return;
        }
        // Invariant 5c: `sending` is reset on the way in, before any drain.
        const stored = await loadQueue(active, { resetInterrupted });
        const serverNow = await loadServerTime();
        const hydrated = hydrateQueue(stored, Date.now(), serverNow ?? undefined);
        if (stale()) {
          return;
        }
        // An explicit snapshot: `queueRef` is not this identity's until the
        // line below, so there is no live queue to read yet. Through the chain
        // all the same, so a later write cannot overtake the cold read's.
        await persistLive(active, hydrated.queue);
        if (stale()) {
          return;
        }
        queueRef.current = hydrated.queue;
        setQueue(hydrated.queue);
        setDroppedThisLaunch(hydrated.droppedCount);
        // The last time this device saw the server answer, from the persisted
        // server `Date` header. Never the device clock: feeding a device
        // timestamp into that store would launder it into FR-018's cross-check.
        setLastSyncedAt(serverNow === null ? null : new Date(serverNow).toISOString());
        setReadFailed(false);
        setReady(true);
        await drain();
      } catch {
        // The device store would not answer. `ready` deliberately does NOT
        // flip: the gate exists because an edit made before the queue is known
        // is persisted over unsent work, and a read that failed knows less than
        // one that has not finished — opening it here would be the overwrite
        // itself, on the one path where the device has already proved it cannot
        // be trusted to say what it holds. What changes is only what the person
        // is told: "checking" describes a wait that is now never going to end.
        if (!stale()) {
          setReadFailed(true);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [enabled, serverUrl, accountId, drain, persistLive]);

  // Trigger 1 of 2: the app comes to the foreground.
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state: AppStateStatus) => {
      if (state === "active") {
        void drain();
      }
    });
    return () => subscription.remove();
  }, [drain]);

  const enqueue = useCallback(
    async (edit: Omit<ClassificationEdit, "accountId" | "serverUrl">) => {
      const active = identityRef.current;
      if (!active) {
        return;
      }
      await commit(
        coalesce(
          queueRef.current,
          { ...edit, accountId: active.accountId, serverUrl: active.serverUrl },
          Date.now(),
          newIdempotencyKey,
        ),
      );
      // Trigger 2 of 2 is "after a successful request"; an edit made while
      // online should not wait for one, so it drains immediately and the
      // offline case simply fails and keeps the entry.
      await drain();
    },
    [commit, drain],
  );

  const conflict = useMemo(() => selectPendingConflict(queue), [queue]);

  const keepMine = useCallback(
    async (serverRevision: number) => {
      const pending = selectPendingConflict(queueRef.current);
      if (!pending) {
        return;
      }
      await commit(
        resolveConflictKeepMine(
          queueRef.current,
          pending.entry,
          resolutionRevision(pending.entry, serverRevision),
          newIdempotencyKey,
        ),
      );
      await drain();
    },
    [commit, drain],
  );

  const discardMine = useCallback(
    async (serverRevision: number) => {
      const pending = selectPendingConflict(queueRef.current);
      if (!pending) {
        return;
      }
      await commit(
        // Discarding re-bases any successor edit for this task onto the
        // server's revision, so a stale one here simply moves the conflict to
        // the next entry.
        resolveConflictDiscardMine(
          queueRef.current,
          pending.entry,
          resolutionRevision(pending.entry, serverRevision),
        ),
      );
    },
    [commit],
  );

  const dismissExpiredNotice = useCallback(
    async (taskId: string) => {
      await commit(dismissExpired(queueRef.current, taskId));
    },
    [commit],
  );

  const pendingFor = useCallback(
    (taskId: string) => pendingEntryFor(queue, taskId),
    [queue],
  );

  const expiredNoticeFor = useCallback(
    (taskId: string, server?: ClassificationState | null) => {
      const expired = queue.find(
        (entry) => entry.taskId === taskId && entry.sendState === "expired",
      );
      return expired ? describeExpiredChange(expired, server) : null;
    },
    [queue],
  );

  return {
    queue,
    ready,
    readFailed,
    lastSyncedAt,
    conflict,
    expiredTotal: countExpired(queue),
    droppedThisLaunch,
    pendingFor,
    expiredNoticeFor,
    enqueue,
    drain,
    keepMine,
    discardMine,
    dismissExpiredNotice,
  };
}
