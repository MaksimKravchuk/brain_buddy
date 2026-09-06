/**
 * Wire types for the Brain Buddy API.
 *
 * Ported from `frontend/src/api/taskTypes.ts` — keep the two in sync. The
 * backend request models are `extra="forbid"`: never add client-side fields
 * to request payloads.
 */

export type TaskState = "inbox" | "next" | "waiting" | "someday" | "completed" | "cancelled";
export type OpenTaskState = "inbox" | "next" | "waiting" | "someday";
export type TaskPriority = "none" | "low" | "medium" | "high";
export type TaskSort = "manual" | "due" | "priority" | "title";

export const OPEN_TASK_STATES: OpenTaskState[] = ["inbox", "next", "waiting", "someday"];

export interface TaskCounts {
  inbox: number;
  next: number;
  waiting: number;
  someday: number;
}

export interface TaskResponse {
  id: string;
  title: string;
  details: string | null;
  state: TaskState;
  project_id: string | null;
  tag_ids: string[];
  due_date: string | null;
  priority: TaskPriority;
  waiting_for: string | null;
  waiting_since: string | null;
  order_key: number;
  source_capture_ids: string[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  cancelled_at: string | null;
  revision: number;
  subtasks?: TaskSubtaskResponse[];
  comments?: TaskCommentResponse[];
}

export interface TaskSubtaskResponse {
  id: string;
  title: string;
  state: "open" | "completed" | "cancelled";
  order_key: number;
  revision: number;
}

export interface TaskCommentResponse {
  id: string;
  body: string;
  actor_id: string;
  created_at: string;
  edited_at: string | null;
  revision: number;
}

export interface TaskListResponse {
  items: TaskResponse[];
  next_cursor: string | null;
  has_more: boolean;
  counts_by_state: TaskCounts;
}

export interface ProjectResponse {
  id: string;
  name: string;
  color: string | null;
  state: "active" | "completed" | "archived";
  revision: number;
  open_task_count: number;
}

export interface TagResponse {
  id: string;
  name: string;
  state: "active" | "archived" | "deleted";
  revision: number;
  open_task_count: number;
}

export interface TaskListFilters {
  state?: TaskState;
  projectId?: string;
  tagId?: string;
  unassignedProject?: boolean;
  cursor?: string;
  limit?: number;
  includeCompleted?: boolean;
  includeCancelled?: boolean;
  q?: string;
  priority?: TaskPriority[];
  dueBefore?: string;
  dueOn?: string;
  dueAfter?: string;
  sort?: TaskSort;
}

export interface TaskCreateRequest {
  title: string;
  details?: string | null;
  state?: OpenTaskState;
  project_id?: string | null;
  tag_ids?: string[];
  due_date?: string | null;
  priority?: TaskPriority;
  waiting_for?: string | null;
}

export type SmartAddClassificationRef = { id: string; name?: never } | { id?: never; name: string };

export interface SmartAddTaskCreateRequest {
  title: string;
  details?: string | null;
  state?: OpenTaskState;
  waiting_for?: string | null;
  due_date?: string | null;
  priority?: TaskPriority;
  project?: SmartAddClassificationRef | null;
  tags?: SmartAddClassificationRef[];
}

export interface SmartAddTaskResponse {
  task: TaskResponse;
  project: ProjectResponse | null;
  tags: TagResponse[];
  created: {
    project_id: string | null;
    tag_ids: string[];
  };
}

export interface TaskUpdateRequest {
  title?: string;
  details?: string | null;
  project_id?: string | null;
  tag_ids?: string[];
  due_date?: string | null;
  priority?: TaskPriority;
  waiting_for?: string | null;
  expected_revision: number;
}

export interface TaskTransitionRequest {
  action: "move" | "complete" | "reopen" | "cancel";
  to_state?: OpenTaskState;
  waiting_for?: string | null;
  expected_revision: number;
}

export interface TaskSubtaskCreateRequest {
  title: string;
}

export interface TaskSubtaskUpdateRequest {
  title?: string;
  expected_revision: number;
}

export interface TaskSubtaskTransitionRequest {
  action: "complete" | "reopen" | "cancel";
  expected_revision: number;
}

export interface TaskCommentCreateRequest {
  body: string;
}

export interface TaskCommentUpdateRequest {
  body: string;
  expected_revision: number;
}

// --- Auth ---

export interface MeResponse {
  id: string;
  email: string;
  feature_flags: Record<string, boolean>;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface SignupRequest {
  email: string;
  password: string;
  invite_code: string;
}

/** Error body shape shared by every backend error response. */
export interface ErrorPayload {
  message: string;
  detail?: unknown;
  reference_id?: string | null;
}

// --- Voice brain dump ---

export type BrainDumpStatus =
  | "recording"
  | "paused"
  | "sealing"
  | "fast_processing"
  | "accurate_transcribing"
  | "reconciling"
  | "retryable_error"
  | "terminal_error"
  | "awaiting_confirmation"
  | "committing"
  | "completed"
  | "cancelled";

export type BrainDumpProposalStatus =
  | "provisional"
  | "wording_changing"
  | "ready_to_review"
  | "user_edited"
  | "reconciled"
  | "conflicted";

export interface BrainDumpProposalConflict {
  field: string;
  current_value: string | null;
  suggested_value: string | null;
  producer: "fast" | "accurate" | "reconciler" | "user";
  source_segment_ids: string[];
}

export interface BrainDumpProposal {
  id: string;
  ordinal: number;
  title: string;
  status: BrainDumpProposalStatus;
  source_segment_ids: string[];
  predecessor_ids?: string[];
  successor_ids?: string[];
  locked_fields?: string[];
  conflicts?: BrainDumpProposalConflict[];
  deleted: boolean;
  user_edited: boolean;
  revision: number;
}

export interface BrainDumpAudioChunkMeta {
  chunk_number: number;
  sha256: string;
  size_bytes: number;
}

export interface BrainDumpOperationResponse {
  id: string;
  owner_id: string;
  kind: "voice_brain_dump";
  status: BrainDumpStatus;
  consent: {
    microphone: boolean;
    external_processing_allowed: boolean;
    provider: string | null;
    providers?: string[];
    language_hints: string[];
    vocabulary: string[];
    recorded_at: string;
  };
  segments: {
    id: string;
    sequence: number;
    text: string;
    stability: "interim" | "stable";
    start_ms?: number;
    end_ms?: number;
    provider_role?: "browser_preview" | "fast" | "accurate";
    provider?: string | null;
    model?: string | null;
    supersedes_segment_ids?: string[];
    created_at: string;
  }[];
  proposals: BrainDumpProposal[];
  media_ref?: string | null;
  audio_chunks?: BrainDumpAudioChunkMeta[];
  sealed_manifest_hash?: string | null;
  raw_audio_expires_at?: string | null;
  raw_audio_present?: boolean;
  working_artifacts_expires_at?: string | null;
  reconciliation_quality?: "none" | "provisional_only" | "accurate" | "conflicted";
  committable?: boolean;
  /**
   * Owner-initiated recovery commands the server will accept right now, in
   * the order it advertises them. `reconcile_preview` extracts tasks from the
   * browser-preview transcript when the accurate one never arrived; mobile
   * has no preview lane of its own, so it shows up only for dumps that were
   * started on the web and resumed here.
   */
  available_recovery_actions?: (
    | "retry"
    | "review_provisional"
    | "reconcile_preview"
    | "cancel"
  )[];
  provider_runs?: {
    id: string;
    role: "accurate_stt" | "reconciler";
    status: "pending" | "running" | "succeeded" | "retryable_error" | "terminal_error";
    checkpoint: "sealed" | "accurate_transcribed" | "reconciled";
    attempt: number;
    recovery_count: number;
    error: string | null;
    error_code: string | null;
    provider: string | null;
    model: string | null;
    template_version: string | null;
    estimated_cost_usd: number;
    reserved_cost_usd?: number;
    consumed_cost_usd?: number;
  }[];
  status_history?: BrainDumpStatus[];
  committed_task_ids: string[];
  created_at: string;
  updated_at: string;
  revision: number;
}

export interface BrainDumpStartRequest {
  consent: {
    microphone: boolean;
    external_processing_allowed: boolean;
    provider?: string | null;
    providers?: string[];
    language_hints: string[];
    vocabulary: string[];
  };
}

export interface BrainDumpProvidersResponse {
  accurate_stt: string | null;
  reconciler: string | null;
}

export interface BrainDumpTranscriptAppendRequest {
  segments: { sequence: number; text: string; stability: "interim" | "stable" }[];
}

export type BrainDumpAction =
  | "pause"
  | "resume"
  | "finish"
  | "cancel"
  | "commit"
  | "retry"
  | "review_provisional"
  | "reconcile_preview"
  | "withdraw_consent"
  | "delete_raw_audio";

// --- External agents ---
//
// Mirrors `backend/app/schemas/agents.py` (and the web client's agent types).
// Two rules survive the port: no response type can carry a saved credential,
// and connector-reported facts, BrainBuddy-derived conditions, and pending
// commands stay in separate fields so no client blends them into an invented
// progress number.

/**
 * What the agent's own card declared. Never a Brain Buddy claim.
 *
 * Kept apart from `AgentControls`: blending the two would let a product
 * decision be rendered as something the agent promised (FR-002, FR-010).
 */
export interface AgentCapabilities {
  streaming: boolean;
  push_notifications: boolean;
}

/** The controls Brain Buddy offers here. Cards advertise neither (FR-010). */
export interface AgentControls {
  reply: boolean;
  cancel: boolean;
}

export type AgentAuthScheme = "bearer" | "api_key";
export type AgentGuaranteeTier = "guaranteed" | "best_effort";
export type AgentDisconnectReason = "owner" | "superseded_wire_contract";
export type AgentExchangeState = "none" | "queued" | "open" | "closed" | "interrupted";
export type AgentExchangeKind = "start" | "reply";
export type AgentPushRegistration =
  | "unregistered"
  | "registered"
  | "refused"
  | "unsupported";
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
 * Every string here is untrusted agent text and is rendered inertly: never a
 * `Linking` target, never auto-linked, never markup-interpreted, exactly as
 * `result_link` is treated (FR-016, AC-031). `interface_url` is shown so the
 * owner can see where their content would go — which is also why it is never
 * made tappable.
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

/** Closed per-code shapes for the last test's coarse detail. */
export type AgentTestErrorDetail =
  | { found_version: string }
  | { scheme: string }
  | { retry_after_seconds: number | null }
  | { interface_url: string | null };

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

export interface AgentConnectionResponse {
  id: string;
  name: string;
  agent_address: string;
  auth_scheme: AgentAuthScheme;
  /** Card-sourced, and only for an API-key connection. Never user input. */
  auth_header_name: string | null;
  status: AgentConnectionStatus;
  /** Server-derived from the clock: last contact older than the threshold. */
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
  current_password?: string;
  expected_revision: number;
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

export interface AgentPushCallback {
  registered: boolean;
  url_preview: string | null;
  disclosure: string | null;
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

export interface AgentHandoffPreviewRequest {
  connection_id: string;
  include_details?: boolean;
  supporting_items?: AgentContextItem[];
}

export interface AgentHandoffConfirmRequest extends AgentHandoffPreviewRequest {
  manifest_token: string;
  current_password?: string | null;
  /** Part of the canonical request identity, so a replay carries it (AC-026). */
  acknowledge_duplicate_risk?: boolean;
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

/** Exactly what will leave Brain Buddy, itemised for review. */
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
  acknowledgement_required: boolean;
  cancellation_disclosure: string;
  push_callback: AgentPushCallback | null;
  external_copy_notice: string;
  reauthentication_required: boolean;
  parts_preview: string[];
}

export interface AgentReplyRequest {
  message: string;
  expected_revision: number;
}

/** Why an observation ran. Shown as detail on the row it produced. */
export type AgentRunEventTrigger = "dispatch" | "schedule" | "push" | "command";

/**
 * What a timeline row *is*.
 *
 * `task_succession` is not a state change: the agent moved the work into a new
 * task inside the same conversation, and the row exists so the identifier the
 * user saw yesterday is not silently replaced (M-03-S26).
 */
export type AgentRunEventKind = "observation" | "task_succession";

/**
 * What became of a cancellation request (AC-018, AC-029).
 *
 * `unsupported` and `not_cancelable` come only from an explicit agent answer
 * and withdraw the control. `unconfirmed` is the ambiguous ending and keeps it:
 * Brain Buddy does not know whether the request landed, and hiding the control
 * would present its own uncertainty as the agent's refusal.
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
 * A placeholder for something the agent produced and Brain Buddy never fetched.
 *
 * Names the content type rather than the content: the relay stores no
 * attachment, so a row implying a download would promise something that does
 * not exist (M-03-S10).
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

  // What Brain Buddy knows about its own outbound request.
  dispatch_state: AgentDispatchState;
  dispatch_error_code: string | null;

  // What the connector last authenticated as, and its authoritative version.
  reported_state: AgentReportedState | null;
  run_version: number;

  // Conditions Brain Buddy derived or the user requested — never blended into
  // the reported state above.
  stopped_reporting: boolean;
  connection_disconnected: boolean;
  reply_pending: boolean;
  cancel_requested: boolean;
  needs_user: boolean;

  /** Already honest and user-facing: render verbatim, never recompute. */
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
  /** The A2A exchange this run is waiting on: Queued and Sent stay apart. */
  guarantee_tier: AgentGuaranteeTier | null;
  message_id: string | null;
  correlation_id: string | null;
  agent_task_id: string | null;
  exchange_open: boolean;
  exchange_state: AgentExchangeState;
  exchange_kind: AgentExchangeKind | null;
  push_registration: AgentPushRegistration;

  /**
   * What Brain Buddy's own observation of the agent's task established.
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

/**
 * The compact task list's view of a run: latest only, no timeline.
 *
 * Deliberately narrower than `AgentRunResponse` — a task row shows that an
 * agent is involved and whether it needs the user, and routes to the task
 * detail for anything more.
 */
export interface AgentRunSummaryResponse {
  id: string;
  task_id: string;
  agent_name: string;
  /** Server-owned honest label. Render verbatim; never re-derive or embellish. */
  primary_state_label: string;
  needs_user: boolean;
  stopped_reporting: boolean;
  last_contact_at: string | null;
  /**
   * The compact row states the tier in full and shows the same withdrawals the
   * full projection does, so the two surfaces cannot disagree about what the
   * user may still do (M-03-S24).
   */
  guarantee_tier: AgentGuaranteeTier | null;
  cancel_outcome: AgentCancelOutcome;
  agent_task_missing: boolean;
}
