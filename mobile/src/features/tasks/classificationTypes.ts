/**
 * The device-local classification queue, as specified in
 * specs/006-mobile-task-classification/data-model.md.
 *
 * This file is the shared contract between the reducer, the storage adapter
 * and the drain hook. It holds types only — no behaviour — so that the three
 * can be built and tested independently.
 */

/** What a classification change intends the task to end up as. */
export interface ClassificationValue {
  /** `null` clears the project. `undefined` means "not part of this change". */
  projectId: string | null | undefined;
  /** The intended whole set, not a delta. Absent means "not part of this change". */
  tagIds: string[] | undefined;
}

/**
 * `expired` retains its payload rather than deleting it, so a device clock
 * that jumped forward is recoverable instead of terminal (FR-018).
 *
 * `sending` is a liveness marker for the running process and is never
 * authoritative across a restart — see `resetInterrupted` (FR-021).
 */
export type SendState = "queued" | "sending" | "conflicted" | "expired";

export interface PendingClassificationChange {
  taskId: string;
  /** Owner identity this entry was made under. Checked on read as defence in
   *  depth; the storage key already scopes it (SC-007). */
  accountId: string;
  serverUrl: string;

  /** The intended net effect. Coalescing rewrites this, never appends. */
  value: ClassificationValue;

  /** The task revision seen when the FIRST uncoalesced change was made.
   *  Never refreshed: refreshing would silently swallow a concurrent edit. */
  observedRevision: number;

  /** What the DEVICE last displayed when that first change was made — not
   *  necessarily what the server held. Labelled as such in the conflict
   *  prompt, because a stale cache would otherwise tell a confident and
   *  false story about who changed what (FR-010, invariant 9). */
  originalValue: { projectId: string | null; tagIds: string[] };

  /** When the DEVICE last read this task from the server — not when the change
   *  was made. Immutable, and captured with `originalValue`.
   *
   *  Without it the conflict prompt cannot honestly date the value it shows.
   *  Back-filling the age from `firstQueuedAt` would claim the phone's
   *  knowledge is 14 minutes old when it may be three weeks old, which is the
   *  precise falsehood the labelled row exists to prevent (FR-010,
   *  invariant 9). Optional because a task read before this field existed has
   *  no honest value to supply — the prompt then omits the age rather than
   *  inventing one. */
  observedAt?: string;

  /** Immutable. Pairs with `originalValue` and `observedRevision`. */
  firstQueuedAt: string;
  /** Refreshed on every coalesce. FR-018's 30 days runs from this, so a live
   *  entry is never destroyed for the age of an edit it no longer contains. */
  lastEditedAt: string;

  /** Set on the first send attempt. Past 24h from it the server's replay
   *  window has closed and the entry may not be retried blind (invariant 10). */
  firstSentAt?: string;

  /** Stable across retries of an UNCHANGED payload; re-minted whenever the
   *  payload changes.
   *
   *  Not "never regenerated" — the backend raises ConflictError when a stored
   *  key arrives with a different request hash, and the hash covers the whole
   *  body, so reusing a key across a coalesce produces an entry that can never
   *  be sent. `src/utils/ids.ts` already documents the correct convention. */
  idempotencyKey: string;

  sendState: SendState;

  /** Why this entry was parked, when `sendState` is `conflicted`.
   *
   *  `conflicted` covers two outcomes that need different sheets: a stale
   *  revision, and a 404 on a target deleted elsewhere. Recording only the
   *  state makes them indistinguishable at the call site, so a deleted task
   *  renders the revision prompt and offers "Keep mine, replace theirs" for
   *  something that no longer exists. Typed loosely to avoid a cycle with
   *  `conflictDecision.ts`, which imports this module. */
  conflictReason?: string;

  /** The correlation id of the response that parked it, so FR-012's
   *  "reportable" applies to a conflict and not only to an inline error. */
  correlationId?: string;

  /** The task revision the re-read observed when this entry was parked.
   *
   *  A 409 is answered by re-reading the task, and that revision is the only
   *  one a resolution can be aimed at. Nothing writes it back to the screen's
   *  copy of the task and a conflicted pass settles nothing, so resolving
   *  against what the screen holds re-sends the same stale
   *  `expected_revision`, earns the same 409, and puts the same sheet back up
   *  for ever — a loop with no exit the person can reach. Absent when the
   *  re-read itself could not be made. */
  conflictServerRevision?: number;
}

/** Cached project and Tag lists, so the pickers work after a cold start with
 *  no connection. Holds NAMES the person wrote, where the queue holds only
 *  ids — the two are modelled separately because their safety argument is
 *  different, not because they are stored differently. */
export interface CachedClassificationLists {
  projects: { id: string; name: string }[];
  tags: { id: string; name: string }[];
  fetchedAt: string;
}

/** Why a session ended, which decides whether unsent work survives. */
export type IdentityEventKind = "deliberate" | "involuntary";

export type QueueDisposition = "keep" | "discard" | "warn-then-discard";

export const RETENTION_DAYS = 30;
export const RETENTION_MS = RETENTION_DAYS * 24 * 60 * 60 * 1000;

/** The server forgets an idempotency key after this long
 *  (`IDEMPOTENCY_RETENTION` in backend/app/modules/tasks/repository.py).
 *  Beyond it, at-most-once is carried by `expected_revision`, not the key. */
export const SERVER_REPLAY_WINDOW_MS = 24 * 60 * 60 * 1000;
