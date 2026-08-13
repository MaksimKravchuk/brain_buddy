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
  AgentConnectionUpdateRequest,
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
import { IntentSnapshotRegistry, requireIdempotencyKey } from "@/utils/intentSnapshot";

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
  /** Captures the account/session scope at request start. */
  getSessionEpoch?: (() => number) | null;
  /** Called on a 401 with the exact scope that issued the request. */
  onUnauthorized?: ((requestEpoch: number | undefined) => void) | null;
  /** Every successful response's `Date` header. Feature 006 persists it so
   *  FR-018's retention bound can be cross-checked against a clock the person
   *  cannot set — without it the bound trusts the device alone, which is the
   *  hole the adversarial review opened. */
  onServerTime?: ((date: string, monotonicTimeMs: number, requestEpoch: number | undefined) => void) | null;
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
  requestEpoch?: number;
  baseUrl?: string;
};

const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * 4xx statuses that still leave the outcome unknown.
 *
 * A request timeout can fire after the server read and executed the body, and a
 * throttle can come from an edge that has already forwarded it. Neither is
 * evidence that nothing was sent (FR-006), so both hold the relay key on the
 * same terms as a dropped connection or a 5xx.
 */
const AMBIGUOUS_STATUSES: ReadonlySet<number> = new Set([408, 429]);

/** True only when the server's answer proves the command did not take effect. */
export function isDefinitiveMutationFailure(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status >= 400 &&
    error.status < 500 &&
    !AMBIGUOUS_STATUSES.has(error.status)
  );
}

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
  const {
    getBaseUrl,
    getSessionEpoch,
    onUnauthorized,
    onServerTime,
    fetchImpl,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  } = options;
  // Preserve the global binding: calling an unbound fetch reference throws in
  // some environments (illegal invocation).
  const doFetch: typeof fetch = fetchImpl ?? ((...args) => fetch(...args));
  const relayIntents = new IntentSnapshotRegistry();

  async function request<T>(path: string, opts: JsonRequestOptions = {}): Promise<T> {
    const requestEpoch = opts.requestEpoch ?? getSessionEpoch?.();
    const { body, headers: extraHeaders, method = "GET", signal } = opts;
    const baseUrl = opts.baseUrl ?? normalizeBaseUrl(getBaseUrl());
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

    const response = await doFetch(`${baseUrl}${path}`, {
      method,
      headers,
      body: requestBody,
      credentials: "include",
      signal: combined,
    });

    if (response.status === 401 && onUnauthorized) {
      onUnauthorized(requestEpoch);
    }

    if (onServerTime && response.ok) {
      const served = response.headers.get("Date");
      if (served) {
        onServerTime(served, performance.now(), requestEpoch);
      }
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

  async function relayMutation<T>(
    operation: string,
    path: string,
    body: unknown,
    idempotencyKey: string,
    method = "POST",
  ): Promise<T> {
    const key = requireIdempotencyKey(operation, idempotencyKey);
    const requestEpoch = getSessionEpoch?.();
    const baseUrl = normalizeBaseUrl(getBaseUrl());
    relayIntents.hold(operation, key, {
      method,
      baseUrl,
      requestEpoch,
      path,
      ...(body === undefined ? {} : { body }),
    });
    try {
      const result = await request<T>(path, {
        method,
        headers: { "Idempotency-Key": key },
        requestEpoch,
        baseUrl,
        ...(body === undefined ? {} : { body }),
      });
      relayIntents.settle(key);
      return result;
    } catch (error) {
      if (isDefinitiveMutationFailure(error)) {
        relayIntents.settle(key);
      } else {
        relayIntents.preserve(key);
      }
      throw error;
    }
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
      return relayMutation<AgentConnectionCreatedResponse>(
        "createAgentConnection",
        "/agent-connections",
        payload,
        idempotencyKey,
      );
    },

    getAgentConnection(connectionId: string, signal?: AbortSignal) {
      return request<AgentConnectionResponse>(`/agent-connections/${connectionId}`, { signal });
    },

    updateAgentConnection(
      connectionId: string,
      payload: AgentConnectionUpdateRequest,
      idempotencyKey: string,
    ) {
      return relayMutation<AgentConnectionResponse>(
        "updateAgentConnection",
        `/agent-connections/${connectionId}`,
        payload,
        idempotencyKey,
        "PUT",
      );
    },

    /**
     * Deliberately not a `relayMutation`: the backend's `test_agent_connection`
     * accepts no `Idempotency-Key` and passes none to the service. Holding a
     * relay key here would block the user's retry on a duplicate the server
     * never deduplicates.
     */
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
      return relayMutation<AgentConnectionResponse>(
        "rotateAgentCredential",
        `/agent-connections/${connectionId}/credential`,
        payload,
        idempotencyKey,
      );
    },

    rotateAgentSigningSecret(
      connectionId: string,
      payload: AgentConnectionRotateSigningSecretRequest,
      idempotencyKey: string,
    ) {
      return relayMutation<AgentConnectionSigningSecretResponse>(
        "rotateAgentSigningSecret",
        `/agent-connections/${connectionId}/signing-secret`,
        payload,
        idempotencyKey,
      );
    },

    disconnectAgentConnection(
      connectionId: string,
      payload: AgentConnectionDisconnectRequest,
      idempotencyKey: string,
    ) {
      return relayMutation<AgentConnectionResponse>(
        "disconnectAgentConnection",
        `/agent-connections/${connectionId}/disconnect`,
        payload,
        idempotencyKey,
      );
    },

    /**
     * Reserves and returns the manifest to review. Nothing leaves yet, so like
     * `testAgentConnection` this is not a `relayMutation`: `preview_agent_handoff`
     * takes no `Idempotency-Key`. The key enters at `confirmAgentHandoff`,
     * derived from the token this call mints.
     */
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
      return relayMutation<AgentRunResponse>(
        "confirmAgentHandoff",
        `/tasks/${taskId}/agent-runs`,
        payload,
        idempotencyKey,
      );
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
      return relayMutation<AgentRunResponse>(
        "replyToAgentRun",
        `/agent-runs/${runId}/reply`,
        payload,
        idempotencyKey,
      );
    },

    /** Cancel carries no body: the run id in the path is the whole request. */
    cancelAgentRun(runId: string, idempotencyKey: string) {
      return relayMutation<AgentRunResponse>(
        "cancelAgentRun",
        `/agent-runs/${runId}/cancel`,
        undefined,
        idempotencyKey,
      );
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
