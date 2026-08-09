/**
 * Brain Buddy API client for React Native.
 *
 * Port of `frontend/src/api/client.ts` with the same method surface and
 * payloads, restructured as a factory so the base URL, unauthorized handler,
 * and fetch implementation are injectable (device vs. Node integration
 * tests).
 *
 * Session auth is an HttpOnly cookie (`brainbuddy_session`): on iOS the
 * request stack is NSURLSession with the shared cookie jar, so the cookie is
 * stored and replayed automatically. In Node tests a cookie-aware `fetchImpl`
 * is injected instead.
 */

import type {
  AgentConnectionCreatedResponse,
  AgentConnectionCreateRequest,
  AgentConnectionDisconnectRequest,
  AgentConnectionResponse,
  AgentConnectionRotateRequest,
  AgentConnectionRotateSigningSecretRequest,
  AgentConnectionSigningSecretResponse,
  AgentHandoffConfirmRequest,
  AgentHandoffPreviewRequest,
  AgentManifestResponse,
  AgentReplyRequest,
  AgentRunResponse,
  AgentRunSummaryResponse,
  BrainDumpAction,
  BrainDumpOperationResponse,
  BrainDumpProvidersResponse,
  BrainDumpStartRequest,
  BrainDumpTranscriptAppendRequest,
  ErrorPayload,
  LoginRequest,
  MeResponse,
  ProjectResponse,
  SignupRequest,
  SmartAddTaskCreateRequest,
  SmartAddTaskResponse,
  TagResponse,
  TaskCommentCreateRequest,
  TaskCommentResponse,
  TaskCommentUpdateRequest,
  TaskCreateRequest,
  TaskListFilters,
  TaskListResponse,
  TaskResponse,
  TaskSubtaskCreateRequest,
  TaskSubtaskResponse,
  TaskSubtaskTransitionRequest,
  TaskSubtaskUpdateRequest,
  TaskTransitionRequest,
  TaskUpdateRequest,
} from "./types";

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

  /** Server-provided human message when the body is an ErrorPayload. */
  get serverMessage(): string {
    const payload = this.payload as ErrorPayload | undefined;
    if (payload && typeof payload === "object" && typeof payload.message === "string") {
      return payload.message;
    }
    return this.message;
  }

  get referenceId(): string | undefined {
    const payload = this.payload as ErrorPayload | undefined;
    if (payload && typeof payload === "object" && typeof payload.reference_id === "string") {
      return payload.reference_id;
    }
    return this.correlationId;
  }
}

export interface ApiClientOptions {
  /** Returns the API base URL, e.g. `https://host/api` (no trailing slash needed). */
  getBaseUrl: () => string;
  /** Called on any 401 response (session expired / signed out elsewhere). */
  onUnauthorized?: (() => void) | null;
  /** Injectable fetch for tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
  /** Request timeout in ms. Generous default: the Fly frontend cold-starts. */
  timeoutMs?: number;
}

type JsonRequestOptions = {
  method?: string;
  headers?: Record<string, string>;
  body?: unknown;
  signal?: AbortSignal;
};

const DEFAULT_TIMEOUT_MS = 30_000;

function normalizeBaseUrl(raw: string): string {
  return raw.replace(/\/+$/, "");
}

/** Uint8Array → standalone ArrayBuffer (RN fetch handles ArrayBuffer bodies). */
export function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  if (bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength) {
    return bytes.buffer as ArrayBuffer;
  }
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}

export function createApiClient(options: ApiClientOptions) {
  const { getBaseUrl, onUnauthorized, fetchImpl, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  // Preserve the global binding: calling an unbound fetch reference throws in
  // some environments (illegal invocation).
  const doFetch: typeof fetch = fetchImpl ?? ((...args) => fetch(...args));

  async function request<T>(path: string, opts: JsonRequestOptions = {}): Promise<T> {
    const { body, headers: extraHeaders, method = "GET", signal } = opts;
    const headers: Record<string, string> = { ...extraHeaders };

    let requestBody: string | ArrayBuffer | undefined;
    if (body !== undefined && body !== null) {
      if (body instanceof Uint8Array) {
        // Binary body (brain-dump audio chunk). Content-Type set by caller.
        requestBody = toArrayBuffer(body);
      } else if (body instanceof ArrayBuffer) {
        requestBody = body;
      } else {
        headers["Content-Type"] = "application/json";
        requestBody = JSON.stringify(body);
      }
    }

    const timeout = AbortSignal.timeout(timeoutMs);
    const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

    const response = await doFetch(`${normalizeBaseUrl(getBaseUrl())}${path}`, {
      method,
      headers,
      body: requestBody,
      credentials: "include",
      signal: combined,
    });

    if (response.status === 401 && onUnauthorized) {
      onUnauthorized();
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const contentType = response.headers.get("Content-Type");
    const isJson = contentType ? contentType.includes("application/json") : false;
    const data: unknown = isJson ? await response.json() : await response.text();

    if (!response.ok) {
      const correlationId = response.headers.get("X-Correlation-ID") ?? undefined;
      throw new ApiError(response.statusText || "Request failed", response.status, data, correlationId);
    }

    return data as T;
  }

  return {
    request,

    // --- Auth ---

    me(signal?: AbortSignal) {
      return request<MeResponse>("/auth/me", { signal });
    },

    login(payload: LoginRequest) {
      return request<MeResponse>("/auth/login", { method: "POST", body: payload });
    },

    signup(payload: SignupRequest) {
      return request<MeResponse>("/auth/signup", { method: "POST", body: payload });
    },

    logout() {
      return request<void>("/auth/logout", { method: "POST" });
    },

    // --- Tasks ---

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
        body: payload,
      });
    },

    smartAddTask(payload: SmartAddTaskCreateRequest, idempotencyKey: string) {
      return request<SmartAddTaskResponse>("/tasks/smart-add", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    getTask(taskId: string, signal?: AbortSignal) {
      return request<TaskResponse>(`/tasks/${taskId}`, { signal });
    },

    updateTask(taskId: string, payload: TaskUpdateRequest, idempotencyKey: string) {
      return request<TaskResponse>(`/tasks/${taskId}`, {
        method: "PATCH",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    transitionTask(taskId: string, payload: TaskTransitionRequest, idempotencyKey: string) {
      return request<TaskResponse>(`/tasks/${taskId}/transitions`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    createSubtask(taskId: string, payload: TaskSubtaskCreateRequest, idempotencyKey: string) {
      return request<TaskSubtaskResponse>(`/tasks/${taskId}/subtasks`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    updateSubtask(
      taskId: string,
      subtaskId: string,
      payload: TaskSubtaskUpdateRequest,
      idempotencyKey: string,
    ) {
      return request<TaskSubtaskResponse>(`/tasks/${taskId}/subtasks/${subtaskId}`, {
        method: "PATCH",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    transitionSubtask(
      taskId: string,
      subtaskId: string,
      payload: TaskSubtaskTransitionRequest,
      idempotencyKey: string,
    ) {
      return request<TaskSubtaskResponse>(`/tasks/${taskId}/subtasks/${subtaskId}/transitions`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    createComment(taskId: string, payload: TaskCommentCreateRequest, idempotencyKey: string) {
      return request<TaskCommentResponse>(`/tasks/${taskId}/comments`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    updateComment(
      taskId: string,
      commentId: string,
      payload: TaskCommentUpdateRequest,
      idempotencyKey: string,
    ) {
      return request<TaskCommentResponse>(`/tasks/${taskId}/comments/${commentId}`, {
        method: "PATCH",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    // --- Projects ---

    listProjects(signal?: AbortSignal) {
      return request<ProjectResponse[]>("/projects", { signal });
    },

    createProject(payload: { name: string; color?: string | null }, idempotencyKey: string) {
      return request<ProjectResponse>("/projects", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    updateProject(
      projectId: string,
      payload: { name?: string; color?: string | null; expected_revision: number },
      idempotencyKey: string,
    ) {
      return request<ProjectResponse>(`/projects/${projectId}`, {
        method: "PATCH",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    archiveProject(projectId: string, expectedRevision: number, idempotencyKey: string) {
      return request<ProjectResponse>(`/projects/${projectId}/archive`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: { expected_revision: expectedRevision },
      });
    },

    // --- Tags ---

    listTags(signal?: AbortSignal) {
      return request<TagResponse[]>("/tags", { signal });
    },

    createTag(payload: { name: string }, idempotencyKey: string) {
      return request<TagResponse>("/tags", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    updateTag(
      tagId: string,
      payload: { name?: string; expected_revision: number },
      idempotencyKey: string,
    ) {
      return request<TagResponse>(`/tags/${tagId}`, {
        method: "PATCH",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    deleteTag(tagId: string, expectedRevision: number, idempotencyKey: string) {
      return request<TagResponse>(`/tags/${tagId}?expected_revision=${expectedRevision}`, {
        method: "DELETE",
        headers: { "Idempotency-Key": idempotencyKey },
      });
    },

    // --- Voice brain dump ---

    getBrainDumpProviders(signal?: AbortSignal) {
      return request<BrainDumpProvidersResponse>("/brain-dump-providers", { signal });
    },

    startBrainDump(payload: BrainDumpStartRequest, idempotencyKey: string) {
      return request<BrainDumpOperationResponse>("/brain-dump-operations", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    getBrainDump(operationId: string, signal?: AbortSignal) {
      return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}`, { signal });
    },

    appendBrainDumpTranscript(
      operationId: string,
      payload: BrainDumpTranscriptAppendRequest,
      idempotencyKey: string,
    ) {
      return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/transcript`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    uploadBrainDumpAudio(
      operationId: string,
      chunkNumber: number,
      content: Uint8Array,
      sha256Hex: string,
      mimeType: string,
    ) {
      return request<BrainDumpOperationResponse>(
        `/brain-dump-operations/${operationId}/audio/${chunkNumber}`,
        {
          method: "PUT",
          headers: { "Content-Type": mimeType, "X-Content-SHA256": sha256Hex },
          body: content,
        },
      );
    },

    sealBrainDump(
      operationId: string,
      payload: { expected_revision: number; expected_chunks: number; manifest_hash: string },
      idempotencyKey: string,
    ) {
      return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/seal`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    updateBrainDumpProposal(
      operationId: string,
      proposalId: string,
      payload: {
        title?: string;
        deleted?: boolean;
        conflict_resolution?: "keep" | "accept";
        expected_revision: number;
      },
      idempotencyKey: string,
    ) {
      return request<BrainDumpOperationResponse>(
        `/brain-dump-operations/${operationId}/proposals/${proposalId}`,
        {
          method: "PATCH",
          headers: { "Idempotency-Key": idempotencyKey },
          body: payload,
        },
      );
    },

    commandBrainDump(
      operationId: string,
      action: BrainDumpAction,
      expectedRevision: number,
      idempotencyKey: string,
    ) {
      return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/${action}`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: { expected_revision: expectedRevision },
      });
    },

    // --- External agents ---

    listAgentConnections(signal?: AbortSignal) {
      return request<AgentConnectionResponse[]>("/agent-connections", { signal });
    },

    /**
     * The 201 body is the only time the inbound signing secret is ever
     * returned — show it once and never persist it.
     */
    createAgentConnection(payload: AgentConnectionCreateRequest, idempotencyKey: string) {
      return request<AgentConnectionCreatedResponse>("/agent-connections", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    getAgentConnection(connectionId: string, signal?: AbortSignal) {
      return request<AgentConnectionResponse>(`/agent-connections/${connectionId}`, { signal });
    },

    testAgentConnection(connectionId: string) {
      return request<AgentConnectionResponse>(`/agent-connections/${connectionId}/test`, {
        method: "POST",
      });
    },

    rotateAgentCredential(
      connectionId: string,
      payload: AgentConnectionRotateRequest,
      idempotencyKey: string,
    ) {
      return request<AgentConnectionResponse>(`/agent-connections/${connectionId}/credential`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    rotateAgentSigningSecret(
      connectionId: string,
      payload: AgentConnectionRotateSigningSecretRequest,
      idempotencyKey: string,
    ) {
      return request<AgentConnectionSigningSecretResponse>(
        `/agent-connections/${connectionId}/signing-secret`,
        {
          method: "POST",
          headers: { "Idempotency-Key": idempotencyKey },
          body: payload,
        },
      );
    },

    disconnectAgentConnection(
      connectionId: string,
      payload: AgentConnectionDisconnectRequest,
      idempotencyKey: string,
    ) {
      return request<AgentConnectionResponse>(`/agent-connections/${connectionId}/disconnect`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    /** Reserves and returns the manifest to review. Nothing leaves yet. */
    previewAgentHandoff(taskId: string, payload: AgentHandoffPreviewRequest) {
      return request<AgentManifestResponse>(`/tasks/${taskId}/agent-runs/preview`, {
        method: "POST",
        body: payload,
      });
    },

    confirmAgentHandoff(
      taskId: string,
      payload: AgentHandoffConfirmRequest,
      idempotencyKey: string,
    ) {
      return request<AgentRunResponse>(`/tasks/${taskId}/agent-runs`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    listAgentRuns(taskId: string, signal?: AbortSignal) {
      return request<AgentRunResponse[]>(`/tasks/${taskId}/agent-runs`, { signal });
    },

    getAgentRun(runId: string, signal?: AbortSignal) {
      return request<AgentRunResponse>(`/agent-runs/${runId}`, { signal });
    },

    /**
     * The latest run for each of the given tasks, keyed by task ID and sparse:
     * a task with no hand-off is absent from the answer.
     */
    listAgentRunSummaries(taskIds: string[], signal?: AbortSignal) {
      const query = taskIds
        .map((taskId) => `task_id=${encodeURIComponent(taskId)}`)
        .join("&");
      return request<Record<string, AgentRunSummaryResponse>>(
        `/agent-run-summaries?${query}`,
        { signal },
      );
    },

    replyToAgentRun(runId: string, payload: AgentReplyRequest, idempotencyKey: string) {
      return request<AgentRunResponse>(`/agent-runs/${runId}/reply`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: payload,
      });
    },

    /** Cancel carries no body: the run id in the path is the whole request. */
    cancelAgentRun(runId: string, idempotencyKey: string) {
      return request<AgentRunResponse>(`/agent-runs/${runId}/cancel`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
      });
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
