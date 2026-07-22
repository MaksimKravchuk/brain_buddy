import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi, type AuthUser } from "../../api/auth";
import { useAuthStore } from "../authStore";

// Controllable promise so tests can decide exactly when an in-flight
// authApi.me() call settles, relative to other store transitions --
// without relying on real timers or resolution-order luck.
function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("authStore", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "loading", epoch: 0 });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("hydrate sets authed when /me returns a user", async () => {
    vi.spyOn(authApi, "me").mockResolvedValue({ id: "u1", email: "a@b.c" });
    await useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.email).toBe("a@b.c");
  });

  it("hydrate sets anon when /me returns null", async () => {
    vi.spyOn(authApi, "me").mockResolvedValue(null);
    await useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("hydrate sets anon when /me throws", async () => {
    vi.spyOn(authApi, "me").mockRejectedValue(new Error("network down"));
    await useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().status).toBe("anon");
  });

  it("login stores the returned user", async () => {
    vi.spyOn(authApi, "login").mockResolvedValue({ id: "u1", email: "a@b.c" });
    await useAuthStore.getState().login({ email: "a@b.c", password: "x" });
    expect(useAuthStore.getState().status).toBe("authed");
  });

  it("logout clears the session even when the API call fails", async () => {
    useAuthStore.setState({
      user: { id: "u1", email: "a@b.c" },
      status: "authed"
    });
    vi.spyOn(authApi, "logout").mockRejectedValue(new Error("boom"));
    await useAuthStore.getState().logout();
    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("signup stores the returned user and marks the session authed", async () => {
    vi.spyOn(authApi, "signup").mockResolvedValue({ id: "u2", email: "new@example.com" });
    await useAuthStore.getState().signup({ email: "new@example.com", password: "secret", invite_code: "invite" });
    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.email).toBe("new@example.com");
  });

  it("clearSession resets to anon without a network call", () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    useAuthStore.getState().clearSession();
    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("advances the auth epoch on every session transition, even A -> anon -> the same A", async () => {
    // The epoch must be a strictly monotonic transition counter, independent
    // of whether the resolved owner identity happens to repeat. Owner
    // equality alone cannot distinguish a fresh A session from an earlier one
    // that also happened to be A, once an anon gap separates them.
    vi.spyOn(authApi, "login").mockResolvedValue({ id: "u1", email: "a@b.c" });

    const epoch0 = useAuthStore.getState().epoch;
    await useAuthStore.getState().login({ email: "a@b.c", password: "x" });
    const epochAfterFirstLogin = useAuthStore.getState().epoch;
    expect(epochAfterFirstLogin).toBeGreaterThan(epoch0);

    useAuthStore.getState().clearSession();
    const epochAfterClear = useAuthStore.getState().epoch;
    expect(epochAfterClear).toBeGreaterThan(epochAfterFirstLogin);
    expect(useAuthStore.getState().user).toBeNull();

    await useAuthStore.getState().login({ email: "a@b.c", password: "x" });
    const epochAfterSecondLogin = useAuthStore.getState().epoch;

    // Same resolved user both times, but this must be recognized as a
    // distinct session from the first login.
    expect(useAuthStore.getState().user?.id).toBe("u1");
    expect(epochAfterSecondLogin).toBeGreaterThan(epochAfterClear);
    expect(epochAfterSecondLogin).toBeGreaterThan(epochAfterFirstLogin);
  });

  it("a stale startup hydrate that resolves null after a later login does not overwrite the login", async () => {
    const meDeferred = createDeferred<AuthUser | null>();
    vi.spyOn(authApi, "me").mockReturnValue(meDeferred.promise);
    vi.spyOn(authApi, "login").mockResolvedValue({ id: "u1", email: "login@b.c" });

    const hydratePromise = useAuthStore.getState().hydrate();
    // A later, faster login wins the race while the startup hydrate is still pending.
    await useAuthStore.getState().login({ email: "login@b.c", password: "x" });
    const epochAfterLogin = useAuthStore.getState().epoch;

    meDeferred.resolve(null);
    await hydratePromise;

    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.id).toBe("u1");
    expect(useAuthStore.getState().epoch).toBe(epochAfterLogin);
  });

  it("a stale startup hydrate that rejects after a later login does not overwrite the login", async () => {
    const meDeferred = createDeferred<AuthUser | null>();
    vi.spyOn(authApi, "me").mockReturnValue(meDeferred.promise);
    vi.spyOn(authApi, "login").mockResolvedValue({ id: "u1", email: "login@b.c" });

    const hydratePromise = useAuthStore.getState().hydrate();
    await useAuthStore.getState().login({ email: "login@b.c", password: "x" });
    const epochAfterLogin = useAuthStore.getState().epoch;

    meDeferred.reject(new Error("network down"));
    await hydratePromise;

    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.id).toBe("u1");
    expect(useAuthStore.getState().epoch).toBe(epochAfterLogin);
  });

  it("an older concurrent hydrate response cannot overwrite a later concurrent hydrate's result", async () => {
    // React StrictMode-style double invocation: two overlapping hydrate()
    // calls in flight at once. The second call is the "current" one; the
    // first must never be allowed to win, even if it settles last.
    const firstDeferred = createDeferred<AuthUser | null>();
    const secondDeferred = createDeferred<AuthUser | null>();
    const meMock = vi.spyOn(authApi, "me");
    meMock.mockReturnValueOnce(firstDeferred.promise);
    meMock.mockReturnValueOnce(secondDeferred.promise);

    const firstHydrate = useAuthStore.getState().hydrate();
    const secondHydrate = useAuthStore.getState().hydrate();

    // The later (current) hydrate settles first with its own identity.
    secondDeferred.resolve({ id: "u-second", email: "second@b.c" });
    await secondHydrate;
    const epochAfterSecond = useAuthStore.getState().epoch;
    expect(useAuthStore.getState().user?.id).toBe("u-second");

    // The stale, earlier hydrate settles afterward with a different identity.
    firstDeferred.resolve({ id: "u-first", email: "first@b.c" });
    await firstHydrate;

    expect(useAuthStore.getState().user?.id).toBe("u-second");
    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().epoch).toBe(epochAfterSecond);
  });

  it("the later concurrent hydrate call still publishes when it is the one that settles last", async () => {
    const firstDeferred = createDeferred<AuthUser | null>();
    const secondDeferred = createDeferred<AuthUser | null>();
    const meMock = vi.spyOn(authApi, "me");
    meMock.mockReturnValueOnce(firstDeferred.promise);
    meMock.mockReturnValueOnce(secondDeferred.promise);

    const firstHydrate = useAuthStore.getState().hydrate();
    const secondHydrate = useAuthStore.getState().hydrate();

    // The stale, earlier hydrate settles first and must not publish.
    firstDeferred.resolve({ id: "u-first", email: "first@b.c" });
    await firstHydrate;
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().status).toBe("loading");

    // The later (current) hydrate settles last and must win.
    secondDeferred.resolve({ id: "u-second", email: "second@b.c" });
    await secondHydrate;

    expect(useAuthStore.getState().user?.id).toBe("u-second");
    expect(useAuthStore.getState().status).toBe("authed");
  });
});
