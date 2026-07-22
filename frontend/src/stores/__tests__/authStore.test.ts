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

async function assertFailedSignupFencesEarlierHydrate(
  settleHydrate: (deferred: ReturnType<typeof createDeferred<AuthUser | null>>) => void
) {
  const meDeferred = createDeferred<AuthUser | null>();
  vi.spyOn(authApi, "me").mockReturnValue(meDeferred.promise);
  vi.spyOn(authApi, "signup").mockRejectedValue(new Error("invite code invalid"));

  const hydratePromise = useAuthStore.getState().hydrate();
  await expect(
    useAuthStore.getState().signup({ email: "new@b.c", password: "secret", invite_code: "bad" })
  ).rejects.toThrow();
  const epochAfterFailedSignup = useAuthStore.getState().epoch;
  expect(useAuthStore.getState().status).toBe("anon");

  settleHydrate(meDeferred);
  await hydratePromise;

  expect(useAuthStore.getState().status).toBe("anon");
  expect(useAuthStore.getState().status).not.toBe("loading");
  expect(useAuthStore.getState().user).toBeNull();
  expect(useAuthStore.getState().epoch).toBe(epochAfterFailedSignup);
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

  it("an old login that settles after a later clearSession does not resurrect the session", async () => {
    // The shared auth-operation generation must fence *every* operation
    // type against every other, not just hydrate-vs-hydrate. clearSession is
    // synchronous, so it advances the generation and publishes anon before
    // the earlier, still in-flight login ever gets a chance to settle.
    const loginDeferred = createDeferred<AuthUser>();
    vi.spyOn(authApi, "login").mockReturnValue(loginDeferred.promise);

    const loginPromise = useAuthStore.getState().login({ email: "a@b.c", password: "x" });

    useAuthStore.getState().clearSession();
    const epochAfterClear = useAuthStore.getState().epoch;
    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();

    loginDeferred.resolve({ id: "u1", email: "a@b.c" });
    await loginPromise;

    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().epoch).toBe(epochAfterClear);
  });

  it("clearSession aborts a pending login before its response can set a stale browser credential", async () => {
    let loginSignal: AbortSignal | undefined;
    vi.spyOn(authApi, "login").mockImplementation((_payload, signal) => {
      loginSignal = signal;
      return new Promise<AuthUser>((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(new Error("login aborted")), { once: true });
      });
    });

    const loginPromise = useAuthStore.getState().login({ email: "a@b.c", password: "x" });
    useAuthStore.getState().clearSession();

    expect(loginSignal?.aborted).toBe(true);
    await expect(loginPromise).rejects.toThrow("login aborted");
    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("an old logout that settles after a later login does not clobber the newer session", async () => {
    useAuthStore.setState({ user: { id: "u0", email: "old@b.c" }, status: "authed" });
    const logoutDeferred = createDeferred<void>();
    vi.spyOn(authApi, "logout").mockReturnValue(logoutDeferred.promise);
    vi.spyOn(authApi, "login").mockResolvedValue({ id: "u1", email: "new@b.c" });

    const logoutPromise = useAuthStore.getState().logout();

    // A later, faster login wins the race while the older logout call is
    // still waiting on its network response.
    await useAuthStore.getState().login({ email: "new@b.c", password: "x" });
    const epochAfterLogin = useAuthStore.getState().epoch;
    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.id).toBe("u1");

    logoutDeferred.resolve();
    await logoutPromise;

    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.id).toBe("u1");
    expect(useAuthStore.getState().epoch).toBe(epochAfterLogin);
  });

  it("a stale signup that resolves after a later clearSession does not resurrect the session", async () => {
    const signupDeferred = createDeferred<AuthUser>();
    vi.spyOn(authApi, "signup").mockReturnValue(signupDeferred.promise);

    const signupPromise = useAuthStore
      .getState()
      .signup({ email: "new@example.com", password: "secret", invite_code: "invite" });

    useAuthStore.getState().clearSession();
    const epochAfterClear = useAuthStore.getState().epoch;

    signupDeferred.resolve({ id: "u2", email: "new@example.com" });
    await signupPromise;

    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().epoch).toBe(epochAfterClear);
  });

  it("of two concurrent explicit auth operations, only the later one's result publishes", async () => {
    // Two calls with no synchronous transition between them -- e.g. a login
    // form double-submit racing an unrelated signup flow. Whichever call
    // started later must win regardless of which network response returns
    // first.
    const firstLoginDeferred = createDeferred<AuthUser>();
    const secondLoginDeferred = createDeferred<AuthUser>();
    const loginMock = vi.spyOn(authApi, "login");
    loginMock.mockReturnValueOnce(firstLoginDeferred.promise);
    loginMock.mockReturnValueOnce(secondLoginDeferred.promise);

    const firstLogin = useAuthStore.getState().login({ email: "first@b.c", password: "x" });
    const secondLogin = useAuthStore.getState().login({ email: "second@b.c", password: "x" });

    // The stale, earlier call settles first and must not publish.
    firstLoginDeferred.resolve({ id: "u-first", email: "first@b.c" });
    await firstLogin;
    expect(useAuthStore.getState().status).toBe("loading");
    expect(useAuthStore.getState().user).toBeNull();

    // The later (current) call settles last and must win.
    secondLoginDeferred.resolve({ id: "u-second", email: "second@b.c" });
    await secondLogin;

    expect(useAuthStore.getState().user?.id).toBe("u-second");
    expect(useAuthStore.getState().status).toBe("authed");
  });

  it("a stale hydrate outcome does not publish once a later explicit logout has already run", async () => {
    useAuthStore.setState({ user: { id: "u0", email: "old@b.c" }, status: "authed" });
    const meDeferred = createDeferred<AuthUser | null>();
    vi.spyOn(authApi, "me").mockReturnValue(meDeferred.promise);
    vi.spyOn(authApi, "logout").mockResolvedValue(undefined);

    const hydratePromise = useAuthStore.getState().hydrate();
    await useAuthStore.getState().logout();
    const epochAfterLogout = useAuthStore.getState().epoch;

    meDeferred.resolve({ id: "u0", email: "old@b.c" });
    await hydratePromise;

    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().epoch).toBe(epochAfterLogout);
  });

  describe("a failed current explicit login/signup settles the store truthfully", () => {
    it("login rejects for the caller but still settles the store out of loading", async () => {
      // LoginPage relies solely on the rejection to show an error message --
      // it never reads status/user for failure detection -- so the store
      // must both rethrow AND publish a truthful non-loading state.
      const failure = new Error("invalid credentials");
      vi.spyOn(authApi, "login").mockRejectedValue(failure);
      const epoch0 = useAuthStore.getState().epoch;

      await expect(useAuthStore.getState().login({ email: "a@b.c", password: "wrong" })).rejects.toBe(failure);

      expect(useAuthStore.getState().status).toBe("anon");
      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().epoch).toBeGreaterThan(epoch0);
    });

    it("signup rejects for the caller but still settles the store out of loading", async () => {
      const failure = new Error("invite code invalid");
      vi.spyOn(authApi, "signup").mockRejectedValue(failure);
      const epoch0 = useAuthStore.getState().epoch;

      await expect(
        useAuthStore.getState().signup({ email: "new@b.c", password: "secret", invite_code: "bad" })
      ).rejects.toBe(failure);

      expect(useAuthStore.getState().status).toBe("anon");
      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().epoch).toBeGreaterThan(epoch0);
    });

    it("a startup hydrate that later resolves with a user cannot overwrite an already-failed later login", async () => {
      const meDeferred = createDeferred<AuthUser | null>();
      vi.spyOn(authApi, "me").mockReturnValue(meDeferred.promise);
      vi.spyOn(authApi, "login").mockRejectedValue(new Error("invalid credentials"));

      const hydratePromise = useAuthStore.getState().hydrate();
      // The later login starts and fails while hydrate is still pending.
      await expect(useAuthStore.getState().login({ email: "a@b.c", password: "wrong" })).rejects.toThrow();
      const epochAfterFailedLogin = useAuthStore.getState().epoch;
      expect(useAuthStore.getState().status).toBe("anon");

      // The stale hydrate resolves afterward with a real user.
      meDeferred.resolve({ id: "u0", email: "old@b.c" });
      await hydratePromise;

      expect(useAuthStore.getState().status).toBe("anon");
      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().epoch).toBe(epochAfterFailedLogin);
    });

    it("a startup hydrate that later resolves null cannot overwrite an already-failed later login", async () => {
      const meDeferred = createDeferred<AuthUser | null>();
      vi.spyOn(authApi, "me").mockReturnValue(meDeferred.promise);
      vi.spyOn(authApi, "login").mockRejectedValue(new Error("invalid credentials"));

      const hydratePromise = useAuthStore.getState().hydrate();
      await expect(useAuthStore.getState().login({ email: "a@b.c", password: "wrong" })).rejects.toThrow();
      const epochAfterFailedLogin = useAuthStore.getState().epoch;

      meDeferred.resolve(null);
      await hydratePromise;

      expect(useAuthStore.getState().status).toBe("anon");
      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().epoch).toBe(epochAfterFailedLogin);
    });

    it("a startup hydrate that later resolves with a user cannot overwrite an already-failed later signup", async () => {
      await assertFailedSignupFencesEarlierHydrate((deferred) => {
        deferred.resolve({ id: "u0", email: "old@b.c" });
      });
    });

    it("a startup hydrate that later resolves null cannot overwrite an already-failed later signup", async () => {
      await assertFailedSignupFencesEarlierHydrate((deferred) => {
        deferred.resolve(null);
      });
    });

    it("a startup hydrate that later rejects cannot overwrite an already-failed later signup", async () => {
      await assertFailedSignupFencesEarlierHydrate((deferred) => {
        deferred.reject(new Error("network down"));
      });
    });

    it("a startup hydrate that later rejects cannot overwrite an already-failed later login, and never leaves the store loading", async () => {
      const meDeferred = createDeferred<AuthUser | null>();
      vi.spyOn(authApi, "me").mockReturnValue(meDeferred.promise);
      vi.spyOn(authApi, "login").mockRejectedValue(new Error("invalid credentials"));

      const hydratePromise = useAuthStore.getState().hydrate();
      await expect(useAuthStore.getState().login({ email: "a@b.c", password: "wrong" })).rejects.toThrow();
      const epochAfterFailedLogin = useAuthStore.getState().epoch;
      expect(useAuthStore.getState().status).not.toBe("loading");

      meDeferred.reject(new Error("network down"));
      await hydratePromise;

      expect(useAuthStore.getState().status).toBe("anon");
      expect(useAuthStore.getState().status).not.toBe("loading");
      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().epoch).toBe(epochAfterFailedLogin);
    });

    it("later-intent-wins still holds when a failed login is itself superseded by a later successful signup", async () => {
      const meDeferred = createDeferred<AuthUser | null>();
      vi.spyOn(authApi, "me").mockReturnValue(meDeferred.promise);
      const loginDeferred = createDeferred<AuthUser>();
      vi.spyOn(authApi, "login").mockReturnValue(loginDeferred.promise);
      vi.spyOn(authApi, "signup").mockResolvedValue({ id: "u-signup", email: "new@b.c" });

      const hydratePromise = useAuthStore.getState().hydrate();
      const loginPromise = useAuthStore.getState().login({ email: "a@b.c", password: "wrong" });
      // A later signup starts (and will succeed) before the login settles.
      await useAuthStore.getState().signup({ email: "new@b.c", password: "secret", invite_code: "good" });
      const epochAfterSignup = useAuthStore.getState().epoch;
      expect(useAuthStore.getState().status).toBe("authed");
      expect(useAuthStore.getState().user?.id).toBe("u-signup");

      // The stale login now fails -- it must not clobber the newer signup.
      loginDeferred.reject(new Error("invalid credentials"));
      await expect(loginPromise).rejects.toThrow();

      // The even-staler hydrate resolves last -- it must not clobber it either.
      meDeferred.resolve({ id: "u0", email: "old@b.c" });
      await hydratePromise;

      expect(useAuthStore.getState().status).toBe("authed");
      expect(useAuthStore.getState().user?.id).toBe("u-signup");
      expect(useAuthStore.getState().epoch).toBe(epochAfterSignup);
    });
  });
});
