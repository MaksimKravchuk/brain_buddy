/**
 * Owner-scoped run feed for one task.
 *
 * Reopening the app refetches the server projection; closing it only stops the
 * timer and never cancels a run (FR-018). A transient transport failure keeps
 * the last projection on screen and flips `online` to false so the surface can
 * say the state is potentially stale instead of quietly looking current.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AppState } from "react-native";

import type { AgentRunResponse } from "@/api/types";
import {
  applyRun,
  applyRuns,
  isOfflineError,
  isRunPollable,
  nextPollDelay,
  projectRunsAt,
} from "@/agents/machine";
import { useSession } from "@/auth/SessionProvider";
import { normalizeServerUrl } from "@/config/serverUrl";

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

export interface AgentRunsPollRuntime {
  now?: () => number;
  schedule: (callback: () => void, delayMs: number) => () => void;
}

const defaultPollRuntime: AgentRunsPollRuntime = {
  schedule: (callback, delayMs) => {
    const timer = setTimeout(callback, delayMs);
    return () => clearTimeout(timer);
  },
};

export function useAgentRunsFeed(
  taskId: string,
  enabled: boolean,
  runtime: AgentRunsPollRuntime = defaultPollRuntime,
): AgentRunsFeed {
  const { api, serverUrl, accountId, serverTimeAnchor } = useSession();
  const normalizedServerUrl = normalizeServerUrl(serverUrl);
  const scope = useMemo(
    () => ({ api, serverUrl: normalizedServerUrl, accountId, taskId }),
    [api, normalizedServerUrl, accountId, taskId],
  );
  const emptyView = useCallback(
    () => ({ scope, runs: [] as AgentRunResponse[], loading: enabled, error: null as unknown, online: true, lastSyncedAt: null as number | null }),
    [enabled, scope],
  );
  const [view, setView] = useState(emptyView);
  if (view.scope !== scope) {
    setView(emptyView());
  }

  // The committed scope. Every async continuation compares against it before
  // touching shared state: a request issued under an older scope answers for
  // another task or another account, so its result may not reach this hook's
  // cache, its timer or its view. Published in the layout phase because refs
  // may not be written during render — and because it runs ahead of every
  // passive effect in the same commit, no fetch is armed under a scope this
  // ref has not caught up to yet.
  const liveScopeRef = useRef(scope);
  useLayoutEffect(() => {
    liveScopeRef.current = scope;
  }, [scope]);
  const isCurrentScope = useCallback(() => liveScopeRef.current === scope, [scope]);
  const updateView = useCallback(
    (patch: Partial<Omit<typeof view, "scope">>) => {
      setView((current) => current.scope === scope ? { ...current, ...patch } : current);
    },
    [scope],
  );

  const runsRef = useRef({ scope, runs: [] as AgentRunResponse[] });
  const cancelPollRef = useRef<(() => void) | null>(null);
  const pollDelayRef = useRef<number | null>(null);
  const activeRef = useRef(false);
  const schedulePollRef = useRef<(current?: AgentRunResponse[] | null) => void>(() => undefined);
  const effectScopeRef = useRef(scope);
  const now = useCallback(() => {
    if (!serverTimeAnchor) {
      return Number.POSITIVE_INFINITY;
    }
    const monotonicNow = runtime.now?.() ?? performance.now();
    return serverTimeAnchor.serverTimeMs + (monotonicNow - serverTimeAnchor.monotonicTimeMs);
  }, [runtime, serverTimeAnchor]);

  const remember = useCallback(
    (incoming: AgentRunResponse[]) => {
      if (!isCurrentScope()) {
        return null;
      }
      const current = runsRef.current.scope === scope ? runsRef.current.runs : [];
      const next = applyRuns(current, projectRunsAt(incoming, now()));
      runsRef.current = { scope, runs: next };
      updateView({ runs: next });
      return next;
    },
    [isCurrentScope, now, scope, updateView],
  );

  const fetchOnce = useCallback(async () => {
    try {
      const fresh = await api.listAgentRuns(taskId);
      if (!isCurrentScope()) {
        return null;
      }
      updateView({ error: null, online: true, lastSyncedAt: now() });
      return remember(fresh);
    } catch (caught) {
      if (!isCurrentScope()) {
        return null;
      }
      updateView({ error: caught, online: !isOfflineError(caught) });
      return null;
    } finally {
      if (isCurrentScope()) {
        updateView({ loading: false });
      }
    }
  }, [api, taskId, isCurrentScope, remember, now, updateView]);

  const clearPoll = useCallback(() => {
    cancelPollRef.current?.();
    cancelPollRef.current = null;
  }, []);

  // `schedulePollRef` always holds the *current* scope's scheduler, so a stale
  // continuation reaching it would seed the live timer with another scope's
  // runs. Only the scope that issued the request may hand results back.
  const scheduleAfter = useCallback(
    (fresh: AgentRunResponse[] | null) => {
      if (!isCurrentScope()) {
        return;
      }
      schedulePollRef.current(fresh);
    },
    [isCurrentScope],
  );

  const schedulePoll = useCallback(
    (current?: AgentRunResponse[] | null) => {
      if (!isCurrentScope()) {
        return;
      }
      const source = current ?? (runsRef.current.scope === scope ? runsRef.current.runs : []);
      const pollable = source.some(isRunPollable);
      const currentNow = now();
      const expiryDelay = serverTimeAnchor
        ? source
            .filter((run) => !run.content_expired)
            .map((run) => Date.parse(run.content_expires_at))
            .filter((deadline) => !Number.isNaN(deadline) && deadline > currentNow)
            .reduce<number | null>(
              (earliest, deadline) =>
                earliest === null || deadline - currentNow < earliest
                  ? deadline - currentNow
                  : earliest,
              null,
            )
        : null;
      if (!activeRef.current || (!pollable && expiryDelay === null) || cancelPollRef.current) {
        if (!pollable) {
          pollDelayRef.current = null;
        }
        return;
      }
      const nextPollingDelay = pollable ? nextPollDelay(pollDelayRef.current) : null;
      const expiryWake =
        expiryDelay !== null && (nextPollingDelay === null || expiryDelay <= nextPollingDelay);
      // Native/JS timers overflow above a signed 32-bit delay. An early wake
      // simply projects again and rearms the remaining retention interval.
      const delay = Math.min(
        expiryWake ? (expiryDelay as number) : (nextPollingDelay as number),
        2_147_483_647,
      );
      if (!expiryWake) {
        pollDelayRef.current = delay;
      }
      cancelPollRef.current = runtime.schedule(() => {
        // A timer that outlived its scope owns nothing here any more — not even
        // `cancelPollRef`, which the current scope may already have re-armed.
        if (!isCurrentScope()) {
          return;
        }
        cancelPollRef.current = null;
        if (expiryWake) {
          const sourceRuns = runsRef.current.scope === scope ? runsRef.current.runs : [];
          const projected = projectRunsAt(sourceRuns, now());
          runsRef.current = { scope, runs: projected };
          updateView({ runs: projected });
          schedulePollRef.current(projected);
        } else {
          void fetchOnce().then(scheduleAfter);
        }
      }, delay);
    },
    [fetchOnce, isCurrentScope, now, runtime, scheduleAfter, scope, serverTimeAnchor, updateView],
  );
  useEffect(() => {
    schedulePollRef.current = schedulePoll;
  }, [schedulePoll]);

  const absorb = useCallback(
    (incoming: AgentRunResponse) => {
      // A mutation that resolved after the task or account changed answers for
      // the scope it was issued under, not this one.
      if (!isCurrentScope()) {
        return;
      }
      const projected = projectRunsAt([incoming], now())[0];
      const current = runsRef.current.scope === scope ? runsRef.current.runs : [];
      const next = current.some((run) => run.id === projected.id)
        ? current.map((run) => (run.id === projected.id ? applyRun(run, projected) : run))
        : [projected, ...current];
      runsRef.current = { scope, runs: next };
      updateView({ runs: next });
      // A command just changed the run: look again promptly. There is still at
      // most one owned timer, including the empty-list → first-handoff edge.
      clearPoll();
      pollDelayRef.current = null;
      schedulePollRef.current(next);
    },
    [clearPoll, isCurrentScope, now, scope, updateView],
  );

  const refresh = useCallback(() => {
    if (!isCurrentScope()) {
      return;
    }
    clearPoll();
    pollDelayRef.current = null;
    void fetchOnce().then(scheduleAfter);
  }, [clearPoll, fetchOnce, isCurrentScope, scheduleAfter]);

  useEffect(() => {
    if (effectScopeRef.current !== scope) {
      effectScopeRef.current = scope;
      activeRef.current = false;
      clearPoll();
      pollDelayRef.current = null;
      runsRef.current = { scope, runs: [] };
    }
    if (!enabled) {
      activeRef.current = false;
      return;
    }
    activeRef.current = true;
    void Promise.resolve().then(fetchOnce).then(scheduleAfter);

    // Returning to the foreground resets the backoff: the user is looking now.
    const subscription = AppState.addEventListener("change", (state) => {
      if (!isCurrentScope()) {
        return;
      }
      clearPoll();
      if (state === "active") {
        pollDelayRef.current = null;
        void fetchOnce().then(scheduleAfter);
      }
    });

    return () => {
      activeRef.current = false;
      subscription.remove();
      clearPoll();
    };
  }, [clearPoll, enabled, fetchOnce, isCurrentScope, scheduleAfter, scope]);

  return {
    runs: view.scope === scope ? view.runs : [],
    loading: view.scope === scope ? view.loading : enabled,
    error: view.scope === scope ? view.error : null,
    online: view.scope === scope ? view.online : true,
    lastSyncedAt: view.scope === scope ? view.lastSyncedAt : null,
    refresh,
    absorb,
  };
}
