import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi } from "../auth";
import { ApiError } from "../client";

function response(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Request failed" : "OK",
    headers: { "Content-Type": "application/json", ...headers }
  });
}

describe("authApi", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("submits signup and login credentials as same-origin JSON requests", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "user-1", email: "person@example.com" })));

    await authApi.signup({ email: "person@example.com", password: "secure-password", invite_code: "invite" });
    await authApi.login({ email: "person@example.com", password: "secure-password" });

    const [signupUrl, signupInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(signupUrl).toBe("/api/auth/signup");
    expect(signupInit).toMatchObject({ credentials: "include", method: "POST" });
    expect(signupInit.body).toBe(
      JSON.stringify({ email: "person@example.com", password: "secure-password", invite_code: "invite" })
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/auth/login");
  });

  it("accepts logout responses without content", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await expect(authApi.logout()).resolves.toBeUndefined();
  });

  // The session cookie is set and cleared by these three calls alone, so their
  // verb and path are the contract: a logout sent as a GET leaves the user
  // signed in on the server while the UI says otherwise.
  it.each([
    ["login", () => authApi.login({ email: "a@b.c", password: "secret" }), "/api/auth/login", "POST"],
    ["logout", () => authApi.logout(), "/api/auth/logout", "POST"],
    ["me", () => authApi.me(), "/api/auth/me", "GET"]
  ])("sends %s to its own endpoint with the right verb", async (_name, call, url, method) => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "user-1", email: "a@b.c" })));

    await call();

    const [requestUrl, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toBe(url);
    expect(init.method).toBe(method);
    expect(init.credentials).toBe("include");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
  });

  it("sends the credentials it was given rather than an empty envelope", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(response({ id: "user-1", email: "a@b.c" })));

    await authApi.login({ email: "person@example.com", password: "secure-password" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      email: "person@example.com",
      password: "secure-password"
    });
  });

  it("returns an anonymous session when the profile endpoint responds with unauthorized", async () => {
    fetchMock.mockResolvedValue(response({ detail: "expired" }, 401));

    await expect(authApi.me()).resolves.toBeNull();
  });

  it("keeps other profile errors visible to callers with their correlation ID", async () => {
    fetchMock.mockResolvedValue(response({ detail: "unavailable" }, 503, { "X-Correlation-ID": "corr-2" }));

    await expect(authApi.me()).rejects.toMatchObject({
      status: 503,
      correlationId: "corr-2",
      payload: { detail: "unavailable" }
    } satisfies Partial<ApiError>);
  });
});
