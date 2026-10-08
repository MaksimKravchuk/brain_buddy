/**
 * Browser-local drafts of the review's form text (FR-052, data-model E11).
 *
 * Unsaved wording, a first step, Waiting-for and an extension reason are kept
 * under `bb.reviewFormDraft.v1.<origin>.<account>.<task>.<formulation>` (a
 * project's next action under `project.<project id>`), so a draft never comes
 * back on a newer wording. They are removed on save or discard, when the
 * formulation changes, on sign-out or an account switch, and by a sweep after
 * 7 days. The text fields of the review's own steps are kept the same way under
 * `step.<session>.<step>.<item>.<field>` in place of `<task>.<formulation>`. Drafts are never sent anywhere and never logged: nothing in this
 * module touches the network or the console.
 */
import { getApiBaseUrl } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";

export const DRAFT_PREFIX = "bb.reviewFormDraft.v1";
export const DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
/** Every browser-local review key starts with this (drafts, the WYWA day, the last zone). */
const REVIEW_KEY_PREFIX = "bb.review";

export type DraftForm = "reformulate" | "first_step" | "waiting" | "extend";
/** `step` marks the text of a review step's own field (mind sweep, Inbox, Waiting, Someday, Projects). */
const STEP_FORM = "step";
const DRAFT_FORMS: ReadonlySet<string> = new Set<string>(["reformulate", "first_step", "waiting", "extend", STEP_FORM]);

export interface ReviewDraftScope {
  apiOrigin: string;
  accountId: string;
}

export type ReviewDraftTarget =
  | { kind: "task"; taskId: string; formulationId: string }
  | { kind: "project"; projectId: string };

/** One text field of a review step: the run, the step, the item (task or project) it is about, and which field. */
export interface ReviewStepField {
  sessionId: string;
  step: string;
  itemId: string;
  field: string;
}

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

function stepPrefix(scope: ReviewDraftScope, sessionId: string, step: string): string {
  return `${accountPrefix(scope)}step.${enc(sessionId)}.${enc(step)}.`;
}

/** `<account prefix>step.<session>.<step>.<item>.<field>`: it cannot meet a task or project key. */
export function reviewStepDraftKey(scope: ReviewDraftScope, target: ReviewStepField): string {
  return `${stepPrefix(scope, target.sessionId, target.step)}${enc(target.itemId)}.${enc(target.field)}`;
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

function readDraftAt(key: string, now: Date, storage: Storage): ReviewFormDraft | null {
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

/** The draft for this form's task and wording, or `null`; an expired or corrupt one is removed. */
export function loadReviewDraft(
  scope: ReviewDraftScope,
  target: ReviewDraftTarget,
  now = new Date(),
  storage = defaultStorage()
): ReviewFormDraft | null {
  return readDraftAt(reviewDraftKey(scope, target), now, storage);
}

export function removeReviewDraft(scope: ReviewDraftScope, target: ReviewDraftTarget, storage = defaultStorage()): void {
  attempt(() => storage.removeItem(reviewDraftKey(scope, target)), undefined);
}

/** A review step's field text (FR-052): saving an empty text removes the draft. */
export function saveStepDraft(
  scope: ReviewDraftScope,
  target: ReviewStepField,
  text: string,
  now = new Date(),
  storage = defaultStorage()
): void {
  const key = reviewStepDraftKey(scope, target);
  if (text === "") {
    attempt(() => storage.removeItem(key), undefined);
    return;
  }
  const value: ReviewFormDraft = { form: STEP_FORM as DraftForm, text, savedAt: now.toISOString() };
  attempt(() => storage.setItem(key, JSON.stringify(value)), undefined);
}

/** The text of a step field's draft, or `null`; an expired or corrupt one is removed. */
export function loadStepDraft(scope: ReviewDraftScope, target: ReviewStepField, now = new Date(), storage = defaultStorage()): string | null {
  return readDraftAt(reviewStepDraftKey(scope, target), now, storage)?.text ?? null;
}

export function removeStepDraft(scope: ReviewDraftScope, target: ReviewStepField, storage = defaultStorage()): void {
  attempt(() => storage.removeItem(reviewStepDraftKey(scope, target)), undefined);
}

/** Every field draft of one step of one run (the step's text was discarded). */
export function removeStepDrafts(scope: ReviewDraftScope, sessionId: string, step: string, storage = defaultStorage()): void {
  const prefix = stepPrefix(scope, sessionId, step);
  for (const key of keysOf(storage)) {
    if (key.startsWith(prefix)) {
      attempt(() => storage.removeItem(key), undefined);
    }
  }
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

/** `bb.review<Name>.v<N>`: the namespace of every browser-local review key. */
const REVIEW_NAMESPACE = /^bb\.review[A-Za-z]+\.v\d+(?=\.)/;

/**
 * Whether a review key belongs to this account: `<namespace>.<origin>.<account>`
 * exactly, or followed by `.<more>`. `null` for a key that is not a review key.
 */
function ownedBy(key: string, scope: ReviewDraftScope): boolean | null {
  const namespace = REVIEW_NAMESPACE.exec(key)?.[0];
  if (namespace === undefined) {
    return null;
  }
  const owner = `.${enc(scope.apiOrigin)}.${enc(scope.accountId)}`;
  const rest = key.slice(namespace.length);
  return rest === owner || rest.startsWith(`${owner}.`);
}

/**
 * Startup and window-focus sweep, whatever the `weekly_review` flag says:
 * drafts older than 7 days (or unreadable) go, and with an account signed in
 * every review key of any other account goes too (drafts, the
 * While-you-were-away day, the last zone: an account switch). With nobody
 * signed in only expired drafts are removed, of any account.
 */
export function sweepReviewLocalState(scope: ReviewDraftScope | null, now = new Date(), storage = defaultStorage()): void {
  for (const key of keysOf(storage)) {
    const own = scope === null ? null : ownedBy(key, scope);
    if (own === false) {
      attempt(() => storage.removeItem(key), undefined);
      continue;
    }
    if (!key.startsWith(`${DRAFT_PREFIX}.`)) {
      continue;
    }
    const draft = parseDraft(attempt(() => storage.getItem(key), null));
    if (!draft || isExpired(draft, now)) {
      attempt(() => storage.removeItem(key), undefined);
    }
  }
}

/** Sign-out or account switch: every browser-local review key of that account. */
export function clearReviewLocalState(scope: ReviewDraftScope, storage = defaultStorage()): void {
  for (const key of keysOf(storage)) {
    if (key.startsWith(REVIEW_KEY_PREFIX) && ownedBy(key, scope) === true) {
      attempt(() => storage.removeItem(key), undefined);
    }
  }
}

/** Clears the departing account's review keys whenever the signed-in account changes. */
export function subscribeReviewLocalCleanup(apiOrigin = getApiBaseUrl()): () => void {
  return useAuthStore.subscribe((state, previous) => {
    const departing = previous.user?.id;
    if (departing !== undefined && departing !== state.user?.id) {
      clearReviewLocalState({ apiOrigin, accountId: departing });
    }
  });
}

/**
 * Production lifecycle binding, started once at app start from `queryClient.ts`
 * and independent of the `weekly_review` flag and of the shell being mounted
 * (FR-052, data-model E11): the departing account's keys are cleared on
 * sign-out, `clearSession` and an account switch; the sweep runs at start,
 * whenever an account signs in, and on window focus.
 */
export function bindReviewLocalState(apiOrigin = getApiBaseUrl()): () => void {
  const sweep = () => {
    const accountId = useAuthStore.getState().user?.id;
    sweepReviewLocalState(accountId === undefined ? null : { apiOrigin, accountId });
  };
  sweep();
  const stopCleanup = subscribeReviewLocalCleanup(apiOrigin);
  const stopArrivals = useAuthStore.subscribe((state, previous) => {
    if (state.user !== null && state.user.id !== previous.user?.id) {
      sweep();
    }
  });
  window.addEventListener("focus", sweep);
  return () => {
    stopCleanup();
    stopArrivals();
    window.removeEventListener("focus", sweep);
  };
}
