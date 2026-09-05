/**
 * Server-shaped fixtures for relay tests.
 *
 * These mirror the API contracts exactly — especially `primary_state_label`,
 * which the server computes and the client renders verbatim. Tests override
 * single fields so a fixture never quietly encodes a state the server would
 * not produce.
 */

import type {
  AgentConnectionResponse,
  AgentManifestResponse,
  AgentRunEvent,
  AgentRunResponse,
  AgentRunSummaryResponse,
  TaskResponse,
} from "@/api/types";

export function makeTask(overrides: Partial<TaskResponse> = {}): TaskResponse {
  return {
    id: "task_1",
    title: "Draft the launch note",
    details: "Two paragraphs, plain language.",
    state: "next",
    project_id: null,
    tag_ids: [],
    due_date: null,
    priority: "none",
    waiting_for: null,
    waiting_since: null,
    order_key: 1,
    source_capture_ids: [],
    created_at: "2026-08-01T09:00:00Z",
    updated_at: "2026-08-01T09:00:00Z",
    completed_at: null,
    cancelled_at: null,
    revision: 3,
    subtasks: [],
    comments: [],
    ...overrides,
  };
}

export function makeCard(
  overrides: Partial<NonNullable<AgentConnectionResponse["card"]>> = {},
): NonNullable<AgentConnectionResponse["card"]> {
  return {
    name: "My Claude Code box",
    version: "1.2.3",
    description: "A research agent.",
    protocol_version: "1.0",
    interface_url: "https://agent.example.test/a2a",
    streaming: true,
    push_notifications: false,
    skills: [{ id: "research", name: "Research", description: "Digs." }],
    auth_schemes_offered: [{ name: "bearer", kind: "bearer", header_name: null }],
    extension_uris: [],
    fetched_at: "2026-08-09T09:00:00Z",
    ...overrides,
  };
}

export function makeConnection(
  overrides: Partial<AgentConnectionResponse> = {},
): AgentConnectionResponse {
  return {
    id: "conn_1",
    name: "My Claude Code box",
    agent_address: "https://agent.example.test",
    auth_scheme: "bearer",
    auth_header_name: null,
    status: "ready",
    stale: false,
    ready_for_handoff: true,
    capabilities: { streaming: true, push_notifications: false },
    controls_offered: { reply: true, cancel: true },
    card: makeCard(),
    guarantee_tier: "best_effort",
    tier_disclosure:
      "Best-effort single start. This agent's card does not declare Brain Buddy's single-start extension.",
    tier_disclosure_url: "https://example.invalid/single-start/v1.md",
    cancellation_disclosure: "Cancellation depends on the agent.",
    agent_changed: false,
    best_effort_acknowledged_at: null,
    correlation_id_honoured: null,
    disconnect_reason: null,
    last_test_error_code: null,
    last_test_error_detail: null,
    last_contact_at: "2026-08-09T09:00:00Z",
    last_tested_at: "2026-08-09T09:00:00Z",
    stale_after_seconds: 3600,
    created_at: "2026-08-01T09:00:00Z",
    revision: 1,
    ...overrides,
  };
}

export function makeManifest(
  overrides: Partial<AgentManifestResponse> = {},
): AgentManifestResponse {
  return {
    token: "manifest_token_1",
    run_id: "run_1",
    task_id: "task_1",
    connection_id: "conn_1",
    agent_name: "My Claude Code box",
    title: "Draft the launch note",
    details: "Two paragraphs, plain language.",
    supporting_items: [],
    message_id: "run_1:start",
    correlation_id: "run_1",
    destination_interface: "https://agent.example.test/a2a",
    protocol_version: "1.0",
    guarantee_tier: "best_effort",
    tier_disclosure:
      "Best-effort single start. This agent's card does not declare Brain Buddy's single-start extension.",
    tier_disclosure_url: "https://example.invalid/single-start/v1.md",
    acknowledgement_required: false,
    cancellation_disclosure: "Cancellation depends on the agent.",
    push_callback: null,
    parts_preview: ["Draft the launch note"],
    external_copy_notice:
      "This sends a copy of the task below to a system Brain Buddy does not control.",
    reauthentication_required: false,
    ...overrides,
  };
}

export function makeRun(overrides: Partial<AgentRunResponse> = {}): AgentRunResponse {
  return {
    id: "run_1",
    task_id: "task_1",
    connection_id: "conn_1",
    agent_name: "My Claude Code box",
    dispatch_state: "sent",
    dispatch_error_code: null,
    reported_state: "running",
    run_version: 2,
    stopped_reporting: false,
    connection_disconnected: false,
    reply_pending: false,
    cancel_requested: false,
    needs_user: false,
    primary_state_label: "Running",
    progress_text: null,
    question_text: null,
    result_text: null,
    result_link: null,
    result_link_interactive: false,
    failure_reason: null,
    content_expired: false,
    content_expires_at: "2026-09-01T09:00:00Z",
    last_contact_at: "2026-08-09T09:05:00Z",
    reporting_window_seconds: 900,
    capabilities: { reply: true, cancel: true },
    guarantee_tier: "best_effort",
    message_id: "run_1:start",
    correlation_id: "run_1",
    agent_task_id: null,
    exchange_open: false,
    exchange_state: "closed",
    exchange_kind: "start",
    push_registration: "unregistered",
    agent_task_missing: false,
    cancel_outcome: "none",
    blocked_reason: null,
    artifacts_summary: [],
    result_availability: null,
    last_observed_at: null,
    observation_interval_seconds: 60,
    identifiers_expired: false,
    manifest: null,
    events: [],
    commands: [],
    created_at: "2026-08-09T09:00:00Z",
    revision: 2,
    ...overrides,
  };
}

/** One timeline row with the 014 fields at their ordinary-observation values. */
export function makeRunEvent(
  overrides: Partial<AgentRunEvent> &
    Pick<AgentRunEvent, "id" | "type" | "run_version">,
): AgentRunEvent {
  return {
    received_at: "2026-08-09T09:05:00Z",
    summary: null,
    trigger: "schedule",
    kind: "observation",
    previous_agent_task_id: null,
    new_agent_task_id: null,
    ...overrides,
  };
}

/** One compact task-row summary, carrying the tier and the withdrawals. */
export function makeRunSummary(
  overrides: Partial<AgentRunSummaryResponse> = {},
): AgentRunSummaryResponse {
  return {
    id: "run_1",
    task_id: "task_1",
    agent_name: "My Claude Code box",
    primary_state_label: "Running",
    needs_user: false,
    stopped_reporting: false,
    last_contact_at: "2026-08-09T09:05:00Z",
    guarantee_tier: "best_effort",
    cancel_outcome: "none",
    agent_task_missing: false,
    ...overrides,
  };
}
