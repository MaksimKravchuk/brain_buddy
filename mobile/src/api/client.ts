import Constants from "expo-constants";

import type { Project, SessionCredential, Tag, Task, TaskList, TaskState, User } from "./types";
import type { CreateTaskInput } from "./taskCreate";

export class MobileApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly correlationId?: string,
    public readonly retryable = false,
  ) {
    super("The request could not be completed.");
  }
}

type CredentialProvider = () => Promise<string | null>;

type RequestOptions = { method?: "GET" | "POST"; body?: unknown; idempotencyKey?: string; token?: string };

export class MobileApiClient {
  constructor(
    private readonly origin: string,
    private readonly credential: CredentialProvider,
    private readonly onUnauthorized: () => Promise<void>,
  ) {}

  async session(email: string, password: string): Promise<SessionCredential> {
    return this.request<SessionCredential>("/auth/mobile/sessions", { method: "POST", body: { email, password } });
  }

  async me(): Promise<User> { return this.request<User>("/auth/me"); }
  async tasks(state: Exclude<TaskState, "completed" | "cancelled">, cursor?: string): Promise<TaskList> {
    const query = new URLSearchParams({ state, ...(cursor ? { cursor } : {}) });
    return this.request<TaskList>(`/tasks?${query.toString()}`);
  }
  async task(taskId: string): Promise<Task> { return this.request<Task>(`/tasks/${encodeURIComponent(taskId)}`); }
  async createTask(body: CreateTaskInput): Promise<Task> {
    return this.request<Task>("/tasks", { method: "POST", body, idempotencyKey: crypto.randomUUID() });
  }
  async projects(): Promise<Project[]> { return this.request<Project[]>("/projects"); }
  async tags(): Promise<Tag[]> { return this.request<Tag[]>("/tags"); }
  async transition(taskId: string, body: { action: "complete" | "reopen"; expected_revision: number; to_state?: "inbox" | "next" | "waiting" | "someday" }): Promise<Task> {
    return this.request<Task>(`/tasks/${encodeURIComponent(taskId)}/transitions`, { method: "POST", body, idempotencyKey: crypto.randomUUID() });
  }
  async logout(token?: string): Promise<void> { await this.request<void>("/auth/logout", { method: "POST", token }); }

  private async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const token = options.token ?? await this.credential();
    const response = await fetch(`${this.origin}${path}`, {
      method: options.method ?? "GET",
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {}),
      },
      ...(options.body ? { body: JSON.stringify(options.body) } : {}),
    });
    if (!response.ok) {
      const error = new MobileApiError(response.status, response.headers.get("X-Correlation-ID") ?? undefined, response.status >= 500);
      if (response.status === 401) await this.onUnauthorized();
      throw error;
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }
}

export function publicApiOrigin(): string {
  const origin = Constants.expoConfig?.extra?.apiOrigin;
  if (typeof origin !== "string" || !origin.startsWith("http")) throw new Error("A public API origin is required.");
  return origin.replace(/\/$/, "");
}
