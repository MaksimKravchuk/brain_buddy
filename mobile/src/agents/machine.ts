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
  AgentRunSummaryResponse,
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
  "reported_state" | "connection_disconnected" | "dispatch_state"
>;

/**
 * Poll while an update is still possible. A run that stopped reporting stays
 * pollable on purpose: FR-013 requires a later valid event to still land.
 */
export function isRunPollable(run: PollableRun): boolean {
  if (isTerminalRun(run)) {
    return false;
  }
  // Expiry redacts content locally but a later authenticated report can still
  // change coarse terminal/contact state. Only unreachable/never-sent runs stop.
  return !run.connection_disconnected && run.dispatch_state !== "not_sent";
}

type DispatchShape = Pick<
  AgentRunResponse,
  "dispatch_state" | "dispatch_error_code" | "exchange_state" | "exchange_open" | "reported_state"
>;

/**
 * What Brain Buddy knows about its *own* outbound request — and nothing else.
 *
 * The same four states the web surface keeps apart, kept apart here for the
 * same reason: each licenses a different next step. **Queued** means the
 * identifiers are reserved and nothing has left; **Sent** means the message
 * went out; **Not sent** means it provably did not, so the identical hand-off
 * can be offered again; **Delivery unconfirmed** means Brain Buddy does not
 * know, and nothing is re-sent on its own.
 *
 * Once the agent itself has reported, its state is the authority and this says
 * nothing rather than competing with it.
 */
export function dispatchStateDetail(run: DispatchShape): string | null {
  if (run.reported_state !== null) {
    return null;
  }
  if (run.exchange_state === "queued") {
    return "Waiting for a free connection slot; nothing has been sent yet";
  }
  if (run.dispatch_state === "not_sent") {
    if (run.dispatch_error_code === "restarted_before_send") {
      return "Brain Buddy restarted before this hand-off was sent. Nothing left Brain Buddy.";
    }
    if (run.dispatch_error_code === "a2a_rate_limited") {
      return "The agent is rate limiting.";
    }
    return null;
  }
  if (run.dispatch_state === "sent" || run.exchange_state === "open") {
    return "Some agents answer only when the work is finished.";
  }
  return "Brain Buddy could not confirm the agent received this hand-off. It was not re-sent.";
}

/** **Check again** is offered only where Brain Buddy genuinely does not know. */
export function canCheckDelivery(
  run: DispatchShape & Pick<AgentRunResponse, "connection_disconnected">,
): boolean {
  return (
    run.dispatch_state === "delivery_unconfirmed" &&
    run.exchange_state !== "queued" &&
    run.reported_state === null &&
    !run.connection_disconnected
  );
}

/**
 * A hand-off that never left can be offered again exactly as it was reviewed —
 * but only while Brain Buddy still holds what was reviewed.
 */
export function canRetryHandoff(
  run: Pick<AgentRunResponse, "dispatch_state" | "manifest" | "content_expired">,
): boolean {
  return run.dispatch_state === "not_sent" && !run.content_expired && run.manifest !== null;
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

/** The server flag or the local retention deadline, whichever expires first. */
export function isRunContentExpired(
  run: Pick<AgentRunResponse, "content_expired" | "content_expires_at">,
  now: number = Date.now(),
): boolean {
  if (run.content_expired) {
    return true;
  }
  const deadline = Date.parse(run.content_expires_at);
  return !Number.isNaN(deadline) && now >= deadline;
}

/**
 * Privacy projection used for both network answers and cached snapshots.
 * Coarse lifecycle/contact facts remain so an expired run can still converge.
 */
export function projectRunAt(run: AgentRunResponse, now: number = Date.now()): AgentRunResponse {
  if (!isRunContentExpired(run, now)) {
    return run;
  }
  return {
    ...run,
    content_expired: true,
    progress_text: null,
    question_text: null,
    result_text: null,
    result_link: null,
    result_link_interactive: false,
    failure_reason: null,
    // Content tier as well (data-model.md §8). The projection feeds the cached
    // snapshot, not only the rendered card, so anything the agent said — the
    // block reason, the names and media types of its artifacts, whether its
    // result fitted — has to go with the rest of the 30-day content.
    blocked_reason: null,
    artifacts_summary: [],
    result_availability: null,
    manifest: null,
    events: run.events.map((event) => ({ ...event, summary: null })),
    commands: run.commands.map((command) => ({ ...command, body: null })),
  };
}

export function projectRunsAt(
  runs: readonly AgentRunResponse[],
  now: number = Date.now(),
): AgentRunResponse[] {
  return runs.map((run) => projectRunAt(run, now));
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

/** The timeline wording for a task succession row (M-03-S26). */
export const TASK_SUCCESSION_COPY = "The agent continued this run in a new task";

/**
 * What one timeline row reads as.
 *
 * A succession row is not a state change: the agent moved the work into a new
 * task inside the same conversation, and the row exists so the identifier the
 * user saw yesterday is not silently replaced.
 */
export function timelineRowLabel(event: AgentRunEvent): string {
  return event.kind === "task_succession" ? TASK_SUCCESSION_COPY : eventLabel(event.type);
}

/** The secondary sentence a cancel outcome earns, if any. Never the label. */
export function cancelOutcomeCopy(
  run: Pick<AgentRunResponse, "cancel_outcome">,
): string | null {
  if (run.cancel_outcome === "unsupported" || run.cancel_outcome === "not_cancelable") {
    return "Cancellation not supported by this agent.";
  }
  if (run.cancel_outcome === "unconfirmed") {
    return "Cancellation request unconfirmed — you can try again.";
  }
  return null;
}

/**
 * The marker shown in place of a result Brain Buddy could not store.
 *
 * The state was observed and is true; only the result exceeded what the relay
 * keeps. Saying so is the difference between an honest marker and rendering a
 * healthy agent as having stopped reporting (M-03-S10, too-large variant).
 */
export function resultAvailabilityCopy(
  run: Pick<AgentRunResponse, "result_availability">,
): string | null {
  return run.result_availability === "too_large" ? "Result too large to store." : null;
}

/** One artifact placeholder: the content type, never a download. */
export function artifactPlaceholderCopy(artifact: {
  name: string | null;
  media_type: string | null;
  kind: string;
}): string {
  const name = artifact.name?.trim() || `Untitled ${artifact.kind}`;
  return artifact.media_type ? `${name} · ${artifact.media_type}` : name;
}

/** The guarantee tier, spelled out. Never an abbreviation (FR-013, FR-003). */
export function guaranteeTierLabel(
  tier: AgentRunSummaryResponse["guarantee_tier"],
): string | null {
  if (tier === "guaranteed") {
    return "Guaranteed single start";
  }
  if (tier === "best_effort") {
    return "Best-effort single start";
  }
  return null;
}

/**
 * The compact task-row line (M-03-S24).
 *
 * The tier is spelled out rather than abbreviated: it is a statement about
 * duplicate risk, and a code the user has to learn is a warning nobody reads.
 * A withdrawn cancellation is repeated here so the row and the detail screen
 * cannot disagree about what the user may still do.
 */
export function compactRunLabel(
  summary: Pick<
    AgentRunSummaryResponse,
    "primary_state_label" | "guarantee_tier" | "cancel_outcome"
  >,
): string {
  const parts = [summary.primary_state_label];
  const tier = guaranteeTierLabel(summary.guarantee_tier);
  if (tier) {
    parts.push(tier);
  }
  if (
    summary.cancel_outcome === "unsupported" ||
    summary.cancel_outcome === "not_cancelable"
  ) {
    parts.push("Cancellation not supported");
  }
  return parts.join(" · ");
}

type ConnectionConditionInput = Pick<
  AgentConnectionResponse,
  "status" | "stale" | "agent_changed" | "last_test_error_code" | "disconnect_reason"
>;

export function connectionStatusLabel(connection: ConnectionConditionInput): string {
  // Both of these are checked before `status`, because a changed or
  // rate-limited connection is stored as `untested` and "Not tested yet" would
  // hide the very thing the owner has to look at (FR-002, FR-014).
  if (connection.agent_changed) {
    return "Agent changed";
  }
  if (connection.last_test_error_code === "a2a_rate_limited") {
    return "Rate limited";
  }
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
      return "Unsupported";
    case "disconnected":
      return connection.disconnect_reason === "superseded_wire_contract"
        ? "Superseded wire contract"
        : "Disconnected";
  }
}

/**
 * The four `unsupported` categories are four different sentences.
 *
 * Collapsing them would leave the owner with the least actionable message the
 * product has: "no card at the well-known location" and "this card requires
 * OAuth2" call for entirely different next steps (M-01-S12..S15).
 */
function unsupportedDetail(connection: ConnectionConditionInput & {
  last_test_error_detail: AgentConnectionResponse["last_test_error_detail"];
}): string {
  const detail = connection.last_test_error_detail;
  switch (connection.last_test_error_code) {
    case "a2a_not_an_agent":
      return "There is no agent card at its well-known location. Check the address, then test again.";
    case "a2a_protocol_version_unsupported": {
      const found = detail && "found_version" in detail ? detail.found_version : null;
      return found
        ? `The card declares A2A ${found}. Brain Buddy speaks protocol version 1.0.x only.`
        : "The card declares a protocol version outside 1.0.x. Brain Buddy speaks protocol version 1.0.x only.";
    }
    case "a2a_auth_scheme_unsupported": {
      const scheme = detail && "scheme" in detail ? detail.scheme : null;
      return scheme
        ? `This card requires ${scheme}. Brain Buddy supports a bearer token or an API key named by the card.`
        : "This card requires an authentication scheme Brain Buddy does not support.";
    }
    default:
      return "No JSON-RPC interface Brain Buddy can use over HTTPS.";
  }
}

/** One sentence for whatever the last test found. Never a shrug. */
export function connectionStatusDetail(connection: AgentConnectionResponse): string {
  if (connection.agent_changed) {
    return "This agent's card now advertises a different interface address or different authentication requirements than the one you tested. Brain Buddy will not send task content to a destination you have not tested.";
  }
  if (connection.last_test_error_code === "a2a_rate_limited") {
    return "The agent is rate limiting. It answered the test by refusing it, so Brain Buddy learned nothing about the connection and nothing was sent.";
  }
  switch (connection.status) {
    case "disconnected":
      return connection.disconnect_reason === "superseded_wire_contract"
        ? "Superseded wire contract. This connection was made under Brain Buddy's previous agent wire, which no longer exists. Add the agent again by its address to use it."
        : "The stored credential and the agent-card summary Brain Buddy discovered were destroyed.";
    case "invalid_credentials":
      return "The agent answered and rejected the credential. Rotate it, then test again.";
    case "unreachable":
      return "Brain Buddy could not reach this address before the test timeout. Nothing was sent.";
    case "unsupported":
      return unsupportedDetail(connection);
    case "untested":
      return "Brain Buddy has not contacted this agent yet. Test it before handing over a task.";
    default:
      return connection.stale
        ? "The last contact is older than the staleness threshold. Test it again before a hand-off."
        : "The last test reached this agent and it authenticated.";
  }
}

/** "Test again in about N seconds." — the agent's own number, or nothing. */
export function rateLimitRetryCopy(connection: AgentConnectionResponse): string {
  const detail = connection.last_test_error_detail;
  const seconds =
    detail && "retry_after_seconds" in detail ? detail.retry_after_seconds : null;
  // CHK051: an agent that gave no hint gets no invented countdown, which would
  // send the owner back at exactly the wrong moment.
  return seconds === null || seconds === undefined
    ? "Test again shortly."
    : `Test again in about ${seconds} ${seconds === 1 ? "second" : "seconds"}.`;
}

/** Names the scheme the credential travels under. Never the credential. */
export function authSchemeLabel(connection: AgentConnectionResponse): string {
  return connection.auth_scheme === "bearer"
    ? "Bearer token · stored sealed"
    : `API key${connection.auth_header_name ? ` in ${connection.auth_header_name}` : ""} · stored sealed`;
}

const CAPABILITY_ORDER = ["streaming", "push_notifications"] as const;

const CAPABILITY_LABELS: Record<keyof AgentCapabilities, string> = {
  streaming: "streaming updates",
  push_notifications: "push notifications",
};

/**
 * Names what the agent's *card* declares, so neither claim is left implied.
 *
 * Replies and cancellation are absent by design: no A2A card advertises either,
 * so listing them here would turn a Brain Buddy product decision into something
 * the agent appears to have promised (FR-002, FR-010).
 */
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
