import { ApiError } from "./client";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

export type AuthUser = {
  id: string;
  email: string;
};

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
