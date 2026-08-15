import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi } from "../../api/auth";
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

  it("clearSession resets to anon without a network call", () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    useAuthStore.getState().clearSession();
    expect(useAuthStore.getState().status).toBe("anon");
    expect(useAuthStore.getState().user).toBeNull();
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
