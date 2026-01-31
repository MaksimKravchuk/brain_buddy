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

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";
const API_KEY_HEADER = import.meta.env.VITE_API_KEY_HEADER ?? "X-API-Key";
const API_KEY_STORAGE_KEY = "brainbuddy:api-key";
const SESSION_OWNER_ID = import.meta.env.VITE_OWNER_ID ?? import.meta.env.VITE_API_OWNER_ID ?? null;
const hasStorage =
  typeof window !== "undefined" &&
  typeof window.localStorage !== "undefined" &&
  typeof window.localStorage.getItem === "function" &&
  typeof window.localStorage.setItem === "function";

let cachedApiKey: string | null = import.meta.env.VITE_API_KEY ?? null;
if (hasStorage) {
  const stored = window.localStorage.getItem(API_KEY_STORAGE_KEY);
  if (stored) {
    cachedApiKey = stored;
  }
}

type JsonRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  signal?: AbortSignal;
};

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

export function setApiKey(apiKey: string | null) {
  cachedApiKey = apiKey;
  if (hasStorage) {
    if (apiKey) {
      window.localStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
    } else {
      window.localStorage.removeItem(API_KEY_STORAGE_KEY);
    }
  }
}

export function getApiKey(): string | null {
  return cachedApiKey;
}

export function getOwnerId(): string | null {
  return SESSION_OWNER_ID ?? null;
}

export function hasApiKey(): boolean {
  return Boolean(cachedApiKey);
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
  const apiKey = getApiKey();
  if (apiKey && !headers.has(API_KEY_HEADER)) {
    headers.set(API_KEY_HEADER, apiKey);
  }
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

  const response = await fetch(buildUrl(path), {
    ...rest,
    method,
    headers,
    body: requestBody
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("Content-Type");
  const isJson = contentType && contentType.includes("application/json");
  const data = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const correlationId = response.headers.get("X-Correlation-ID") ?? undefined;
    throw new ApiError(response.statusText || "Request failed", response.status, data, correlationId);
  }

  return data as T;
}

export const apiClient = {
  listTrees(signal?: AbortSignal) {
    return request<TreeListItem[]>("/trees", { signal });
  },

  getTree(treeId: string, signal?: AbortSignal) {
    return request<TreeDetailResponse>(`/trees/${treeId}`, { signal });
  },

  createTree(payload: TreeCreateRequest) {
    const ownerId = getOwnerId();
    const body = ownerId
      ? {
          ...payload,
          owner_id: payload.owner_id ?? ownerId,
          metadata: payload.metadata
            ? { ...payload.metadata, owner_id: payload.metadata.owner_id ?? ownerId }
            : undefined
        }
      : payload;
    return request<TreeDetailResponse>("/trees", { method: "POST", body });
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
