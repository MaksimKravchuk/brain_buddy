import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRelayMutation } from "../agentLifecycle";
import { agentKeys } from "../agentHooks";
import { ApiError } from "../client";
import { bindRelaySession } from "../relaySession";
import handoffSource from "../../features/agents/AgentHandoffOverlay.tsx?raw";
import runSectionSource from "../../features/agents/AgentRunSection.tsx?raw";
import settingsSource from "../../features/agents/AgentSettingsPage.tsx?raw";
import { useAuthStore } from "../../stores/authStore";

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";
const browserOriginChangesApiScope =
  new URL(configuredApiBaseUrl, "https://app.example.test").href !==
  new URL(configuredApiBaseUrl, "https://other.example.test").href;

/** Every way the relay scope can stop being the one a command was dispatched under. */
const SCOPE_TRANSITIONS: Array<[string, () => void]> = [
  ["logout", () => useAuthStore.getState().clearSession()],
  [
    "account switch",
    () =>
      useAuthStore.setState({
        user: { id: "user-2", email: "two@example.test" },
        status: "authed"
      })
  ],
  ...(browserOriginChangesApiScope ? [[
    "API-origin switch",
    () => {
      const scopedWindow = Object.create(window) as Window;
      Object.defineProperty(scopedWindow, "location", {
        configurable: true,
        value: { origin: "https://other.example.test" }
      });
      vi.stubGlobal("window", scopedWindow);
      useAuthStore.setState({ status: "authed" });
    }
  ] as [string, () => void]] : [])
];

describe("relay mutation lifecycle", () => {
  beforeEach(() => {
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
    onlineManager.setOnline(true);
    useAuthStore.setState({ user: { id: "user-1", email: "one@example.test" }, status: "authed" });
  });

  afterEach(() => {
    onlineManager.setOnline(true);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("rejects every representative relay mutation offline and never auto-resumes it", async () => {
    const apiCalls = {
      createConnection: vi.fn(async () => undefined),
      testConnection: vi.fn(async () => undefined),
      rotateCredential: vi.fn(async () => undefined),
      rotateSigningSecret: vi.fn(async () => undefined),
      disconnectConnection: vi.fn(async () => undefined),
      confirmHandoff: vi.fn(async () => undefined),
      replyToRun: vi.fn(async () => undefined),
      cancelRun: vi.fn(async () => undefined)
    };
    type Operation = keyof typeof apiCalls;
    const operations = Object.keys(apiCalls) as Operation[];
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
    });
    const offlineWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(
      () =>
        useRelayMutation({
          mutationKey: ["agents", "https://app.example.test/api::user-1", "mutation", "representative"],
          mutationFn: (operation: Operation) => apiCalls[operation]()
        }),
      { wrapper: offlineWrapper }
    );

    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    act(() => onlineManager.setOnline(false));
    const attempts: Array<Promise<unknown>> = [];
    act(() => {
      for (const operation of operations) {
        attempts.push(result.current.mutateAsync(operation).catch((error: unknown) => error));
      }
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(Object.values(apiCalls).every((call) => call.mock.calls.length === 0)).toBe(true);
    expect(client.getMutationCache().getAll().every((mutation) => !mutation.state.isPaused)).toBe(true);

    // Navigating away must not leave an offline intent behind for React Query
    // to replay after this relay surface no longer exists.
    unmount();

    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
    act(() => onlineManager.setOnline(true));
    await Promise.all(attempts);
    await Promise.resolve();

    expect(Object.values(apiCalls).every((call) => call.mock.calls.length === 0)).toBe(true);
    expect(client.getMutationCache().getAll().every((mutation) => !mutation.state.isPaused)).toBe(true);
  });

  it("routes all nine real relay mutation call sites through the guarded hook", () => {
    const relaySurfaces = [handoffSource, runSectionSource, settingsSource].join("\n");

    expect(relaySurfaces).not.toMatch(/\buseMutation\s*\(/);
    expect(relaySurfaces.match(/\buseRelayMutation\s*\(\{/g)).toHaveLength(9);
  });

  it.each(SCOPE_TRANSITIONS)("suppresses delayed success settlement after %s", async (_transition, leaveScope) => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const unbind = bindRelaySession(client);
    const ownerKeys = agentKeys.forOwner("user-1");
    let resolve!: (value: string) => void;
    const pending = new Promise<string>((settle) => {
      resolve = settle;
    });
    const onSuccess = vi.fn((value: string) => client.setQueryData(ownerKeys.run("run-1"), value));
    const perCallSuccess = vi.fn((value: string) => client.setQueryData(ownerKeys.run("run-local"), value));
    const onSettled = vi.fn();
    const scopedWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(
      () =>
        useRelayMutation({
          mutationKey: agentKeys.forOwner(useAuthStore.getState().user?.id ?? null).mutation("reply", "run-1"),
          mutationFn: () => pending,
          onSuccess,
          onSettled
        }),
      { wrapper: scopedWrapper }
    );

    act(() => result.current.mutate(undefined, { onSuccess: perCallSuccess }));
    act(leaveScope);
    rerender();
    await act(async () => resolve("owner-1 secret"));

    expect(onSuccess).not.toHaveBeenCalled();
    expect(perCallSuccess).not.toHaveBeenCalled();
    expect(onSettled).not.toHaveBeenCalled();
    expect(client.getQueryData(ownerKeys.run("run-1"))).toBeUndefined();
    expect(JSON.stringify(client.getQueryCache().getAll().map((query) => query.state.data))).not.toContain(
      "owner-1 secret"
    );
    unbind();
  });

  it("suppresses a delayed 401 error settlement after the unauthorized purge", async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const unbind = bindRelaySession(client);
    const ownerKeys = agentKeys.forOwner("user-1");
    let reject!: (reason: unknown) => void;
    const pending = new Promise<string>((_resolve, fail) => {
      reject = fail;
    });
    const onError = vi.fn();
    const onSettled = vi.fn();
    const scopedWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useRelayMutation({
          mutationKey: ownerKeys.mutation("cancel", "run-1"),
          mutationFn: () => pending,
          onError,
          onSettled
        }),
      { wrapper: scopedWrapper }
    );

    act(() => result.current.mutate(undefined));
    act(() => useAuthStore.getState().clearSession());
    await act(async () => reject(new ApiError("Unauthorized", 401, { message: "Session expired" })));

    expect(onError).not.toHaveBeenCalled();
    expect(onSettled).not.toHaveBeenCalled();
    expect(client.getMutationCache().findAll({ mutationKey: agentKeys.all })).toHaveLength(0);
    unbind();
  });
});

/**
 * Settlement belongs to the session that dispatched the command, not to whichever
 * session happens to be current when the answer arrives.
 *
 * The cases that matter are the ones where nothing detaches the mutation for us.
 * React Query re-reads a pending mutation's options on every rerender under an
 * unchanged mutation key, so a render-time capture is quietly re-pointed at the
 * new session; and a per-call callback lives on the observer, which a scope
 * change alone never touches. Both are covered here without relying on the
 * mutation key moving with the owner.
 */
describe("relay mutation settlement binds to the dispatching scope", () => {
  // Fixed on purpose. A key derived from the current owner would make React
  // Query reset the observer on every transition below, and these assertions
  // would then hold with no guard in the hook at all.
  const STABLE_KEY = ["agents", "https://app.example.test/api::user-1", "mutation", "cancel", "run-1"];
  const HOOK_SLOT = agentKeys.forOwner("user-1").run("settled-by-hook");
  const PER_CALL_SLOT = agentKeys.forOwner("user-1").run("settled-per-call");
  const OWNER_SECRET = "owner-1 relay answer";

  beforeEach(() => {
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
    onlineManager.setOnline(true);
    useAuthStore.setState({ user: { id: "user-1", email: "one@example.test" }, status: "authed" });
  });

  afterEach(() => {
    onlineManager.setOnline(true);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function deferred() {
    let resolve!: (value: string) => void;
    let reject!: (reason: unknown) => void;
    const promise = new Promise<string>((settle, fail) => {
      resolve = settle;
      reject = fail;
    });
    return { promise, resolve, reject };
  }

  function renderRelayMutation() {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const unbind = bindRelaySession(client);
    const calls = {
      hookSuccess: vi.fn((value: string) => client.setQueryData(HOOK_SLOT, value)),
      hookError: vi.fn(),
      hookSettled: vi.fn(),
      callSuccess: vi.fn((value: string) => client.setQueryData(PER_CALL_SLOT, value)),
      callError: vi.fn(),
      callSettled: vi.fn()
    };
    const renders = { count: 0 };
    const rendered = renderHook(
      () => {
        renders.count += 1;
        return useRelayMutation({
          mutationKey: STABLE_KEY,
          mutationFn: (gate: Promise<string>) => gate,
          onSuccess: calls.hookSuccess,
          onError: calls.hookError,
          onSettled: calls.hookSettled
        });
      },
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        )
      }
    );
    const dispatch = (gate: Promise<string>) =>
      act(() =>
        rendered.result.current.mutate(gate, {
          onSuccess: calls.callSuccess,
          onError: calls.callError,
          onSettled: calls.callSettled
        })
      );
    return { ...rendered, client, unbind, calls, renders, dispatch };
  }

  type Harness = ReturnType<typeof renderRelayMutation>;

  function expectNothingSettled(harness: Harness) {
    for (const [name, callback] of Object.entries(harness.calls)) {
      expect(callback, name).not.toHaveBeenCalled();
    }
    expect(harness.client.getQueryData(HOOK_SLOT)).toBeUndefined();
    expect(harness.client.getQueryData(PER_CALL_SLOT)).toBeUndefined();
    const cached = harness.client
      .getQueryCache()
      .getAll()
      .map((query) => query.state.data);
    expect(JSON.stringify(cached)).not.toContain(OWNER_SECRET);
  }

  it.each(SCOPE_TRANSITIONS)(
    "suppresses a delayed success after %s when the hook rerenders under an unchanged mutation key",
    async (_transition, leaveScope) => {
      const harness = renderRelayMutation();
      const gate = deferred();

      harness.dispatch(gate.promise);
      act(leaveScope);
      harness.rerender();
      await act(async () => gate.resolve(OWNER_SECRET));

      expectNothingSettled(harness);
      harness.unbind();
    }
  );

  it.each(SCOPE_TRANSITIONS)(
    "suppresses a delayed success after %s that happens without any rerender",
    async (_transition, leaveScope) => {
      const harness = renderRelayMutation();
      const gate = deferred();

      harness.dispatch(gate.promise);
      const rendersAtDispatch = harness.renders.count;
      act(leaveScope);
      // Nothing subscribes the hook to the session, so the guard cannot be
      // allowed to depend on a render arriving to refresh it.
      expect(harness.renders.count).toBe(rendersAtDispatch);
      await act(async () => gate.resolve(OWNER_SECRET));

      expectNothingSettled(harness);
      harness.unbind();
    }
  );

  it.each(SCOPE_TRANSITIONS)(
    "suppresses a delayed failure after %s under an unchanged mutation key",
    async (_transition, leaveScope) => {
      const harness = renderRelayMutation();
      const gate = deferred();

      harness.dispatch(gate.promise);
      act(leaveScope);
      harness.rerender();
      await act(async () => gate.reject(new ApiError("Unavailable", 503, { message: OWNER_SECRET })));

      expectNothingSettled(harness);
      harness.unbind();
    }
  );

  it("settles each of two overlapping dispatches in the scope that dispatched it", async () => {
    const harness = renderRelayMutation();
    const first = deferred();
    const second = deferred();
    const laterSuccess = vi.fn();
    const laterSettled = vi.fn();

    harness.dispatch(first.promise);
    act(() =>
      useAuthStore.setState({ user: { id: "user-2", email: "two@example.test" }, status: "authed" })
    );
    harness.rerender();
    act(() =>
      harness.result.current.mutate(second.promise, {
        onSuccess: laterSuccess,
        onSettled: laterSettled
      })
    );

    await act(async () => second.resolve("owner-2 relay answer"));
    await act(async () => first.resolve(OWNER_SECRET));

    expect(laterSuccess).toHaveBeenCalledTimes(1);
    expect(laterSuccess.mock.calls[0][0]).toBe("owner-2 relay answer");
    expect(laterSettled).toHaveBeenCalledTimes(1);
    expect(harness.calls.hookSuccess).toHaveBeenCalledTimes(1);
    expect(harness.calls.hookSuccess.mock.calls[0][0]).toBe("owner-2 relay answer");
    expect(harness.calls.hookSettled).toHaveBeenCalledTimes(1);
    expect(harness.calls.callSuccess).not.toHaveBeenCalled();
    expect(harness.calls.callSettled).not.toHaveBeenCalled();
    expect(harness.client.getQueryData(PER_CALL_SLOT)).toBeUndefined();
    const cached = harness.client
      .getQueryCache()
      .getAll()
      .map((query) => query.state.data);
    expect(JSON.stringify(cached)).not.toContain(OWNER_SECRET);
    harness.unbind();
  });

  it("runs hook-level and per-call success callbacks while the dispatching scope is current", async () => {
    const harness = renderRelayMutation();
    const gate = deferred();

    harness.dispatch(gate.promise);
    harness.rerender();
    harness.rerender();
    await act(async () => gate.resolve(OWNER_SECRET));

    expect(harness.calls.hookSuccess).toHaveBeenCalledTimes(1);
    expect(harness.calls.callSuccess).toHaveBeenCalledTimes(1);
    expect(harness.calls.hookSettled).toHaveBeenCalledTimes(1);
    expect(harness.calls.callSettled).toHaveBeenCalledTimes(1);
    expect(harness.calls.hookError).not.toHaveBeenCalled();
    expect(harness.calls.callError).not.toHaveBeenCalled();
    expect(harness.client.getQueryData(HOOK_SLOT)).toBe(OWNER_SECRET);
    expect(harness.client.getQueryData(PER_CALL_SLOT)).toBe(OWNER_SECRET);
    harness.unbind();
  });

  it("runs hook-level and per-call error callbacks while the dispatching scope is current", async () => {
    const harness = renderRelayMutation();
    const gate = deferred();
    const failure = new ApiError("Unavailable", 503, { message: "Try again later." });

    harness.dispatch(gate.promise);
    harness.rerender();
    await act(async () => gate.reject(failure));

    expect(harness.calls.hookError).toHaveBeenCalledTimes(1);
    expect(harness.calls.hookError.mock.calls[0][0]).toBe(failure);
    expect(harness.calls.callError).toHaveBeenCalledTimes(1);
    expect(harness.calls.hookSettled).toHaveBeenCalledTimes(1);
    expect(harness.calls.callSettled).toHaveBeenCalledTimes(1);
    expect(harness.calls.hookSuccess).not.toHaveBeenCalled();
    harness.unbind();
  });

  it("hands the caller's own onMutate result to every callback and exposes it unwrapped", async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const onMutate = vi.fn(() => ({ rolledBackTo: "previous" }));
    const onSuccess = vi.fn();
    const onSettled = vi.fn();
    const perCallSettled = vi.fn();
    const { result } = renderHook(
      () =>
        useRelayMutation({
          mutationKey: STABLE_KEY,
          mutationFn: (gate: Promise<string>) => gate,
          onMutate,
          onSuccess,
          onSettled
        }),
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        )
      }
    );

    const gate = deferred();
    act(() => result.current.mutate(gate.promise, { onSettled: perCallSettled }));
    await act(async () => gate.resolve(OWNER_SECRET));

    expect(onMutate).toHaveBeenCalledTimes(1);
    expect(onSuccess.mock.calls[0][2]).toEqual({ rolledBackTo: "previous" });
    expect(onSettled.mock.calls[0][3]).toEqual({ rolledBackTo: "previous" });
    expect(perCallSettled.mock.calls[0][3]).toEqual({ rolledBackTo: "previous" });
    // Whatever the guard threads through a dispatch stays private to the guard:
    // observable mutation state still shows the caller's own rollback context.
    expect(client.getMutationCache().getAll().map((mutation) => mutation.state.context)).toEqual([
      { rolledBackTo: "previous" }
    ]);
  });
});
