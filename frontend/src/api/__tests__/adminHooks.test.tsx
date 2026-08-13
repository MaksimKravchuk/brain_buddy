import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { adminKeys, useAdminStatus } from "../adminHooks";
import { apiClient } from "../client";
import { useAuthStore } from "../../stores/authStore";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("adminHooks", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    act(() => {
      useAuthStore.setState({ user: null, status: "loading", deletionCancelledNotice: false });
    });
  });

  it("exposes a stable key factory", () => {
    expect(adminKeys.status()).toEqual(["admin", "status"]);
  });

  it("009-FR-002: stays disabled and never calls the endpoint while the session is not authed", () => {
    const spy = vi.spyOn(apiClient, "getAdminStatus");
    act(() => {
      useAuthStore.setState({ user: null, status: "anon", deletionCancelledNotice: false });
    });

    const { result } = renderHook(() => useAdminStatus(), { wrapper });

    expect(result.current.fetchStatus).toBe("idle");
    expect(spy).not.toHaveBeenCalled();
  });

  it("009-FR-002: fetches operator status once a session exists", async () => {
    const spy = vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    act(() => {
      useAuthStore.setState({
        user: { id: "operator-1", email: "operator@example.com" },
        status: "authed",
        deletionCancelledNotice: false
      });
    });

    const { result } = renderHook(() => useAdminStatus(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ is_operator: true });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("009-FR-002: a denial is terminal and is never retried", async () => {
    const spy = vi.spyOn(apiClient, "getAdminStatus").mockRejectedValue(new Error("Forbidden"));
    act(() => {
      useAuthStore.setState({
        user: { id: "member-1", email: "member@example.com" },
        status: "authed",
        deletionCancelledNotice: false
      });
    });

    const { result } = renderHook(() => useAdminStatus(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
