/**
 * Client-side guard matrix for the external-agent relay.
 *
 * Mirrors `src/lifecycle/guards.ts` in shape and the server rules in
 * `backend/app/modules/agents/service.py` in meaning:
 *
 * - hand-off  → `_require_dispatchable`: not disconnected, status `ready`,
 *   not stale (exactly the server's own `ready_for_handoff`);
 * - reply / cancel → `_require_commandable`: dispatched, connection live,
 *   run not terminal — then the disclosed capability;
 * - test / rotate → refused on a disconnected connection.
 *
 * One rule is the client's own: while offline, submission is refused rather
 * than queued (FR-018), because Brain Buddy must not imply that a reply or a
 * cancellation reached an agent it never contacted.
 *
 * The server stays authoritative. These guards only decide what the UI offers,
 * and every refusal is a finished sentence the user can read as-is.
 */

import type {
  AgentControls,
  AgentConnectionResponse,
  AgentRunResponse,
} from "../api/types";

export type AgentGuard = { ok: true } | { ok: false; reason: string };

const ALLOWED: AgentGuard = { ok: true };

function refuse(reason: string): AgentGuard {
  return { ok: false, reason };
}

export interface AgentGuardOptions {
  /** False once a request failed in transport — see `isOfflineError`. */
  online?: boolean;
}

function offlineGuard(options: AgentGuardOptions, action: string): AgentGuard | null {
  if (options.online === false) {
    return refuse(`You are offline. Brain Buddy will not queue ${action} — reconnect first.`);
  }
  return null;
}

type ConnectionGuardInput = Pick<AgentConnectionResponse, "status" | "stale">;

/** Refuses before any task content leaves Brain Buddy. */
export function canHandOff(
  connection: ConnectionGuardInput,
  options: AgentGuardOptions = {},
): AgentGuard {
  const offline = offlineGuard(options, "a hand-off");
  if (offline) {
    return offline;
  }
  if (connection.status === "disconnected") {
    return refuse("This agent is disconnected. Connect it again before handing work to it.");
  }
  if (connection.status !== "ready") {
    return refuse("Test this connection successfully before handing work to it.");
  }
  if (connection.stale) {
    return refuse(
      "This connection has not been in contact recently. Test it again before handing work to it.",
    );
  }
  return ALLOWED;
}

type RunGuardInput = Pick<
  AgentRunResponse,
  | "dispatch_state"
  | "connection_disconnected"
  | "reported_state"
  | "capabilities"
  | "cancel_requested"
  | "content_expired"
  | "content_expires_at"
> & {
  needs_user?: boolean;
  // Optional so a caller holding only the compact summary can still ask, and
  // so a run written before the observation lane existed reads as "nothing
  // observed" rather than as a withdrawal.
  agent_task_missing?: boolean;
  cancel_outcome?: AgentRunResponse["cancel_outcome"];
};

/**
 * Whether the run is waiting on the user *now*.
 *
 * Gated on the live state rather than on `question_text` alone, so a question
 * the run has already moved past can never resurface as a control. Web keeps
 * the same rule (`frontend/src/features/agents/agentCopy.ts`).
 */
export function awaitsAnswer(
  run: Pick<AgentRunResponse, "question_text" | "reported_state"> & { needs_user?: boolean },
): boolean {
  return Boolean(run.question_text) && (run.needs_user === true || run.reported_state === "blocked");
}

/** The shared `_require_commandable` checks, in the server's own order. */
function commandableGuard(run: RunGuardInput): AgentGuard {
  if (run.dispatch_state === "not_sent") {
    return refuse("This run was never sent, so there is no external run to reach.");
  }
  if (run.connection_disconnected) {
    return refuse("This agent is disconnected, so Brain Buddy can no longer reach this run.");
  }
  if (run.agent_task_missing === true) {
    // AC-020. Not a failure and not a refusal by the agent: there is simply
    // nothing left at the agent for a command to reach.
    return refuse("This agent no longer reports this run, so there is nothing left to send it.");
  }
  if (run.content_expired) {
    return refuse("This run's content has expired, so Brain Buddy cannot send another command.");
  }
  if (
    run.reported_state === "completed" ||
    run.reported_state === "failed" ||
    run.reported_state === "cancelled"
  ) {
    return refuse("This run has already finished.");
  }
  return ALLOWED;
}

/**
 * A pending reply never blocks another one: the server accepts it, and the
 * unconfirmed earlier command stays visible in the run's own command list. Only
 * a run that is actually blocked can be answered, so a run that has moved on
 * never offers a control for a question nobody is waiting on.
 */
export function canReply(
  run: RunGuardInput,
  capabilities: AgentControls = run.capabilities,
  options: AgentGuardOptions = {},
): AgentGuard {
  const offline = offlineGuard(options, "a reply");
  if (offline) {
    return offline;
  }
  const commandable = commandableGuard(run);
  if (!commandable.ok) {
    return commandable;
  }
  if (run.needs_user !== true && run.reported_state !== "blocked") {
    return refuse("This agent is not waiting on an answer right now.");
  }
  if (!capabilities.reply) {
    return refuse("This agent does not support replies.");
  }
  return ALLOWED;
}

/** A cancellation request is one user intent; while it is pending, do not create another. */
export function canCancel(
  run: RunGuardInput,
  capabilities: AgentControls = run.capabilities,
  options: AgentGuardOptions = {},
): AgentGuard {
  const offline = offlineGuard(options, "a cancellation request");
  if (offline) {
    return offline;
  }
  // Retention removes content and replies, not the backend's cancellation lifecycle.
  const commandable = commandableGuard({ ...run, content_expired: false });
  if (!commandable.ok) {
    return commandable;
  }
  if (!capabilities.cancel) {
    return refuse("This agent does not support cancellation.");
  }
  if (run.cancel_outcome === "unsupported" || run.cancel_outcome === "not_cancelable") {
    // The agent itself answered. Offering the control again would invite a
    // request that cannot work, and would keep asking a question already
    // answered (AC-018).
    return refuse("Cancellation not supported by this agent.");
  }
  if (run.cancel_outcome === "unconfirmed") {
    // Deliberately still offered: Brain Buddy does not know whether the request
    // landed, and hiding the control would present its own uncertainty as the
    // agent's refusal. The server reuses the same command id (AC-029).
    return ALLOWED;
  }
  if (run.cancel_requested) {
    return refuse("Cancellation was already requested.");
  }
  return ALLOWED;
}

export function canTestConnection(
  connection: ConnectionGuardInput,
  options: AgentGuardOptions = {},
): AgentGuard {
  const offline = offlineGuard(options, "a connection test");
  if (offline) {
    return offline;
  }
  if (connection.status === "disconnected") {
    return refuse("This agent is disconnected. Connect it again to test it.");
  }
  return ALLOWED;
}

export function canRotateCredential(
  connection: ConnectionGuardInput,
  options: AgentGuardOptions = {},
): AgentGuard {
  const offline = offlineGuard(options, "a credential change");
  if (offline) {
    return offline;
  }
  if (connection.status === "disconnected") {
    return refuse("This agent is disconnected, so its credential is already destroyed.");
  }
  return ALLOWED;
}

export function canReplaceSigningSecret(
  connection: ConnectionGuardInput,
  options: AgentGuardOptions = {},
): AgentGuard {
  const offline = offlineGuard(options, "a signing-secret replacement");
  if (offline) {
    return offline;
  }
  if (connection.status === "disconnected") {
    return refuse("This agent is disconnected, so its signing secret is already destroyed.");
  }
  return ALLOWED;
}

export function canDisconnect(
  connection: ConnectionGuardInput,
  options: AgentGuardOptions = {},
): AgentGuard {
  const offline = offlineGuard(options, "a disconnect");
  if (offline) {
    return offline;
  }
  if (connection.status === "disconnected") {
    return refuse("This agent is already disconnected.");
  }
  return ALLOWED;
}

/**
 * No address an agent reports is ever opened (product decision, 2026-09-04).
 *
 * `result_link_interactive` is always false now, and this guard refuses even if
 * it were not: a link the product makes tappable is a link the product is
 * vouching for, and Brain Buddy verified nothing about where it leads. The
 * address is shown as inert text beside a **Copy link** control instead
 * (M-03-S10, FR-014, AC-031).
 */
export function canOpenResultLink(
  run: Pick<AgentRunResponse, "result_link" | "result_link_interactive">,
): AgentGuard {
  if (!run.result_link) {
    return refuse("This run has no result link.");
  }
  return refuse(
    "Brain Buddy never opens an address an agent reported. Copy it if you want to go there yourself.",
  );
}
