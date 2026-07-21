import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi } from "../auth";
import { installTaskCacheOwnerGuard } from "../taskCacheOwnerGuard";
import { taskKeys } from "../taskHooks";
import { useAuthStore } from "../../stores/authStore";

describe("installTaskCacheOwnerGuard", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "anon", epoch: 0 });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    useAuthStore.setState({ user: null, status: "anon", epoch: 0 });
  });

  it("purges the task cache on a same-owner relogin, not just when the owner text changes", async () => {
    // Two consecutive logins as the same user are two distinct sessions --
    // the owner id alone can't tell them apart, so the purge must trigger on
    // the epoch transition itself, not on whether the derived owner string
    // happened to change.
    vi.spyOn(authApi, "login").mockResolvedValue({ id: "user-a", email: "a@example.test" });
    const queryClient = new QueryClient();
    const uninstall = installTaskCacheOwnerGuard(queryClient);

    await useAuthStore.getState().login({ email: "a@example.test", password: "x" });
    queryClient.setQueryData(taskKeys.all("user-a"), { seeded: true });
    expect(queryClient.getQueryData(taskKeys.all("user-a"))).toEqual({ seeded: true });

    await useAuthStore.getState().login({ email: "a@example.test", password: "x" });

    expect(queryClient.getQueryData(taskKeys.all("user-a"))).toBeUndefined();

    uninstall();
  });
});
