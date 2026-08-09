/**
 * Owner-scoped run feed for one task.
 *
 * Reopening the app refetches the server projection; closing it only stops the
 * timer and never cancels a run (FR-018). A transient transport failure keeps
 * the last projection on screen and flips `online` to false so the surface can
 * say the state is potentially stale instead of quietly looking current.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

import type { AgentRunResponse } from "@/api/types";
import { applyRun, applyRuns, isOfflineError, isRunPollable, nextPollDelay } from "@/agents/machine";
import { useApi } from "@/auth/SessionProvider";

export interface AgentRunsFeed {
  runs: AgentRunResponse[];
  loading: boolean;
  error: unknown;
  /** False once a request failed before reaching the server. */
  online: boolean;
  lastSyncedAt: number | null;
  refresh: () => void;
  /** Merge a run a mutation just returned, monotonically. */
  absorb: (run: AgentRunResponse) => void;
}

export function useAgentRunsFeed(taskId: string, enabled: boolean): AgentRunsFeed {
  const api = useApi();
  const [runs, setRuns] = useState<AgentRunResponse[]>([]);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<unknown>(null);
  const [online, setOnline] = useState(true);
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);

  const runsRef = useRef<AgentRunResponse[]>([]);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollDelayRef = useRef<number | null>(null);

  const remember = useCallback((incoming: AgentRunResponse[]) => {
    const next = applyRuns(runsRef.current, incoming);
    runsRef.current = next;
    setRuns(next);
    return next;
  }, []);

  const fetchOnce = useCallback(async () => {
    try {
      const fresh = await api.listAgentRuns(taskId);
      setError(null);
      setOnline(true);
      setLastSyncedAt(Date.now());
      return remember(fresh);
    } catch (caught) {
      setError(caught);
      setOnline(!isOfflineError(caught));
      return null;
    } finally {
      setLoading(false);
    }
  }, [api, taskId, remember]);

  const absorb = useCallback((incoming: AgentRunResponse) => {
    const next = runsRef.current.some((run) => run.id === incoming.id)
      ? runsRef.current.map((run) => (run.id === incoming.id ? applyRun(run, incoming) : run))
      : [incoming, ...runsRef.current];
    runsRef.current = next;
    setRuns(next);
    // A command just changed the run: look again promptly.
    pollDelayRef.current = null;
  }, []);

  const refresh = useCallback(() => {
    pollDelayRef.current = null;
    void fetchOnce();
  }, [fetchOnce]);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let disposed = false;

    const schedule = (current: AgentRunResponse[] | null) => {
      const source = current ?? runsRef.current;
      if (disposed || !source.some(isRunPollable)) {
        pollDelayRef.current = null;
        return;
      }
      const delay = nextPollDelay(pollDelayRef.current);
      pollDelayRef.current = delay;
      pollTimerRef.current = setTimeout(async () => {
        const fresh = await fetchOnce();
        schedule(fresh);
      }, delay);
    };

    void fetchOnce().then((fresh) => schedule(fresh));

    // Returning to the foreground resets the backoff: the user is looking now.
    const subscription = AppState.addEventListener("change", (state) => {
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      if (state === "active") {
        pollDelayRef.current = null;
        void fetchOnce().then((fresh) => schedule(fresh));
      }
    });

    return () => {
      disposed = true;
      subscription.remove();
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [enabled, fetchOnce]);

  return { runs, loading, error, online, lastSyncedAt, refresh, absorb };
}
