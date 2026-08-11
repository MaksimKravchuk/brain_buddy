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
 * The four seams this file owns, each with its data-model invariant:
 *
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
  type ClassificationState,
  type ConflictDecision,
} from "./conflictDecision";
import { queueKey, type ClassificationIdentity } from "./storageKeys";

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

export type DrainStop = "drained" | "conflict" | "retry-later" | "error" | "limit";

export interface DrainPassResult {
  queue: PendingClassificationChange[];
  /** Entries the server accepted, or already held. */
  settled: number;
  lastSyncedAt?: string;
  stoppedBecause: DrainStop;
  /** Newest last. Everything the person may need to be told about. */
  decisions: ConflictDecision[];
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
      queue: applyRejected(queue, entry.idempotencyKey, "revision-conflict"),
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
    queue: applyRejected(queue, entry.idempotencyKey, "idempotency-key-conflict", mintKey),
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
 * - otherwise → re-present it against the revision just observed, with a new
 *   key and a refreshed `originalValue`. Refreshing the original is the single
 *   sanctioned exception to invariant 7, and it is sound precisely because the
 *   device has *just* read the server: the conflict prompt would otherwise diff
 *   against a value up to 30 days stale and name the wrong disagreement.
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

  for (let step = 0; step < MAX_DRAIN_STEPS; step += 1) {
    const plan = planDrainStep(current, port.now());
    if (plan.kind === "idle") {
      return { queue: plan.queue, settled, lastSyncedAt, stoppedBecause: "drained", decisions };
    }

    current = plan.queue;
    // The `sending` marker must be on the device before the request leaves, or
    // a kill mid-send leaves no trace that an attempt was ever made.
    await port.persist?.(current);

    let resolution: DrainResolution;
    if (plan.kind === "reread") {
      try {
        resolution = resolveRereadOutcome({
          queue: current,
          entry: plan.entry,
          task: await port.reread(plan.entry.taskId),
          mintKey: port.mintKey,
        });
      } catch (error) {
        // Nothing was sent, so the ordinary rejection rules apply: unreachable
        // goes back to `queued` with the same key and waits.
        resolution = resolveSendRejection({
          queue: current,
          entry: plan.entry,
          error,
          mintKey: port.mintKey,
        });
      }
    } else {
      try {
        resolution = resolveSendSuccess(current, plan.entry, await port.send(plan.request));
      } catch (error) {
        let serverTask: ServerTaskState | null = null;
        if (shouldRereadAfterRejection(error)) {
          try {
            serverTask = await port.reread(plan.entry.taskId);
          } catch {
            // Offline again between the two calls. Deciding without the server's
            // value prompts, which is the safe direction: it asks rather than
            // resolving anything on its own.
            serverTask = null;
          }
        }
        resolution = resolveSendRejection({
          queue: current,
          entry: plan.entry,
          error,
          mintKey: port.mintKey,
          serverTask,
        });
      }
    }

    current = resolution.queue;
    await port.persist?.(current);
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
      return { queue: current, settled, lastSyncedAt, stoppedBecause: stopReasonFor(resolution), decisions };
    }
  }

  return { queue: current, settled, lastSyncedAt, stoppedBecause: "limit", decisions };
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
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [droppedThisLaunch, setDroppedThisLaunch] = useState(0);

  const queueRef = useRef<PendingClassificationChange[]>(EMPTY);
  const identityRef = useRef<ClassificationIdentity | null>(null);
  const apiRef = useRef(api);
  apiRef.current = api;
  const onSyncedRef = useRef(onSynced);
  onSyncedRef.current = onSynced;
  /** One pass at a time. The queue's own `sending` marker is what makes a
   *  concurrent send impossible; this only stops two passes interleaving their
   *  writes to the same key. */
  const drainingRef = useRef(false);

  const serverUrl = identity?.serverUrl ?? null;
  const accountId = identity?.accountId ?? null;

  const commit = useCallback(async (next: PendingClassificationChange[]) => {
    queueRef.current = next;
    setQueue(next);
    const active = identityRef.current;
    if (active) {
      await saveQueue(active, next, Date.now());
    }
  }, []);

  const drain = useCallback(async () => {
    const active = identityRef.current;
    if (!active || drainingRef.current) {
      return;
    }
    drainingRef.current = true;
    try {
      const result = await drainQueue(queueRef.current, {
        now: () => Date.now(),
        mintKey: newIdempotencyKey,
        send: async ({ taskId, payload, idempotencyKey }) =>
          serverStateOf(await apiRef.current.updateTask(taskId, payload, idempotencyKey)),
        reread: async (taskId) => serverStateOf(await apiRef.current.getTask(taskId)),
        persist: async (next) => {
          queueRef.current = next;
          setQueue(next);
          await saveQueue(active, next, Date.now());
        },
      });
      queueRef.current = result.queue;
      setQueue(result.queue);
      if (result.lastSyncedAt) {
        setLastSyncedAt(result.lastSyncedAt);
      }
      if (result.settled > 0) {
        onSyncedRef.current?.();
      }
    } finally {
      drainingRef.current = false;
    }
  }, []);

  // The cold read, and the drain trigger that follows it. Runs again on every
  // identity change: the key changes with it, and nothing of one identity's is
  // ever read under another (FR-011, SC-007).
  useEffect(() => {
    if (!enabled || !serverUrl || !accountId) {
      identityRef.current = null;
      queueRef.current = EMPTY;
      setQueue(EMPTY);
      setReady(false);
      return;
    }
    const active: ClassificationIdentity = { serverUrl, accountId };
    identityRef.current = active;
    let cancelled = false;

    (async () => {
      // Invariant 8b, with 8a's guard: the sweep deletes foreign keys and this
      // identity's aged *cache*, and must be told which key is active or it
      // deletes this identity's unsent work too.
      await sweepAllIdentities({ activeKey: sweepActiveKey(active), now: Date.now() });
      // Invariant 5c: `sending` is reset on the way in, before any drain.
      const stored = await loadQueue(active, { resetInterrupted });
      const serverNow = await loadServerTime();
      const hydrated = hydrateQueue(stored, Date.now(), serverNow ?? undefined);
      await saveQueue(active, hydrated.queue, Date.now());
      if (cancelled || identityRef.current !== active) {
        return;
      }
      queueRef.current = hydrated.queue;
      setQueue(hydrated.queue);
      setDroppedThisLaunch(hydrated.droppedCount);
      // The last time this device saw the server answer, from the persisted
      // server `Date` header. Never the device clock: feeding a device
      // timestamp into that store would launder it into FR-018's cross-check.
      setLastSyncedAt(serverNow === null ? null : new Date(serverNow).toISOString());
      setReady(true);
      await drain();
    })();

    return () => {
      cancelled = true;
    };
  }, [enabled, serverUrl, accountId, drain]);

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
        resolveConflictKeepMine(queueRef.current, pending.entry, serverRevision, newIdempotencyKey),
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
      await commit(resolveConflictDiscardMine(queueRef.current, pending.entry, serverRevision));
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
