/**
 * Wire contracts for the external-agent relay (`backend/app/schemas/agents.py`).
 *
 * Two properties of that contract shape everything here. No response type can
 * carry a saved credential, and registration returns no secret of any kind — the
 * A2A wire has no inbound secret for an owner to configure. And a run keeps
 * agent-reported facts, BrainBuddy-derived conditions, and pending user commands
 * in separate fields, so the client never has to blend them into an invented
 * status.
 */

/**
 * What the agent's own card declared. Never a BrainBuddy claim.
 *
 * Kept apart from `AgentControls` on purpose: blending the two would let a
 * product decision be rendered as something the agent promised.
 */
export type AgentCapabilities = {
  streaming: boolean;
  push_notifications: boolean;
};

/** The controls BrainBuddy offers here. Cards advertise neither (FR-010). */
export type AgentControls = {
  reply: boolean;
  cancel: boolean;
};

export type AgentAuthScheme = "bearer" | "api_key";

export type AgentGuaranteeTier = "guaranteed" | "best_effort";

export type AgentDisconnectReason = "owner" | "superseded_wire_contract";

export type AgentSchemeKind =
  | "bearer"
  | "api_key"
  | "oauth2"
  | "oidc"
  | "mtls"
  | "other";

export interface AgentSkill {
  id: string | null;
  name: string | null;
  description: string | null;
}

export interface AgentAuthSchemeOffer {
  name: string;
  kind: AgentSchemeKind;
  header_name: string | null;
}

/**
 * The discovery result read off the agent's published card.
 *
 * Every string here is untrusted agent text. It is rendered as inert plain text
 * — never an anchor, never a markup or markdown interpretation, never
 * auto-linkified — exactly as `result_link` is (FR-016, AC-031). `interface_url`
 * is shown precisely so the owner can see where their content would go, which is
 * also why it is never made navigable.
 */
export interface AgentCard {
  name: string | null;
  version: string | null;
  description: string | null;
  protocol_version: string | null;
  interface_url: string | null;
  streaming: boolean;
  push_notifications: boolean;
  skills: AgentSkill[];
  auth_schemes_offered: AgentAuthSchemeOffer[];
  extension_uris: string[];
  fetched_at: string | null;
}

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

export type AgentCommandDelivery = "unconfirmed" | "confirmed" | "rejected";

export type AgentExchangeState = "none" | "queued" | "open" | "closed" | "interrupted";

export type AgentExchangeKind = "start" | "reply";

export type AgentPushRegistration =
  | "unregistered"
  | "registered"
  | "refused"
  | "unsupported";

/**
 * Closed per-code shapes for the last test's coarse detail.
 *
 * A union rather than `Record<string, unknown>`: each variant belongs to exactly
 * one `last_test_error_code`, and the copy the client renders differs per
 * variant, so a loose shape would let a missing branch render an empty sentence.
 */
export type AgentTestErrorDetail =
  | { found_version: string }
  | { scheme: string }
  | { retry_after_seconds: number | null }
  | { interface_url: string | null };

export interface AgentConnectionResponse {
  id: string;
  name: string;
  agent_address: string;
  auth_scheme: AgentAuthScheme;
  /** Card-sourced, and only for an API-key connection. Never user input. */
  auth_header_name: string | null;
  status: AgentConnectionStatus;
  /** Time-derived: a ready connection ages out of readiness without a re-test. */
  stale: boolean;
  ready_for_handoff: boolean;
  capabilities: AgentCapabilities;
  controls_offered: AgentControls;
  card: AgentCard | null;
  guarantee_tier: AgentGuaranteeTier | null;
  /** Server-owned sentences. Rendered verbatim; never re-worded client-side. */
  tier_disclosure: string | null;
  tier_disclosure_url: string | null;
  cancellation_disclosure: string | null;
  /** The fifth connection condition: the card moved under the connection. */
  agent_changed: boolean;
  best_effort_acknowledged_at: string | null;
  correlation_id_honoured: boolean | null;
  disconnect_reason: AgentDisconnectReason | null;
  last_test_error_code: string | null;
  last_test_error_detail: AgentTestErrorDetail | null;
  last_contact_at: string | null;
  last_tested_at: string | null;
  stale_after_seconds: number;
  created_at: string;
  revision: number;
}

export interface AgentConnectionCreateRequest {
  name: string;
  agent_address: string;
  auth_scheme?: AgentAuthScheme;
  credential: string;
  current_password: string;
}

export interface AgentConnectionUpdateRequest {
  name?: string;
  agent_address?: string;
  auth_scheme?: AgentAuthScheme;
  expected_revision: number;
  current_password?: string;
}

export interface AgentConnectionRotateRequest {
  credential: string;
  current_password: string;
  expected_revision: number;
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
  supporting_items?: AgentContextItem[];
}

export interface AgentHandoffConfirmRequest extends AgentHandoffPreviewRequest {
  manifest_token: string;
  current_password?: string | null;
  /**
   * Part of the canonical request identity, not a header.
   *
   * A retry that quietly dropped it would be a different request wearing the
   * same Idempotency-Key, and the acknowledgement is the thing the user
   * actually gave (AC-026).
   */
  acknowledge_duplicate_risk?: boolean;
}

/**
 * **Check again** carries no identifiers of its own: every id is on the run.
 *
 * It does carry the revision the user was looking at. The check can end in a
 * message on the wire, so it is a mutation like any other and names the state
 * it was composed against; a check replayed from a stale cached run would
 * resend for a state nobody is being shown any more.
 */
export interface AgentCheckDeliveryRequest {
  current_password?: string | null;
  expected_revision?: number | null;
}

/**
 * The private per-run push callback, disclosed in the review (AC-007).
 *
 * The address arrives with its token already masked; the token itself appears
 * in no response. An unregistered callback carries neither an address nor a
 * disclosure — there is nothing to disclose, and a masked address for something
 * that does not exist would read as one that does.
 */
export interface AgentPushCallback {
  registered: boolean;
  url_preview: string | null;
  disclosure: string | null;
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
  supporting_items: AgentContextItem[];
  message_id: string;
  correlation_id: string;
  /** Where content would actually go: the interface the card named. */
  destination_interface: string;
  protocol_version: string;
  guarantee_tier: AgentGuaranteeTier;
  /** Server-owned sentences, rendered verbatim. Never re-worded client-side. */
  tier_disclosure: string;
  tier_disclosure_url: string;
  /** Best-effort tier, not yet acknowledged on this connection (AC-026). */
  acknowledgement_required: boolean;
  cancellation_disclosure: string;
  push_callback: AgentPushCallback | null;
  external_copy_notice: string;
  reauthentication_required: boolean;
  /** The exact text of each part that will be sent, in order. */
  parts_preview: string[];
}

/** Why an observation ran. Shown as detail on the row it produced. */
export type AgentRunEventTrigger = "dispatch" | "schedule" | "push" | "command";

/**
 * What a timeline row *is*.
 *
 * `task_succession` is not a state change: the agent moved the work into a new
 * task inside the same conversation, and the row exists so the identifier the
 * user saw yesterday is not silently replaced (D-03-S27).
 */
export type AgentRunEventKind = "observation" | "task_succession";

/**
 * What became of a cancellation request (AC-018, AC-029).
 *
 * `unsupported` and `not_cancelable` come only from an explicit agent answer
 * and withdraw the control. `unconfirmed` is the ambiguous ending and keeps it:
 * BrainBuddy does not know whether the request landed, and taking the control
 * away would turn its own uncertainty into a refusal the agent never made.
 */
export type AgentCancelOutcome =
  | "none"
  | "requested"
  | "unconfirmed"
  | "accepted"
  | "unsupported"
  | "not_cancelable"
  | "task_missing";

/** Whether the terminal result could be stored at all. */
export type AgentResultAvailability = "available" | "too_large";

export type AgentArtifactKind = "text" | "file" | "data" | "link";

/**
 * A placeholder for something the agent produced and BrainBuddy never fetched.
 *
 * Names the content type rather than the content: the relay stores no
 * attachment, so a row implying a download would promise something that does
 * not exist (D-03-S11).
 */
export interface AgentArtifactSummary {
  name: string | null;
  media_type: string | null;
  kind: AgentArtifactKind;
}

export interface AgentRunEvent {
  id: string;
  type: AgentReportedState;
  run_version: number;
  received_at: string;
  summary: string | null;
  trigger: AgentRunEventTrigger;
  kind: AgentRunEventKind;
  previous_agent_task_id: string | null;
  new_agent_task_id: string | null;
}

export interface AgentRunCommand {
  id: string;
  kind: AgentCommandKind;
  body: string | null;
  delivery: AgentCommandDelivery;
  /** The agent's own answer as a coarse code, or null when it never gave one. */
  outcome_code: string | null;
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
  /** The controls still offered on *this* run. Never a card declaration. */
  capabilities: AgentControls;

  /**
   * The A2A exchange this run is waiting on.
   *
   * `exchange_state` is the difference between **Queued** and **Sent**, and
   * that difference is the point: a queued exchange has provably not been sent,
   * so rendering it as sent would be the one claim this projection exists to
   * avoid making.
   */
  guarantee_tier: AgentGuaranteeTier | null;
  message_id: string | null;
  correlation_id: string | null;
  agent_task_id: string | null;
  exchange_open: boolean;
  exchange_state: AgentExchangeState;
  exchange_kind: AgentExchangeKind | null;
  push_registration: AgentPushRegistration;

  /**
   * What BrainBuddy's own observation of the agent's task established.
   *
   * Every default here is the absence of a claim rather than a neutral-looking
   * state: a run nobody has observed yet says only that.
   */
  agent_task_missing: boolean;
  cancel_outcome: AgentCancelOutcome;
  blocked_reason: string | null;
  artifacts_summary: AgentArtifactSummary[];
  /** `too_large` is an honest marker, never **Stopped reporting**. */
  result_availability: AgentResultAvailability | null;
  last_observed_at: string | null;
  /** The base poll rate. The server may observe less often after the window. */
  observation_interval_seconds: number;
  identifiers_expired: boolean;

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
  /**
   * The compact row states the tier in full and shows the same withdrawals the
   * full projection does, so the two surfaces cannot disagree about what the
   * user may still do (D-03-S21).
   */
  guarantee_tier: AgentGuaranteeTier | null;
  cancel_outcome: AgentCancelOutcome;
  agent_task_missing: boolean;
}
