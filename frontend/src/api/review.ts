/**
 * Weekly-review HTTP client (spec 020, contracts/http.md §2 – §5).
 *
 * Kept out of `client.ts`, which is in the frontend mutation-enforced tier
 * (research R18). Every response is checked against the wire contract before
 * a component sees it, every mutation carries an Idempotency-Key, every
 * request sends its own correlation id so even a dropped connection has a Ref
 * to show (FR-045), and telemetry names only the route template, the status
 * and the timing — never a body, a title or a reason (FR-044).
 */
import { ApiError, notifyUnauthorized } from "./client";
import type { TaskResponse } from "./taskTypes";
import type { StallReason } from "../features/review/stallRecommendation";
import { nowMs, recordTelemetry } from "../utils/telemetry";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";
export const REVIEW_READ_TIMEOUT_MS = 15_000;
export const REVIEW_MUTATION_TIMEOUT_MS = 30_000;

// ------------------------------------------------------------------ types

export type ThresholdDays = 7 | 14 | 21 | 28;
export const THRESHOLD_OPTIONS: readonly ThresholdDays[] = [7, 14, 21, 28];

export type DecisionType =
  | "complete"
  | "reformulate"
  | "first_step"
  | "waiting"
  | "someday"
  | "cancel"
  | "extend"
  | "keep_waiting"
  | "follow_up"
  | "return_to_next"
  | "keep_someday";

/** What the web sends: no client ids, the server mints them (wire fixture W-011). */
export interface DecisionRequest {
  type: DecisionType;
  expected_revision: number;
  formulation_id?: string;
  stall_reason?: StallReason;
  title?: string;
  waiting_for?: string;
  reason?: string;
  session_id?: string;
}

export interface SessionCounts {
  done: number;
  reformulated: number;
  first_step: number;
  waiting: number;
  someday: number;
  cancelled: number;
  extended: number;
  inbox_processed: number;
  kept: number;
  moved_to_next: number;
}

export interface DecisionRecord {
  id: string;
  type: string;
  task_id: string;
  session_id: string | null;
  decided_at: string;
  substantive: boolean | null;
  stall_reason: string | null;
  ai_use: string;
  yielded_auto_park: boolean;
}

export interface ReviewReceipt {
  task_id: string;
  kind: string;
  hidden_until: string;
  task_revision: number;
}

export interface DecisionResponse {
  decision: DecisionRecord;
  task: TaskResponse;
  created_task: TaskResponse | null;
  receipt: ReviewReceipt | null;
  session_counts: SessionCounts | null;
}

export interface UndoDecisionResponse {
  task: TaskResponse;
  undone_decision_id: string;
  deleted_task_id: string | null;
  session_counts: SessionCounts | null;
}

export interface ReviewSettings {
  threshold_days: ThresholdDays;
  review_weekday: number;
  review_time: string;
  time_zone: string;
  onboarded_at: string | null;
  activated_at: string | null;
  owner_park_floor_at: string | null;
  revision: number;
}

export interface ReviewSettingsUpdate {
  threshold_days?: ThresholdDays;
  expected_revision: number;
}

export interface UnseenPark {
  task_id: string;
  formulation_id: string;
  parked_at: string;
}

export interface ReviewState {
  settings: ReviewSettings;
  explainer_seen: boolean;
  grace_until: string | null;
  last_counted_review_at: string | null;
  last_counted_review: Record<string, unknown> | null;
  next_review_at: string | null;
  restart_mode: boolean;
  open_session: Record<string, unknown> | null;
  unseen_parks: UnseenPark[];
  counts: { asks_for_decision: number; moves_tomorrow: number };
  receipts: ReviewReceipt[];
  server_now: string;
}

export interface ParkAcknowledgement {
  items: Array<{ task_id: string; formulation_id: string }>;
}

// ------------------------------------------------------------- validation

/** A body that does not match the review wire contract. */
export class ReviewWireError extends Error {
  constructor(path: string) {
    super(`Unexpected review response at ${path}`);
    this.name = "ReviewWireError";
  }
}

type FieldKind = "string" | "number" | "boolean" | "string|null" | "boolean|null";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new ReviewWireError(path);
  }
  return value;
}

function fields(value: unknown, path: string, shape: Readonly<Record<string, FieldKind>>): Record<string, unknown> {
  const object = record(value, path);
  for (const [name, kind] of Object.entries(shape)) {
    const field = object[name];
    const [type, nullable] = kind.split("|");
    if (!(nullable !== undefined && field === null) && typeof field !== type) {
      throw new ReviewWireError(`${path}.${name}`);
    }
  }
  return object;
}

function list(value: unknown, path: string, item: (entry: unknown, path: string) => unknown): void {
  if (!Array.isArray(value)) {
    throw new ReviewWireError(path);
  }
  value.forEach((entry, index) => item(entry, `${path}[${index}]`));
}

function nullable(value: unknown, path: string, parse: (entry: unknown, path: string) => unknown): void {
  if (value !== null) {
    parse(value, path);
  }
}

const FORMULATION_SHAPE = {
  id: "string",
  started_at: "string",
  extended_at: "string|null",
  extension_reason: "string|null",
  park_floor_at: "string|null",
  consecutive_stalled: "number",
  ageing_at: "string|null",
  ask_at: "string|null",
  park_due_at: "string|null",
  paused_until: "string|null"
} as const;

const COUNTS_SHAPE = {
  done: "number",
  reformulated: "number",
  first_step: "number",
  waiting: "number",
  someday: "number",
  cancelled: "number",
  extended: "number",
  inbox_processed: "number",
  kept: "number",
  moved_to_next: "number"
} as const;

const SETTINGS_SHAPE = {
  threshold_days: "number",
  review_weekday: "number",
  review_time: "string",
  time_zone: "string",
  onboarded_at: "string|null",
  activated_at: "string|null",
  owner_park_floor_at: "string|null",
  revision: "number"
} as const;

function checkTask(value: unknown, path: string): void {
  const task = fields(value, path, { id: "string", title: "string", state: "string", revision: "number" });
  // Both fields are absent on a backend that predates spec 020.
  nullable(task.formulation ?? null, `${path}.formulation`, (entry, at) => fields(entry, at, FORMULATION_SHAPE));
  nullable(task.parked ?? null, `${path}.parked`, (entry, at) => fields(entry, at, { at: "string", formulation_id: "string" }));
}

function checkSettings(value: unknown, path: string): void {
  const settings = fields(value, path, SETTINGS_SHAPE);
  if (!THRESHOLD_OPTIONS.includes(settings.threshold_days as ThresholdDays)) {
    throw new ReviewWireError(`${path}.threshold_days`);
  }
}

function checkCounts(value: unknown, path: string): void {
  nullable(value, path, (entry, at) => fields(entry, at, COUNTS_SHAPE));
}

export function parseTaskResponse(value: unknown): TaskResponse {
  checkTask(value, "task");
  return value as TaskResponse;
}

export function parseReviewSettings(value: unknown): ReviewSettings {
  checkSettings(value, "settings");
  return value as ReviewSettings;
}

export function parseReviewState(value: unknown): ReviewState {
  const state = fields(value, "state", {
    explainer_seen: "boolean",
    grace_until: "string|null",
    last_counted_review_at: "string|null",
    next_review_at: "string|null",
    restart_mode: "boolean",
    server_now: "string"
  });
  checkSettings(state.settings, "state.settings");
  nullable(state.last_counted_review, "state.last_counted_review", record);
  nullable(state.open_session, "state.open_session", record);
  list(state.unseen_parks, "state.unseen_parks", (entry, at) =>
    fields(entry, at, { task_id: "string", formulation_id: "string", parked_at: "string" })
  );
  fields(state.counts, "state.counts", { asks_for_decision: "number", moves_tomorrow: "number" });
  list(state.receipts, "state.receipts", record);
  return value as ReviewState;
}

export function parseDecisionResponse(value: unknown): DecisionResponse {
  const response = record(value, "decision_response");
  fields(response.decision, "decision", {
    id: "string",
    type: "string",
    task_id: "string",
    session_id: "string|null",
    decided_at: "string",
    substantive: "boolean|null",
    stall_reason: "string|null",
    ai_use: "string",
    yielded_auto_park: "boolean"
  });
  checkTask(response.task, "task");
  nullable(response.created_task, "created_task", checkTask);
  nullable(response.receipt, "receipt", record);
  checkCounts(response.session_counts, "session_counts");
  return value as DecisionResponse;
}

export function parseUndoDecisionResponse(value: unknown): UndoDecisionResponse {
  const response = fields(value, "undo_response", { undone_decision_id: "string", deleted_task_id: "string|null" });
  checkTask(response.task, "task");
  checkCounts(response.session_counts, "session_counts");
  return value as UndoDecisionResponse;
}

/** The standard error envelope, read leniently: any missing part is `null`. */
export function parseErrorEnvelope(value: unknown): { message: string; reason: string | null; referenceId: string | null } {
  const envelope = fields(value, "error", { message: "string" });
  return { message: envelope.message as string, reason: reasonOf(envelope), referenceId: referenceOf(envelope) };
}

function reasonOf(payload: unknown): string | null {
  return isRecord(payload) && isRecord(payload.detail) && typeof payload.detail.reason === "string"
    ? payload.detail.reason
    : null;
}

function referenceOf(payload: unknown): string | null {
  return isRecord(payload) && typeof payload.reference_id === "string" ? payload.reference_id : null;
}

// ---------------------------------------------------------------- errors

export type ReviewErrorKind =
  | "stale"
  | "network"
  | "decision_not_allowed"
  | "undo_unavailable"
  | "details_too_long"
  | "extension_already_used"
  | "extension_not_due"
  | "project_archived"
  | "id_conflict"
  | "idempotency_conflict"
  | "weekly_review_disabled"
  | "invalid_time_zone"
  | "other";

const KNOWN_REASONS: ReadonlySet<string> = new Set<ReviewErrorKind>([
  "decision_not_allowed",
  "undo_unavailable",
  "details_too_long",
  "extension_already_used",
  "extension_not_due",
  "project_archived",
  "id_conflict",
  "idempotency_conflict",
  "weekly_review_disabled",
  "invalid_time_zone"
]);

/** A message with its Ref appended, or the message alone when there is no Ref to quote (FR-045). */
export function withReference(message: string, referenceId: string | undefined): string {
  return referenceId ? `${message} Ref ${referenceId}` : message;
}

/** What failed, in the review's own terms, with the Ref to show (FR-045). */
export function describeReviewError(error: unknown): { kind: ReviewErrorKind; referenceId: string | undefined } {
  if (!(error instanceof ApiError)) {
    return { kind: "other", referenceId: undefined };
  }
  const referenceId = error.correlationId ?? referenceOf(error.payload) ?? undefined;
  if (error.status === 0) {
    return { kind: "network", referenceId };
  }
  const reason = reasonOf(error.payload);
  if (reason !== null && KNOWN_REASONS.has(reason)) {
    return { kind: reason as ReviewErrorKind, referenceId };
  }
  // The existing ConflictError carries `{resource, id}`: the task changed
  // since the card was shown (http §3 "revision or formulation mismatch").
  return { kind: error.status === 409 && reason === null ? "stale" : "other", referenceId };
}

// --------------------------------------------------------------- request

type ComposedSignal = { signal: AbortSignal; cleanup: () => void };

function composeSignal(callerSignal: AbortSignal | undefined, timeoutMs: number): ComposedSignal {
  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => {
    controller.abort(new DOMException("Review request timed out", "TimeoutError"));
  }, timeoutMs);
  const onCallerAbort = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) {
    onCallerAbort();
  } else {
    callerSignal?.addEventListener("abort", onCallerAbort, { once: true });
  }
  return {
    signal: controller.signal,
    cleanup: () => {
      globalThis.clearTimeout(timeoutId);
      callerSignal?.removeEventListener("abort", onCallerAbort);
    }
  };
}

interface RequestOptions<T> {
  method: "GET" | "POST" | "PUT";
  /** The path with its ids escaped. */
  path: string;
  /** The path template, which is all telemetry ever records. */
  route: string;
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
  timeoutMs: number;
  parse: (value: unknown) => T;
}

function log(method: string, route: string, startMs: number, ok: boolean, details: Record<string, unknown>): void {
  recordTelemetry(
    { name: "review.request", durationMs: nowMs() - startMs, ok, details: { method, route, ...details } },
    ok ? "info" : "warn"
  );
}

async function request<T>(options: RequestOptions<T>): Promise<T> {
  const correlationId = globalThis.crypto.randomUUID();
  const headers = new Headers({ Accept: "application/json", "X-Correlation-ID": correlationId });
  if (options.idempotencyKey !== undefined) {
    headers.set("Idempotency-Key", options.idempotencyKey);
  }
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  const composed = composeSignal(options.signal, options.timeoutMs);
  const startMs = nowMs();
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL.replace(/\/$/, "")}${options.path}`, {
      method: options.method,
      headers,
      credentials: "include",
      signal: composed.signal,
      body: options.body === undefined ? undefined : JSON.stringify(options.body)
    });
  } catch (error) {
    // Only the error's class is logged: a message can echo request content.
    log(options.method, options.route, startMs, false, { error: error instanceof Error ? error.name : "UnknownError" });
    throw new ApiError("Couldn't reach Brain Buddy", 0, null, correlationId);
  } finally {
    composed.cleanup();
  }

  if (response.status === 401) {
    notifyUnauthorized();
  }
  const isJson = response.headers.get("Content-Type")?.includes("application/json") === true;
  const data: unknown = response.status === 204 ? undefined : isJson ? await response.json() : await response.text();
  const referenceId = response.headers.get("X-Correlation-ID") ?? referenceOf(data) ?? correlationId;
  log(options.method, options.route, startMs, response.ok, { status: response.status, correlationId: referenceId });
  if (!response.ok) {
    throw new ApiError("Review request failed", response.status, data, referenceId);
  }
  try {
    return options.parse(data);
  } catch {
    throw new ApiError("Unexpected review response", response.status, null, referenceId);
  }
}

const enc = encodeURIComponent;

export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

export const reviewApi = {
  getState(signal?: AbortSignal): Promise<ReviewState> {
    return request({
      method: "GET",
      path: "/review/state",
      route: "/review/state",
      signal,
      timeoutMs: REVIEW_READ_TIMEOUT_MS,
      parse: parseReviewState
    });
  },

  decide(taskId: string, body: DecisionRequest, idempotencyKey: string): Promise<DecisionResponse> {
    return request({
      method: "POST",
      path: `/tasks/${enc(taskId)}/decisions`,
      route: "/tasks/{task_id}/decisions",
      body,
      idempotencyKey,
      timeoutMs: REVIEW_MUTATION_TIMEOUT_MS,
      parse: parseDecisionResponse
    });
  },

  undoDecision(decisionId: string, body: { expected_task_revision: number }, idempotencyKey: string): Promise<UndoDecisionResponse> {
    return request({
      method: "POST",
      path: `/review/decisions/${enc(decisionId)}/undo`,
      route: "/review/decisions/{decision_id}/undo",
      body,
      idempotencyKey,
      timeoutMs: REVIEW_MUTATION_TIMEOUT_MS,
      parse: parseUndoDecisionResponse
    });
  },

  acknowledgeExplainer(body: { time_zone?: string }, idempotencyKey: string): Promise<ReviewState> {
    return request({
      method: "POST",
      path: "/review/explainer/acknowledge",
      route: "/review/explainer/acknowledge",
      body,
      idempotencyKey,
      timeoutMs: REVIEW_MUTATION_TIMEOUT_MS,
      parse: parseReviewState
    });
  },

  updateSettings(body: ReviewSettingsUpdate, idempotencyKey: string): Promise<ReviewSettings> {
    return request({
      method: "PUT",
      path: "/review/settings",
      route: "/review/settings",
      body,
      idempotencyKey,
      timeoutMs: REVIEW_MUTATION_TIMEOUT_MS,
      parse: parseReviewSettings
    });
  },

  acknowledgeParks(body: ParkAcknowledgement, idempotencyKey: string): Promise<void> {
    return request({
      method: "POST",
      path: "/review/parks/acknowledge",
      route: "/review/parks/acknowledge",
      body,
      idempotencyKey,
      timeoutMs: REVIEW_MUTATION_TIMEOUT_MS,
      parse: () => undefined
    });
  }
};
