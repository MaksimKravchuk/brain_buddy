import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { adminKeys, bindAdminSession, useAdminStatus } from "../adminHooks";
import { ApiError, apiClient } from "../client";
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

  it("exposes a stable key factory, scoped to the account the answer is about", () => {
    // Replaces an assertion on a constant `["admin", "status"]` key. That key
    // was the 009-FR-005 defect itself: one entry in the process-global cache
    // shared by every account that ever signs in. It is not kept as a
    // compatibility alias — there are no other callers, and re-exposing it
    // would let the same bug back in.
    expect(adminKeys.forOwner("operator-1").status()).toEqual([
      "admin",
      "operator-1",
      "status"
    ]);
    expect(adminKeys.forOwner(null).status()).toEqual(["admin", "anonymous", "status"]);
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

  it("009-FR-011: caches the answer for the session and never refetches on focus", async () => {
    const spy = vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    act(() => {
      useAuthStore.setState({
        user: { id: "operator-1", email: "operator@example.com" },
        status: "authed",
        deletionCancelledNotice: false
      });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const sharedWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const first = renderHook(() => useAdminStatus(), { wrapper: sharedWrapper });
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));

    act(() => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("visibilitychange"));
    });
    // A remount (navigating back to /admin) must reuse the cached answer too.
    const second = renderHook(() => useAdminStatus(), { wrapper: sharedWrapper });
    await waitFor(() => expect(second.result.current.isSuccess).toBe(true));

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

// The capability answer is an authorization fact about *one* signed-in
// account, cached for the session with staleTime Infinity. The process-global
// QueryClient outlives any single session, so a key that does not name the
// account — or a cache that survives a session boundary — lets a later caller
// read an earlier caller's `is_operator` without any server request. That is
// the 009-FR-005 server-side check being skipped entirely.
describe("useAdminStatus session isolation (009-FR-005)", () => {
  // `bindAdminSession` subscribes to the module-level auth store, so a test
  // that returns without unbinding leaves a live subscriber behind and the
  // next test's call counts stop being its own. Teardown is unconditional.
  const unbinds: Array<() => void> = [];

  afterEach(() => {
    while (unbinds.length > 0) {
      unbinds.pop()?.();
    }
    vi.restoreAllMocks();
    act(() => {
      useAuthStore.setState({ user: null, status: "loading", deletionCancelledNotice: false });
    });
  });

  function bind(client: QueryClient) {
    unbinds.push(bindAdminSession(client));
  }

  function signIn(id: string, email: string) {
    act(() => {
      useAuthStore.setState({
        user: { id, email },
        status: "authed",
        deletionCancelledNotice: false
      });
    });
  }

  function sharedWrapper(client: QueryClient) {
    return ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  }

  it("009-FR-005: a later member never reads the previous operator's cached capability", async () => {
    const spy = vi
      .spyOn(apiClient, "getAdminStatus")
      .mockResolvedValueOnce({ is_operator: true })
      .mockRejectedValueOnce(new ApiError("Forbidden", 403, null));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    bind(client);
    const wrapper = sharedWrapper(client);

    signIn("operator-1", "operator@example.com");
    const operator = renderHook(() => useAdminStatus(), { wrapper });
    await waitFor(() => expect(operator.result.current.data).toEqual({ is_operator: true }));
    operator.unmount();

    await act(async () => {
      await useAuthStore.getState().logout();
    });
    signIn("member-2", "member@example.com");

    const member = renderHook(() => useAdminStatus(), { wrapper });

    // Never the previous session's answer, not even for one render.
    expect(member.result.current.data).toBeUndefined();
    await waitFor(() => expect(member.result.current.isError).toBe(true));
    expect(member.result.current.data).toBeUndefined();
    // A *new* server check was required before anything could be shown.
    expect(spy.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("009-FR-005: the inverse is also true — a stale denial is not reused by an operator", async () => {
    const spy = vi
      .spyOn(apiClient, "getAdminStatus")
      .mockRejectedValueOnce(new ApiError("Forbidden", 403, null))
      .mockResolvedValueOnce({ is_operator: true });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    bind(client);
    const wrapper = sharedWrapper(client);

    signIn("member-2", "member@example.com");
    const member = renderHook(() => useAdminStatus(), { wrapper });
    await waitFor(() => expect(member.result.current.isError).toBe(true));
    member.unmount();

    act(() => {
      useAuthStore.getState().clearSession();
    });
    signIn("operator-1", "operator@example.com");

    const operator = renderHook(() => useAdminStatus(), { wrapper });
    await waitFor(() => expect(operator.result.current.data).toEqual({ is_operator: true }));
    expect(spy.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("009-FR-005: re-signing in as the same operator still re-checks with the server", async () => {
    const spy = vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    bind(client);
    const wrapper = sharedWrapper(client);

    signIn("operator-1", "operator@example.com");
    const first = renderHook(() => useAdminStatus(), { wrapper });
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
    first.unmount();

    act(() => {
      useAuthStore.getState().clearSession();
    });
    signIn("operator-1", "operator@example.com");

    // Exactly one request served the whole first session: the cache held, and
    // crossing the session boundary did not itself trigger a refetch.
    expect(spy).toHaveBeenCalledTimes(1);
    spy.mockClear();

    const second = renderHook(() => useAdminStatus(), { wrapper });
    // The allow-list can change between sessions; a session boundary is not a
    // remount, so the session cache must not carry across it.
    expect(second.result.current.data).toBeUndefined();
    await waitFor(() => expect(second.result.current.isSuccess).toBe(true));
    // The second session asked the server itself rather than reading the first
    // session's answer.
    expect(spy.mock.calls.length).toBeGreaterThanOrEqual(1);
  });

  it("009-FR-005: the status key names the signed-in account", () => {
    expect(adminKeys.forOwner("operator-1").status()).not.toEqual(
      adminKeys.forOwner("member-2").status()
    );
    expect(adminKeys.forOwner("operator-1").status()).toContain("operator-1");
  });
});
