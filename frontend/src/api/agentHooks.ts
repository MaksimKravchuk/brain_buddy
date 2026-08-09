import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import type { AgentRunResponse } from "./agentTypes";
import { apiClient } from "./client";

export const agentKeys = {
  all: ["agents"] as const,
  connections: () => [...agentKeys.all, "connections"] as const,
  connection: (connectionId: string) => [...agentKeys.all, "connections", connectionId] as const,
  runs: (taskId: string) => [...agentKeys.all, "runs", taskId] as const,
  run: (runId: string) => [...agentKeys.all, "run", runId] as const,
  summaries: (taskIds: string[]) => [...agentKeys.all, "summaries", taskIds] as const
};

/** 1.5s → ×2 → 8s cap, the same ladder the iOS run machine climbs. */
export const INITIAL_RUN_POLL_MS = 1500;
export const MAX_RUN_POLL_MS = 8000;

/** The compact list has no timeline to follow, so it just stays fresh. */
export const SUMMARY_POLL_MS = 15000;

const TERMINAL_REPORTED_STATES = new Set(["completed", "failed", "cancelled"]);

/**
 * Whether a further report could still change this run.
 *
 * Mirrors `mobile/src/agents/machine.ts`: terminal means the connector said so,
 * and silence never becomes terminal — a run that stopped reporting stays
 * pollable because a later valid event must still be able to land (FR-013).
 */
export function isRunPollable(run: AgentRunResponse): boolean {
  if (run.reported_state !== null && TERMINAL_REPORTED_STATES.has(run.reported_state)) {
    return false;
  }
  // Disconnect ends the relay (FR-016), expired content has nothing left to
  // refresh (FR-015), and an undispatched run was never sent (FR-006).
  return !run.connection_disconnected && !run.content_expired && run.dispatch_state !== "not_sent";
}

export function runPollDelay(pollsSinceChange: number): number {
  return Math.min(INITIAL_RUN_POLL_MS * 2 ** Math.max(0, pollsSinceChange), MAX_RUN_POLL_MS);
}

/**
 * What "the projection changed" means for backoff purposes.
 *
 * `revision` covers BrainBuddy's own record (commands included) and
 * `run_version` the connector's, so either moving is real news and resets the
 * ladder to its fastest rung.
 */
function runsSignature(runs: AgentRunResponse[]): string {
  return runs.map((run) => `${run.id}:${run.revision}:${run.run_version}`).join("|");
}

/**
 * The latest run per task, for the compact list surface.
 *
 * Keyed on the visible task IDs so paging or filtering asks only about what is
 * on screen. The answer is sparse: tasks without a hand-off are simply absent.
 * It refreshes on its own so a run that starts needing the user surfaces on the
 * list without a page reload.
 */
export function useAgentRunSummaries(taskIds: string[], enabled: boolean) {
  return useQuery({
    enabled: enabled && taskIds.length > 0,
    queryKey: agentKeys.summaries(taskIds),
    queryFn: ({ signal }) => apiClient.listAgentRunSummaries(taskIds, signal),
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
    // A summary carries no reported state to judge terminality by, so this is a
    // flat interval rather than the run backoff — and only while the tab is
    // actually being looked at.
    refetchInterval: SUMMARY_POLL_MS,
    refetchIntervalInBackground: false
  });
}

/**
 * The owner's saved connections.
 *
 * `enabled` carries the `external_agent_relay` rollout flag: the backend answers
 * 404 while the flag is OFF, so asking at all would only manufacture an error
 * toast for a capability the user cannot see.
 */
export function useAgentConnections(enabled: boolean) {
  return useQuery({
    enabled,
    queryKey: agentKeys.connections(),
    queryFn: ({ signal }) => apiClient.listAgentConnections(signal)
  });
}

/**
 * Every external run attached to one task, kept live while one can still move.
 *
 * Always refetched on mount rather than served stale: closing and reopening the
 * app must show the server's projection, never a cached claim about what the
 * external agent is doing (FR-018). Beyond that it polls on the same bounded
 * ladder iOS uses, and stops entirely once nothing on screen can change — a
 * terminal, disconnected, or expired run is not worth another request. A failed
 * poll leaves the last projection in place; React Query surfaces the error
 * alongside it rather than replacing it with a blank surface.
 */
export function useAgentRuns(taskId: string | undefined, enabled: boolean) {
  // Which projection the ladder is currently climbing away from. Derived from
  // query state (not a render counter) so re-renders cannot advance the backoff.
  const ladder = useRef<{ signature: string; atUpdateCount: number } | null>(null);

  return useQuery({
    enabled: enabled && Boolean(taskId),
    queryKey: agentKeys.runs(taskId ?? ""),
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
      return runPollDelay(query.state.dataUpdateCount - ladder.current.atUpdateCount);
    },
    refetchIntervalInBackground: false
  });
}
