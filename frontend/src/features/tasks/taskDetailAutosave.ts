import { ApiError, apiClient } from "../../api/client";
import type { OpenTaskState, TaskResponse, TaskTransitionRequest, TaskUpdateRequest } from "../../api/taskTypes";

export type EditableField = "title" | "details" | "state" | "project_id" | "priority" | "tag_ids" | "waiting_for" | "due_date";
export type TaskDraft = Pick<TaskResponse, EditableField>;
export type DirtyValue = { baseValue: TaskDraft[EditableField]; generation: number; value: TaskDraft[EditableField] };
export type AutosaveStatus = "clean" | "queued" | "saving" | "retrying" | "saved" | "conflicted" | "failed";
export type AutosaveError = { kind: "network" | "validation" | "unauthorized" | "unavailable" | "protocol"; message: string; retryAllowed: boolean; offline: boolean; refetchFailed?: boolean };
export type AutosaveConflict = { latestServerTask: TaskResponse | null; correlationId?: string; rejectedCommandKind: "patch" | "transition"; refetchFailed: boolean };

type InFlight = {
  kind: "patch" | "transition";
  body: TaskUpdateRequest | TaskTransitionRequest;
  generations: Partial<Record<EditableField, number>>;
  idempotencyKey: string;
  attempt: number;
};
type Barrier = { action: "complete" | "cancel" | "reopen"; toState?: OpenTaskState };
type PersistedState = {
  version: 1;
  identity: { accountId: string; apiOrigin: string; taskId: string };
  baseline: TaskResponse;
  draft: TaskDraft;
  dirty: Partial<Record<EditableField, DirtyValue>>;
  inFlight: InFlight | null;
  barriers: Barrier[];
  status: AutosaveStatus;
  conflict: AutosaveConflict | null;
  error: AutosaveError | null;
  retrying: boolean;
  /** Compatibility projection for callers that only inspected the active body. */
  body?: TaskUpdateRequest | TaskTransitionRequest;
};
export type AutosaveSnapshot = PersistedState & { dirtyFields: EditableField[]; queuedCount: number };
export type AutosaveResult =
  | { status: "saved"; task: TaskResponse }
  | { status: "conflict"; task: TaskResponse; retry: () => Promise<AutosaveResult>; discard: () => TaskResponse };
export type AutosaveCommand =
  | { kind: "patch"; payload: Omit<TaskUpdateRequest, "expected_revision"> }
  | { kind: "transition"; payload: Omit<TaskTransitionRequest, "expected_revision"> };

const STORAGE_PREFIX = "bb.taskDetailDraft.v1";
const fields: EditableField[] = ["title", "details", "state", "project_id", "priority", "tag_ids", "waiting_for", "due_date"];
const openStates: OpenTaskState[] = ["inbox", "next", "waiting", "someday"];
class TaskProtocolError extends Error {}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const sortedTags = (value: string[]) => [...new Set(value)].sort();
const equal = (field: EditableField, left: unknown, right: unknown) => field === "tag_ids"
  ? JSON.stringify(sortedTags((left as string[]) ?? [])) === JSON.stringify(sortedTags((right as string[]) ?? []))
  : left === right;
const draftFrom = (task: TaskResponse): TaskDraft => ({
  title: task.title,
  details: task.details,
  state: task.state,
  project_id: task.project_id,
  priority: task.priority,
  tag_ids: sortedTags(task.tag_ids),
  waiting_for: task.waiting_for,
  due_date: task.due_date
});
const normalize = (field: EditableField, value: TaskDraft[EditableField]): TaskDraft[EditableField] => {
  if (field === "tag_ids") return sortedTags(value as string[]);
  if (field === "details" || field === "due_date" || field === "project_id") return value === "" ? null : value;
  return value;
};
const randomKey = () => globalThis.crypto?.randomUUID?.() ?? `autosave-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
// Subtasks and comments have their own revisions. GET includes those projections,
// while parent mutation acknowledgements leave them empty; neither changes the
// parent revision. Compare only parent-owned data, independently of JSON key order.
const taskEqual = (a: TaskResponse, b: TaskResponse) => fields.every((field) => equal(field, a[field], b[field])) &&
  (["id", "waiting_since", "order_key", "created_at", "updated_at", "completed_at", "cancelled_at", "revision"] as const)
    .every((field) => a[field] === b[field]) &&
  a.source_capture_ids.length === b.source_capture_ids.length &&
  a.source_capture_ids.every((id, index) => id === b.source_capture_ids[index]);

export function taskAutosaveStorageKey(accountId: string, apiOrigin: string, taskId: string): string {
  if (!accountId || !apiOrigin || !taskId) throw new Error("Autosave identity is incomplete");
  return `${STORAGE_PREFIX}.${encodeURIComponent(apiOrigin)}.${encodeURIComponent(accountId)}.${encodeURIComponent(taskId)}`;
}

function validTask(value: unknown): value is TaskResponse {
  if (!isRecord(value)) return false;
  return typeof value.id === "string" && typeof value.title === "string" &&
    ["inbox", "next", "waiting", "someday", "completed", "cancelled"].includes(String(value.state)) &&
    (value.details === null || typeof value.details === "string") &&
    (value.project_id === null || typeof value.project_id === "string") &&
    Array.isArray(value.tag_ids) && value.tag_ids.every((id) => typeof id === "string") &&
    (value.due_date === null || typeof value.due_date === "string") &&
    ["none", "low", "medium", "high"].includes(String(value.priority)) &&
    (value.waiting_for === null || typeof value.waiting_for === "string") &&
    typeof value.revision === "number" && Number.isInteger(value.revision) &&
    Array.isArray(value.source_capture_ids) && Array.isArray(value.subtasks) && Array.isArray(value.comments);
}

/** A malformed or non-monotonic mutation response can never become canonical. */
export function validateTaskResponse(
  value: unknown,
  taskId: string,
  previousRevision: number,
  command?: AutosaveCommand,
  requireAdvance = true,
  previousState?: TaskResponse["state"]
): TaskResponse {
  if (!validTask(value) || value.id !== taskId || (requireAdvance && value.revision <= previousRevision)) {
    throw new TaskProtocolError("Server returned an invalid task acknowledgement");
  }
  const waitingValid = value.state === "waiting"
    ? Boolean(value.waiting_for?.trim()) && typeof value.waiting_since === "string"
    : value.waiting_for === null && value.waiting_since === null;
  const terminalValid = value.state === "completed"
    ? value.completed_at !== null && value.cancelled_at === null
    : value.state === "cancelled"
      ? value.cancelled_at !== null && value.completed_at === null
      : value.completed_at === null && value.cancelled_at === null;
  if (!waitingValid || !terminalValid) throw new TaskProtocolError("Server returned an invalid task acknowledgement");
  if (command?.kind === "patch") {
    if (previousState !== undefined && value.state !== previousState) throw new TaskProtocolError("Server returned an invalid task acknowledgement");
    for (const [key, expected] of Object.entries(command.payload)) {
      if (expected !== undefined && !equal(key as EditableField, value[key as keyof TaskResponse], expected)) {
        throw new TaskProtocolError("Server acknowledgement does not match the saved task");
      }
    }
  }
  if (command?.kind === "transition") {
    const { action, to_state: toState, waiting_for: waitingFor } = command.payload;
    if (action === "complete" && value.state !== "completed") throw new TaskProtocolError("Server returned an invalid task acknowledgement");
    if (action === "cancel" && value.state !== "cancelled") throw new TaskProtocolError("Server returned an invalid task acknowledgement");
    if ((action === "move" || action === "reopen") && value.state !== toState) throw new TaskProtocolError("Server returned an invalid task acknowledgement");
    if (action === "reopen" && (!previousState || !["completed", "cancelled"].includes(previousState))) throw new TaskProtocolError("Server returned an invalid task acknowledgement");
    if (toState === "waiting" && value.waiting_for !== waitingFor?.trim()) throw new TaskProtocolError("Server returned an invalid task acknowledgement");
  }
  return value;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && isRecord(error.payload)) {
    const detail = error.payload.detail;
    if (typeof detail === "string") return detail;
  }
  return error instanceof Error ? error.message : "Couldn’t save changes";
}
function retryable(error: unknown): boolean {
  return error instanceof TypeError || error instanceof ApiError && (error.status === 408 || error.status === 429 || error.status >= 500);
}
function validInFlight(value: unknown): value is InFlight {
  if (!isRecord(value) || (value.kind !== "patch" && value.kind !== "transition") || !isRecord(value.body) || !isRecord(value.generations) ||
    typeof value.idempotencyKey !== "string" || value.idempotencyKey.length === 0 || !Number.isInteger(value.attempt) || Number(value.attempt) < 1 || Number(value.attempt) > 3 ||
    !Number.isInteger(value.body.expected_revision) || Number(value.body.expected_revision) < 0) return false;
  if (value.kind === "patch") {
    const allowed = new Set(["expected_revision", "title", "details", "project_id", "priority", "tag_ids", "waiting_for", "due_date"]);
    return Object.keys(value.body).every((key) => allowed.has(key)) && Object.keys(value.body).length > 1;
  }
  const action = value.body.action;
  if (!["move", "complete", "cancel", "reopen"].includes(String(action))) return false;
  if (action === "move" || action === "reopen") return openStates.includes(value.body.to_state as OpenTaskState);
  return value.body.to_state === undefined && value.body.waiting_for === undefined;
}
function persisted(accountId: string, apiOrigin: string, taskId: string): PersistedState | null {
  if (typeof sessionStorage === "undefined") return null;
  const key = taskAutosaveStorageKey(accountId, apiOrigin, taskId);
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(key) ?? "null");
    const valid = isRecord(value) && value.version === 1 && isRecord(value.identity) && value.identity.accountId === accountId && value.identity.apiOrigin === apiOrigin && value.identity.taskId === taskId &&
      validTask(value.baseline) && isRecord(value.draft) && isRecord(value.dirty) && Array.isArray(value.barriers) && (value.inFlight === null || validInFlight(value.inFlight));
    if (!valid) {
      sessionStorage.removeItem(key);
      return null;
    }
    return value as unknown as PersistedState;
  } catch {
    sessionStorage.removeItem(key);
    return null;
  }
}

export function loadTaskAutosaveRecovery(accountId: string, taskId: string, apiOrigin = window.location.origin): PersistedState | null {
  return persisted(accountId, apiOrigin, taskId);
}

export function createTaskDetailAutosaveController(
  accountId: string,
  apiOriginOrTask: string | TaskResponse,
  taskOrAccepted?: TaskResponse | ((task: TaskResponse) => void | Promise<void>),
  onAccepted?: (task: TaskResponse) => void | Promise<void>
) {
  const apiOrigin = typeof apiOriginOrTask === "string" ? apiOriginOrTask : window.location.origin;
  const suppliedTask = typeof apiOriginOrTask === "string" ? taskOrAccepted as TaskResponse : apiOriginOrTask;
  let acceptedCallback = (typeof apiOriginOrTask === "string" ? onAccepted : taskOrAccepted) as ((task: TaskResponse) => void | Promise<void>) | undefined;
  const restored = persisted(accountId, apiOrigin, suppliedTask.id);
  let state: PersistedState = restored ?? {
    version: 1,
    identity: { accountId, apiOrigin, taskId: suppliedTask.id },
    baseline: suppliedTask,
    draft: draftFrom(suppliedTask),
    dirty: {},
    inFlight: null,
    barriers: [],
    status: "clean",
    conflict: null,
    error: null,
    retrying: false
  };
  if (restored?.status === "saving" || restored?.status === "retrying") state = { ...state, status: "queued", retrying: false };
  const listeners = new Set<() => void>();
  const timers = new Map<EditableField, ReturnType<typeof setTimeout>>();
  let snapshot: AutosaveSnapshot;
  let running: Promise<void> | null = null;
  let requestedKey: string | undefined;
  let savedTimer: ReturnType<typeof setTimeout> | null = null;
  const idleWaiters = new Set<() => void>();
  const pausedWaiters = new Set<() => void>();

  const derive = () => {
    const dirtyFields = fields.filter((field) => state.dirty[field]);
    const queuedCount = dirtyFields.filter((field) => state.inFlight?.generations[field] !== state.dirty[field]?.generation).length;
    if (!state.conflict && !state.error) {
      if (state.inFlight) state.status = state.retrying ? "retrying" : queuedCount || state.barriers.length ? "queued" : "saving";
      else if (dirtyFields.length || state.barriers.length) state.status = "queued";
      else if (state.status !== "saved") state.status = "clean";
    }
    snapshot = { ...state, dirty: { ...state.dirty }, draft: { ...state.draft, tag_ids: [...state.draft.tag_ids] }, dirtyFields, queuedCount };
  };
  const persistAndEmit = () => {
    derive();
    if (typeof sessionStorage !== "undefined") {
      const key = taskAutosaveStorageKey(accountId, apiOrigin, suppliedTask.id);
      if (state.status === "clean" || state.status === "saved") sessionStorage.removeItem(key);
      else sessionStorage.setItem(key, JSON.stringify(state));
    }
    listeners.forEach((listener) => listener());
    if ((state.status === "clean" || state.status === "saved") && !running && timers.size === 0) {
      idleWaiters.forEach((resolve) => resolve()); idleWaiters.clear();
    }
    if ((state.status === "failed" || state.status === "conflicted") && !running) {
      pausedWaiters.forEach((resolve) => resolve()); pausedWaiters.clear();
    }
  };
  derive();

  const markFailed = (error: unknown, kind?: AutosaveError["kind"], retryAllowed = true) => {
    const apiStatus = error instanceof ApiError ? error.status : 0;
    state.error = {
      kind: kind ?? (error instanceof TaskProtocolError ? "protocol" : error instanceof TypeError ? "network" : apiStatus === 400 || apiStatus === 422 ? "validation" : apiStatus === 401 ? "unauthorized" : apiStatus === 404 ? "unavailable" : "network"),
      message: errorMessage(error),
      retryAllowed: retryAllowed && apiStatus !== 401 && apiStatus !== 404,
      offline: typeof navigator !== "undefined" && navigator.onLine === false
    };
    state.status = "failed";
    state.retrying = false;
  };

  const mergeCanonical = (canonical: TaskResponse) => {
    const canonicalDraft = draftFrom(canonical);
    const nextDraft = { ...state.draft };
    for (const field of fields) if (!state.dirty[field]) (nextDraft[field] as never) = canonicalDraft[field] as never;
    state = { ...state, baseline: canonical, draft: nextDraft };
  };
  const clearDirty = (field: EditableField) => {
    state.dirty = Object.fromEntries(Object.entries(state.dirty).filter(([key]) => key !== field)) as PersistedState["dirty"];
  };

  const build = (): InFlight | null => {
    const takeKey = () => {
      const key = requestedKey ?? randomKey();
      requestedKey = undefined;
      return key;
    };
    const stateDirty = state.dirty.state;
    if (stateDirty && state.draft.state !== state.baseline.state) {
      const target = state.draft.state;
      const action = ["completed", "cancelled"].includes(state.baseline.state) ? "reopen" : "move";
      const generations: Partial<Record<EditableField, number>> = { state: stateDirty.generation };
      const body: TaskTransitionRequest = { action, to_state: target as OpenTaskState, expected_revision: state.baseline.revision };
      if (target === "waiting") {
        const waiting = state.draft.waiting_for?.trim();
        if (!waiting) return null;
        body.waiting_for = waiting;
        if (state.dirty.waiting_for) generations.waiting_for = state.dirty.waiting_for.generation;
      }
      return { kind: "transition", body, generations, idempotencyKey: takeKey(), attempt: 1 };
    }
    const body: Record<string, unknown> = { expected_revision: state.baseline.revision };
    const generations: Partial<Record<EditableField, number>> = {};
    for (const field of fields) {
      const dirty = state.dirty[field];
      if (!dirty || field === "state") continue;
      if (field === "waiting_for" && state.baseline.state !== "waiting") continue;
      if (field === "title" && !(state.draft.title as string).trim()) continue;
      body[field] = field === "title" || field === "details" || field === "waiting_for"
        ? (state.draft[field] as string | null)?.trim() || null
        : state.draft[field];
      generations[field] = dirty.generation;
    }
    if (Object.keys(generations).length) return { kind: "patch", body: body as unknown as TaskUpdateRequest, generations, idempotencyKey: takeKey(), attempt: 1 };
    if (state.barriers.length) {
      const barrier = state.barriers.shift();
      if (!barrier) return null;
      return {
        kind: "transition",
        body: { action: barrier.action, to_state: barrier.toState, expected_revision: state.baseline.revision },
        generations: {}, idempotencyKey: takeKey(), attempt: 1
      };
    }
    return null;
  };

  const handleConflict = async (command: InFlight, error: ApiError) => {
    if (command.kind === "transition") {
      const body = command.body as TaskTransitionRequest;
      if (body.action === "complete" || body.action === "cancel" || body.action === "reopen") {
        state.barriers.unshift({ action: body.action, toState: body.to_state });
      }
    }
    state.inFlight = null;
    state.conflict = { latestServerTask: null, correlationId: error.correlationId, rejectedCommandKind: command.kind, refetchFailed: false };
    state.error = null;
    state.status = "conflicted";
    persistAndEmit();
    try {
      const canonical = validateTaskResponse(await apiClient.getTask(suppliedTask.id), suppliedTask.id, state.baseline.revision, undefined, false);
      if (canonical.revision < state.baseline.revision || canonical.revision === state.baseline.revision && !taskEqual(canonical, state.baseline)) throw new Error("Server returned contradictory canonical task data");
      mergeCanonical(canonical);
      const conflict = state.conflict;
      if (conflict) state.conflict = { ...conflict, latestServerTask: canonical, refetchFailed: false };
    } catch {
      const conflict = state.conflict;
      if (conflict) state.conflict = { ...conflict, refetchFailed: true };
    }
    persistAndEmit();
  };

  const dispatch = async (command: InFlight) => {
    state.inFlight = command;
    state.error = null;
    persistAndEmit();
    while (state.inFlight === command) {
      try {
        const response = command.kind === "patch"
          ? await apiClient.updateTask(suppliedTask.id, command.body as TaskUpdateRequest, command.idempotencyKey)
          : await apiClient.transitionTask(suppliedTask.id, command.body as TaskTransitionRequest, command.idempotencyKey);
        const previousState = state.baseline.state;
        const payload = Object.fromEntries(Object.entries(command.body).filter(([key]) => key !== "expected_revision"));
        const accepted = validateTaskResponse(response, suppliedTask.id, Math.max(state.baseline.revision, Number(command.body.expected_revision)), { kind: command.kind, payload } as AutosaveCommand, true, previousState);
        state.baseline = accepted;
        for (const [field, generation] of Object.entries(command.generations) as [EditableField, number][]) {
          const dirty = state.dirty[field];
          if (dirty?.generation === generation && equal(field, draftFrom(accepted)[field], state.draft[field])) clearDirty(field);
        }
        if (accepted.state !== "waiting" && state.draft.state !== "waiting" && state.dirty.waiting_for) {
          clearDirty("waiting_for");
          state.draft.waiting_for = null;
        }
        const acceptedDraft = draftFrom(accepted);
        for (const field of fields) if (!state.dirty[field]) (state.draft[field] as never) = acceptedDraft[field] as never;
        state.inFlight = null;
        state.retrying = false;
        state.error = null;
        await acceptedCallback?.(accepted);
        persistAndEmit();
        return;
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) { await handleConflict(command, error); return; }
        if (retryable(error) && command.attempt < 3) {
          command = { ...command, attempt: command.attempt + 1 };
          state.inFlight = command;
          state.retrying = true;
          persistAndEmit();
          const fallback = command.attempt === 2 ? 500 : 1500;
          const delay = error instanceof ApiError && error.status === 429 && error.retryAfterMs !== undefined ? Math.min(Math.max(error.retryAfterMs, 0), 10_000) : fallback;
          await wait(delay);
          continue;
        }
        state.inFlight = command;
        markFailed(error);
        persistAndEmit();
        return;
      }
    }
  };

  const drain = async () => {
    if (running || state.inFlight || state.conflict || state.error) return;
    running = (async () => {
      while (!state.conflict && !state.error) {
        const next = build();
        if (!next) break;
        await dispatch(next);
        if (state.inFlight || state.conflict || state.error) break;
      }
    })();
    await running;
    running = null;
    if (!state.inFlight && !state.conflict && !state.error && !build()) {
      if (fields.every((field) => !state.dirty[field])) {
        state.status = "saved";
        persistAndEmit();
        if (savedTimer) clearTimeout(savedTimer);
        savedTimer = setTimeout(() => { state.status = "clean"; savedTimer = null; persistAndEmit(); }, 2000);
      } else persistAndEmit();
    } else persistAndEmit();
  };
  const schedule = (field: EditableField, delayMs: number) => {
    const existing = timers.get(field); if (existing) clearTimeout(existing);
    if (delayMs > 0) {
      const timer = setTimeout(() => { timers.delete(field); void drain(); }, delayMs);
      timers.set(field, timer);
    } else queueMicrotask(() => void drain());
  };
  const flushTimers = () => { timers.forEach(clearTimeout); timers.clear(); };

  const controller = {
    subscribe(listener: () => void) { listeners.add(listener); return () => listeners.delete(listener); },
    getSnapshot() { return snapshot; },
    get task() { return state.baseline; },
    change(field: EditableField, value: TaskDraft[EditableField], delayMs = 0) {
      const next = normalize(field, value);
      const old = state.dirty[field];
      (state.draft[field] as never) = next as never;
      if (equal(field, next, state.baseline[field])) clearDirty(field);
      else state.dirty[field] = { baseValue: old?.baseValue ?? state.baseline[field], generation: (old?.generation ?? 0) + 1, value: next } as DirtyValue;
      persistAndEmit();
      if (!state.conflict && !state.error) schedule(field, delayMs);
    },
    flush(field?: EditableField) {
      if (field) { const timer = timers.get(field); if (timer) clearTimeout(timer); timers.delete(field); }
      else flushTimers();
      void drain();
    },
    transition(toState: OpenTaskState) {
      if (toState === "waiting" && !state.draft.waiting_for?.trim()) return { accepted: false as const, reason: "waiting-required" as const };
      controller.change("state", toState, 0);
      return { accepted: true as const };
    },
    barrier(action: Barrier["action"], toState?: OpenTaskState) {
      flushTimers(); state.barriers.push({ action, toState }); persistAndEmit(); void drain();
    },
    retry() {
      if (state.conflict) {
        if (!state.conflict.latestServerTask) return;
        state.conflict = null; state.error = null; state.inFlight = null; state.retrying = true; persistAndEmit(); void drain(); return;
      }
      if (state.error?.retryAllowed && state.inFlight) {
        const failed = state.inFlight;
        state.error = null; state.retrying = true; state.inFlight = null; persistAndEmit();
        running = dispatch(failed).then(() => undefined);
        void running.then(() => { running = null; void drain(); persistAndEmit(); });
      } else if (!state.error && !state.inFlight) {
        flushTimers(); void drain();
      }
    },
    async retryRefetch() {
      if (!state.conflict && (state.error?.kind !== "protocol" || state.inFlight)) return;
      try {
        const canonical = validateTaskResponse(await apiClient.getTask(suppliedTask.id), suppliedTask.id, state.baseline.revision, undefined, false);
        if (canonical.revision < state.baseline.revision || canonical.revision === state.baseline.revision && !taskEqual(canonical, state.baseline)) throw new Error("Server returned contradictory canonical task data");
        mergeCanonical(canonical);
        if (state.conflict) state.conflict = { ...state.conflict, latestServerTask: canonical, refetchFailed: false };
        else {
          state.error = null;
          state.status = "clean";
          if (fields.some((field) => state.dirty[field]) || state.barriers.length) {
            state.conflict = { latestServerTask: canonical, rejectedCommandKind: state.barriers.length ? "transition" : "patch", refetchFailed: false };
            state.status = "conflicted";
          } else await acceptedCallback?.(canonical);
        }
      } catch (error) {
        if (state.conflict) state.conflict = { ...state.conflict, refetchFailed: true };
        else if (state.error) state.error = { ...state.error, message: errorMessage(error), refetchFailed: true };
      }
      persistAndEmit();
    },
    discard() {
      const canonical = state.conflict?.latestServerTask ?? state.baseline;
      state = { ...state, baseline: canonical, draft: draftFrom(canonical), dirty: {}, inFlight: null, barriers: [], conflict: null, error: null, retrying: false, status: "clean" };
      flushTimers(); persistAndEmit(); void acceptedCallback?.(canonical); return canonical;
    },
    sync(nextTask: TaskResponse) {
      if (nextTask.id !== suppliedTask.id || nextTask.revision < state.baseline.revision) return;
      if (nextTask.revision === state.baseline.revision) {
        if (!taskEqual(nextTask, state.baseline)) { state.inFlight = null; markFailed(new Error("Server returned contradictory canonical task data"), "protocol", false); persistAndEmit(); return; }
        const childrenChanged = JSON.stringify([nextTask.subtasks, nextTask.comments]) !== JSON.stringify([state.baseline.subtasks, state.baseline.comments]);
        if (childrenChanged) { mergeCanonical(nextTask); persistAndEmit(); }
        return;
      }
      mergeCanonical(nextTask); persistAndEmit();
    },
    setOnAccepted(callback?: (task: TaskResponse) => void | Promise<void>) { acceptedCallback = callback; },
    whenIdle() { if ((state.status === "clean" || state.status === "saved") && !running && timers.size === 0) return Promise.resolve(); return new Promise<void>((resolve) => idleWaiters.add(resolve)); },
    whenPaused() { if ((state.status === "failed" || state.status === "conflicted") && !running) return Promise.resolve(); return new Promise<void>((resolve) => pausedWaiters.add(resolve)); },
    save(command: AutosaveCommand, key?: string): Promise<AutosaveResult> {
      requestedKey = key;
      if (command.kind === "patch") for (const [field, value] of Object.entries(command.payload) as [EditableField, TaskDraft[EditableField]][]) controller.change(field, value, 0);
      else if (command.payload.action === "move" || command.payload.action === "reopen") {
        if (command.payload.waiting_for) controller.change("waiting_for", command.payload.waiting_for, 0);
        controller.transition(command.payload.to_state as OpenTaskState);
      } else controller.barrier(command.payload.action);
 controller.flush();
      return Promise.race([
        controller.whenIdle().then(() => ({ status: "saved" as const, task: state.baseline })),
        controller.whenPaused().then(() => state.conflict
          ? { status: "conflict" as const, task: state.conflict.latestServerTask ?? state.baseline, retry: async () => { controller.retry(); await controller.whenIdle(); return { status: "saved" as const, task: state.baseline }; }, discard: () => controller.discard() }
          : Promise.reject(new Error(state.error?.message ?? "Autosave failed")))
      ]);
    },
    recover: () => persisted(accountId, apiOrigin, suppliedTask.id),
    resumeRecovery: async () => {
      controller.retry();
      await Promise.race([
        controller.whenIdle(),
        controller.whenPaused().then(() => { throw new Error(state.error?.kind === "protocol" ? "The saved version could not be verified. Check it in the task details." : state.error?.message ?? "Task changed elsewhere. Review the latest task before retrying."); })
      ]);
      return { status: "saved" as const, task: state.baseline };
    },
    discardRecovery: () => controller.discard(),
    get conflict() { return state.conflict; }
  };
  // Reconcile old false-protocol journals only when the reopened parent agrees.
  // Any later local edits remain dirty until the user explicitly retries them.
  if (restored?.error?.kind === "protocol" && !restored.inFlight && taskEqual(suppliedTask, restored.baseline)) {
    state.error = null; state.status = "clean"; mergeCanonical(suppliedTask); persistAndEmit();
  }
  const restoredCommand = restored?.inFlight;
  if (restoredCommand && (restored?.status === "saving" || restored?.status === "retrying" || restored?.status === "queued")) queueMicrotask(() => {
    if (state.inFlight !== restoredCommand) return;
    state.inFlight = null;
    persistAndEmit();
    void dispatch(restoredCommand).then(() => drain());
  });
  return controller;
}

const controllers = new Map<string, ReturnType<typeof createTaskDetailAutosaveController>>();
export type TaskDetailAutosaveController = ReturnType<typeof createTaskDetailAutosaveController>;
export function resetTaskDetailAutosaveControllersForTests(): void {
  controllers.clear();
}
export function getTaskDetailAutosaveController(
  accountId: string,
  apiOriginOrTask: string | TaskResponse,
  taskOrAccepted?: TaskResponse | ((task: TaskResponse) => void | Promise<void>),
  onAccepted?: (task: TaskResponse) => void | Promise<void>
) {
  const apiOrigin = typeof apiOriginOrTask === "string" ? apiOriginOrTask : window.location.origin;
  const task = typeof apiOriginOrTask === "string" ? taskOrAccepted as TaskResponse : apiOriginOrTask;
  const callback = (typeof apiOriginOrTask === "string" ? onAccepted : taskOrAccepted) as ((task: TaskResponse) => void | Promise<void>) | undefined;
  const key = `${accountId}:${apiOrigin}:${task.id}`;
  const existing = controllers.get(key);
  if (existing) {
    const recoveryStillExists = typeof sessionStorage !== "undefined" && sessionStorage.getItem(taskAutosaveStorageKey(accountId, apiOrigin, task.id)) !== null;
    const snapshot = existing.getSnapshot();
    if ((snapshot.dirtyFields.length || snapshot.inFlight || snapshot.error || snapshot.conflict) && !recoveryStillExists) {
      controllers.delete(key);
    } else {
      queueMicrotask(() => existing.sync(task));
      existing.setOnAccepted(callback);
      return existing;
    }
  }
  const created = createTaskDetailAutosaveController(accountId, apiOrigin, task, callback);
  controllers.set(key, created);
  return created;
}
