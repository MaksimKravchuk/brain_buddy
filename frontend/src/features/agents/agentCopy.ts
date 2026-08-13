import type {
  AgentCapabilities,
  AgentConnectionResponse,
  AgentRunResponse
} from "../../api/agentTypes";

/**
 * Owner-facing wording for a saved connection.
 *
 * Every string here answers one question honestly: what did BrainBuddy actually
 * observe, and what does the user have to do next? Nothing infers that an agent
 * works — only a successful, non-stale test does that, and only the server
 * decides it (`ready_for_handoff`).
 */

/**
 * Staleness is derived from the clock, not from the last test result, so it
 * overrides an otherwise-successful `ready` — the connection was reachable once,
 * which is not a claim that it is reachable now.
 */
export function connectionStatusLabel(connection: AgentConnectionResponse): string {
  switch (connection.status) {
    case "disconnected":
      return "Disconnected";
    case "invalid_credentials":
      return "Invalid credentials";
    case "unreachable":
      return "Unreachable";
    case "unsupported":
      return "Unsupported connector";
    case "untested":
      return "Not tested";
    default:
      return connection.stale ? "Stale" : "Tested ready";
  }
}

export function connectionStatusDetail(connection: AgentConnectionResponse): string {
  switch (connection.status) {
    case "disconnected":
      return "The stored credential was destroyed. New hand-offs and replies through this agent are blocked.";
    case "invalid_credentials":
      return "The agent rejected the credential. Replace it below, then test again.";
    case "unreachable":
      return "BrainBuddy could not reach this endpoint. Nothing was sent. Check the address and test again.";
    case "unsupported":
      return "The agent answered but does not speak a protocol version BrainBuddy supports.";
    case "untested":
      return "BrainBuddy has not contacted this agent yet. Test it before handing over a task.";
    default:
      return connection.stale
        ? `The last contact is older than the ${formatDuration(connection.stale_after_seconds)} staleness threshold. Test it again before a hand-off.`
        : "The last test reached this agent and it authenticated.";
  }
}

type RunGuardInput = Pick<
  AgentRunResponse,
  | "dispatch_state"
  | "connection_disconnected"
  | "reported_state"
  | "cancel_requested"
  | "capabilities"
>;

/** The server's `_require_commandable`: sent, still connected, not finished. */
function isCommandable(run: RunGuardInput): boolean {
  return (
    run.dispatch_state !== "not_sent" &&
    !run.connection_disconnected &&
    run.reported_state !== "completed" &&
    run.reported_state !== "failed" &&
    run.reported_state !== "cancelled"
  );
}

/**
 * Whether this run is actually waiting on the user right now.
 *
 * Gated on the live state rather than on `question_text` alone, so a question
 * the run has already moved past can never resurface as a control. The two
 * clients keep the same rule (`mobile/src/lifecycle/agentGuards.ts`).
 */
export function awaitsAnswer(
  run: Pick<AgentRunResponse, "question_text" | "needs_user" | "reported_state">
): boolean {
  return Boolean(run.question_text) && (run.needs_user || run.reported_state === "blocked");
}

/** Reply is offered only for a live, connected, blocked run that discloses it. */
export function canReplyToRun(run: RunGuardInput & { needs_user: boolean }): boolean {
  return (
    isCommandable(run) &&
    (run.needs_user || run.reported_state === "blocked") &&
    run.capabilities.reply
  );
}

/** A second request while the first is unconfirmed would say nothing new. */
export function canCancelRun(run: RunGuardInput): boolean {
  return isCommandable(run) && !run.cancel_requested && run.capabilities.cancel;
}

/** Fixed order so a missing capability is a visible "not supported", never a gap. */
export function capabilityDisclosure(
  capabilities: AgentCapabilities
): Array<{ label: string; supported: boolean }> {
  return [
    { label: "Progress updates", supported: capabilities.progress },
    { label: "Replies to questions", supported: capabilities.reply },
    { label: "Cancellation", supported: capabilities.cancel }
  ];
}

/** "Never" for an absent timestamp — an empty cell reads like a loading state. */
export function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Never";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

/** Deployment thresholds are server-configured, so they are reported, not promised. */
export function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds} ${seconds === 1 ? "second" : "seconds"}`;
  }
  if (seconds < 3600) {
    const minutes = Math.round(seconds / 60);
    return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  }
  const hours = Math.round(seconds / 3600);
  return `${hours} ${hours === 1 ? "hour" : "hours"}`;
}
