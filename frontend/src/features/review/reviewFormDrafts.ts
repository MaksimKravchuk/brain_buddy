/**
 * Browser-local drafts of the review's form text (FR-052, data-model E11).
 *
 * Unsaved wording, a first step, Waiting-for and an extension reason are kept
 * under `bb.reviewFormDraft.v1.<origin>.<account>.<task>.<formulation>` (a
 * project's next action under `project.<project id>`), so a draft never comes
 * back on a newer wording. They are removed on save or discard, when the
 * formulation changes, on sign-out or an account switch, and by a sweep after
 * 7 days. Drafts are never sent anywhere and never logged: nothing in this
 * module touches the network or the console.
 */
import { getApiBaseUrl } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";

export const DRAFT_PREFIX = "bb.reviewFormDraft.v1";
export const DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
/** Every browser-local review key starts with this (drafts, the WYWA day, the last zone). */
const REVIEW_KEY_PREFIX = "bb.review";

export type DraftForm = "reformulate" | "first_step" | "waiting" | "extend";
const DRAFT_FORMS: ReadonlySet<string> = new Set<DraftForm>(["reformulate", "first_step", "waiting", "extend"]);

export interface ReviewDraftScope {
  apiOrigin: string;
  accountId: string;
}

export type ReviewDraftTarget =
  | { kind: "task"; taskId: string; formulationId: string }
  | { kind: "project"; projectId: string };

export interface ReviewFormDraft {
  form: DraftForm;
  text: string;
  savedAt: string;
}

const enc = encodeURIComponent;

function accountPrefix(scope: ReviewDraftScope): string {
  return `${DRAFT_PREFIX}.${enc(scope.apiOrigin)}.${enc(scope.accountId)}.`;
}

export function reviewDraftKey(scope: ReviewDraftScope, target: ReviewDraftTarget): string {
  const subject = target.kind === "task"
    ? `${enc(target.taskId)}.${enc(target.formulationId)}`
    : `project.${enc(target.projectId)}`;
  return `${accountPrefix(scope)}${subject}`;
}

function defaultStorage(): Storage {
  return window.localStorage;
}

/** Storage can refuse (private mode, quota); a draft is best effort, never an error. */
function attempt<T>(action: () => T, fallback: T): T {
  try {
    return action();
  } catch {
    return fallback;
  }
}

function keysOf(storage: Storage): string[] {
  return attempt(() => Array.from({ length: storage.length }, (_, index) => storage.key(index) as string), []);
}

function parseDraft(raw: string | null): ReviewFormDraft | null {
  const value: unknown = attempt(() => JSON.parse(raw as string), null);
  if (
    typeof value !== "object" ||
    value === null ||
    !DRAFT_FORMS.has((value as ReviewFormDraft).form) ||
    typeof (value as ReviewFormDraft).text !== "string" ||
    typeof (value as ReviewFormDraft).savedAt !== "string"
  ) {
    return null;
  }
  return value as ReviewFormDraft;
}

function isExpired(draft: ReviewFormDraft, now: Date): boolean {
  return now.getTime() - Date.parse(draft.savedAt) >= DRAFT_MAX_AGE_MS;
}

export function saveReviewDraft(
  scope: ReviewDraftScope,
  target: ReviewDraftTarget,
  draft: { form: DraftForm; text: string },
  now = new Date(),
  storage = defaultStorage()
): void {
  const key = reviewDraftKey(scope, target);
  if (draft.text === "") {
    attempt(() => storage.removeItem(key), undefined);
    return;
  }
  const value: ReviewFormDraft = { form: draft.form, text: draft.text, savedAt: now.toISOString() };
  attempt(() => storage.setItem(key, JSON.stringify(value)), undefined);
}

/** The draft for this form's task and wording, or `null`; an expired or corrupt one is removed. */
export function loadReviewDraft(
  scope: ReviewDraftScope,
  target: ReviewDraftTarget,
  now = new Date(),
  storage = defaultStorage()
): ReviewFormDraft | null {
  const key = reviewDraftKey(scope, target);
  const raw = attempt(() => storage.getItem(key), null);
  if (raw === null) {
    return null;
  }
  const draft = parseDraft(raw);
  if (!draft || isExpired(draft, now)) {
    attempt(() => storage.removeItem(key), undefined);
    return null;
  }
  return draft;
}

export function removeReviewDraft(scope: ReviewDraftScope, target: ReviewDraftTarget, storage = defaultStorage()): void {
  attempt(() => storage.removeItem(reviewDraftKey(scope, target)), undefined);
}

/** The task's wording changed: its drafts for any other formulation are stale. */
export function removeOtherFormulationDrafts(
  scope: ReviewDraftScope,
  taskId: string,
  currentFormulationId: string | null,
  storage = defaultStorage()
): void {
  const taskPrefix = `${accountPrefix(scope)}${enc(taskId)}.`;
  const keep = currentFormulationId === null ? null : `${taskPrefix}${enc(currentFormulationId)}`;
  for (const key of keysOf(storage)) {
    if (key.startsWith(taskPrefix) && key !== keep) {
      attempt(() => storage.removeItem(key), undefined);
    }
  }
}

/**
 * Startup and window-focus sweep: drafts older than 7 days go, and so do the
 * drafts of any other account in this browser (an account switch).
 */
export function sweepReviewDrafts(scope: ReviewDraftScope, now = new Date(), storage = defaultStorage()): void {
  const own = accountPrefix(scope);
  for (const key of keysOf(storage)) {
    if (!key.startsWith(`${DRAFT_PREFIX}.`)) {
      continue;
    }
    const draft = key.startsWith(own) ? parseDraft(attempt(() => storage.getItem(key), null)) : null;
    if (!draft || isExpired(draft, now)) {
      attempt(() => storage.removeItem(key), undefined);
    }
  }
}

/** Sign-out or account switch: every browser-local review key of that account. */
export function clearReviewLocalState(scope: ReviewDraftScope, storage = defaultStorage()): void {
  const owner = `.${enc(scope.apiOrigin)}.${enc(scope.accountId)}`;
  for (const key of keysOf(storage)) {
    if (key.startsWith(REVIEW_KEY_PREFIX) && (key.includes(`${owner}.`) || key.endsWith(owner))) {
      attempt(() => storage.removeItem(key), undefined);
    }
  }
}

/** Clears the departing account's review keys whenever the signed-in account changes. */
export function subscribeReviewLocalCleanup(): () => void {
  return useAuthStore.subscribe((state, previous) => {
    const departing = previous.user?.id;
    if (departing !== undefined && departing !== state.user?.id) {
      clearReviewLocalState({ apiOrigin: getApiBaseUrl(), accountId: departing });
    }
  });
}
