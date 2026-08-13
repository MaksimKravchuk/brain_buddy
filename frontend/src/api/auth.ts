import { ApiError } from "./client";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

export type AuthUser = {
  id: string;
  email: string;
  display_name?: string | null;
  // True only on a login response that cancelled a pending account deletion,
  // so the client can tell the user their account was kept.
  deletion_cancelled?: boolean;
  // Server-driven rollout flags from GET /api/auth/me (e.g. `voice_brain_dump`,
  // `delivery_canary`). Absent on older backends that predate the field, so
  // callers must fail closed and treat a missing flag as OFF.
  feature_flags?: Record<string, boolean>;
};

// Reads a server rollout flag, defaulting to OFF (fail-closed) when the flag —
// or the whole `feature_flags` map — is absent, so a gated capability stays
// hidden until the backend explicitly enables it.
export function hasFeatureFlag(user: AuthUser | null, flag: string): boolean {
  return user?.feature_flags?.[flag] === true;
}

export type SignupPayload = {
  email: string;
  password: string;
  invite_code: string;
};

export type LoginPayload = {
  email: string;
  password: string;
};

function buildUrl(path: string): string {
  return `${API_BASE_URL.replace(/\/$/, "")}${path}`;
}

async function authRequest<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(buildUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {})
    },
    credentials: "include"
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

export const authApi = {
  signup(payload: SignupPayload) {
    return authRequest<AuthUser>("/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },
  login(payload: LoginPayload) {
    return authRequest<AuthUser>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },
  logout() {
    return authRequest<void>("/auth/logout", { method: "POST" });
  },
  async me(): Promise<AuthUser | null> {
    try {
      return await authRequest<AuthUser>("/auth/me", { method: "GET" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        return null;
      }
      throw err;
    }
  }
};
