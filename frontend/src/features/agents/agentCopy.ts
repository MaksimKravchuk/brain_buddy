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
  // Checked before `status`, because a changed agent's stored status is
  // `untested` and "Not tested" would hide the thing the user has to look at
  // (FR-002, D-01-S20).
  if (connection.agent_changed) {
    return "Agent changed";
  }
  if (connection.last_test_error_code === "a2a_rate_limited") {
    return "Rate limited";
  }
  switch (connection.status) {
    case "disconnected":
      return connection.disconnect_reason === "superseded_wire_contract"
        ? "Superseded wire contract"
        : "Disconnected";
    case "invalid_credentials":
      return "Invalid credentials";
    case "unreachable":
      return "Unreachable";
    case "unsupported":
      return "Unsupported";
    case "untested":
      return "Not tested";
    default:
      return connection.stale ? "Stale" : "Tested ready";
  }
}

/**
 * The four `unsupported` categories are four different sentences.
 *
 * Collapsing them into one would leave the owner with the least actionable
 * message the product has: "no card at the well-known location" and "this card
 * requires OAuth2" call for entirely different next steps (D-01-S14..S17).
 */
function unsupportedDetail(connection: AgentConnectionResponse): string {
  const detail = connection.last_test_error_detail;
  switch (connection.last_test_error_code) {
    case "a2a_not_an_agent":
      return "There is no agent card at its well-known location. Check the address you entered, then test again.";
    case "a2a_protocol_version_unsupported": {
      const found = detail && "found_version" in detail ? detail.found_version : null;
      return found
        ? `The card declares A2A ${found}. BrainBuddy speaks protocol version 1.0.x only.`
        : "The card declares a protocol version outside 1.0.x. BrainBuddy speaks protocol version 1.0.x only.";
    }
    case "a2a_auth_scheme_unsupported": {
      const scheme = detail && "scheme" in detail ? detail.scheme : null;
      return scheme
        ? `This card requires ${scheme}. BrainBuddy supports a bearer token or an API key named by the card, and nothing else.`
        : "This card requires an authentication scheme BrainBuddy does not support. BrainBuddy supports a bearer token or an API key named by the card.";
    }
    default:
      return "No JSON-RPC interface BrainBuddy can use over HTTPS.";
  }
}

/** "Test again in about N seconds." — the agent's own number, or nothing. */
export function rateLimitRetryCopy(connection: AgentConnectionResponse): string {
  const detail = connection.last_test_error_detail;
  const seconds =
    detail && "retry_after_seconds" in detail ? detail.retry_after_seconds : null;
  // CHK051: an agent that gave no hint gets no invented countdown. A fabricated
  // number would send the user back at exactly the wrong moment.
  return seconds === null || seconds === undefined
    ? "Test again shortly."
    : `Test again in about ${seconds} ${seconds === 1 ? "second" : "seconds"}.`;
}

export function connectionStatusDetail(connection: AgentConnectionResponse): string {
  if (connection.agent_changed) {
    return "This agent's card now advertises a different interface address or different authentication requirements than the one you tested. BrainBuddy will not send task content to a destination you have not tested. Test the connection again — you will be asked for your password, because a new destination is a new content-bearing send.";
  }
  if (connection.last_test_error_code === "a2a_rate_limited") {
    return "The agent is rate limiting. It answered the test by refusing it, so BrainBuddy learned nothing about the connection and nothing was sent.";
  }
  switch (connection.status) {
    case "disconnected":
      return connection.disconnect_reason === "superseded_wire_contract"
        ? "Superseded wire contract. This connection was made under BrainBuddy's previous agent wire, which no longer exists. Add the agent again by its address to use it."
        : "The stored credential and the agent-card summary BrainBuddy discovered were destroyed. New hand-offs and replies through this agent are blocked.";
    case "invalid_credentials":
      return "The agent answered and rejected the credential. Rotate it below, then test again.";
    case "unreachable":
      return "BrainBuddy could not reach this address before the test timeout. Nothing was sent.";
    case "unsupported":
      return unsupportedDetail(connection);
    case "untested":
      return "BrainBuddy has not contacted this agent yet. Test it before handing over a task.";
    default:
      return connection.stale
        ? `The last contact is older than the ${formatDuration(connection.stale_after_seconds)} staleness threshold. Test it again before a hand-off.`
        : "The last test reached this agent and it authenticated.";
  }
}

/** The label beside the credential scheme. Never the credential itself. */
export function authSchemeLabel(connection: AgentConnectionResponse): string {
  return connection.auth_scheme === "bearer"
    ? "Bearer token · stored sealed"
    : `API key${connection.auth_header_name ? ` in ${connection.auth_header_name}` : ""} · stored sealed`;
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

type DispatchShape = Pick<
  AgentRunResponse,
  "dispatch_state" | "dispatch_error_code" | "exchange_state" | "exchange_open" | "reported_state"
>;

/**
 * What BrainBuddy knows about its *own* outbound request — and nothing else.
 *
 * Four states that are routinely collapsed into one are kept apart here, because
 * each one licenses a different next step:
 *
 * - **Queued**: the run's identifiers are reserved and its content frozen, but
 *   no byte has left. Calling this "Sent" is the single dishonest claim this
 *   whole projection exists to prevent.
 * - **Sent**: the message went out, or is going out inside an open exchange.
 * - **Not sent**: it provably did not go out, so the same hand-off — the same
 *   run ID, the same message ID — can simply be offered again.
 * - **Delivery unconfirmed**: BrainBuddy does not know. Nothing is re-sent on
 *   its own; the user asks for a lookup.
 *
 * Once the agent itself has reported, its state is the authority and this says
 * nothing at all rather than competing with it.
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
      return "BrainBuddy restarted before this hand-off was sent. Nothing left BrainBuddy.";
    }
    if (run.dispatch_error_code === "a2a_rate_limited") {
      return "The agent is rate limiting.";
    }
    return null;
  }
  if (run.dispatch_state === "sent" || run.exchange_state === "open") {
    return "Some agents answer only when the work is finished.";
  }
  return "BrainBuddy could not confirm the agent received this hand-off. It was not re-sent.";
}

/**
 * What the *card* declared, in a fixed order.
 *
 * Only the two booleans an A2A card actually carries. Reply and cancellation are
 * deliberately absent: no card advertises either, so listing them here would
 * turn a BrainBuddy product decision into something that reads as an agent
 * promise (FR-002, FR-010).
 */
export function capabilityDisclosure(
  capabilities: AgentCapabilities
): Array<{ label: string; supported: boolean }> {
  return [
    { label: "Streaming updates", supported: capabilities.streaming },
    { label: "Push notifications", supported: capabilities.push_notifications }
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
