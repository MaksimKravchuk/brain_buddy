import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi, type AuthUser } from "../../api/auth";
import * as crtBoundary from "../../features/crt/crtDraftCoordinator";
import { FLAG_REFRESH_INTERVAL_MS, startFlagRefresh, useAuthStore } from "../authStore";

describe("authStore", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "loading" });
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
    expect(useAuthStore.getState().deletionCancelledNotice).toBe(false);
  });

  it("carries a scheduled deletion purge date across the session clear", async () => {
    useAuthStore.getState().scheduleDeletionNotice("2026-08-20T12:00:00Z");
    useAuthStore.getState().clearSession();
    expect(useAuthStore.getState().deletionScheduledFor).toBe("2026-08-20T12:00:00Z");

    // A successful login means the deletion is cancelled — drop the notice.
    vi.spyOn(authApi, "login").mockResolvedValue({ id: "u1", email: "a@b.c" });
    await useAuthStore.getState().login({ email: "a@b.c", password: "x" });
    expect(useAuthStore.getState().deletionScheduledFor).toBeNull();
  });

  it("login surfaces a cancelled account deletion as a dismissible notice", async () => {
    vi.spyOn(authApi, "login").mockResolvedValue({
      id: "u1",
      email: "a@b.c",
      deletion_cancelled: true
    });
    await useAuthStore.getState().login({ email: "a@b.c", password: "x" });
    expect(useAuthStore.getState().deletionCancelledNotice).toBe(true);

    useAuthStore.getState().dismissDeletionNotice();
    expect(useAuthStore.getState().deletionCancelledNotice).toBe(false);
  });

  it("starts as loading, so no route decides anything before hydration", () => {
    expect(useAuthStore.getInitialState().status).toBe("loading");
    expect(useAuthStore.getInitialState().user).toBeNull();
  });

  it("logout cleans departing-owner CRT records before ending the session", async () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    const cleanup = vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 2 });
    const logoutSpy = vi.spyOn(authApi, "logout").mockResolvedValue(undefined);

    await useAuthStore.getState().logout();

    expect(cleanup).toHaveBeenCalledWith("u1", window.location.origin);
    expect(logoutSpy).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().status).toBe("anon");
  });

  it("cancels logout when departing-owner CRT cleanup fails", async () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    const cleanup = vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    const logoutSpy = vi.spyOn(authApi, "logout").mockResolvedValue(undefined);

    await expect(useAuthStore.getState().logout()).resolves.toBe(false);

    expect(cleanup).toHaveBeenCalledWith("u1", window.location.origin);
    expect(logoutSpy).not.toHaveBeenCalled();
    expect(useAuthStore.getState().status).toBe("authed");
  });

  it("clearSessionAfterCleanup leaves the session in place when CRT cleanup fails", async () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: false, reason: "cleanup-failed" });

    await expect(useAuthStore.getState().clearSessionAfterCleanup()).resolves.toBe(false);

    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.id).toBe("u1");
  });

  it("logout ends the server session as well as the local one", async () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    const logoutSpy = vi.spyOn(authApi, "logout").mockResolvedValue(undefined);

    await useAuthStore.getState().logout();

    expect(logoutSpy).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().status).toBe("anon");
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

  it("drops stale hydrate results and protects account changes behind CRT cleanup", async () => {
    let resolveMe!: (value: AuthUser | null) => void;
    const pending = new Promise<AuthUser | null>((resolve) => { resolveMe = resolve; });
    vi.spyOn(authApi, "me").mockReturnValue(pending);
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    const hydrate = useAuthStore.getState().hydrate();
    useAuthStore.getState().clearSession();
    resolveMe({ id: "u2", email: "b@b.c" });
    await hydrate;
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue({ id: "u2", email: "b@b.c" });
    const cleanup = vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 1 });
    await useAuthStore.getState().hydrate();
    expect(cleanup).toHaveBeenCalledWith("u1", window.location.origin);
    expect(useAuthStore.getState().user?.id).toBe("u2");
  });

  it("leaves the current account in place when hydrate cleanup is refused", async () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue(null);
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    await useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().user?.id).toBe("u1");
    expect(useAuthStore.getState().status).toBe("authed");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockRejectedValue(new Error("offline"));
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockImplementation(async () => {
      useAuthStore.getState().clearSession();
      return { ok: true, removed: 0 };
    });
    await useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().status).toBe("anon");
  });

  it("covers refresh account replacement, cleanup refusal, and stale cleanup completion", async () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue({ id: "u2", email: "b@b.c" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 1 });
    await useAuthStore.getState().refreshSession();
    expect(useAuthStore.getState().user?.id).toBe("u2");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue({ id: "u2", email: "b@b.c" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    await useAuthStore.getState().refreshSession();
    expect(useAuthStore.getState().user?.id).toBe("u1");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue({ id: "u2", email: "b@b.c" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockImplementation(async () => {
      useAuthStore.getState().clearSession();
      return { ok: true, removed: 0 };
    });
    await useAuthStore.getState().refreshSession();
    expect(useAuthStore.getState().status).toBe("anon");
  });

  it("keeps the existing user identity when a refresh is semantically unchanged", async () => {
    const current: AuthUser = {
      id: "u1",
      email: "a@b.c",
      display_name: "A",
      deletion_cancelled: false,
      feature_flags: { crt_canvas: true, voice_brain_dump: false }
    };
    useAuthStore.setState({ user: current, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue({
      id: "u1",
      email: "a@b.c",
      display_name: "A",
      deletion_cancelled: false,
      feature_flags: { voice_brain_dump: false, crt_canvas: true }
    });

    await useAuthStore.getState().refreshSession();

    expect(useAuthStore.getState().user).toBe(current);
  });

  it("publishes a refresh when a feature flag changes", async () => {
    const current: AuthUser = {
      id: "u1",
      email: "a@b.c",
      feature_flags: { crt_canvas: true }
    };
    useAuthStore.setState({ user: current, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue({
      id: "u1",
      email: "a@b.c",
      feature_flags: { crt_canvas: false }
    });

    await useAuthStore.getState().refreshSession();

    expect(useAuthStore.getState().user).not.toBe(current);
    expect(useAuthStore.getState().user?.feature_flags?.crt_canvas).toBe(false);
  });

  it("refuses a null refresh when departing-owner CRT cleanup fails", async () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue(null);
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    await useAuthStore.getState().refreshSession();
    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.id).toBe("u1");
  });

  it("guards login and signup when cleanup fails or a newer transition starts", async () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    const loginApi = vi.spyOn(authApi, "login");
    await expect(useAuthStore.getState().login({ email: "b@b.c", password: "x" })).rejects.toThrow("Could not clear");
    expect(loginApi).not.toHaveBeenCalled();

    vi.restoreAllMocks();
    let resolveLogin!: (value: AuthUser) => void;
    const loginResult = new Promise<AuthUser>((resolve) => { resolveLogin = resolve; });
    vi.spyOn(authApi, "login").mockReturnValue(loginResult);
    const login = useAuthStore.getState().login({ email: "b@b.c", password: "x" });
    await Promise.resolve();
    useAuthStore.getState().clearSession();
    resolveLogin({ id: "u2", email: "b@b.c" });
    await login;
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    await expect(useAuthStore.getState().signup({ email: "b@b.c", password: "x", invite_code: "i" })).rejects.toThrow("Could not clear");
  });

  it("drops stale signup and logout completions and handles synchronous 401 cleanup", async () => {
    let resolveSignup!: (value: AuthUser) => void;
    const signupResult = new Promise<AuthUser>((resolve) => { resolveSignup = resolve; });
    vi.spyOn(authApi, "signup").mockReturnValue(signupResult);
    const signup = useAuthStore.getState().signup({ email: "b@b.c", password: "x", invite_code: "i" });
    await Promise.resolve();
    useAuthStore.getState().clearSession();
    resolveSignup({ id: "u2", email: "b@b.c" });
    await signup;
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    let resolveLogout!: () => void;
    const logoutResult = new Promise<void>((resolve) => { resolveLogout = resolve; });
    vi.spyOn(authApi, "logout").mockReturnValue(logoutResult);
    const logout = useAuthStore.getState().logout();
    await Promise.resolve();
    useAuthStore.getState().clearSession();
    resolveLogout();
    await expect(logout).resolves.toBe(false);

    vi.restoreAllMocks();
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockRejectedValue(new Error("cleanup"));
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    expect(useAuthStore.getState().clearSession()).toBe(true);
    await Promise.resolve();
    expect(useAuthStore.getState().status).toBe("anon");
  });

  it("supports successful fail-closed session clearing and rejects a superseded cleanup", async () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 1 });
    await expect(useAuthStore.getState().clearSessionAfterCleanup()).resolves.toBe(true);
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockImplementation(async () => {
      useAuthStore.getState().clearSession();
      return { ok: true, removed: 0 };
    });
    await expect(useAuthStore.getState().clearSessionAfterCleanup()).resolves.toBe(false);
    expect(useAuthStore.getState().status).toBe("anon");
  });
  it("covers remaining hydrate and transition generation exits", async () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue({ id: "u2", email: "b@b.c" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    await useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().user?.id).toBe("u1");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue({ id: "u2", email: "b@b.c" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockImplementation(async () => {
      useAuthStore.getState().clearSession();
      return { ok: true, removed: 0 };
    });
    await useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue(null);
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 0 });
    await useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockResolvedValue(null);
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockImplementation(async () => {
      useAuthStore.getState().clearSession();
      return { ok: true, removed: 0 };
    });
    await useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    let rejectMe!: (error: Error) => void;
    const rejectedMe = new Promise<AuthUser | null>((_resolve, reject) => { rejectMe = reject; });
    vi.spyOn(authApi, "me").mockReturnValue(rejectedMe);
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    const hydrate = useAuthStore.getState().hydrate();
    useAuthStore.getState().clearSession();
    rejectMe(new Error("offline"));
    await hydrate;
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    vi.spyOn(authApi, "me").mockRejectedValue(new Error("offline"));
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: false, reason: "cleanup-failed" });
    await useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().status).toBe("authed");

    vi.restoreAllMocks();
    let resolveRefresh!: (value: AuthUser | null) => void;
    const refreshResult = new Promise<AuthUser | null>((resolve) => { resolveRefresh = resolve; });
    vi.spyOn(authApi, "me").mockReturnValue(refreshResult);
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockImplementation(async () => {
      useAuthStore.getState().clearSession();
      return { ok: true, removed: 0 };
    });
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    const refresh = useAuthStore.getState().refreshSession();
    resolveRefresh(null);
    await refresh;
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    let resolveLogin!: (value: AuthUser) => void;
    const loginResult = new Promise<AuthUser>((resolve) => { resolveLogin = resolve; });
    vi.spyOn(authApi, "login").mockReturnValue(loginResult);
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 0 });
    useAuthStore.setState({ user: null, status: "anon" });
    const login = useAuthStore.getState().login({ email: "b@b.c", password: "x" });
    await Promise.resolve();
    useAuthStore.getState().clearSession();
    resolveLogin({ id: "u2", email: "b@b.c" });
    await login;
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    const staleSignupApi = vi.spyOn(authApi, "signup");
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockImplementation(async () => {
      useAuthStore.getState().clearSession();
      return { ok: true, removed: 0 };
    });
    await useAuthStore.getState().signup({ email: "b@b.c", password: "x", invite_code: "i" });
    expect(staleSignupApi).not.toHaveBeenCalled();

    vi.restoreAllMocks();
    let resolveSignup!: (value: AuthUser) => void;
    const signupResult = new Promise<AuthUser>((resolve) => { resolveSignup = resolve; });
    const signupApi = vi.spyOn(authApi, "signup").mockReturnValue(signupResult);
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 0 });
    const signup = useAuthStore.getState().signup({ email: "b@b.c", password: "x", invite_code: "i" });
    await Promise.resolve();
    await Promise.resolve();
    expect(signupApi).toHaveBeenCalled();
    useAuthStore.getState().clearSession();
    resolveSignup({ id: "u2", email: "b@b.c" });
    await signup;
    expect(useAuthStore.getState().status).toBe("anon");

    vi.restoreAllMocks();
    let resolveLogout!: () => void;
    const logoutResult = new Promise<void>((resolve) => { resolveLogout = resolve; });
    const logoutApi = vi.spyOn(authApi, "logout").mockReturnValue(logoutResult);
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 0 });
    const logout = useAuthStore.getState().logout();
    await Promise.resolve();
    await Promise.resolve();
    expect(logoutApi).toHaveBeenCalled();
    useAuthStore.getState().clearSession();
    resolveLogout();
    await expect(logout).resolves.toBe(false);
  });

});

/**
 * A request/transition generation guard on `refreshSession` (see the comment
 * above `sessionGeneration` in authStore.ts): a poll response that resolves
 * after something newer has started — a transition or a later poll — must be
 * dropped instead of applied.
 */
describe("authStore refreshSession generation guard", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const deferred = <T>() => {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((res) => {
      resolve = res;
    });
    return { promise, resolve };
  };

  it("a slower in-flight refresh does not resurrect the session after logout", async () => {
    const pending = deferred<AuthUser | null>();
    vi.spyOn(authApi, "me").mockReturnValue(pending.promise);
    vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });

    const refreshPromise = useAuthStore.getState().refreshSession();
    await useAuthStore.getState().logout();
    expect(useAuthStore.getState().status).toBe("anon");

    pending.resolve({ id: "u1", email: "a@b.c" });
    await refreshPromise;

    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("switching from account A to account B drops A's slower in-flight refresh", async () => {
    const pending = deferred<AuthUser | null>();
    vi.spyOn(authApi, "me").mockReturnValue(pending.promise);
    vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    vi.spyOn(authApi, "login").mockResolvedValue({ id: "u2", email: "b@b.c" });
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });

    const refreshPromise = useAuthStore.getState().refreshSession();
    await useAuthStore.getState().logout();
    await useAuthStore.getState().login({ email: "b@b.c", password: "x" });

    pending.resolve({ id: "u1", email: "a@b.c" });
    await refreshPromise;

    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.id).toBe("u2");
  });

  it("only the newest of two overlapping refreshes applies, even if it resolves first", async () => {
    const first = deferred<AuthUser | null>();
    const second = deferred<AuthUser | null>();
    vi.spyOn(authApi, "me")
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    useAuthStore.setState({
      user: { id: "u1", email: "a@b.c", feature_flags: { x: false } },
      status: "authed"
    });

    const firstRefresh = useAuthStore.getState().refreshSession();
    const secondRefresh = useAuthStore.getState().refreshSession();

    second.resolve({ id: "u1", email: "a@b.c", feature_flags: { x: true } });
    await secondRefresh;
    expect(useAuthStore.getState().user?.feature_flags?.x).toBe(true);

    first.resolve({ id: "u1", email: "a@b.c", feature_flags: { x: false } });
    await firstRefresh;

    expect(useAuthStore.getState().user?.feature_flags?.x).toBe(true);
  });
});

/**
 * 010-FR-009 / 010-SC-004 — live propagation to an already-open session.
 *
 * Two deliberately different failure tolerances live in this store now:
 * `hydrate()` (initial/startup load) fails **closed** to anon so a cold load
 * against an unreachable backend cannot hang on "loading" forever, while
 * `refreshSession()` (the background poll) fails **open** so ordinary network
 * noise never signs a member out (DD-11).
 */
describe("authStore background flag refresh (010-FR-009)", () => {
  let stop: (() => void) | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    useAuthStore.setState({ user: null, status: "loading" });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible"
    });
  });

  afterEach(() => {
    stop?.();
    stop = undefined;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  const authed = (flags: Record<string, boolean>) => {
    useAuthStore.setState({
      user: { id: "u1", email: "a@b.c", feature_flags: flags },
      status: "authed"
    });
  };

  const advance = async (ms: number) => {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  };

  it("010-FR-009: refetches /api/auth/me once per 15-second interval while authed", async () => {
    const me = vi.spyOn(authApi, "me").mockResolvedValue({
      id: "u1",
      email: "a@b.c",
      feature_flags: { voice_brain_dump: true }
    });
    authed({ voice_brain_dump: false });

    stop = startFlagRefresh();
    expect(me).not.toHaveBeenCalled();

    await advance(FLAG_REFRESH_INTERVAL_MS);
    expect(me).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().user?.feature_flags?.voice_brain_dump).toBe(true);

    await advance(FLAG_REFRESH_INTERVAL_MS);
    expect(me).toHaveBeenCalledTimes(2);
  });

  it("010-SC-004: focus and visibilitychange each trigger an immediate refetch", async () => {
    const me = vi.spyOn(authApi, "me").mockResolvedValue({ id: "u1", email: "a@b.c" });
    authed({});
    stop = startFlagRefresh();

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(me).toHaveBeenCalledTimes(1);

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(me).toHaveBeenCalledTimes(2);
  });

  it("010-SC-004: issues no request at all while unauthenticated", async () => {
    const me = vi.spyOn(authApi, "me").mockResolvedValue(null);
    useAuthStore.setState({ user: null, status: "anon" });

    stop = startFlagRefresh();
    await advance(FLAG_REFRESH_INTERVAL_MS * 4);
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(me).not.toHaveBeenCalled();
  });

  it("010-SC-004: issues no request while the document is hidden", async () => {
    const me = vi.spyOn(authApi, "me").mockResolvedValue({ id: "u1", email: "a@b.c" });
    authed({});
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden"
    });

    stop = startFlagRefresh();
    await advance(FLAG_REFRESH_INTERVAL_MS * 3);
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(me).not.toHaveBeenCalled();
  });

  it("010-FR-009: tears the interval and listeners down on sign-out, leaving no timer", async () => {
    const me = vi.spyOn(authApi, "me").mockResolvedValue({ id: "u1", email: "a@b.c" });
    authed({});
    stop = startFlagRefresh();

    await advance(FLAG_REFRESH_INTERVAL_MS);
    expect(me).toHaveBeenCalledTimes(1);

    act(() => {
      useAuthStore.getState().clearSession();
    });
    await advance(FLAG_REFRESH_INTERVAL_MS * 3);
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(me).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("010-FR-009: teardown removes the listeners as well as the interval", async () => {
    const me = vi.spyOn(authApi, "me").mockResolvedValue({ id: "u1", email: "a@b.c" });
    authed({});
    stop = startFlagRefresh();
    stop();
    stop = undefined;

    await advance(FLAG_REFRESH_INTERVAL_MS * 2);
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(me).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("010-SC-004: a 401 on the background path clears the session and stops the timer", async () => {
    // `authApi.me()` resolves null for a 401 and throws for anything else.
    const me = vi.spyOn(authApi, "me").mockResolvedValue(null);
    authed({ voice_brain_dump: true });
    stop = startFlagRefresh();

    await advance(FLAG_REFRESH_INTERVAL_MS);

    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
    await advance(FLAG_REFRESH_INTERVAL_MS * 3);
    expect(me).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("010-SC-004: a transient failure keeps the session and the poll recovers", async () => {
    const me = vi
      .spyOn(authApi, "me")
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({
        id: "u1",
        email: "a@b.c",
        feature_flags: { voice_brain_dump: true }
      });
    authed({ voice_brain_dump: false });
    stop = startFlagRefresh();

    await advance(FLAG_REFRESH_INTERVAL_MS);
    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.id).toBe("u1");
    expect(useAuthStore.getState().user?.feature_flags?.voice_brain_dump).toBe(false);

    await advance(FLAG_REFRESH_INTERVAL_MS);
    expect(me).toHaveBeenCalledTimes(2);
    expect(useAuthStore.getState().status).toBe("authed");
    expect(useAuthStore.getState().user?.feature_flags?.voice_brain_dump).toBe(true);
  });

  it("010-FR-009: hydrate still fails closed to anon on a transient error", async () => {
    // Pinned deliberately: initial/startup load must NOT adopt the poll's
    // transient tolerance, or a cold load against an unreachable backend would
    // hang on "loading" forever (DD-11).
    vi.spyOn(authApi, "me").mockRejectedValue(new Error("network down"));
    authed({ voice_brain_dump: true });

    await act(async () => {
      await useAuthStore.getState().hydrate();
    });

    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
  });
});
