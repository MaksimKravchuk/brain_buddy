import { notifyManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  agentKeys,
  INITIAL_RUN_POLL_MS,
  isRunPollable,
  MAX_RUN_POLL_MS,
  runPollDelay,
  useAgentConnections,
  useAgentRuns,
  useAgentRunSummaries
} from "../agentHooks";
import type { AgentConnectionResponse, AgentRunResponse } from "../agentTypes";
import { authApi } from "../auth";
import { apiClient, setUnauthorizedHandler } from "../client";
import { bindRelaySession } from "../relaySession";
import { ProtectedRoute } from "../../components/auth/ProtectedRoute";
import { useAuthStore } from "../../stores/authStore";

const connection: AgentConnectionResponse = {
  id: "conn-1",
  name: "Hermes",
  endpoint_url: "https://agent.example.com/hooks",
  auth_header_name: "Authorization",
  status: "ready",
  stale: false,
  ready_for_handoff: true,
  capabilities: { progress: true, reply: true, cancel: false },
  last_test_error_code: null,
  last_contact_at: "2026-08-09T10:00:00Z",
  last_tested_at: "2026-08-09T10:00:00Z",
  stale_after_seconds: 3600,
  created_at: "2026-08-09T09:00:00Z",
  revision: 1
};

const run = { id: "run-1", task_id: "task-1" } as AgentRunResponse;

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";

function expectedAgentScope(browserOrigin: string, ownerId: string): string {
  const url = new URL(configuredApiBaseUrl, browserOrigin);
  return `${url.origin}${url.pathname.replace(/\/$/, "")}::${ownerId}`;
}

function makeRun(overrides: Partial<AgentRunResponse> = {}): AgentRunResponse {
  return {
    id: "run-1",
    task_id: "task-1",
    connection_id: "conn-1",
    agent_name: "Hermes",
    dispatch_state: "sent",
    dispatch_error_code: null,
    reported_state: null,
    run_version: 0,
    stopped_reporting: false,
    connection_disconnected: false,
    reply_pending: false,
    cancel_requested: false,
    needs_user: false,
    primary_state_label: "Sent",
    progress_text: null,
    question_text: null,
    result_text: null,
    result_link: null,
    result_link_interactive: false,
    failure_reason: null,
    content_expired: false,
    content_expires_at: "2026-09-08T12:00:00Z",
    last_contact_at: null,
    reporting_window_seconds: 3600,
    capabilities: { progress: true, reply: true, cancel: true },
    manifest: null,
    events: [],
    commands: [],
    created_at: "2026-08-09T12:00:00Z",
    revision: 1,
    ...overrides
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function ConnectionNames(): React.JSX.Element {
  const connections = useAgentConnections(true);
  return <div>{connections.data?.map((item) => item.name).join(", ") ?? "Loading relay"}</div>;
}

function renderProtectedConnections(client: QueryClient) {
  const unbind = bindRelaySession(client);
  const rendered = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <ConnectionNames />
              </ProtectedRoute>
            }
          />
          <Route path="/login" element={<div>Signed out</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return { ...rendered, unbind };
}

describe("agentHooks", () => {
  afterEach(() => {
    setUnauthorizedHandler(null);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("namespaces every agent query under one stable key factory", () => {
    expect(agentKeys.all).toEqual(["agents"]);
    const scoped = agentKeys.forOwner("user-1");
    expect(scoped.all[0]).toBe("agents");
    expect(scoped.all[1]).toContain("user-1");
    expect(scoped.connections()).toEqual([...scoped.all, "connections"]);
    expect(scoped.connection("conn-1")).toEqual([...scoped.all, "connections", "conn-1"]);
    expect(scoped.runs("task-1")).toEqual([...scoped.all, "runs", "task-1"]);
    expect(scoped.run("run-1")).toEqual([...scoped.all, "run", "run-1"]);
    expect(scoped.summaries(["task-1"])).toEqual([...scoped.all, "summaries", ["task-1"]]);
  });

  it("uses distinct normalized API origins for the same owner", () => {
    const originalWindow = window;
    const atOrigin = (origin: string) => {
      const scopedWindow = Object.create(originalWindow) as Window;
      Object.defineProperty(scopedWindow, "location", { configurable: true, value: { origin } });
      vi.stubGlobal("window", scopedWindow);
      return agentKeys.forOwner("user-1").all[1];
    };

    const first = atOrigin("https://first.example.test");
    const firstAgain = atOrigin("https://first.example.test");
    const second = atOrigin("https://second.example.test");
    vi.stubGlobal("window", originalWindow);

    expect(first).toBe(expectedAgentScope("https://first.example.test", "user-1"));
    expect(firstAgain).toBe(first);
    expect(second).toBe(expectedAgentScope("https://second.example.test", "user-1"));
    expect(second === first).toBe(
      expectedAgentScope("https://second.example.test", "user-1") ===
        expectedAgentScope("https://first.example.test", "user-1")
    );
  });

  it("purges the prior API-origin scope when the authenticated origin changes", () => {
    const originalWindow = window;
    const atOrigin = (origin: string) => {
      const scopedWindow = Object.create(originalWindow) as Window;
      Object.defineProperty(scopedWindow, "location", { configurable: true, value: { origin } });
      vi.stubGlobal("window", scopedWindow);
    };
    const client = new QueryClient();
    const publicKey = ["public", "release-notes"];

    atOrigin("https://first.example.test");
    act(() => {
      useAuthStore.setState({ user: { id: "user-1", email: "one@example.test" }, status: "authed" });
    });
    client.setQueryData(agentKeys.forOwner("user-1").connections(), [connection]);
    client.setQueryData(publicKey, "keep me");
    const unbind = bindRelaySession(client);

    atOrigin("https://second.example.test");
    act(() => {
      useAuthStore.setState({ status: "authed" });
    });

    const effectiveOriginChanged =
      expectedAgentScope("https://first.example.test", "user-1") !==
      expectedAgentScope("https://second.example.test", "user-1");
    expect(client.getQueryCache().findAll({ queryKey: agentKeys.all })).toHaveLength(
      effectiveOriginChanged ? 0 : 1
    );
    expect(client.getQueryData(publicKey)).toBe("keep me");
    unbind();
  });

  it("loads the owner's connections when the relay is enabled", async () => {
    const spy = vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([connection]);

    const { result } = renderHook(() => useAgentConnections(true), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([connection]);
    expect(spy).toHaveBeenCalled();
  });

  it("never calls the gated connections endpoint while the relay is off", () => {
    const spy = vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([connection]);

    renderHook(() => useAgentConnections(false), { wrapper });

    expect(spy).not.toHaveBeenCalled();
  });

  it("loads the runs attached to one task and skips the call without a task", async () => {
    const spy = vi.spyOn(apiClient, "listAgentRuns").mockResolvedValue([run]);

    const { result } = renderHook(() => useAgentRuns("task-1", true), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([run]);

    spy.mockClear();
    renderHook(() => useAgentRuns(undefined, true), { wrapper });
    expect(spy).not.toHaveBeenCalled();
  });

  it("loads sparse run summaries only when visible tasks exist", async () => {
    const spy = vi.spyOn(apiClient, "listAgentRunSummaries").mockResolvedValue({ "task-1": run });

    const { result } = renderHook(() => useAgentRunSummaries(["task-1"], true), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalled();

    spy.mockClear();
    renderHook(() => useAgentRunSummaries([], true), { wrapper });
    expect(spy).not.toHaveBeenCalled();
  });

  it("never exposes account A relay data to account B and preserves public cache", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const publicKey = ["public", "release-notes"];
    client.setQueryData(publicKey, "keep me");
    let resolveA!: (value: AgentConnectionResponse[]) => void;
    const pendingA = new Promise<AgentConnectionResponse[]>((resolve) => {
      resolveA = resolve;
    });
    const connectionB = { ...connection, id: "conn-b", name: "Account B agent" };
    vi.spyOn(apiClient, "listAgentConnections")
      .mockReturnValueOnce(pendingA)
      .mockResolvedValueOnce([connectionB]);
    act(() => {
      useAuthStore.setState({ user: { id: "user-a", email: "a@example.test" }, status: "authed" });
    });
    const accountWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useAgentConnections(true), { wrapper: accountWrapper });

    act(() => {
      useAuthStore.setState({ user: { id: "user-b", email: "b@example.test" }, status: "authed" });
    });
    await waitFor(() => expect(result.current.data).toEqual([connectionB]));

    await act(async () => resolveA([{ ...connection, name: "Account A secret agent" }]));
    expect(result.current.data).toEqual([connectionB]);
    expect(client.getQueryData(publicKey)).toBe("keep me");
    expect(JSON.stringify(client.getQueryCache().getAll().map((query) => query.state.data))).not.toContain(
      "Account A secret agent"
    );
  });

  it("purges relay records when real logout unmounts the protected relay tree", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const publicKey = ["public", "release-notes"];
    client.setQueryData(publicKey, "keep me");
    client.getMutationCache().build(client, {
      mutationKey: agentKeys.forOwner("user-a").mutation("reply", "run-a"),
      mutationFn: async () => undefined
    });
    client.getMutationCache().build(client, {
      mutationKey: ["preferences", "save"],
      mutationFn: async () => undefined
    });
    vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([
      { ...connection, name: "Account A secret agent" }
    ]);
    vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    act(() => {
      useAuthStore.setState({ user: { id: "user-a", email: "a@example.test" }, status: "authed" });
    });
    const { unbind } = renderProtectedConnections(client);
    expect(await screen.findByText("Account A secret agent")).toBeInTheDocument();

    await act(async () => useAuthStore.getState().logout());
    expect(await screen.findByText("Signed out")).toBeInTheDocument();

    expect(client.getQueryData(publicKey)).toBe("keep me");
    expect(client.getQueryCache().findAll({ queryKey: agentKeys.all })).toHaveLength(0);
    expect(client.getMutationCache().findAll({ mutationKey: agentKeys.all })).toHaveLength(0);
    expect(client.getMutationCache().findAll({ mutationKey: ["preferences"] })).toHaveLength(1);
    unbind();
  });

  it("purges revoked owner A before a delayed owner B request can render or cache data", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const publicKey = ["public", "release-notes"];
    client.setQueryData(publicKey, "keep me");
    let resolveB!: (value: AgentConnectionResponse[]) => void;
    const pendingB = new Promise<AgentConnectionResponse[]>((resolve) => {
      resolveB = resolve;
    });
    vi.spyOn(apiClient, "listAgentConnections")
      .mockResolvedValueOnce([{ ...connection, name: "Account A secret agent" }])
      .mockReturnValueOnce(pendingB);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("revoked", { status: 401 })));
    act(() => {
      useAuthStore.setState({ user: { id: "user-a", email: "a@example.test" }, status: "authed" });
    });
    setUnauthorizedHandler(() => useAuthStore.getState().clearSession());
    const accountA = renderProtectedConnections(client);
    expect(await screen.findByText("Account A secret agent")).toBeInTheDocument();
    await act(async () => {
      await expect(apiClient.getAgentConnection("revoked-connection")).rejects.toMatchObject({ status: 401 });
    });
    expect(await screen.findByText("Signed out")).toBeInTheDocument();
    expect(client.getQueryCache().findAll({ queryKey: agentKeys.all })).toHaveLength(0);
    expect(JSON.stringify(client.getQueryCache().getAll().map((query) => query.state.data))).not.toContain(
      "Account A secret agent"
    );
    accountA.unbind();
    accountA.unmount();
    act(() => {
      useAuthStore.setState({ user: { id: "user-b", email: "b@example.test" }, status: "authed" });
    });
    const accountB = renderProtectedConnections(client);
    expect(await screen.findByText("Loading relay")).toBeInTheDocument();
    expect(screen.queryByText("Account A secret agent")).not.toBeInTheDocument();
    expect(JSON.stringify(client.getQueryCache().getAll().map((query) => query.state.data))).not.toContain(
      "Account A secret agent"
    );
    await act(async () => resolveB([{ ...connection, id: "conn-b", name: "Account B agent" }]));
    expect(await screen.findByText("Account B agent")).toBeInTheDocument();
    expect(client.getQueryData(publicKey)).toBe("keep me");
    expect(JSON.stringify(client.getQueryCache().getAll().map((query) => query.state.data))).not.toContain(
      "Account A secret agent"
    );
    accountB.unbind();
    setUnauthorizedHandler(null);
  });
});

/**
 * A polling harness with no wall-clock in it.
 *
 * Two things have to be pinned down for a poll to be observable at the exact
 * millisecond it is due. Fake timers freeze the refetch interval itself, and
 * React Query batches observer notifications through `notifyManager`, whose
 * default scheduler is a `setTimeout(cb, 0)` — also frozen. Left alone, the
 * result of a poll that fires at t=1500 only reaches the render on the *next*
 * timer advance, which reads as "the hook never updated". Notifying
 * synchronously removes that phantom frame, so each `advanceTimers` below is a
 * true statement about the hook and not a sleep long enough to paper over it.
 */
const DEFAULT_NOTIFY_SCHEDULER = (callback: () => void) => setTimeout(callback, 0);

function pollingHarness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function pollingWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, pollingWrapper };
}

describe("run polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    notifyManager.setScheduler((callback) => callback());
  });

  afterEach(() => {
    notifyManager.setScheduler(DEFAULT_NOTIFY_SCHEDULER);
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("keeps polling a run that could still move and stops once one cannot", () => {
    expect(isRunPollable(makeRun({ reported_state: null }))).toBe(true);
    expect(isRunPollable(makeRun({ reported_state: "running" }))).toBe(true);
    expect(isRunPollable(makeRun({ reported_state: "blocked" }))).toBe(true);
    // Silence is not terminal: a later valid event must still be able to land.
    expect(isRunPollable(makeRun({ reported_state: "running", stopped_reporting: true }))).toBe(true);

    expect(isRunPollable(makeRun({ reported_state: "completed" }))).toBe(false);
    expect(isRunPollable(makeRun({ reported_state: "failed" }))).toBe(false);
    expect(isRunPollable(makeRun({ reported_state: "cancelled" }))).toBe(false);
    expect(isRunPollable(makeRun({ connection_disconnected: true }))).toBe(false);
    expect(isRunPollable(makeRun({ content_expired: true }))).toBe(true);
    expect(isRunPollable(makeRun({ dispatch_state: "not_sent" }))).toBe(false);
  });

  it("backs off from 1.5s and never past the 8s cap", () => {
    expect(runPollDelay(0)).toBe(1500);
    expect(runPollDelay(1)).toBe(3000);
    expect(runPollDelay(2)).toBe(6000);
    expect(runPollDelay(3)).toBe(MAX_RUN_POLL_MS);
    expect(runPollDelay(9)).toBe(MAX_RUN_POLL_MS);
  });


  it("surfaces Sent → Running → Blocked → complete while the task stays open", async () => {
    const { pollingWrapper } = pollingHarness();
    const spy = vi
      .spyOn(apiClient, "listAgentRuns")
      .mockResolvedValueOnce([makeRun({ primary_state_label: "Sent" })])
      .mockResolvedValueOnce([
        makeRun({ reported_state: "running", primary_state_label: "Running", run_version: 1, revision: 2 })
      ])
      .mockResolvedValueOnce([
        makeRun({
          reported_state: "blocked",
          primary_state_label: "Needs you",
          needs_user: true,
          question_text: "Which environment?",
          run_version: 2,
          revision: 3
        })
      ])
      .mockResolvedValue([
        makeRun({
          reported_state: "completed",
          primary_state_label: "Agent reported complete",
          run_version: 3,
          revision: 4
        })
      ]);

    const { result, unmount } = renderHook(() => useAgentRuns("task-1", true), { wrapper: pollingWrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(result.current.data?.[0].primary_state_label).toBe("Sent");

    // Each rung of the ladder resets while the projection keeps changing, so the
    // next report is a poll away rather than a doubled wait.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(INITIAL_RUN_POLL_MS);
    });
    expect(spy).toHaveBeenCalledTimes(2);
    expect(result.current.data?.[0].reported_state).toBe("running");
    expect(result.current.data?.[0].primary_state_label).toBe("Running");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(INITIAL_RUN_POLL_MS);
    });
    expect(spy).toHaveBeenCalledTimes(3);
    expect(result.current.data?.[0].reported_state).toBe("blocked");
    expect(result.current.data?.[0].needs_user).toBe(true);
    expect(result.current.data?.[0].question_text).toBe("Which environment?");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(INITIAL_RUN_POLL_MS);
    });
    expect(spy).toHaveBeenCalledTimes(4);
    expect(result.current.data?.[0].primary_state_label).toBe("Agent reported complete");

    // Terminal: nothing further is asked, however long the task stays open.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(spy).toHaveBeenCalledTimes(4);

    // And unmounting leaves no timer behind to fire into a dead component.
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(spy).toHaveBeenCalledTimes(4);
  });

  it("climbs the backoff ladder to the cap while the projection stops changing", async () => {
    const { pollingWrapper } = pollingHarness();
    // Same revision and run_version every time: the run is alive but silent, so
    // each poll is one more rung rather than a reset.
    const spy = vi.spyOn(apiClient, "listAgentRuns").mockResolvedValue([makeRun({ reported_state: "running" })]);

    const { result, unmount } = renderHook(() => useAgentRuns("task-1", true), { wrapper: pollingWrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(spy).toHaveBeenCalledTimes(1);

    // 1.5s → 3s → 6s → 8s (capped). Each step advances one millisecond short of
    // the rung first, so an early poll would be caught rather than absorbed.
    for (const rung of [INITIAL_RUN_POLL_MS, 3000, 6000, MAX_RUN_POLL_MS, MAX_RUN_POLL_MS]) {
      const before = spy.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(rung - 1);
      });
      expect(spy).toHaveBeenCalledTimes(before);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(spy).toHaveBeenCalledTimes(before + 1);
    }
    expect(result.current.data?.[0].reported_state).toBe("running");

    unmount();
  });

  it("never polls a run that is already disconnected", async () => {
    const { pollingWrapper } = pollingHarness();
    const spy = vi
      .spyOn(apiClient, "listAgentRuns")
      .mockResolvedValue([makeRun({ connection_disconnected: true, primary_state_label: "Connection disconnected" })]);

    const { unmount } = renderHook(() => useAgentRuns("task-1", true), { wrapper: pollingWrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(spy).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(spy).toHaveBeenCalledTimes(1);

    unmount();
  });

  it("keeps the last projection on screen when a poll fails, and recovers on the next one", async () => {
    const { pollingWrapper } = pollingHarness();
    const blocked = makeRun({
      reported_state: "blocked",
      primary_state_label: "Needs you",
      needs_user: true,
      question_text: "Which environment?"
    });
    const answered = makeRun({
      reported_state: "completed",
      primary_state_label: "Agent reported complete",
      run_version: 4,
      revision: 5
    });
    const spy = vi
      .spyOn(apiClient, "listAgentRuns")
      .mockResolvedValueOnce([blocked])
      .mockRejectedValueOnce(new Error("network unreachable"))
      .mockResolvedValue([answered]);

    const { result, unmount } = renderHook(() => useAgentRuns("task-1", true), { wrapper: pollingWrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // Reading the failure fields here is load-bearing, not decoration: React
    // Query notifies an observer only about result properties something has
    // actually touched, so a field first read after the fact would still hold
    // its mount-time value while the cache had long since moved on.
    expect(result.current.data).toEqual([blocked]);
    expect(result.current.isRefetchError).toBe(false);
    expect(result.current.error).toBeNull();

    // The poll due at 1.5s fails.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(INITIAL_RUN_POLL_MS);
    });
    expect(spy).toHaveBeenCalledTimes(2);
    // The failure is reported alongside the projection, never instead of it.
    expect(result.current.data).toEqual([blocked]);
    expect(result.current.isRefetchError).toBe(true);
    expect(result.current.error).toEqual(new Error("network unreachable"));

    // A transient failure does not end the relay: the ladder keeps climbing and
    // the next successful poll replaces the stale projection.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MAX_RUN_POLL_MS);
    });
    expect(spy.mock.calls.length).toBeGreaterThan(2);
    expect(result.current.data).toEqual([answered]);
    expect(result.current.error).toBeNull();
    expect(result.current.isRefetchError).toBe(false);

    unmount();
  });
});
