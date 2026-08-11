/**
 * M-04 and M-05 as data.
 *
 * `mobile/` installs no React renderer, so anything decided inside a `.tsx`
 * file is untestable except through the integration harness. Every row of the
 * two sheet state tables in `specs/006-mobile-task-classification/design.md` is
 * therefore resolved here, as a pure function over plain values, and
 * `ConflictSheet.tsx` / `DiscardUnsentSheet.tsx` only render what comes back.
 *
 * Three things carry most of the weight:
 *
 * - **The conflict prompt names three values, not two.** The first is what the
 *   *device* last showed, labelled and dated as such. A stale cache would
 *   otherwise tell a confident and false story about who changed what — the
 *   person reads "it was Inbox, you set Q3", picks "Keep mine", and destroys
 *   work they would have kept. `originalValue` is the device's own memory
 *   (`classificationTypes.ts` says so in as many words), so it is never
 *   presented as server history.
 * - **`already-applied` is not a conflict.** When the server already holds what
 *   the entry intended there is no disagreement to put to anyone, so no prompt
 *   is built at all. This is design.md's one explicit exception to SC-005.
 * - **M-05 states a count and never a list.** That was decided at human
 *   sign-off (design.md, "Decisions taken at sign-off", 2) and is asserted in
 *   the tests rather than left as a comment, so adding a list later cannot pass
 *   as an improvement.
 *
 * Nothing here reads the clock: `now` is an argument, matching `syncStatus.ts`
 * and `expireQueue`. `mobile/` has no fake-timer precedent, so an internal
 * `Date.now()` would make every age below untestable.
 *
 * Copy is exported rather than inlined so a reviewer can diff it against
 * design.md's copy column in one place. FR-013 applies to all of it: **Tag**,
 * never Context, never @context.
 */

import type { PendingClassificationChange } from "./classificationTypes";
import { serverHoldsIntendedValue, type DecisionReason } from "./conflictDecision";
import type { NamedEntity } from "./matchExisting";
import { toEpochMs, type Instant } from "./syncStatus";

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;

/**
 * "14 minutes ago", "3 weeks ago", or `null` when the value carries no usable
 * time. Never "in 3 hours": a device clock that ran ahead is clamped, the same
 * way `describeLastSynced` and the queue's own timestamps are.
 *
 * `now` may be `null`, which is not the same as `Date.now()`: React's purity
 * rule forbids reading the clock while rendering, so a screen has no clock
 * until its first effect runs. Claiming no age for that frame is honest;
 * defaulting to the current time would print "just now" against a change made
 * three weeks ago.
 */
export function formatAge(
  instant: Instant | null | undefined,
  now: Instant | null | undefined,
): string | null {
  const then = toEpochMs(instant);
  const current = toEpochMs(now);
  if (then === null || current === null) {
    return null;
  }
  const elapsed = Math.max(0, current - then);
  if (elapsed < MINUTE) {
    return "just now";
  }
  const plural = (count: number, unit: string) => `${count} ${unit}${count === 1 ? "" : "s"} ago`;
  if (elapsed < HOUR) {
    return plural(Math.floor(elapsed / MINUTE), "minute");
  }
  if (elapsed < DAY) {
    return plural(Math.floor(elapsed / HOUR), "hour");
  }
  if (elapsed < WEEK) {
    return plural(Math.floor(elapsed / DAY), "day");
  }
  return plural(Math.floor(elapsed / WEEK), "week");
}

// =========================================================== M-04, the conflict

export type ConflictField = "project" | "tags";
export type ConflictChoice = "keep-mine" | "discard";

/** The lists the device can name ids from. `null` means it holds none. */
export interface ConflictNames {
  projects: readonly NamedEntity[] | null;
  tags: readonly NamedEntity[] | null;
}

/** The task as the server currently holds it, and the revision it is at. */
export interface ConflictServerState {
  projectId: string | null;
  tagIds: readonly string[];
  revision: number;
}

export type ConflictResolutionState =
  | { status: "idle" }
  | { status: "sending"; choice: ConflictChoice }
  | { status: "failed"; choice: ConflictChoice; message?: string; correlationId?: string };

export interface ConflictDiffRow {
  /** `device` is what this phone last showed — not what the server held. */
  key: "device" | "yours" | "server";
  label: string;
  /** The age of the device's knowledge. Only ever set on the `device` row. */
  note: string | null;
  value: string;
  /** The row carries its own name; the pill styling is decorative. */
  accessibilityLabel: string;
}

export interface ConflictSection {
  field: ConflictField;
  /** `null` when the sheet title is already this field's sentence. */
  heading: string | null;
  /** Three rows, or two when the target is gone and there is no server value. */
  rows: ConflictDiffRow[];
}

interface SheetButtonBase {
  label: string;
  disabled: boolean;
  /** The chosen button shows progress; the other one does not. */
  busy: boolean;
  /** Why it is unavailable, in words. design.md forbids colour alone. */
  reason: string | null;
  variant: "primary" | "secondary" | "destructive";
}

export interface ConflictButton extends SheetButtonBase {
  choice: ConflictChoice;
}

export interface SheetError {
  /** The sheet's own actionable sentence — always present, always stable. */
  text: string;
  /** The server's words, when it supplied any. */
  detail: string | null;
}

export interface ConflictPromptView {
  kind: "prompt";
  reason: DecisionReason;
  title: string;
  body: string;
  sections: ConflictSection[];
  /** M-04, "device was far behind". */
  multiChangeNotice: string | null;
  /** M-04, "partial failure": "1 of 3". Null for a queue of one. */
  progressLabel: string | null;
  buttons: ConflictButton[];
  error: SheetError | null;
  /** FR-012 — carried whenever the client captured one. */
  correlationLine: string | null;
  /** design.md: the heading, never a button. */
  initialFocus: "heading";
  /** design.md: Escape is the non-destructive choice and never resolves. */
  escapeAction: "dismiss";
}

export type ConflictView =
  | { kind: "no-prompt"; reason: "already-applied" | "nothing-changed" }
  | ConflictPromptView;

export interface ConflictViewInput {
  entry: PendingClassificationChange;
  /** `null` when the drain could not read the task — a deleted target, say. */
  server: ConflictServerState | null;
  /** From `decideOnRejection`. `conflicted` does **not** imply a revision
   *  conflict: a 404 on a deleted target parks an entry the same way. */
  reason: DecisionReason;
  names: ConflictNames;
  /**
   * When the device last read this task from the server. The queue entry does
   * not record it, so an absent value is left absent rather than back-filled
   * from `firstQueuedAt` — that would claim the phone's knowledge is as fresh
   * as the change, which is the exact falsehood this row exists to prevent.
   */
  deviceObservedAt?: Instant | null;
  /** `null` until the screen's first effect has read the clock. Every age is
   *  simply omitted until then, rather than guessed. */
  now: Instant | null;
  /** 1-based, from `selectPendingConflict`. */
  index?: number;
  total?: number;
  /** The correlation id of the rejection that opened this sheet. */
  correlationId?: string;
  resolution?: ConflictResolutionState;
  /** Which target the 404 named, when the client knows. */
  missingTarget?: "task" | "project" | "tag";
}

export const CONFLICT_COPY = {
  deviceRowLabel: "Your phone last showed",
  /** Said instead of an age when nothing recorded when the device last read the
   *  task. Claims no freshness at all, which is the honest fallback. */
  deviceRowUndatedNote: "the value this phone was showing you",
  yoursRowLabel: (field: ConflictField) =>
    field === "tags" ? "You changed them to" : "You changed it to",
  serverRowLabel: "Now on server",
  fieldSentence: (field: ConflictField, age: string | null) => {
    const subject = field === "tags" ? "the Tags" : "the project";
    return age === null ? `You changed ${subject}` : `You changed ${subject} ${age}`;
  },
  /** Two fields changed at once: the per-field headings say which and when, so
   *  the title says only what happened to the change as a whole. */
  multiFieldTitle: "Your queued change was not applied",
  staleRevisionBody:
    "This task was updated somewhere else before your change was sent, so it was not applied. " +
    "Choose which one to keep — nothing has been discarded yet.",
  multiChangeNotice: "This task has changed more than once since your phone last saw it.",
  missingTitle: "This change can't be applied any more",
  missingTaskBody:
    "This task was deleted somewhere else, so there is nothing left to apply your change to. " +
    "Nothing else of yours is affected.",
  missingProjectBody:
    "The project you chose was deleted somewhere else, so your change can't be applied. " +
    "Nothing else of yours is affected.",
  missingTagBody:
    "The Tag you chose was deleted somewhere else, so your change can't be applied. " +
    "Nothing else of yours is affected.",
  missingUnknownBody:
    "The task, project or Tag this change points to was deleted somewhere else, so there is " +
    "nothing left to apply it to. Nothing else of yours is affected.",
  keepMine: "Keep mine, replace theirs",
  discardMine: "Discard mine, keep the server's",
  /** With the target gone, "keep the server's" names something that is not there. */
  discardOnly: "Discard my change",
  waitingOnChoice: "Waiting for the choice you made to finish",
  resolutionFailed: "We couldn't send your choice. Nothing has been discarded — try again.",
  noProject: "None",
  noTags: "No Tags",
  unnamedProject: "A project this phone can't name yet",
  unnamedTags: (count: number) => `${count} Tag${count === 1 ? "" : "s"} this phone can't name yet`,
  moreUnnamedTags: (count: number) => `and ${count} more this phone can't name yet`,
  progress: (index: number, total: number) => `${index} of ${total}`,
  correlation: (id: string) => `correlation id ${id}`,
} as const;

function nameOf(id: string, entities: readonly NamedEntity[] | null): string | undefined {
  return entities?.find((entity) => entity.id === id)?.name;
}

/** A project value as one line. `null` is a deliberate clear, not an absence. */
function renderProject(projectId: string | null, names: ConflictNames): string {
  if (projectId === null) {
    return CONFLICT_COPY.noProject;
  }
  return nameOf(projectId, names.projects) ?? CONFLICT_COPY.unnamedProject;
}

/**
 * A Tag set as one line.
 *
 * Sorted, because the person is comparing three rows by eye and a set has no
 * order of its own — the same set must render the same way in all three.
 * Unnameable ids are counted rather than listed as blanks.
 */
function renderTags(tagIds: readonly string[], names: ConflictNames): string {
  if (tagIds.length === 0) {
    return CONFLICT_COPY.noTags;
  }
  const resolved: string[] = [];
  let unnamed = 0;
  for (const id of tagIds) {
    const name = nameOf(id, names.tags);
    if (name === undefined) {
      unnamed += 1;
    } else {
      resolved.push(name);
    }
  }
  resolved.sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));
  if (resolved.length === 0) {
    return CONFLICT_COPY.unnamedTags(unnamed);
  }
  const listed = resolved.join(", ");
  return unnamed === 0 ? listed : `${listed}, ${CONFLICT_COPY.moreUnnamedTags(unnamed)}`;
}

function diffRow(
  key: ConflictDiffRow["key"],
  label: string,
  value: string,
  note: string | null,
): ConflictDiffRow {
  return {
    key,
    label,
    note,
    value,
    accessibilityLabel: note === null ? `${label}: ${value}` : `${label}: ${value} (${note})`,
  };
}

function changedFields(entry: PendingClassificationChange): ConflictField[] {
  const fields: ConflictField[] = [];
  if (entry.value.projectId !== undefined) {
    fields.push("project");
  }
  if (entry.value.tagIds !== undefined) {
    fields.push("tags");
  }
  return fields;
}

function sectionFor(
  field: ConflictField,
  input: ConflictViewInput,
  deviceNote: string | null,
  title: string,
  age: string | null,
): ConflictSection {
  const { entry, server, names } = input;
  const render = (projectId: string | null, tagIds: readonly string[]) =>
    field === "project" ? renderProject(projectId, names) : renderTags(tagIds, names);

  const rows: ConflictDiffRow[] = [
    diffRow(
      "device",
      CONFLICT_COPY.deviceRowLabel,
      render(entry.originalValue.projectId, entry.originalValue.tagIds),
      deviceNote,
    ),
    diffRow(
      "yours",
      CONFLICT_COPY.yoursRowLabel(field),
      render(entry.value.projectId ?? null, entry.value.tagIds ?? []),
      null,
    ),
  ];
  if (server !== null) {
    // With no server state there is no third value. Inventing one — showing the
    // device's memory twice, or a blank — would be the false story again.
    rows.push(diffRow("server", CONFLICT_COPY.serverRowLabel, render(server.projectId, server.tagIds), null));
  }

  const sentence = CONFLICT_COPY.fieldSentence(field, age);
  return { field, heading: sentence === title ? null : sentence, rows };
}

function conflictButtons(
  reason: DecisionReason,
  resolution: ConflictResolutionState,
): ConflictButton[] {
  const sendingChoice = resolution.status === "sending" ? resolution.choice : null;
  const inFlight = sendingChoice !== null;
  const build = (
    choice: ConflictChoice,
    label: string,
    variant: SheetButtonBase["variant"],
  ): ConflictButton => {
    const chosen = sendingChoice === choice;
    return {
      choice,
      label,
      // Both are disabled while one is in flight, and the unchosen one stays
      // **visible**: hiding it lets a double tap land on whatever moves into
      // its place, and a second resolution would race the first.
      disabled: inFlight,
      busy: chosen,
      reason: inFlight && !chosen ? CONFLICT_COPY.waitingOnChoice : null,
      variant,
    };
  };

  if (reason === "target-missing") {
    // "Keep mine, replace theirs" means nothing when there is no "theirs" left.
    return [build("discard", CONFLICT_COPY.discardOnly, "secondary")];
  }
  return [
    build("keep-mine", CONFLICT_COPY.keepMine, "primary"),
    build("discard", CONFLICT_COPY.discardMine, "secondary"),
  ];
}

function missingBody(target: ConflictViewInput["missingTarget"]): string {
  switch (target) {
    case "task":
      return CONFLICT_COPY.missingTaskBody;
    case "project":
      return CONFLICT_COPY.missingProjectBody;
    case "tag":
      return CONFLICT_COPY.missingTagBody;
    default:
      return CONFLICT_COPY.missingUnknownBody;
  }
}

/** M-04, every row of it. */
export function buildConflictView(input: ConflictViewInput): ConflictView {
  const { entry, server, reason, now, index = 1, total = 1 } = input;
  const resolution = input.resolution ?? { status: "idle" };

  const fields = changedFields(entry);
  if (fields.length === 0) {
    // The reducer never queues an empty change, so this is defence rather than
    // a state: a sheet with no diff would ask a person about nothing.
    return { kind: "no-prompt", reason: "nothing-changed" };
  }

  if (
    reason === "already-applied" ||
    (server !== null &&
      serverHoldsIntendedValue(entry.value, {
        projectId: server.projectId,
        tagIds: [...server.tagIds],
      }))
  ) {
    // design.md's "already applied": no prompt at all. The entry is dropped and
    // last-synced advances; nothing is overwritten and nothing is discarded, so
    // there is no decision to invent for the person.
    return { kind: "no-prompt", reason: "already-applied" };
  }

  const age = formatAge(entry.lastEditedAt, now);
  const observedAge = formatAge(input.deviceObservedAt, now);
  const deviceNote = observedAge === null ? CONFLICT_COPY.deviceRowUndatedNote : `as of ${observedAge}`;

  const title =
    reason === "target-missing"
      ? CONFLICT_COPY.missingTitle
      : fields.length > 1
        ? CONFLICT_COPY.multiFieldTitle
        : CONFLICT_COPY.fieldSentence(fields[0], age);

  const failed = resolution.status === "failed" ? resolution : null;
  const correlationId = failed?.correlationId ?? input.correlationId;

  return {
    kind: "prompt",
    reason,
    title,
    body: reason === "target-missing" ? missingBody(input.missingTarget) : CONFLICT_COPY.staleRevisionBody,
    sections: fields.map((field) => sectionFor(field, input, deviceNote, title, age)),
    // Without this line a sequence of edits the person was never party to reads
    // as a two-party disagreement, and "Keep mine" destroys work they would
    // have kept.
    multiChangeNotice:
      server !== null && server.revision - entry.observedRevision > 1
        ? CONFLICT_COPY.multiChangeNotice
        : null,
    progressLabel: total > 1 ? CONFLICT_COPY.progress(index, total) : null,
    buttons: conflictButtons(reason, resolution),
    error: failed === null ? null : { text: CONFLICT_COPY.resolutionFailed, detail: failed.message ?? null },
    correlationLine: correlationId === undefined ? null : CONFLICT_COPY.correlation(correlationId),
    initialFocus: "heading",
    escapeAction: "dismiss",
  };
}

// ==================================================== M-05, the discard warning

export type DiscardTrigger = "sign-out" | "account-change" | "server-change";
export type DiscardAction = "stay" | "discard";

export interface DiscardButton extends SheetButtonBase {
  action: DiscardAction;
}

export interface DiscardUnsentPromptView {
  kind: "prompt";
  /** The whole of what the person is told about the work itself. */
  count: number;
  title: string;
  body: string;
  stay: DiscardButton;
  discard: DiscardButton;
  error: SheetError | null;
  correlationLine: string | null;
  initialFocus: "heading";
  /** Escape cancels the identity transition. It never discards. */
  escapeAction: "cancel";
}

export type DiscardUnsentView =
  | { kind: "no-prompt"; reason: "queue-empty"; proceed: true }
  | DiscardUnsentPromptView;

export interface DiscardUnsentViewInput {
  queue: readonly PendingClassificationChange[];
  trigger: DiscardTrigger;
  online: boolean;
  /** A drain that failed while the person was deciding. */
  error?: { message?: string; correlationId?: string } | null;
}

const TRIGGER_CLAUSE: Record<DiscardTrigger, string> = {
  "sign-out": "Signing out discards",
  "account-change": "Switching account discards",
  "server-change": "Switching server discards",
};

export const DISCARD_COPY = {
  title: (count: number) =>
    count === 1 ? "1 change has not been sent" : `${count} changes have not been sent`,
  body: (trigger: DiscardTrigger, count: number) => {
    const one = count === 1;
    return (
      `${TRIGGER_CLAUSE[trigger]} ${one ? "it" : "them"}, because ` +
      `${one ? "it belongs" : "they belong"} to the account and server ` +
      `${one ? "it was" : "they were"} made on and cannot be sent from another. ` +
      "This cannot be undone."
    );
  },
  stay: (count: number) => (count === 1 ? "Stay and let it send" : "Stay and let them send"),
  discard: (count: number) =>
    count === 1 ? "Discard 1 change and continue" : `Discard ${count} changes and continue`,
  stayBlockedOffline: "Nothing can be sent without a connection",
  /** `updateTask` takes no AbortSignal, so an in-flight send cannot be stopped.
   *  Telling someone their change will not be sent and then sending it is the
   *  failure this avoids. */
  discardBlockedSending: (count: number) =>
    count === 1
      ? "A change is being sent right now and can't be called back. " +
        "Discarding is available again once it finishes."
      : `${count} changes are being sent right now and can't be called back. ` +
        "Discarding is available again once they finish.",
  drainFailed: "We couldn't send them just now. Nothing has been discarded — you can still choose.",
  correlation: (id: string) => `correlation id ${id}`,
} as const;

/**
 * How many changes are still unsent.
 *
 * `expired` entries are excluded: FR-018 already discarded those, and the M-01
 * notice is what tells the person. Counting them here would warn a second time
 * about a loss that has already happened, and inflate the number in the one
 * sentence the person gets.
 */
export function countUnsent(queue: readonly PendingClassificationChange[]): number {
  return queue.filter((entry) => entry.sendState !== "expired").length;
}

function countSending(queue: readonly PendingClassificationChange[]): number {
  return queue.filter((entry) => entry.sendState === "sending").length;
}

/** M-05, every row of it. */
export function buildDiscardUnsentView(input: DiscardUnsentViewInput): DiscardUnsentView {
  const { queue, trigger, online, error } = input;
  const count = countUnsent(queue);
  if (count === 0) {
    // design.md's "empty": the sheet never appears and the action proceeds.
    // There is nothing to warn about, and a warning naming zero changes is
    // chrome for its own sake.
    return { kind: "no-prompt", reason: "queue-empty", proceed: true };
  }

  const sending = countSending(queue);
  // Offline *and* something in flight would otherwise disable both choices at
  // once. Something is genuinely being sent, so "nothing can be sent without a
  // connection" is not true here, and staying is exactly the right thing to do.
  const stayBlocked = !online && sending === 0;

  return {
    kind: "prompt",
    count,
    title: DISCARD_COPY.title(count),
    body: DISCARD_COPY.body(trigger, count),
    stay: {
      action: "stay",
      label: DISCARD_COPY.stay(count),
      disabled: stayBlocked,
      busy: false,
      reason: stayBlocked ? DISCARD_COPY.stayBlockedOffline : null,
      variant: "secondary",
    },
    discard: {
      action: "discard",
      label: DISCARD_COPY.discard(count),
      disabled: sending > 0,
      busy: false,
      reason: sending > 0 ? DISCARD_COPY.discardBlockedSending(sending) : null,
      variant: "destructive",
    },
    error: error ? { text: DISCARD_COPY.drainFailed, detail: error.message ?? null } : null,
    correlationLine: error?.correlationId ? DISCARD_COPY.correlation(error.correlationId) : null,
    initialFocus: "heading",
    escapeAction: "cancel",
  };
}
