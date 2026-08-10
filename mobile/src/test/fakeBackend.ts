/**
 * An in-memory stand-in for the Brain Buddy API, installed over `global.fetch`.
 *
 * The api client resolves `fetch` lazily, so replacing the global is enough to
 * drive the real client, the real React Query hooks and the real screens
 * against it. Nothing under `src/` is mocked: a test that fails here fails
 * because the product code is wrong, not because a stub drifted.
 *
 * Routes answer only what the app actually calls. An unrouted request is a
 * loud 500 naming the method and path rather than a silent empty body.
 */

import type {
  MeResponse,
  ProjectResponse,
  TagResponse,
  TaskCounts,
  TaskResponse,
} from "@/api/types";

export interface RecordedCall {
  method: string;
  path: string;
  /** Query string without the leading `?`, or "" when there is none. */
  query: string;
  headers: Record<string, string>;
  body: unknown;
}

export type RouteHandler = (call: RecordedCall) => unknown | Promise<unknown>;

export interface FakeBackend {
  calls: RecordedCall[];
  /** Calls matching `METHOD /path` (path without query string). */
  callsTo(method: string, path: string): RecordedCall[];
  /** Replace or add a route after installation. */
  route(key: string, handler: RouteHandler): void;
  restore(): void;
}

/** A response the fake backend should return as a non-2xx. */
export class FakeHttpError {
  constructor(
    readonly status: number,
    readonly payload: unknown = { message: "Request failed" },
    readonly correlationId: string | null = null,
  ) {}
}

export function makeTask(overrides: Partial<TaskResponse> = {}): TaskResponse {
  return {
    id: "task-1",
    title: "Call the notary",
    details: null,
    state: "next",
    project_id: null,
    tag_ids: [],
    due_date: null,
    priority: "none",
    waiting_for: null,
    waiting_since: null,
    order_key: 1,
    source_capture_ids: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    cancelled_at: null,
    revision: 1,
    ...overrides,
  };
}

export function makeProject(overrides: Partial<ProjectResponse> = {}): ProjectResponse {
  return {
    id: "project-1",
    name: "Wedding",
    color: "#0EA5E9",
    state: "active",
    revision: 1,
    open_task_count: 2,
    ...overrides,
  };
}

export function makeTag(overrides: Partial<TagResponse> = {}): TagResponse {
  return {
    id: "tag-1",
    name: "errand",
    state: "active",
    revision: 1,
    open_task_count: 1,
    ...overrides,
  };
}

export function makeMe(overrides: Partial<MeResponse> = {}): MeResponse {
  return {
    id: "user-1",
    email: "dana.reid@example.test",
    feature_flags: {},
    ...overrides,
  };
}

export function makeCounts(overrides: Partial<TaskCounts> = {}): TaskCounts {
  return { inbox: 0, next: 0, waiting: 0, someday: 0, ...overrides };
}

/** A task page response over the given items, with counts derived from them. */
export function makeTaskPage(items: TaskResponse[], overrides: Partial<TaskCounts> = {}) {
  const counts = makeCounts(overrides);
  for (const task of items) {
    if (task.state in counts) {
      counts[task.state as keyof TaskCounts] += 1;
    }
  }
  return { items, next_cursor: null, has_more: false, counts_by_state: counts };
}

function headersToObject(init: RequestInit | undefined): Record<string, string> {
  const raw = init?.headers;
  if (!raw) {
    return {};
  }
  if (raw instanceof Headers) {
    return Object.fromEntries(raw.entries());
  }
  if (Array.isArray(raw)) {
    return Object.fromEntries(raw);
  }
  return { ...(raw as Record<string, string>) };
}

function parseBody(init: RequestInit | undefined): unknown {
  const body = init?.body;
  if (typeof body !== "string") {
    return body ?? null;
  }
  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

/**
 * Install the fake backend for the duration of a test.
 *
 * `routes` is keyed by `"METHOD /path"`; a handler's return value is sent as
 * JSON, `undefined` becomes a 204, and a thrown/returned {@link FakeHttpError}
 * becomes that status.
 */
export function installFakeBackend(routes: Record<string, RouteHandler>): FakeBackend {
  const table = new Map(Object.entries(routes));
  const calls: RecordedCall[] = [];
  const original = global.fetch;

  global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const path = url.pathname.replace(/^\/api/, "");
    const call: RecordedCall = {
      method: (init?.method ?? "GET").toUpperCase(),
      path,
      query: url.search.replace(/^\?/, ""),
      headers: headersToObject(init),
      body: parseBody(init),
    };
    calls.push(call);

    const handler = table.get(`${call.method} ${path}`);
    if (!handler) {
      return jsonResponse({ message: `No fake route for ${call.method} ${path}` }, 500);
    }

    let result: unknown;
    try {
      // Awaited, so a handler may return a promise — including one that never
      // settles, which is how a test holds a request in flight.
      result = await handler(call);
    } catch (error) {
      if (error instanceof FakeHttpError) {
        return errorResponse(error);
      }
      throw error;
    }
    if (result instanceof FakeHttpError) {
      return errorResponse(result);
    }
    if (result === undefined) {
      return new Response(null, { status: 204 });
    }
    return jsonResponse(result, 200);
  }) as typeof fetch;

  return {
    calls,
    callsTo(method, path) {
      return calls.filter((call) => call.method === method.toUpperCase() && call.path === path);
    },
    route(key, handler) {
      table.set(key, handler);
    },
    restore() {
      global.fetch = original;
    },
  };
}

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function errorResponse(error: FakeHttpError): Response {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (error.correlationId) {
    headers["X-Correlation-ID"] = error.correlationId;
  }
  return new Response(JSON.stringify(error.payload), { status: error.status, headers });
}
