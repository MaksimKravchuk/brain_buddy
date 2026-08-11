/**
 * The task screen as data — feature 006, T046, T047, T051, T063–T066.
 *
 * `mobile/` installs no React renderer, so anything decided inside
 * `app/task/[id].tsx` is untestable except through the integration harness.
 * Every rule the screen applies therefore lives here, as a pure function over
 * plain values, and the screen only renders what comes back. A decision added
 * to the `.tsx` is a decision that leaves the test suite.
 *
 * Nothing here reads the clock (plan.md's clock rule for this feature): `now`
 * is an argument, and `dueLabel` arrives already formatted because
 * `components/TaskRow.dueLabel` reads `Date.now()` itself.
 *
 * Two presentations live side by side, which is the shape T047 asks for:
 *
 * - **rows** (M-01) — four labelled rows with chevrons and muted placeholders
 *   when unset. This is a *relayout*: the screen has no Project or Tags row
 *   today, and hides project and Tags entirely when they are unset.
 * - **chips** (M-01c) — today's wrapped chip row, byte-for-byte the same
 *   decisions the screen takes now. design.md's sign-off decision 3 reads
 *   "today's screen exactly"; `buildMetadataChips` is what makes that a claim a
 *   test can hold rather than a promise, because the M-01c mock draws rows that
 *   today's code does not have.
 *
 * Copy is exported rather than inlined so a reviewer can diff it against
 * design.md's copy column in one place. FR-013 applies to all of it: **Tag**,
 * never Context, never @context.
 */

import type { TaskPriority } from "../../api/types";
import type { ClassificationEdit } from "./classificationQueue";
import type { ClassificationValue, PendingClassificationChange } from "./classificationTypes";
import type { ClassificationState } from "./conflictDecision";
import type { AttachedEntity, ListPhase } from "./pickerState";
import type { ClassificationIdentity } from "./storageKeys";
import { describeLastSynced, type Instant, type LastSyncedBucket, toEpochMs } from "./syncStatus";
import type { ExpiredChangeNotice, ExpiredFieldNotice } from "./useClassificationQueue";

// ------------------------------------------------------------------ the copy

/** M-01, "empty (first run)": rows present with muted placeholders, not hidden. */
export const PROJECT_ROW_PLACEHOLDER = "Add a project";
export const TAGS_ROW_PLACEHOLDER = "Add Tags";
/** Not in design.md's copy column — invented to match the two above. */
export const DUE_ROW_PLACEHOLDER = "Add a date";

/**
 * The device holds the id but not the name (M-02/M-03 "offline, never
 * fetched"). Saying so is honest; a blank row would read as "no project", which
 * is a different fact and the one thing the person might act on wrongly.
 */
export const UNNAMED_PROJECT = "Needs a connection to show its name";
export const UNNAMED_TAGS = "Needs a connection to show their names";

export const ROW_LABELS = {
  project: "Project",
  tags: "Tags",
  due: "Due",
  priority: "Priority",
} as const;

export const PRIORITY_LABELS: Record<TaskPriority, string> = {
  none: "None",
  low: "Low",
  medium: "Medium",
  high: "High",
};

/** design.md, focus: a labelled button, never icon-only. */
export const EXPIRY_DISMISS_LABEL = "Dismiss";
export const ACCOUNT_EXPIRY_DISMISS_LABEL = "Dismiss";

/** What an unset value is called to assistive technology. */
const NONE_SET = "none set";

// ------------------------------------------------------- is this screen live?

/** `SessionProvider`'s four values, restated so this module imports no session. */
export type SessionStatusLike = "loading" | "signed-out" | "signed-in" | "signed-in-offline";

export type ClassificationSurfaceReason = "ok" | "flag-off" | "no-session" | "task-closed";

export interface ClassificationSurfaceInput {
  status: SessionStatusLike;
  /** FR-015/FR-020 — the rollout flag's last known value for THIS identity. */
  taskClassificationEnabled: boolean;
  /** Readable with no live profile, which is what makes SC-009 reachable. */
  accountId: string | null;
  serverUrl: string;
  /** A completed or cancelled task accepts no classification change. */
  taskOpen: boolean;
}

export interface ClassificationSurface {
  /** M-01's four rows, or today's chip row (M-01c). */
  presentation: "rows" | "chips";
  /** Both halves of the storage key, or `null` when the queue cannot be named. */
  identity: ClassificationIdentity | null;
  /** Whether the queue is rehydrated at all. */
  queueEnabled: boolean;
  reason: ClassificationSurfaceReason;
}

/**
 * Both halves of the storage key, or `null` when the device cannot name one.
 *
 * SC-007: a key with an empty half would be one key shared by every account.
 * `storageKeys` throws on that; refusing here is the same rule applied before
 * anything asks for a key. Only `signed-in` and `signed-in-offline` name an
 * identity — a signed-out device may still *hold* one, and reading it back is a
 * deliberate act of the caller (the sign-in screen does exactly that), not
 * something an ambient session read should do on its own.
 */
export function resolveIdentity(input: {
  status: SessionStatusLike;
  accountId: string | null;
  serverUrl: string;
}): ClassificationIdentity | null {
  const signedIn = input.status === "signed-in" || input.status === "signed-in-offline";
  const accountId = input.accountId?.trim() ?? "";
  const serverUrl = input.serverUrl.trim();
  return signedIn && accountId !== "" && serverUrl !== "" ? { serverUrl, accountId } : null;
}

/**
 * SC-009 — whether this screen can classify, resolved entirely from what the
 * device already holds.
 *
 * All three inputs are readable with no connection: the flag from the persisted
 * per-identity flag record, the account id from persisted identity, the server
 * url from `bb.serverUrl`. `signed-in-offline` is therefore not a lesser
 * screen — it is the same screen, which is the whole of SC-009 and is asserted
 * as an equality rather than as two similar-looking cases.
 *
 * Every "no" resolves to today's chips rather than to disabled rows: design.md
 * forbids advertising a capability with a control nobody can use, and a
 * placeholder row that opens nothing is exactly that.
 */
export function resolveClassificationSurface(
  input: ClassificationSurfaceInput,
): ClassificationSurface {
  const identity = resolveIdentity(input);

  if (!input.taskClassificationEnabled) {
    // FR-015: off means the queue is not even rehydrated, so nothing of this
    // feature can be observed on the device before rollout.
    return { presentation: "chips", identity: null, queueEnabled: false, reason: "flag-off" };
  }
  if (!identity) {
    // SC-007: a key with an empty half would be one key shared by every
    // account. `storageKeys` throws on that; refusing here is the same rule,
    // applied before anything asks for a key.
    return { presentation: "chips", identity: null, queueEnabled: false, reason: "no-session" };
  }
  if (!input.taskOpen) {
    // Nothing on a completed task can be classified, so rows with placeholders
    // nobody can act on would be a lie. The queue stays enabled: the footer and
    // the expiry notice are about the device, not about this task's state.
    return { presentation: "chips", identity, queueEnabled: true, reason: "task-closed" };
  }
  return { presentation: "rows", identity, queueEnabled: true, reason: "ok" };
}

// ------------------------------------------------------------ T046, the rows

export type MetadataRowId = "project" | "tags" | "due" | "priority";

export interface MetadataInput {
  projectId: string | null;
  /** Resolved name; `undefined` when the device cannot name the id. */
  projectName: string | undefined;
  tagIds: readonly string[];
  /** Resolved names, unresolvable ids dropped. */
  tagNames: readonly string[];
  /** Already formatted by `components/TaskRow.dueLabel`; `null` when unset. */
  dueLabel: string | null;
  priority: TaskPriority;
}

export interface MetadataRow {
  id: MetadataRowId;
  label: string;
  /** The value as words, or the muted placeholder when unset. */
  value: string;
  /** True when `value` is a placeholder: rendered muted, never hidden. */
  placeholder: boolean;
  /** Values to draw as pills rather than as plain text. */
  pills: string[];
  /** design.md: the chevron is decorative; the row carries name and value. */
  accessibilityLabel: string;
}

function row(
  id: MetadataRowId,
  value: string,
  placeholder: boolean,
  pills: string[] = [],
): MetadataRow {
  const label = ROW_LABELS[id];
  return {
    id,
    label,
    value,
    placeholder,
    pills,
    // A placeholder is an invitation, not a value: reading "Project, Add a
    // project" out loud states neither the field's state nor the action.
    accessibilityLabel: `${label}, ${placeholder ? NONE_SET : value}`,
  };
}

function projectRow(input: MetadataInput): MetadataRow {
  if (input.projectId === null) {
    return row("project", PROJECT_ROW_PLACEHOLDER, true);
  }
  return input.projectName === undefined
    ? row("project", UNNAMED_PROJECT, false)
    : row("project", input.projectName, false, [input.projectName]);
}

function tagsRow(input: MetadataInput): MetadataRow {
  const names = [...input.tagNames];
  if (input.tagIds.length === 0) {
    return row("tags", TAGS_ROW_PLACEHOLDER, true);
  }
  if (names.length === 0) {
    return row("tags", UNNAMED_TAGS, false);
  }
  // Some ids resolved and some did not. Showing only the ones with names would
  // under-report the task's own classification, so the remainder is counted.
  const unnamed = input.tagIds.length - names.length;
  const value = unnamed > 0 ? `${names.join(", ")} +${unnamed}` : names.join(", ");
  return row("tags", value, false, names);
}

/**
 * M-01's four rows, always all four.
 *
 * "Rows present with muted placeholders, not hidden" is the requirement that
 * separates this from today's screen, where project and Tags simply vanish when
 * unset — and a value that is not drawn cannot be tapped, which is how FR-001
 * and FR-002 are unreachable today for exactly the tasks that need them most.
 */
export function buildMetadataRows(input: MetadataInput): MetadataRow[] {
  return [
    projectRow(input),
    tagsRow(input),
    input.dueLabel === null
      ? row("due", DUE_ROW_PLACEHOLDER, true)
      : row("due", input.dueLabel, false),
    // "None" is a real priority value, so it is shown rather than replaced by an
    // invitation — muted, because it is the unset one.
    row("priority", PRIORITY_LABELS[input.priority], input.priority === "none"),
  ];
}

// ------------------------------------------------------- T047, today's chips

export type MetadataChip =
  | {
      key: "due";
      kind: "due";
      label: string;
      accessibilityLabel: string;
      disabled: boolean;
    }
  | { key: "due"; kind: "add-due"; label: string; accessibilityLabel: string }
  | {
      key: "priority";
      kind: "priority";
      label: string;
      priority: TaskPriority;
      accessibilityLabel: string;
      disabled: boolean;
    }
  | { key: "priority"; kind: "add-priority"; label: string; accessibilityLabel: string }
  | { key: string; kind: "tag"; label: string }
  | { key: "project"; kind: "project"; label: string }
  | { key: "state"; kind: "state"; label: string };

export interface MetadataChipInput extends MetadataInput {
  openTask: boolean;
  stateLabel: string;
}

/**
 * FR-015 — today's chip row, unchanged, for when the rollout flag is off.
 *
 * Every branch below mirrors what `app/task/[id].tsx` renders today: a set
 * value becomes a chip that is disabled rather than hidden on a closed task, an
 * unset one becomes a dashed add-affordance only while the task is open, Tags
 * are pills, the project is a plain micro label shown only when the device can
 * name it, and a closed task names its state. Extracting it is what lets
 * "unchanged" be asserted instead of asserted-by-eye.
 */
export function buildMetadataChips(input: MetadataChipInput): MetadataChip[] {
  const chips: MetadataChip[] = [];

  if (input.dueLabel !== null) {
    chips.push({
      key: "due",
      kind: "due",
      label: input.dueLabel,
      accessibilityLabel: "Change due date",
      disabled: !input.openTask,
    });
  } else if (input.openTask) {
    chips.push({
      key: "due",
      kind: "add-due",
      label: "Add date",
      accessibilityLabel: "Add due date",
    });
  }

  if (input.priority !== "none") {
    chips.push({
      key: "priority",
      kind: "priority",
      label: PRIORITY_LABELS[input.priority],
      priority: input.priority,
      accessibilityLabel: "Change priority",
      disabled: !input.openTask,
    });
  } else if (input.openTask) {
    chips.push({
      key: "priority",
      kind: "add-priority",
      label: "Priority",
      accessibilityLabel: "Set priority",
    });
  }

  for (const name of input.tagNames) {
    chips.push({ key: `tag:${name}`, kind: "tag", label: name });
  }

  if (input.projectName !== undefined) {
    chips.push({ key: "project", kind: "project", label: input.projectName });
  }

  if (!input.openTask) {
    chips.push({ key: "state", kind: "state", label: input.stateLabel });
  }

  return chips;
}

// ----------------------------------------------------------- T051, the footer

export interface LastSyncedFooter {
  bucket: LastSyncedBucket;
  label: string;
  accessibilityLabel: string;
}

/**
 * How often the screen recomputes the footer. The label only changes at a
 * minute boundary at worst, so half a minute keeps it honest without the
 * footer being a clock.
 */
export const LAST_SYNCED_TICK_MS = 30_000;

/**
 * SC-004 / FR-007 — the one line that says how current the screen is.
 *
 * Words, never a coloured dot: design.md's rule is that no state in this
 * feature is communicated by colour alone. It says *when*, never *what*, which
 * is what keeps it from becoming the per-change marker FR-007 removed.
 */
export function buildLastSyncedFooter(
  lastSyncedAt: Instant | null | undefined,
  now: Instant,
): LastSyncedFooter {
  const described = describeLastSynced(lastSyncedAt, now);
  return {
    bucket: described.bucket,
    label: described.label,
    accessibilityLabel: described.label,
  };
}

/**
 * design.md, accessible names: the footer is a live region that announces only
 * when the time changes **materially**, not on every tick.
 *
 * The words are the material change — comparing them covers both a new bucket
 * and a new count within one. First paint never announces: the footer is read
 * as part of the screen the person just opened, and announcing it again would
 * make the one quiet signal in this feature the loudest thing on the screen.
 */
export function shouldAnnounceLastSynced(
  previous: LastSyncedFooter | null,
  next: LastSyncedFooter,
): boolean {
  return previous !== null && previous.label !== next.label;
}

// ------------------------------------------------------ T065, the task notice

export interface ExpiredNoticeNames {
  project(id: string | null): string | undefined;
  tags(ids: readonly string[]): string[];
}

export interface ExpiredNoticeView {
  /** One sentence pair per changed field of the one coalesced entry. */
  lines: string[];
  /** The row this sits under, so Dismiss lands in tab order after it. */
  anchor: "project" | "tags";
  dismissLabel: string;
  accessibilityLabel: string;
}

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}

/**
 * "31 days ago", as design.md's own sentence has it.
 *
 * FR-018 discards at 30 days, so days is the case that runs in production. The
 * shorter forms exist because the bound is cross-checked against server time
 * and clamped: a device whose clock was wrong can produce a younger entry, and
 * "0 days ago" would be the kind of nonsense that makes a person distrust the
 * rest of the sentence.
 */
function formatChangeAge(lastEditedAt: string, now: Instant): string {
  const edited = toEpochMs(lastEditedAt);
  const current = toEpochMs(now);
  if (edited === null || current === null) {
    return "earlier today";
  }
  const elapsed = Math.max(0, current - edited);
  if (elapsed >= DAY_MS) {
    return `${plural(Math.floor(elapsed / DAY_MS), "day")} ago`;
  }
  if (elapsed >= HOUR_MS) {
    return `${plural(Math.floor(elapsed / HOUR_MS), "hour")} ago`;
  }
  return "earlier today";
}

/** "a", "a and b", "a, b and c". */
function joinNames(names: readonly string[]): string {
  if (names.length <= 1) {
    return names[0] ?? "";
  }
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * What the row shows now, in words — or `null` when the device cannot say.
 *
 * Naming a value it cannot resolve would be worse than saying less: the second
 * sentence exists to tell the person what they are looking at, and a guess
 * there is a guess about their own data.
 */
function revertedToText(field: ExpiredFieldNotice, names: ExpiredNoticeNames): string | null {
  if (field.field === "project") {
    if (field.revertedTo === null) {
      return "no project";
    }
    return names.project(field.revertedTo) ?? null;
  }
  if (field.revertedTo.length === 0) {
    return "no Tags";
  }
  const resolved = names.tags(field.revertedTo);
  return resolved.length === field.revertedTo.length ? joinNames(resolved) : null;
}

/**
 * FR-018 / SC-003 — the notice for one task's dropped change.
 *
 * It names **the field and what it reverted to**, never a count: a task carries
 * at most one coalesced entry, so "N changes" could not be true here. And with
 * FR-007 having removed every per-change marker, without this sentence the
 * value simply appears to change back on its own, which is precisely the silent
 * loss SC-003 forbids.
 */
export function buildExpiredNotice(
  notice: ExpiredChangeNotice | null,
  names: ExpiredNoticeNames,
  now: Instant,
): ExpiredNoticeView | null {
  if (!notice || notice.fields.length === 0) {
    return null;
  }
  const age = formatChangeAge(notice.lastEditedAt, now);
  const lines = notice.fields.map((field) => {
    const label = field.field === "project" ? ROW_LABELS.project : ROW_LABELS.tags;
    const sentence = `Your change to ${label} from ${age} was not sent and has been discarded.`;
    const reverted = revertedToText(field, names);
    return reverted === null ? sentence : `${sentence} This now shows ${reverted}.`;
  });
  // design.md, focus: the dismiss control sits in tab order immediately after
  // the row it explains. Rows run Project then Tags, so a change that touched
  // both anchors under the later of the two.
  const anchor = notice.fields.some((field) => field.field === "tags") ? "tags" : "project";
  return {
    lines,
    anchor,
    dismissLabel: EXPIRY_DISMISS_LABEL,
    accessibilityLabel: lines.join(" "),
  };
}

// --------------------------------------------------- T066, the account notice

export interface AccountExpiryNotice {
  total: number;
  message: string;
  dismissLabel: string;
}

export interface AccountExpiryNoticeInput {
  /** Every expired entry still held for this identity, across all tasks. */
  expiredTotal: number;
  /** True when this screen already names one of them in full (T065). */
  taskNoticeShown: boolean;
  dismissed: boolean;
}

/**
 * FR-018's account-level MUST — one dismiss-once notice with the total.
 *
 * Triage happens from lists, so a per-task banner alone leaves the requirement
 * unmet for anyone who never reopens that exact task: they would have to guess
 * which of their tasks to visit to learn that anything was dropped at all.
 *
 * The one suppression is deliberate. When the total is one and this screen is
 * already naming that one change in full, the count adds nothing and repeats a
 * sentence the person is looking at. Anything above one is still unaccounted
 * for and is told.
 */
export function resolveAccountExpiryNotice(
  input: AccountExpiryNoticeInput,
): AccountExpiryNotice | null {
  if (input.dismissed || input.expiredTotal <= 0) {
    return null;
  }
  if (input.expiredTotal === 1 && input.taskNoticeShown) {
    return null;
  }
  const total = input.expiredTotal;
  const message =
    total === 1
      ? "1 change older than 30 days was not sent and has been discarded"
      : `${total} changes older than 30 days were not sent and have been discarded`;
  return { total, message, dismissLabel: ACCOUNT_EXPIRY_DISMISS_LABEL };
}

/**
 * "Dismiss once" across screens, for the lifetime of the running app.
 *
 * Module state, deliberately. The notice must not reappear on every task screen
 * the person opens after one sweep, and the screen that shows it is mounted and
 * unmounted per task — so a `useState` cannot remember it and there is no
 * provider in this feature's scope to hold it. It is keyed by identity, so a
 * dismissal never carries across a sign-out or a server change (SC-007).
 *
 * It deliberately does **not** survive a relaunch: the expired entries retain
 * their payloads until each per-task notice is dismissed, so telling the person
 * again on the next launch is the fail-safe direction for a MUST that exists
 * because the alternative is work vanishing unannounced.
 */
const dismissedAccountNotices = new Set<string>();

/** NUL, because it cannot occur in a url or an opaque account id. */
export function accountNoticeKey(identity: ClassificationIdentity | null): string | null {
  return identity ? `${identity.serverUrl}\u0000${identity.accountId}` : null;
}

export function hasDismissedAccountNotice(key: string | null): boolean {
  return key !== null && dismissedAccountNotices.has(key);
}

export function rememberAccountNoticeDismissed(key: string | null): void {
  if (key !== null) {
    dismissedAccountNotices.add(key);
  }
}

/** Tests only. */
export function resetAccountNoticeDismissals(): void {
  dismissedAccountNotices.clear();
}

// -------------------------------------------- T063/T064, identity transitions

export type IdentityTransitionKind = "sign-out" | "server-change";

export interface IdentityTransitionPlan {
  kind: IdentityTransitionKind;
  /** M-05's count. The whole of what the person is told. */
  unsentCount: number;
  needsWarning: boolean;
}

/**
 * FR-011 — whether this deliberate transition has to warn first.
 *
 * An `expired` entry is not unsent work: it has already been discarded and is
 * only being *retained* so its notice can name it. Counting it would tell the
 * person they are about to lose something they were already told they lost.
 *
 * `sending` and `conflicted` both count. In flight is not delivered, and a
 * conflicted entry is a change the person has not yet been asked about — losing
 * either without a word is exactly what SC-008 forbids.
 */
export function planIdentityTransition(
  queue: readonly PendingClassificationChange[],
  kind: IdentityTransitionKind,
): IdentityTransitionPlan {
  const unsentCount = queue.filter((entry) => entry.sendState !== "expired").length;
  // M-05, "empty": the sheet never appears with an empty queue; the action
  // simply proceeds.
  return { kind, unsentCount, needsWarning: unsentCount > 0 };
}

export interface IdentityTransitionSteps {
  /** FR-011 — drop the queue AND the cached lists for the outgoing identity. */
  discard(): Promise<void>;
  /** `signOut()` / `updateServerUrl()`. */
  transition(): Promise<void>;
}

/**
 * The ordering contract, and the reason this trivial-looking function exists.
 *
 * `signOut()` and `updateServerUrl()` both clear the persisted identity, and
 * the persisted identity is both halves of the queue's storage key. Discarding
 * afterwards therefore discards nothing: there is no longer a name for the key
 * to delete. The work is not gone, it is stranded — invisible to the arriving
 * identity by construction (SC-007) and reachable only by the cross-identity
 * sweep, days later, having outlived the account it belonged to on the device.
 *
 * A failed discard aborts the transition rather than proceeding without it, for
 * the same reason: signing out anyway is the outcome this ordering exists to
 * prevent, arrived at by a different route.
 */
export async function performIdentityTransition(steps: IdentityTransitionSteps): Promise<void> {
  await steps.discard();
  await steps.transition();
}

// ------------------------------------------------------ the pickers' own feed

/**
 * `api/hooks.ts` projects a cache fallback with this revision, because the
 * device cannot know the revision of a list it read back from its own storage.
 * A list carrying it was answered by the device, not by the server — which is
 * the only connectivity signal `mobile/` has, since it installs no NetInfo.
 */
export const CACHED_LIST_REVISION = -1;

/**
 * The task's own ids, named where the device can name them.
 *
 * An id with no name is kept rather than dropped: M-03's "offline, never
 * fetched" row is sourced from the task rather than from the uncached list,
 * which is what keeps FR-002's detach reachable on a first-ever visit with no
 * connection.
 */
export function attachedEntities(
  ids: readonly string[],
  known: readonly { id: string; name: string }[] | null,
): AttachedEntity[] {
  const byId = new Map((known ?? []).map((entity) => [entity.id, entity.name]));
  return ids.map((id) => {
    const name = byId.get(id);
    return name === undefined ? { id } : { id, name };
  });
}

/**
 * The picker's three phases from a query's three observable facts.
 *
 * A refetch that failed while the device still holds a list is `loaded`, not
 * `failed`: the picker has something real to offer, and an error state over a
 * usable list would take FR-001's clear and FR-002's detach away for no reason.
 */
export function resolveListPhase(input: {
  pending: boolean;
  failed: boolean;
  hasData: boolean;
}): ListPhase {
  if (input.hasData) {
    return "loaded";
  }
  if (input.failed) {
    return "failed";
  }
  return input.pending ? "loading" : "loaded";
}

export function servedFromCache(
  entities: readonly { revision: number }[] | null | undefined,
): boolean {
  return (entities ?? []).some((entity) => entity.revision === CACHED_LIST_REVISION);
}

export interface ConnectivityInput {
  status: SessionStatusLike;
  /** A list answered from device storage rather than by the server. */
  fromCache: boolean;
  /** A list fetch that failed with nothing cached to answer with. */
  listFailed: boolean;
  /** A list the server answered on this run. */
  hasServerData: boolean;
}

/**
 * FR-016 — whether creating a project or a Tag is available.
 *
 * The list is the better witness than the session: a server that just answered
 * a list request is reachable now, whatever the launch probe concluded, and
 * `signed-in-offline` persists until something re-probes. Getting this wrong in
 * the offline direction only lets a create be attempted and fail, which the
 * picker recovers from with the typed name intact; getting it wrong in the
 * online direction blocks a create that would have worked.
 */
export function resolveOnline(input: ConnectivityInput): boolean {
  if (input.listFailed || input.fromCache) {
    return false;
  }
  if (input.hasServerData) {
    return true;
  }
  return input.status !== "signed-in-offline";
}

/**
 * One classification edit, as the queue wants it.
 *
 * `displayedValue` is what the **device was showing** when the person acted,
 * not what the server holds — invariant 9. The conflict prompt names it as
 * "your phone last showed", and sourcing it from the server instead would tell
 * a confident and false story about who changed what. It is copied rather than
 * referenced so a later render cannot rewrite an entry already queued.
 *
 * `value` carries only the fields this edit touched, and a cleared project
 * travels as an explicit `null` rather than as an omission (FR-001, FR-003) —
 * the two mean opposite things all the way down to the request body.
 *
 * `displayedAt` dates that knowledge for M-04's labelled row. It is omitted
 * rather than guessed when the caller cannot say: an undated row is honest, and
 * one dated from when the *change* was made would claim the phone's picture is
 * 14 minutes old when it may be three weeks old — the precise falsehood the
 * labelled row exists to prevent (FR-010).
 */
export function buildClassificationEdit(
  taskId: string,
  observedRevision: number,
  displayed: ClassificationState,
  value: Partial<ClassificationValue>,
  displayedAt?: string | null,
): Omit<ClassificationEdit, "accountId" | "serverUrl"> {
  const next: Partial<ClassificationValue> = {};
  if ("projectId" in value) {
    next.projectId = value.projectId;
  }
  if ("tagIds" in value && value.tagIds !== undefined) {
    next.tagIds = [...value.tagIds];
  }
  return {
    taskId,
    observedRevision,
    displayedValue: { projectId: displayed.projectId, tagIds: [...displayed.tagIds] },
    value: next,
    ...(displayedAt ? { displayedAt } : {}),
  };
}
