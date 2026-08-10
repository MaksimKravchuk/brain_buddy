import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi } from "../../api/auth";
import { useAuthStore } from "../authStore";

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
