import { ApiError, notifyUnauthorized } from "./client";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";
export const CRT_READ_TIMEOUT_MS = 15_000;
export const CRT_MUTATION_TIMEOUT_MS = 30_000;

export type CrtTreeListItem = {
  id: string;
  name: string;
  updated_at: string;
  owner_id: string | null;
};

export type CrtTreeMetadata = {
  version: number;
  created_at: string;
  updated_at: string;
  layout: Record<string, unknown> | null;
  owner_id: string | null;
};

export type CrtNode = {
  id: string;
  label: string;
  type: "parent" | "child";
  position: { x: number; y: number };
  highlight_state: "none" | "cause_candidate" | "effect_spanning";
  relation_counts: { up_count: number; down_count: number };
};

export type CrtRelation = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  kind: "why";
  created_at: string;
};

export type CrtTreeResponse = {
  id: string;
  name: string;
  revision: number;
  schema_version: number;
  metadata: CrtTreeMetadata;
  nodes: CrtNode[];
  relations: CrtRelation[];
  owner_id: string | null;
};

export type CrtTreeImportPayload = {
  tree: CrtTreeResponse;
};

export type CrtTreeExportResponse = {
  tree: CrtTreeResponse;
};

export type CrtTreeCreatePayload = {
  name: string;
  schema_version?: number | null;
  owner_id?: string | null;
  metadata?: CrtTreeMetadata | null;
  nodes?: CrtNode[];
  relations?: CrtRelation[];
};

export type CrtTreeUpdatePayload = {
  expected_revision: number;
  schema_version: number;
  name: string;
  metadata: CrtTreeMetadata;
  nodes: CrtNode[];
  relations: CrtRelation[];
  owner_id: string | null;
};

export type CrtMutationOptions = {
  idempotencyKey?: string;
  signal?: AbortSignal;
};

export type CrtTreeDeleteOptions = CrtMutationOptions & {
  expectedRevision: number;
};

type CrtRequestOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  idempotencyKey?: string;
  requiresIdempotencyKey?: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
};

type ComposedSignal = {
  signal: AbortSignal;
  cleanup: () => void;
};

function buildUrl(path: string): string {
  return `${API_BASE_URL.replace(/\/$/, "")}${path}`;
}

function composeSignal(callerSignal: AbortSignal | undefined, timeoutMs: number): ComposedSignal {
  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => {
    controller.abort(new DOMException("CRT request timed out", "TimeoutError"));
  }, timeoutMs);
  const onCallerAbort = () => controller.abort(callerSignal?.reason);

  if (callerSignal) {
    if (callerSignal.aborted) {
      onCallerAbort();
    } else {
      callerSignal.addEventListener("abort", onCallerAbort, { once: true });
    }
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      globalThis.clearTimeout(timeoutId);
      callerSignal?.removeEventListener("abort", onCallerAbort);
    }
  };
}

async function request<T>(path: string, options: CrtRequestOptions = {}): Promise<T> {
  const correlationId = globalThis.crypto.randomUUID();
  const idempotencyKey = options.requiresIdempotencyKey
    ? options.idempotencyKey ?? globalThis.crypto.randomUUID()
    : undefined;
  const composed = composeSignal(options.signal, options.timeoutMs ?? CRT_READ_TIMEOUT_MS);
  const headers = new Headers({
    Accept: "application/json",
    "X-Correlation-ID": correlationId
  });
  const hasBody = options.body !== undefined && options.body !== null;

  if (idempotencyKey !== undefined) {
    headers.set("Idempotency-Key", idempotencyKey);
  }
  if (hasBody) {
    headers.set("Content-Type", "application/json");
  }

  try {
    const response = await fetch(buildUrl(path), {
      method: options.method ?? "GET",
      headers,
      credentials: "include",
      signal: composed.signal,
      body: hasBody ? JSON.stringify(options.body) : undefined
    });

    if (response.status === 401) {
      notifyUnauthorized();
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const contentType = response.headers.get("Content-Type");
    const data = contentType?.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      throw new ApiError(
        response.statusText || "Request failed",
        response.status,
        data,
        response.headers.get("X-Correlation-ID") ?? correlationId
      );
    }
    return data as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    const apiError = new ApiError(
      error instanceof Error
        ? error.message
        : typeof error === "object" && error !== null && "message" in error && typeof error.message === "string"
          ? error.message
          : "CRT request failed",
      0,
      error,
      correlationId
    );
    throw apiError;
  } finally {
    composed.cleanup();
  }
}

export const crtApi = {
  probeCrtExposure(signal?: AbortSignal) {
    return request<void>("/crt/exposure", { signal });
  },

  listCrtTrees(signal?: AbortSignal) {
    return request<CrtTreeListItem[]>("/crt/trees", { signal });
  },

  getCrtTree(treeId: string, signal?: AbortSignal) {
    return request<CrtTreeResponse>(`/crt/trees/${encodeURIComponent(treeId)}`, { signal });
  },

  createCrtTree(payload: CrtTreeCreatePayload, options: CrtMutationOptions = {}) {
    return request<CrtTreeResponse>("/crt/trees", {
      method: "POST",
      body: payload,
      idempotencyKey: options.idempotencyKey,
      requiresIdempotencyKey: true,
      signal: options.signal,
      timeoutMs: CRT_MUTATION_TIMEOUT_MS
    });
  },

  updateCrtTree(treeId: string, payload: CrtTreeUpdatePayload, options: CrtMutationOptions = {}) {
    return request<CrtTreeResponse>(`/crt/trees/${encodeURIComponent(treeId)}`, {
      method: "PUT",
      body: payload,
      idempotencyKey: options.idempotencyKey,
      requiresIdempotencyKey: true,
      signal: options.signal,
      timeoutMs: CRT_MUTATION_TIMEOUT_MS
    });
  },

  deleteCrtTree(treeId: string, options: CrtTreeDeleteOptions) {
    return request<void>(
      `/crt/trees/${encodeURIComponent(treeId)}?expected_revision=${encodeURIComponent(String(options.expectedRevision))}`,
      {
        method: "DELETE",
        idempotencyKey: options.idempotencyKey,
        requiresIdempotencyKey: true,
        signal: options.signal,
        timeoutMs: CRT_MUTATION_TIMEOUT_MS
      }
    );
  },

  importCrtTree(payload: CrtTreeImportPayload, options: CrtMutationOptions = {}) {
    return request<CrtTreeResponse>("/crt/trees/import", {
      method: "POST",
      body: payload,
      idempotencyKey: options.idempotencyKey,
      requiresIdempotencyKey: true,
      signal: options.signal,
      timeoutMs: CRT_MUTATION_TIMEOUT_MS
    });
  },

  exportCrtTree(treeId: string, signal?: AbortSignal) {
    return request<CrtTreeExportResponse>(`/crt/trees/${encodeURIComponent(treeId)}/export`, {
      method: "POST",
      signal,
      timeoutMs: CRT_READ_TIMEOUT_MS
    });
  }
};

export const crtClient = crtApi;
