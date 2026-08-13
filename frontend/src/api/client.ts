import type {
  BrainDumpOperationResponse,
  BrainDumpProvidersResponse,
  BrainDumpStartRequest,
  BrainDumpTranscriptAppendRequest,
  ProjectResponse,
  TagResponse,
  TaskCommentCreateRequest,
  TaskCommentResponse,
  TaskCommentUpdateRequest,
  TaskCreateRequest,
  TaskListFilters,
  TaskListResponse,
  SmartAddTaskCreateRequest,
  SmartAddTaskResponse,
  TaskResponse,
  TaskSubtaskCreateRequest,
  TaskSubtaskResponse,
  TaskSubtaskTransitionRequest,
  TaskSubtaskUpdateRequest,
  TaskTransitionRequest,
  TaskUpdateRequest
} from "./taskTypes";
import type {
  AccountDeletePayload,
  AccountDeleteResponse,
  AccountResponse,
  EmailChangePayload,
  PasswordChangePayload,
  ProfileUpdatePayload
} from "./accountTypes";
import type {
  AdminAccountLookupRequest,
  AdminAccountResponse,
  AdminRevokeSessionsResponse
} from "./adminTypes";
import type {
  AgentConnectionCreateRequest,
  AgentConnectionCreatedResponse,
  AgentConnectionDisconnectRequest,
  AgentConnectionResponse,
  AgentConnectionRotateRequest,
  AgentConnectionRotateSigningSecretRequest,
  AgentConnectionSigningSecretResponse,
  AgentConnectionUpdateRequest,
  AgentHandoffConfirmRequest,
  AgentHandoffPreviewRequest,
  AgentManifestResponse,
  AgentReplyRequest,
  AgentRunResponse,
  AgentRunSummaryResponse
} from "./agentTypes";
import { nowMs, recordTelemetry } from "../utils/telemetry";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

type JsonRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  signal?: AbortSignal;
};

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  onUnauthorized = handler;
}

function buildUrl(path: string): string {
  return `${API_BASE_URL.replace(/\/$/, "")}${path}`;
}

export class ApiError extends Error {
  status: number;
  payload: unknown;
  correlationId?: string;

  constructor(message: string, status: number, payload: unknown, correlationId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
    this.correlationId = correlationId;
  }
}

// Every endpoint below passes its own options object, so there is no default:
// the request shape is always stated at the call site.
async function request<T>(path: string, options: JsonRequestOptions): Promise<T> {
  const { body, ...rest } = options;
  const headers = new Headers(rest.headers);
  const method = options.method ?? "GET";
  const hasBody = body !== undefined && body !== null;

  let requestBody: BodyInit | null | undefined = undefined;

  if (hasBody) {
    // ArrayBuffer is the only binary body the client sends (brain-dump audio
    // chunks). FormData and Blob were carried for the tree import/export
    // endpoints and went with them.
    if (body instanceof ArrayBuffer) {
      requestBody = body;
    } else {
      headers.set("Content-Type", "application/json");
      requestBody = JSON.stringify(body);
    }
  }

  const startMs = nowMs();
  let response: Response;
  try {
    response = await fetch(buildUrl(path), {
      ...rest,
      method,
      headers,
      body: requestBody,
      credentials: "include"
    });
  } catch (error) {
    recordTelemetry(
      {
        name: "api.request",
        durationMs: nowMs() - startMs,
        ok: false,
        details: { method, path, error: error instanceof Error ? error.message : String(error) }
      },
      "warn"
    );
    throw error;
  }

  if (response.status === 401 && onUnauthorized) {
    onUnauthorized();
  }

  if (response.status === 204) {
    recordTelemetry({
      name: "api.request",
      durationMs: nowMs() - startMs,
      ok: true,
      details: { method, path, status: response.status }
    });
    return undefined as T;
  }

  const contentType = response.headers.get("Content-Type");
  const isJson = contentType && contentType.includes("application/json");
  const data = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const correlationId = response.headers.get("X-Correlation-ID") ?? undefined;
    recordTelemetry(
      {
        name: "api.request",
        durationMs: nowMs() - startMs,
        ok: false,
        details: { method, path, status: response.status, correlationId }
      },
      "warn"
    );
    throw new ApiError(response.statusText || "Request failed", response.status, data, correlationId);
  }

  recordTelemetry({
    name: "api.request",
    durationMs: nowMs() - startMs,
    ok: true,
    details: { method, path, status: response.status }
  });

  return data as T;
}

export const apiClient = {
  listTasks(filters: TaskListFilters = {}, signal?: AbortSignal) {
    const params = new URLSearchParams();
    if (filters.state) {
      params.set("state", filters.state);
    }
    if (filters.projectId) {
      params.set("project_id", filters.projectId);
    }
    if (filters.tagId) {
      params.set("tag_id", filters.tagId);
    }
    if (filters.cursor) {
      params.set("cursor", filters.cursor);
    }
    if (filters.limit) {
      params.set("limit", String(filters.limit));
    }
    if (filters.includeCompleted) {
      params.set("include_completed", "true");
    }
    if (filters.includeCancelled) {
      params.set("include_cancelled", "true");
    }
    if (filters.q?.trim()) {
      params.set("q", filters.q.trim());
    }
    if (filters.unassignedProject) {
      params.set("unassigned_project", "true");
    }
    for (const priority of filters.priority ?? []) {
      params.append("priority", priority);
    }
    if (filters.dueBefore) {
      params.set("due_before", filters.dueBefore);
    }
    if (filters.dueOn) {
      params.set("due_on", filters.dueOn);
    }
    if (filters.dueAfter) {
      params.set("due_after", filters.dueAfter);
    }
    if (filters.sort && filters.sort !== "manual") {
      params.set("sort", filters.sort);
    }
    const query = params.toString();
    return request<TaskListResponse>(`/tasks${query ? `?${query}` : ""}`, { signal });
  },

  createTask(payload: TaskCreateRequest, idempotencyKey: string) {
    return request<TaskResponse>("/tasks", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  smartAddTask(payload: SmartAddTaskCreateRequest, idempotencyKey: string) {
    return request<SmartAddTaskResponse>("/tasks/smart-add", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  getTask(taskId: string, signal?: AbortSignal) {
    return request<TaskResponse>(`/tasks/${taskId}`, { signal });
  },

  updateTask(taskId: string, payload: TaskUpdateRequest, idempotencyKey: string) {
    return request<TaskResponse>(`/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  transitionTask(taskId: string, payload: TaskTransitionRequest, idempotencyKey: string) {
    return request<TaskResponse>(`/tasks/${taskId}/transitions`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  createSubtask(taskId: string, payload: TaskSubtaskCreateRequest, idempotencyKey: string) {
    return request<TaskSubtaskResponse>(`/tasks/${taskId}/subtasks`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  updateSubtask(taskId: string, subtaskId: string, payload: TaskSubtaskUpdateRequest, idempotencyKey: string) {
    return request<TaskSubtaskResponse>(`/tasks/${taskId}/subtasks/${subtaskId}`, {
      method: "PATCH",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  transitionSubtask(taskId: string, subtaskId: string, payload: TaskSubtaskTransitionRequest, idempotencyKey: string) {
    return request<TaskSubtaskResponse>(`/tasks/${taskId}/subtasks/${subtaskId}/transitions`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  createComment(taskId: string, payload: TaskCommentCreateRequest, idempotencyKey: string) {
    return request<TaskCommentResponse>(`/tasks/${taskId}/comments`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  updateComment(taskId: string, commentId: string, payload: TaskCommentUpdateRequest, idempotencyKey: string) {
    return request<TaskCommentResponse>(`/tasks/${taskId}/comments/${commentId}`, {
      method: "PATCH",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  listProjects(signal?: AbortSignal) {
    return request<ProjectResponse[]>("/projects", { signal });
  },

  createProject(payload: { name: string; color?: string | null }, idempotencyKey: string) {
    return request<ProjectResponse>("/projects", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  updateProject(projectId: string, payload: { name?: string; color?: string | null; expected_revision: number }, idempotencyKey: string) {
    return request<ProjectResponse>(`/projects/${projectId}`, {
      method: "PATCH",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  archiveProject(projectId: string, expectedRevision: number, idempotencyKey: string) {
    return request<ProjectResponse>(`/projects/${projectId}/archive`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: { expected_revision: expectedRevision }
    });
  },

  listTags(signal?: AbortSignal) {
    return request<TagResponse[]>("/tags", { signal });
  },

  createTag(payload: { name: string }, idempotencyKey: string) {
    return request<TagResponse>("/tags", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  updateTag(tagId: string, payload: { name?: string; expected_revision: number }, idempotencyKey: string) {
    return request<TagResponse>(`/tags/${tagId}`, {
      method: "PATCH",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  deleteTag(tagId: string, expectedRevision: number, idempotencyKey: string) {
    return request<TagResponse>(`/tags/${tagId}?expected_revision=${expectedRevision}`, {
      method: "DELETE",
      headers: { "Idempotency-Key": idempotencyKey }
    });
  },

  getBrainDumpProviders(signal?: AbortSignal) {
    return request<BrainDumpProvidersResponse>("/brain-dump-providers", { signal });
  },

  startBrainDump(payload: BrainDumpStartRequest, idempotencyKey: string) {
    return request<BrainDumpOperationResponse>("/brain-dump-operations", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  getBrainDump(operationId: string, signal?: AbortSignal) {
    return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}`, { signal });
  },

  appendBrainDumpTranscript(operationId: string, payload: BrainDumpTranscriptAppendRequest, idempotencyKey: string) {
    return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/transcript`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  uploadBrainDumpAudio(
    operationId: string,
    chunkNumber: number,
    content: ArrayBuffer,
    sha256: string,
    mimeType: string
  ) {
    return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/audio/${chunkNumber}`, {
      method: "PUT",
      headers: { "Content-Type": mimeType, "X-Content-SHA256": sha256 },
      body: content
    });
  },

  sealBrainDump(
    operationId: string,
    payload: { expected_revision: number; expected_chunks: number; manifest_hash: string },
    idempotencyKey: string
  ) {
    return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/seal`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  updateBrainDumpProposal(
    operationId: string,
    proposalId: string,
    payload: { title?: string; deleted?: boolean; conflict_resolution?: "keep" | "accept"; expected_revision: number },
    idempotencyKey: string
  ) {
    return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/proposals/${proposalId}`, {
      method: "PATCH",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  commandBrainDump(operationId: string, action: "pause" | "resume" | "finish" | "cancel" | "commit" | "retry" | "review_provisional" | "withdraw_consent" | "delete_raw_audio", expectedRevision: number, idempotencyKey: string) {
    return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/${action}`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: { expected_revision: expectedRevision }
    });
  },

  // External agent relay. Every mutation carries a caller-generated
  // Idempotency-Key so a retry can never create a second connection, run, or
  // connector-side command. Reads and the connection test are naturally safe to
  // repeat, so they carry none.
  listAgentConnections(signal?: AbortSignal) {
    return request<AgentConnectionResponse[]>("/agent-connections", { signal });
  },

  createAgentConnection(payload: AgentConnectionCreateRequest, idempotencyKey: string) {
    return request<AgentConnectionCreatedResponse>("/agent-connections", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  getAgentConnection(connectionId: string, signal?: AbortSignal) {
    return request<AgentConnectionResponse>(`/agent-connections/${connectionId}`, { signal });
  },

  updateAgentConnection(connectionId: string, payload: AgentConnectionUpdateRequest, idempotencyKey: string) {
    return request<AgentConnectionResponse>(`/agent-connections/${connectionId}`, {
      method: "PUT",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  testAgentConnection(connectionId: string) {
    return request<AgentConnectionResponse>(`/agent-connections/${connectionId}/test`, {
      method: "POST"
    });
  },

  rotateAgentCredential(connectionId: string, payload: AgentConnectionRotateRequest, idempotencyKey: string) {
    return request<AgentConnectionResponse>(`/agent-connections/${connectionId}/credential`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  /**
   * Issue a replacement inbound signing secret.
   *
   * The create response shows that secret once, so this is the only way back
   * from losing it. The replacement takes effect immediately, which is why the
   * request carries the password and the revision the user was looking at.
   * Retrying an ambiguous attempt must reuse the same key: the server answers
   * a matching replay with the same secret rather than a blank success.
   */
  rotateAgentSigningSecret(
    connectionId: string,
    payload: AgentConnectionRotateSigningSecretRequest,
    idempotencyKey: string
  ) {
    return request<AgentConnectionSigningSecretResponse>(
      `/agent-connections/${connectionId}/signing-secret`,
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload
      }
    );
  },

  disconnectAgentConnection(
    connectionId: string,
    payload: AgentConnectionDisconnectRequest,
    idempotencyKey: string
  ) {
    return request<AgentConnectionResponse>(`/agent-connections/${connectionId}/disconnect`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  // Preview reserves nothing the user has not seen: it returns the manifest the
  // confirmation must name back, so a changed payload cannot be dispatched
  // against a stale review.
  previewAgentHandoff(taskId: string, payload: AgentHandoffPreviewRequest, signal?: AbortSignal) {
    return request<AgentManifestResponse>(`/tasks/${taskId}/agent-runs/preview`, {
      method: "POST",
      body: payload,
      signal
    });
  },

  confirmAgentHandoff(taskId: string, payload: AgentHandoffConfirmRequest, idempotencyKey: string) {
    return request<AgentRunResponse>(`/tasks/${taskId}/agent-runs`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  async listAgentRuns(taskId: string, signal?: AbortSignal) {
    const runs = await request<AgentRunResponse[]>(`/tasks/${taskId}/agent-runs`, { signal });
    return Array.isArray(runs) ? runs : [];
  },

  getAgentRun(runId: string, signal?: AbortSignal) {
    return request<AgentRunResponse>(`/agent-runs/${runId}`, { signal });
  },

  listAgentRunSummaries(taskIds: string[], signal?: AbortSignal) {
    const params = new URLSearchParams();
    taskIds.forEach((taskId) => params.append("task_id", taskId));
    return request<Record<string, AgentRunSummaryResponse>>(
      `/agent-run-summaries?${params.toString()}`,
      { signal }
    );
  },

  replyToAgentRun(runId: string, payload: AgentReplyRequest, idempotencyKey: string) {
    return request<AgentRunResponse>(`/agent-runs/${runId}/reply`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  cancelAgentRun(runId: string, idempotencyKey: string) {
    return request<AgentRunResponse>(`/agent-runs/${runId}/cancel`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey }
    });
  },

  // Account management (GDPR data rights). No Idempotency-Key headers here:
  // the backend account endpoints are naturally idempotent or re-auth guarded.
  getAccount(signal?: AbortSignal) {
    return request<AccountResponse>("/account", { signal });
  },

  updateProfile(payload: ProfileUpdatePayload) {
    return request<AccountResponse>("/account/profile", { method: "PATCH", body: payload });
  },

  changeEmail(payload: EmailChangePayload) {
    return request<AccountResponse>("/account/email", { method: "POST", body: payload });
  },

  changePassword(payload: PasswordChangePayload) {
    return request<void>("/account/password", { method: "POST", body: payload });
  },

  requestAccountDeletion(payload: AccountDeletePayload) {
    return request<AccountDeleteResponse>("/account/delete", { method: "POST", body: payload });
  },

  // Minimum admin portal (009): exact account lookup and session revoke,
  // gated server-side on the operator allow-list.
  lookupAdminAccount(payload: AdminAccountLookupRequest) {
    return request<AdminAccountResponse>("/admin/accounts/lookup", { method: "POST", body: payload });
  },

  revokeAdminAccountSessions(accountId: string) {
    return request<AdminRevokeSessionsResponse>(
      `/admin/accounts/${encodeURIComponent(accountId)}/revoke-sessions`,
      { method: "POST" }
    );
  }
};
