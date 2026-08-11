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
