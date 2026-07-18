import {
  AiFeedbackRequest,
  AiFeedbackResponse,
  NodeCreateRequest,
  NodeResponse,
  NodeUpdateRequest,
  RelationCreateRequest,
  RelationResponse,
  RelationUpdateRequest,
  TreeCreateRequest,
  TreeDetailResponse,
  TreeExportResponse,
  TreeImportPayload,
  TreeListItem,
  TreeUpdateRequest,
  ValidationHistoryResponse,
  ValidationRequest,
  ValidationResponse,
  VersionCreateRequest,
  VersionListItem
} from "./types";
import type {
  BrainDumpOperationResponse,
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

function normalizeRelationCreate(payload: RelationCreateRequest): RelationCreateRequest {
  const sourceNodeId =
    payload.source_node_id ?? payload.source_id ?? payload.from_id ?? null;
  const targetNodeId =
    payload.target_node_id ?? payload.target_id ?? payload.to_id ?? null;
  if (!sourceNodeId || !targetNodeId) {
    throw new Error("source_node_id and target_node_id are required for relations");
  }
  return {
    source_node_id: sourceNodeId,
    target_node_id: targetNodeId,
    kind: payload.kind ?? "why"
  };
}

function normalizeRelationUpdate(payload: RelationUpdateRequest): RelationUpdateRequest {
  const sourceNodeId = payload.source_node_id ?? payload.source_id ?? payload.from_id;
  const targetNodeId = payload.target_node_id ?? payload.target_id ?? payload.to_id;
  return {
    ...(sourceNodeId ? { source_node_id: sourceNodeId } : {}),
    ...(targetNodeId ? { target_node_id: targetNodeId } : {}),
    ...(payload.kind ? { kind: payload.kind } : {})
  };
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

async function request<T>(path: string, options: JsonRequestOptions = {}): Promise<T> {
  const { body, ...rest } = options;
  const headers = new Headers(rest.headers);
  const method = options.method ?? "GET";
  const hasBody = body !== undefined && body !== null;

  let requestBody: BodyInit | null | undefined = undefined;

  if (hasBody) {
    if (body instanceof FormData || body instanceof Blob || body instanceof ArrayBuffer) {
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
    sha256: string
  ) {
    return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/audio/${chunkNumber}`, {
      method: "PUT",
      headers: { "X-Content-SHA256": sha256 },
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
    payload: { title?: string; deleted?: boolean; expected_revision: number },
    idempotencyKey: string
  ) {
    return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/proposals/${proposalId}`, {
      method: "PATCH",
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload
    });
  },

  commandBrainDump(operationId: string, action: "pause" | "resume" | "finish" | "cancel" | "commit", expectedRevision: number, idempotencyKey: string) {
    return request<BrainDumpOperationResponse>(`/brain-dump-operations/${operationId}/${action}`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: { expected_revision: expectedRevision }
    });
  },

  listTrees(signal?: AbortSignal) {
    return request<TreeListItem[]>("/trees", { signal });
  },

  getTree(treeId: string, signal?: AbortSignal) {
    return request<TreeDetailResponse>(`/trees/${treeId}`, { signal });
  },

  createTree(payload: TreeCreateRequest) {
    return request<TreeDetailResponse>("/trees", { method: "POST", body: payload });
  },

  updateTree(treeId: string, payload: TreeUpdateRequest) {
    return request<TreeDetailResponse>(`/trees/${treeId}`, { method: "PUT", body: payload });
  },

  deleteTree(treeId: string) {
    return request<void>(`/trees/${treeId}`, { method: "DELETE" });
  },

  createNode(treeId: string, payload: NodeCreateRequest) {
    const body: NodeCreateRequest = {
      highlight_state: "none",
      ...payload
    };
    return request<NodeResponse>(`/trees/${treeId}/nodes`, { method: "POST", body });
  },

  updateNode(treeId: string, nodeId: string, payload: NodeUpdateRequest) {
    return request<NodeResponse>(`/trees/${treeId}/nodes/${nodeId}`, { method: "PATCH", body: payload });
  },

  deleteNode(treeId: string, nodeId: string, cascade = false) {
    const query = cascade ? "?cascade=true" : "";
    return request<void>(`/trees/${treeId}/nodes/${nodeId}${query}`, { method: "DELETE" });
  },

  createRelation(treeId: string, payload: RelationCreateRequest) {
    const body = normalizeRelationCreate(payload);
    return request<RelationResponse>(`/trees/${treeId}/relations`, { method: "POST", body });
  },

  updateRelation(treeId: string, relationId: string, payload: RelationUpdateRequest) {
    const body = normalizeRelationUpdate(payload);
    return request<RelationResponse>(`/trees/${treeId}/relations/${relationId}`, {
      method: "PATCH",
      body
    });
  },

  deleteRelation(treeId: string, relationId: string) {
    return request<void>(`/trees/${treeId}/relations/${relationId}`, { method: "DELETE" });
  },

  createVersion(treeId: string, payload: VersionCreateRequest) {
    return request<VersionListItem>(`/trees/${treeId}/versions`, { method: "POST", body: payload });
  },

  listVersions(treeId: string, signal?: AbortSignal) {
    return request<VersionListItem[]>(`/trees/${treeId}/versions`, { signal });
  },

  restoreVersion(treeId: string, versionId: string) {
    return request<TreeDetailResponse>(`/trees/${treeId}/versions/${versionId}/restore`, { method: "POST" });
  },

  deleteVersion(treeId: string, versionId: string) {
    return request<void>(`/trees/${treeId}/versions/${versionId}`, { method: "DELETE" });
  },

  exportTree(treeId: string) {
    return request<TreeExportResponse>(`/trees/${treeId}/export`, { method: "POST" });
  },

  aiFeedback(treeId: string, payload: AiFeedbackRequest) {
    return request<AiFeedbackResponse>(`/trees/${treeId}/ai-feedback`, { method: "POST", body: payload });
  },

  importTree(tree: TreeImportPayload) {
    return request<TreeDetailResponse>("/trees/import", { method: "POST", body: { tree } });
  },

  triggerValidation(treeId: string, nodeId: string, payload: ValidationRequest) {
    return request<ValidationResponse>(`/trees/${treeId}/validate/${nodeId}`, { method: "POST", body: payload });
  },

  getValidationHistory(treeId: string, nodeId: string, signal?: AbortSignal) {
    return request<ValidationHistoryResponse>(`/trees/${treeId}/nodes/${nodeId}/validation-history`, { signal });
  }
};
