import { useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuthStore } from "../stores/authStore";
import type { AgentRunResponse } from "./agentTypes";
import { apiClient } from "./client";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

function normalizedApiOrigin(): string {
  if (typeof window === "undefined") {
    return API_BASE_URL.replace(/\/$/, "");
  }
  const url = new URL(API_BASE_URL, window.location.origin);
  return `${url.origin}${url.pathname.replace(/\/$/, "")}`;
}

export interface AgentKeyset {
  all: readonly ["agents", string];
  connections: () => readonly ["agents", string, "connections"];
  connection: (connectionId: string) => readonly ["agents", string, "connections", string];
  runs: (taskId: string) => readonly ["agents", string, "runs", string];
  run: (runId: string) => readonly ["agents", string, "run", string];
  summaries: (taskIds: string[]) => readonly ["agents", string, "summaries", string[]];
  handoffPreview: (
    taskId: string,
    connectionId: string | null,
    includeDetails: boolean,
    contextItems: unknown[]
  ) => readonly ["agents", string, "handoff-preview", string, string | null, boolean, unknown[]];
  mutation: (operation: string, target?: string) => readonly ["agents", string, "mutation", string, string?];
}

export function agentKeysFor(ownerId: string | null): AgentKeyset {
  const scope = `${normalizedApiOrigin()}::${ownerId ?? "anonymous"}`;
  const all = ["agents", scope] as const;
  return {
    all,
    connections: () => [...all, "connections"] as const,
    connection: (connectionId) => [...all, "connections", connectionId] as const,
    runs: (taskId) => [...all, "runs", taskId] as const,
    run: (runId) => [...all, "run", runId] as const,
    summaries: (taskIds) => [...all, "summaries", taskIds] as const,
    handoffPreview: (taskId, connectionId, includeDetails, contextItems) =>
      [...all, "handoff-preview", taskId, connectionId, includeDetails, contextItems] as const,
    mutation: (operation, target) =>
      target ? [...all, "mutation", operation, target] as const : [...all, "mutation", operation] as const
  };
}

/** Legacy root used only for relay-wide predicates and compatibility assertions. */
export const agentKeys = {
  all: ["agents"] as const,
  forOwner: agentKeysFor
};

export function useAgentKeys(): AgentKeyset {
  const ownerId = useAuthStore((state) => state.user?.id ?? null);
  return useMemo(() => agentKeysFor(ownerId), [ownerId]);
}

/** 1.5s → ×2 → 8s cap, the same ladder the iOS run machine climbs. */
export const INITIAL_RUN_POLL_MS = 1500;
export const MAX_RUN_POLL_MS = 8000;
export const SUMMARY_POLL_MS = 15000;

const TERMINAL_REPORTED_STATES = new Set(["completed", "failed", "cancelled"]);

export function isRunPollable(run: AgentRunResponse): boolean {
  if (run.reported_state !== null && TERMINAL_REPORTED_STATES.has(run.reported_state)) {
    return false;
  }
  // Expiry is a content boundary, not a lifecycle terminal: late authenticated
  // reports may still advance coarse state/contact metadata.
  return !run.connection_disconnected && run.dispatch_state !== "not_sent";
}

/**
 * How long to wait before asking again, given how long nothing has changed.
 *
 * The ladder climbs so a quiet run costs less, and the ceiling is the *lower*
 * of the client's own cap and the server's observation interval. A deployment
 * that observes every five seconds should be polled every five, not eight —
 * and one that observes every sixty is still polled at the client cap, because
 * a read also resets the server's own backoff and a reply's answer can land
 * between two observations.
 */
export function runPollDelay(
  pollsSinceChange: number,
  observationIntervalSeconds?: number
): number {
  const ceiling =
    observationIntervalSeconds && observationIntervalSeconds > 0
      ? Math.min(MAX_RUN_POLL_MS, observationIntervalSeconds * 1000)
      : MAX_RUN_POLL_MS;
  return Math.min(INITIAL_RUN_POLL_MS * 2 ** Math.max(0, pollsSinceChange), ceiling);
}

/** The tightest interval any pollable run in the list asks for. */
function pollCeilingSeconds(runs: AgentRunResponse[]): number | undefined {
  const intervals = runs
    .filter(isRunPollable)
    .map((run) => run.observation_interval_seconds)
    .filter((seconds) => typeof seconds === "number" && seconds > 0);
  return intervals.length ? Math.min(...intervals) : undefined;
}

function runsSignature(runs: AgentRunResponse[]): string {
  return runs.map((run) => `${run.id}:${run.revision}:${run.run_version}`).join("|");
}

export function useAgentRunSummaries(taskIds: string[], enabled: boolean) {
  const keys = useAgentKeys();
  return useQuery({
    enabled: enabled && taskIds.length > 0,
    queryKey: keys.summaries(taskIds),
    queryFn: ({ signal }) => apiClient.listAgentRunSummaries(taskIds, signal),
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
    refetchInterval: SUMMARY_POLL_MS,
    refetchIntervalInBackground: false
  });
}

export function useAgentConnections(enabled: boolean) {
  const keys = useAgentKeys();
  return useQuery({
    enabled,
    queryKey: keys.connections(),
    queryFn: ({ signal }) => apiClient.listAgentConnections(signal)
  });
}

export function useAgentRuns(taskId: string | undefined, enabled: boolean) {
  const ladder = useRef<{ signature: string; atUpdateCount: number } | null>(null);
  const keys = useAgentKeys();

  return useQuery({
    enabled: enabled && Boolean(taskId),
    queryKey: keys.runs(taskId ?? ""),
    queryFn: ({ signal }) => apiClient.listAgentRuns(taskId ?? "", signal),
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
    refetchInterval: (query) => {
      const runs = query.state.data;
      if (!runs || !runs.some(isRunPollable)) {
        ladder.current = null;
        return false;
      }
      const signature = runsSignature(runs);
      if (!ladder.current || ladder.current.signature !== signature) {
        ladder.current = { signature, atUpdateCount: query.state.dataUpdateCount };
      }
      return runPollDelay(
        query.state.dataUpdateCount - ladder.current.atUpdateCount,
        pollCeilingSeconds(runs)
      );
    },
    refetchIntervalInBackground: false
  });
}
