/**
 * FR-008 / FR-017 — what one rejection of a queued classification change means.
 *
 * Pure: given a rejection and the entry it belongs to, this says what happens
 * next. It never sends, never stores, and never reads the clock.
 *
 * **The two 409s.** The backend raises `ConflictError("Task", id)` for a stale
 * `expected_revision` and `ConflictError("Idempotency-Key", key)` when a stored
 * key arrives with a different request hash
 * (`backend/app/modules/tasks/service.py`). Both leave the wire as HTTP 409
 * with `{"message", "detail": {"resource", "id"}, "reference_id"}`
 * (`backend/app/api/errors.py`), so `detail.resource` is the only thing that
 * tells them apart. Only the first is a disagreement between two people. The
 * second is a client bug — the key was reused across a payload change — and a
 * blind retry with that same key 409s forever: the entry never sends, never
 * conflicts, never errors, and is dropped 30 days later by FR-018 with nothing
 * on screen having ever said it was pending.
 *
 * The 24-hour replay window of data-model invariant 10 is enforced by the drain
 * before it sends (re-read, then drop or re-present). This module answers only
 * what a rejection that has already happened means.
 */

import type {
  ClassificationValue,
  PendingClassificationChange,
  SendState,
} from "./classificationTypes";

/** A task's classification as the server currently holds it. */
export interface ClassificationState {
  projectId: string | null;
  tagIds: string[];
}

/** One failed send, flattened out of whatever the client threw. */
export interface SendRejection {
  /** Absent when the request never got an answer — a timeout or a lost
   *  connection. That case may already have applied server-side, which is why
   *  it is retried with the *same* idempotency key (FR-017). */
  status?: number;
  /** The backend's `detail` object: `{resource, id}`. */
  detail?: { resource?: string; id?: string } | null;
  serverMessage?: string;
  correlationId?: string;
}

export type DecisionReason =
  | "stale-revision"
  | "already-applied"
  | "unreachable"
  | "server-error"
  | "unauthenticated"
  | "idempotency-key-reuse"
  | "target-missing"
  | "rejected";

export interface ConflictDecision {
  /**
   * - `prompt` — open the M-04 conflict sheet; the person decides (FR-008).
   * - `already-applied` — resolved with no prompt; see below.
   * - `retry` — the same payload may be sent again unchanged.
   * - `error` — surfaced to the person; never sent again on its own.
   */
  kind: "prompt" | "already-applied" | "retry" | "error";
  reason: DecisionReason;
  /** `removed` means the entry leaves the queue. */
  nextSendState: SendState | "removed";
  /** `false` ⇒ a new key MUST be minted before this entry is sent again
   *  (FR-017, data-model invariant 6). */
  reuseIdempotencyKey: boolean;
  /** `false` ⇒ the drain must not send this entry again on its own. */
  automaticRetry: boolean;
  /** `true` ⇒ the last-synchronised footer advances (SC-004). */
  advanceLastSynced: boolean;
  /** `true` ⇒ the person is shown something; FR-012 requires the correlation
   *  id to travel with it. */
  surfaceToPerson: boolean;
  correlationId?: string;
  serverMessage?: string;
}

export interface RejectionContext {
  rejection: SendRejection;
  entry: PendingClassificationChange;
  /** The server's current classification, when the drain re-read the task.
   *  Supplying it is what enables the "already applied" resolution. */
  serverState?: ClassificationState | null;
}

function sameTagSet(intended: readonly string[], actual: readonly string[]): boolean {
  // Sets, not sequences: FR-002's acceptance scenario says the order tags were
  // added in does not change which tags the task has.
  const left = new Set(intended);
  const right = new Set(actual);
  if (left.size !== right.size) {
    return false;
  }
  for (const id of left) {
    if (!right.has(id)) {
      return false;
    }
  }
  return true;
}

/**
 * Does the server already hold the entry's intended net effect?
 *
 * `undefined` on a field means the change never touched it, so it is not
 * compared. `null` on `projectId` is a deliberate clear (FR-001) and is
 * satisfied only by the server holding no project.
 */
export function serverHoldsIntendedValue(
  value: ClassificationValue,
  serverState: ClassificationState,
): boolean {
  if (value.projectId !== undefined && value.projectId !== serverState.projectId) {
    return false;
  }
  if (value.tagIds !== undefined && !sameTagSet(value.tagIds, serverState.tagIds)) {
    return false;
  }
  return true;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

/**
 * Flatten whatever the send threw into a `SendRejection`.
 *
 * Duck-typed on purpose: it reads the shape `ApiError` happens to have
 * (`status`, `payload`, `correlationId`) without importing it, so this module
 * stays pure and the API client stays free to move. A throw with no numeric
 * `status` — a bare `TypeError` from `fetch` — is "we never got an answer",
 * which FR-019 insists is not the same thing as a rejection.
 */
export function rejectionFromError(error: unknown): SendRejection {
  const thrown = asRecord(error);
  if (thrown === null) {
    return {};
  }
  const payload = asRecord(thrown.payload);
  const detailSource = asRecord(payload?.detail);
  const resource = asString(detailSource?.resource);
  const identifier = asString(detailSource?.id);
  const detail =
    resource === undefined && identifier === undefined ? undefined : { resource, id: identifier };

  return {
    status: typeof thrown.status === "number" ? thrown.status : undefined,
    detail,
    serverMessage: asString(payload?.message) ?? asString(thrown.message),
    // The body's `reference_id` first, then the `X-Correlation-ID` header the
    // client captured — the same precedence `ApiError.referenceId` uses.
    correlationId: asString(payload?.reference_id) ?? asString(thrown.correlationId),
  };
}

/** Retriable with the same key and the same payload: the drain may just try again. */
function retry(reason: DecisionReason, rejection: SendRejection, automatic: boolean): ConflictDecision {
  return {
    kind: "retry",
    reason,
    nextSendState: "queued",
    reuseIdempotencyKey: true,
    automaticRetry: automatic,
    advanceLastSynced: false,
    surfaceToPerson: false,
    correlationId: rejection.correlationId,
    serverMessage: rejection.serverMessage,
  };
}

/** Stopped, and shown to the person with its correlation id (FR-012). */
function surfaced(
  reason: DecisionReason,
  rejection: SendRejection,
  nextSendState: SendState,
): ConflictDecision {
  return {
    kind: "error",
    reason,
    nextSendState,
    // A person-initiated retry always gets a fresh key — the convention
    // `src/utils/ids.ts` already states for this repo.
    reuseIdempotencyKey: false,
    automaticRetry: false,
    advanceLastSynced: false,
    surfaceToPerson: true,
    correlationId: rejection.correlationId,
    serverMessage: rejection.serverMessage,
  };
}

export function decideOnRejection({
  rejection,
  entry,
  serverState,
}: RejectionContext): ConflictDecision {
  if (serverState && serverHoldsIntendedValue(entry.value, serverState)) {
    // The one explicit exception to SC-005 ("no conflict is resolved without
    // the person choosing"), and design.md's M-04 "already applied" state.
    // Nothing is overwritten and nothing is discarded: the server holds exactly
    // what this entry intended, so there is no disagreement to put to anyone.
    // Asking would be inventing a decision. The entry is dropped and the
    // last-synced footer advances, which is the whole of what the person sees.
    return {
      kind: "already-applied",
      reason: "already-applied",
      nextSendState: "removed",
      reuseIdempotencyKey: false,
      automaticRetry: false,
      advanceLastSynced: true,
      surfaceToPerson: false,
    };
  }

  const { status } = rejection;

  if (status === undefined) {
    // No answer. The write may or may not have landed, so the same key goes
    // back out (FR-017) — that is exactly what makes the retry at-most-once.
    return retry("unreachable", rejection, true);
  }

  if (status === 401) {
    // FR-019/SC-008: nobody chose to end this session. Keep the work, say
    // nothing about it, and let the session layer decide what a 401 means.
    // Not retried on its own, because there is nobody to retry as.
    return retry("unauthenticated", rejection, false);
  }

  if (status === 408 || status === 429 || status >= 500) {
    return retry("server-error", rejection, true);
  }

  if (status === 409) {
    const resource = rejection.detail?.resource;
    if (resource === "Task") {
      // The task changed elsewhere. The person decides, and nothing is chosen
      // for them (FR-008). The key is re-minted for whatever they choose,
      // because the resolved payload carries a new `expected_revision` and the
      // server's request hash covers it (data-model invariant 6).
      return {
        kind: "prompt",
        reason: "stale-revision",
        nextSendState: "conflicted",
        reuseIdempotencyKey: false,
        automaticRetry: false,
        advanceLastSynced: false,
        surfaceToPerson: true,
        correlationId: rejection.correlationId,
        serverMessage: rejection.serverMessage,
      };
    }
    if (resource === "Idempotency-Key") {
      // A client bug: this key was already spent on a different payload. It
      // must never go out again — same key means 409 forever. The entry stays
      // queued so nothing of the person's is destroyed (SC-003), but only a
      // fresh key and a deliberate retry may move it.
      return surfaced("idempotency-key-reuse", rejection, "queued");
    }
    // Some other 409. Unexplained, so it is surfaced rather than looped.
    return surfaced("rejected", rejection, "queued");
  }

  if (status === 404) {
    // The task, or the project/Tag it names, was deleted elsewhere. The spec's
    // edge cases call this a conflict the person is told about, not a silent
    // discard — so it stops (`conflicted`) and waits rather than retrying a
    // target that is gone.
    return surfaced("target-missing", rejection, "conflicted");
  }

  return surfaced("rejected", rejection, "queued");
}
