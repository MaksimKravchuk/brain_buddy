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
  AgentRunResponse,
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

export function makeConnection(
  overrides: Partial<AgentConnectionResponse> = {},
): AgentConnectionResponse {
  return {
    id: "conn_1",
    name: "My Claude Code box",
    endpoint_url: "https://agent.example.test/relay",
    auth_header_name: "Authorization",
    status: "ready",
    stale: false,
    ready_for_handoff: true,
    capabilities: { progress: true, reply: true, cancel: true },
    last_test_error_code: null,
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
    context_items: [],
    reporting_instructions: "Report progress to the callback URL with your signing secret.",
    instructions_version: "2026-08-01",
    protocol_version: "1",
    destination_endpoint: "https://agent.example.test/relay",
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
    capabilities: { progress: true, reply: true, cancel: true },
    manifest: null,
    events: [],
    commands: [],
    created_at: "2026-08-09T09:00:00Z",
    revision: 2,
    ...overrides,
  };
}
