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
});
