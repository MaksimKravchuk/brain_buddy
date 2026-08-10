/**
 * Wire contracts for the external-agent relay (`backend/app/schemas/agents.py`).
 *
 * Two properties of that contract shape everything here. No response type can
 * carry a saved credential — the only secret the server ever returns is the
 * one-time `inbound_signing_secret` on create. And a run keeps connector-reported
 * facts, BrainBuddy-derived conditions, and pending user commands in separate
 * fields, so the client never has to blend them into an invented status.
 */

export type AgentCapabilities = {
  progress: boolean;
  reply: boolean;
  cancel: boolean;
};

export type AgentConnectionStatus =
  | "untested"
  | "ready"
  | "invalid_credentials"
  | "unreachable"
  | "unsupported"
  | "disconnected";

export type AgentDispatchState = "not_sent" | "sent" | "delivery_unconfirmed";

export type AgentReportedState =
  | "accepted"
  | "running"
  | "blocked"
  | "completed"
  | "failed"
  | "cancelled";

export type AgentCommandKind = "start" | "reply" | "cancel";

export type AgentCommandDelivery = "unconfirmed" | "confirmed";

export interface AgentConnectionResponse {
  id: string;
  name: string;
  endpoint_url: string;
  auth_header_name: string;
  status: AgentConnectionStatus;
  /** Time-derived: a ready connection ages out of readiness without a re-test. */
  stale: boolean;
  ready_for_handoff: boolean;
  capabilities: AgentCapabilities;
  last_test_error_code: string | null;
  last_contact_at: string | null;
  last_tested_at: string | null;
  stale_after_seconds: number;
  created_at: string;
  revision: number;
}

/** The only response that ever carries a secret, and only once. */
export interface AgentConnectionCreatedResponse extends AgentConnectionResponse {
  inbound_signing_secret: string;
}

export interface AgentConnectionCreateRequest {
  name: string;
  endpoint_url: string;
  auth_header_name?: string;
  credential: string;
  current_password: string;
}

export interface AgentConnectionRotateRequest {
  credential: string;
  current_password: string;
  expected_revision: number;
}

/**
 * Replace the secret the *agent* signs its reports with.
 *
 * Deliberately carries no credential field: this is the inbound direction, and
 * conflating it with `AgentConnectionRotateRequest` would let a UI ask for the
 * wrong secret and break the connection it was trying to repair.
 */
export interface AgentConnectionRotateSigningSecretRequest {
  current_password: string;
  expected_revision: number;
}

/** The replacement, returned by rotation and by nothing else. */
export interface AgentConnectionSigningSecretResponse extends AgentConnectionResponse {
  inbound_signing_secret: string;
}

export interface AgentConnectionDisconnectRequest {
  current_password: string;
  expected_revision: number;
}

export interface AgentContextItem {
  label: string;
  body: string;
}

export interface AgentHandoffPreviewRequest {
  connection_id: string;
  include_details?: boolean;
  context_items?: AgentContextItem[];
}

export interface AgentHandoffConfirmRequest extends AgentHandoffPreviewRequest {
  manifest_token: string;
  current_password?: string | null;
}

export interface AgentReportingContract {
  callback_url: string;
  connection_id: string;
  connection_header: "X-BrainBuddy-Connection";
  timestamp_header: "X-BrainBuddy-Timestamp";
  signature_header: "X-BrainBuddy-Signature";
  timestamp_format: "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero";
  signature_algorithm: "hmac-sha256";
  signing_bytes: "timestamp_bytes + b'.' + raw_body";
  signature_format: "v1=<lowercase hex>";
  body_envelope_version: string;
}

/** Everything that will leave BrainBuddy, itemised for review before dispatch. */
export interface AgentManifestResponse {
  token: string;
  run_id: string;
  task_id: string;
  connection_id: string;
  agent_name: string;
  title: string;
  details: string | null;
  context_items: AgentContextItem[];
  reporting: AgentReportingContract;
  reporting_instructions: string;
  instructions_version: string;
  protocol_version: string;
  destination_endpoint: string;
  external_copy_notice: string;
  reauthentication_required: boolean;
}

export interface AgentRunEvent {
  id: string;
  type: AgentReportedState;
  run_version: number;
  received_at: string;
  summary: string | null;
}

export interface AgentRunCommand {
  id: string;
  kind: AgentCommandKind;
  body: string | null;
  delivery: AgentCommandDelivery;
  created_at: string;
  confirmed_at: string | null;
}

export interface AgentRunResponse {
  id: string;
  task_id: string;
  connection_id: string;
  agent_name: string;

  dispatch_state: AgentDispatchState;
  dispatch_error_code: string | null;

  reported_state: AgentReportedState | null;
  run_version: number;

  stopped_reporting: boolean;
  connection_disconnected: boolean;
  reply_pending: boolean;
  cancel_requested: boolean;
  needs_user: boolean;

  /** Server-owned honest label. Render verbatim; never re-derive or embellish. */
  primary_state_label: string;

  progress_text: string | null;
  question_text: string | null;
  result_text: string | null;
  result_link: string | null;
  result_link_interactive: boolean;
  failure_reason: string | null;

  content_expired: boolean;
  content_expires_at: string;
  last_contact_at: string | null;
  reporting_window_seconds: number;
  capabilities: AgentCapabilities;
  manifest: AgentManifestResponse | null;
  events: AgentRunEvent[];
  commands: AgentRunCommand[];
  created_at: string;
  revision: number;
}

export interface AgentReplyRequest {
  message: string;
  expected_revision: number;
}

/**
 * The compact Task surface's view of a run: latest only, no timeline.
 *
 * Deliberately narrower than `AgentRunResponse` — a task card shows that an
 * agent is involved and whether it needs the user, and routes to the detail for
 * anything more.
 */
export interface AgentRunSummaryResponse {
  id: string;
  task_id: string;
  agent_name: string;
  primary_state_label: string;
  needs_user: boolean;
  stopped_reporting: boolean;
  last_contact_at: string | null;
}
