/**
 * Pure projection, polling, and disclosure logic for the external-agent relay.
 *
 * Mirrors `src/braindump/machine.ts` in shape and the backend projection in
 * meaning. Two honesty rules are load-bearing here:
 *
 * - `primary_state_label` is already the user-facing sentence the server
 *   computed. Nothing in this module recomputes or prettifies it. The labels
 *   below exist only for facts the server does not label (individual timeline
 *   events, connection status, capability disclosure).
 * - Nothing here invents progress, percentages, stages, or an ETA, and a
 *   connector-reported completion is always phrased as a report.
 */

import { ApiError } from "../api/client";
import type {
  AgentCapabilities,
  AgentConnectionResponse,
  AgentContextItem,
  AgentReportedState,
  AgentRunEvent,
  AgentRunResponse,
  TaskCommentResponse,
  TaskSubtaskResponse,
} from "../api/types";

// --- Polling ------------------------------------------------------------

const TERMINAL_REPORTED_STATES: ReadonlySet<AgentReportedState> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

/** Terminal means the connector said so — silence never becomes terminal. */
export function isTerminalRun(run: Pick<AgentRunResponse, "reported_state">): boolean {
  return run.reported_state !== null && TERMINAL_REPORTED_STATES.has(run.reported_state);
}

type PollableRun = Pick<
  AgentRunResponse,
  "reported_state" | "connection_disconnected" | "content_expired" | "dispatch_state"
>;

/**
 * Poll while an update is still possible. A run that stopped reporting stays
 * pollable on purpose: FR-013 requires a later valid event to still land.
 */
export function isRunPollable(run: PollableRun): boolean {
  if (isTerminalRun(run)) {
    return false;
  }
  // Disconnect stops polling and commands (FR-016); expired content has
  // nothing left to refresh (FR-015); nothing was ever sent (FR-006).
  return (
    !run.connection_disconnected && !run.content_expired && run.dispatch_state !== "not_sent"
  );
}

export const INITIAL_POLL_DELAY_MS = 1500;
export const MAX_POLL_DELAY_MS = 8000;

/** 1.5s → ×2 → 8s cap, matching the brain-dump loop. */
export function nextPollDelay(previous: number | null): number {
  if (previous === null || previous <= 0) {
    return INITIAL_POLL_DELAY_MS;
  }
  return Math.min(previous * 2, MAX_POLL_DELAY_MS);
}

/**
 * Keep the newest snapshot of a run: poll responses can arrive out of order
 * and must never roll the projection back. `revision` covers Brain Buddy's own
 * record (commands included); `run_version` is the connector's authoritative
 * ordering. Neither may go backwards.
 */
export function applyRun(
  current: AgentRunResponse | null,
  incoming: AgentRunResponse,
): AgentRunResponse {
  if (
    current &&
    current.id === incoming.id &&
    (current.revision > incoming.revision || current.run_version > incoming.run_version)
  ) {
    return current;
  }
  return incoming;
}

/** The server's list decides membership and order; each run stays monotonic. */
export function applyRuns(
  current: readonly AgentRunResponse[],
  incoming: readonly AgentRunResponse[],
): AgentRunResponse[] {
  const known = new Map(current.map((run) => [run.id, run]));
  return incoming.map((run) => applyRun(known.get(run.id) ?? null, run));
}

export function runsNewestFirst(runs: readonly AgentRunResponse[]): AgentRunResponse[] {
  return runs
    .slice()
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}

/**
 * True only when the request never reached the server. An `ApiError` means we
 * got an answer, so it is a server condition — not an offline one.
 */
export function isOfflineError(error: unknown): boolean {
  if (error instanceof ApiError) {
    return false;
  }
  return error instanceof Error;
}

// --- Errors -------------------------------------------------------------

/** The `detail.reason` code the backend attaches to a validation failure. */
export function errorReasonCode(error: unknown): string | null {
  if (!(error instanceof ApiError)) {
    return null;
  }
  const payload = error.payload;
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const detail = (payload as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") {
    return null;
  }
  const reason = (detail as { reason?: unknown }).reason;
  return typeof reason === "string" ? reason : null;
}

export type ManifestRejection = "manifest_token_mismatch" | "manifest_not_reserved";

const MANIFEST_REJECTIONS: ReadonlySet<string> = new Set([
  "manifest_token_mismatch",
  "manifest_not_reserved",
]);

/**
 * The only two failures that mean "what you reviewed is no longer what would
 * be sent". They are answered by re-previewing, never by retrying silently.
 */
export function manifestRejectionReason(error: unknown): ManifestRejection | null {
  const reason = errorReasonCode(error);
  return reason && MANIFEST_REJECTIONS.has(reason) ? (reason as ManifestRejection) : null;
}

// --- Display ------------------------------------------------------------

/** FR-010: expiry is a retention fact, never a loading or failure state. */
export const EXPIRED_CONTENT_NOTICE = "Content expired under retention policy";

export function sortedEvents(run: Pick<AgentRunResponse, "events">): AgentRunEvent[] {
  return run.events
    .slice()
    .sort(
      (a, b) =>
        Date.parse(a.received_at) - Date.parse(b.received_at) || a.run_version - b.run_version,
    );
}

const EVENT_LABELS: Record<AgentReportedState, string> = {
  accepted: "Accepted",
  running: "Running",
  blocked: "Needs you",
  // Brain Buddy did not verify the work: this is the agent's own claim.
  completed: "Agent reported complete",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function eventLabel(type: AgentReportedState): string {
  return EVENT_LABELS[type];
}

export function connectionStatusLabel(
  connection: Pick<AgentConnectionResponse, "status" | "stale">,
): string {
  switch (connection.status) {
    case "ready":
      return connection.stale ? "Tested, but not in contact recently" : "Ready";
    case "untested":
      return "Not tested yet";
    case "invalid_credentials":
      return "Invalid credentials";
    case "unreachable":
      return "Unreachable";
    case "unsupported":
      return "Connector not supported";
    case "disconnected":
      return "Disconnected";
  }
}

const CAPABILITY_ORDER = ["progress", "reply", "cancel"] as const;

const CAPABILITY_LABELS: Record<keyof AgentCapabilities, string> = {
  progress: "progress updates",
  reply: "replies",
  cancel: "cancellation",
};

/** Names what the connector can and cannot do, so neither is left implied. */
export function capabilityDisclosure(capabilities: AgentCapabilities): {
  supported: string[];
  unsupported: string[];
} {
  const supported: string[] = [];
  const unsupported: string[] = [];
  for (const key of CAPABILITY_ORDER) {
    (capabilities[key] ? supported : unsupported).push(CAPABILITY_LABELS[key]);
  }
  return { supported, unsupported };
}

const MINUTE_S = 60;
const HOUR_S = 60 * MINUTE_S;
const DAY_S = 24 * HOUR_S;

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
}

/** Reports the server's last authenticated contact; never invents one. */
export function lastContactLabel(iso: string | null, now: number = Date.now()): string {
  if (!iso) {
    return "No contact yet";
  }
  const then = Date.parse(iso);
  if (Number.isNaN(then)) {
    return "Last contact unknown";
  }
  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  if (seconds < MINUTE_S) {
    return "Last contact just now";
  }
  if (seconds < HOUR_S) {
    return `Last contact ${plural(Math.floor(seconds / MINUTE_S), "minute")}`;
  }
  if (seconds < DAY_S) {
    return `Last contact ${plural(Math.floor(seconds / HOUR_S), "hour")}`;
  }
  return `Last contact ${plural(Math.floor(seconds / DAY_S), "day")}`;
}

// --- Hand-off review ----------------------------------------------------

/** Server limits (`AgentContextItemRequest`); review must show what is sent. */
export const MAX_CONTEXT_LABEL_CHARS = 200;
export const MAX_CONTEXT_BODY_CHARS = 4000;

function clamp(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}

export interface ContextSource {
  subtasks?: TaskSubtaskResponse[] | null;
  comments?: TaskCommentResponse[] | null;
}

export interface ContextClassification {
  projectName?: string | null;
  tagNames?: string[] | null;
}

function contextItem(label: string, body: string): AgentContextItem | null {
  const trimmed = body.trim();
  if (!trimmed) {
    return null;
  }
  return { label: clamp(label, MAX_CONTEXT_LABEL_CHARS), body: clamp(trimmed, MAX_CONTEXT_BODY_CHARS) };
}

/**
 * Candidate context for the hand-off review, built only from the task the user
 * opened. Every item is separately removable before anything is sent — nothing
 * here is implicitly included.
 */
export function buildContextCandidates(
  task: ContextSource,
  classification: ContextClassification = {},
): AgentContextItem[] {
  const items: AgentContextItem[] = [];

  const classificationLines: string[] = [];
  if (classification.projectName) {
    classificationLines.push(`Project: ${classification.projectName}`);
  }
  const tags = (classification.tagNames ?? []).filter((name) => name.trim());
  if (tags.length > 0) {
    classificationLines.push(`Tags: ${tags.join(", ")}`);
  }
  if (classificationLines.length > 0) {
    const item = contextItem("Classification", classificationLines.join("\n"));
    if (item) {
      items.push(item);
    }
  }

  const subtaskLines = (task.subtasks ?? [])
    .filter((subtask) => subtask.state !== "cancelled")
    .map((subtask) => `- [${subtask.state === "completed" ? "x" : " "}] ${subtask.title}`);
  if (subtaskLines.length > 0) {
    const item = contextItem("Subtasks", subtaskLines.join("\n"));
    if (item) {
      items.push(item);
    }
  }

  for (const comment of task.comments ?? []) {
    const item = contextItem("Comment", comment.body);
    if (item) {
      items.push(item);
    }
  }

  return items;
}
