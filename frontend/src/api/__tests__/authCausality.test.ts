import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi, type AuthUser } from "../auth";
import { apiClient, setAuthCausalityProvider, setUnauthorizedHandler } from "../client";
import { getAuthCausality, useAuthStore } from "../../stores/authStore";

// Controllable promises so tests can decide exactly when a held fetch (or a
// held authApi call) settles, relative to other store transitions -- without
// relying on real timers or resolution-order luck.
function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function unauthorizedResponse(): Response {
  return new Response(JSON.stringify({ detail: "expired" }), {
    status: 401,
    statusText: "Unauthorized",
    headers: { "Content-Type": "application/json" }
  });
}

// Real client.ts + real authStore.ts wired together the same way App.tsx
// wires them, rather than mocking either side, so these tests exercise the
// actual cross-module fencing contract instead of a stand-in for it.
describe("auth causality: API client 401 handling vs. real authStore operations", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    useAuthStore.setState({ user: { id: "u0", email: "old@b.c" }, status: "authed", epoch: 0 });
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    setUnauthorizedHandler(() => useAuthStore.getState().clearSession());
    setAuthCausalityProvider(getAuthCausality);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    setUnauthorizedHandler(null);
    setAuthCausalityProvider(null);
    useAuthStore.setState({ user: null, status: "loading", epoch: 0 });
  });

  it("a held request's stale 401 does not discard a login that began (but hadn't yet published) while the request was in flight", async () => {
    let resolveFetch!: (value: Response) => void;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        })
    );

    // A request begins under the old session.
    const pending = apiClient.listTrees();

    // A later login begins while that request is still held -- this must
    // advance whatever causal context the client fences on, well before
    // login publishes (and therefore before epoch itself changes).
    const loginDeferred = createDeferred<AuthUser>();
    vi.spyOn(authApi, "login").mockReturnValue(loginDeferred.promise);
    const loginPromise = useAuthStore.getState().login({ email: "new@b.c", password: "x" });

    // Only now does the held request's stale 401 arrive.
    resolveFetch(unauthorizedResponse());
    await expect(pending).rejects.toMatchObject({ status: 401 });

    loginDeferred.resolve({ id: "u1", email: "new@b.c" });
    await loginPromise;

    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.id).toBe("u1");
  });

  it("a held request's stale 401 does not discard a signup that began (but hadn't yet published) while the request was in flight", async () => {
    let resolveFetch!: (value: Response) => void;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        })
    );

    const pending = apiClient.listTrees();

    const signupDeferred = createDeferred<AuthUser>();
    vi.spyOn(authApi, "signup").mockReturnValue(signupDeferred.promise);
    const signupPromise = useAuthStore
      .getState()
      .signup({ email: "new@b.c", password: "secret", invite_code: "good" });

    resolveFetch(unauthorizedResponse());
    await expect(pending).rejects.toMatchObject({ status: 401 });

    signupDeferred.resolve({ id: "u2", email: "new@b.c" });
    await signupPromise;

    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.id).toBe("u2");
  });

  it("still clears the session for a 401 issued while nothing newer has started", async () => {
    fetchMock.mockResolvedValue(unauthorizedResponse());

    await expect(apiClient.listTrees()).rejects.toMatchObject({ status: 401 });

    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
  });
});
