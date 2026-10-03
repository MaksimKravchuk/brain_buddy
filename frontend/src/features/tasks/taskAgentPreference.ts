import type { AgentConnectionResponse } from "../../api/agentTypes";
import { getApiBaseUrl } from "../../api/client";
import { useAuthStore, type AuthStatus } from "../../stores/authStore";

const STORAGE_PREFIX = "bb.taskAgent.lastUsed.v1.";
export const TASK_AGENT_PREFERENCE_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const SWEEP_INTERVAL_MS = 15 * 60 * 1000;

export interface TaskAgentPreferenceScope {
  ownerId: string;
  apiOrigin: string;
}

interface StoredTaskAgentPreference {
  connectionId: string;
  confirmedAt: number;
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function taskAgentPreferenceKey(scope: TaskAgentPreferenceScope): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(scope.apiOrigin)}:${encodeURIComponent(scope.ownerId)}`;
}

function parseRecord(raw: string | null, now: number): StoredTaskAgentPreference | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<StoredTaskAgentPreference>;
    if (
      typeof value.connectionId !== "string" ||
      value.connectionId.length === 0 ||
      typeof value.confirmedAt !== "number" ||
      !Number.isFinite(value.confirmedAt) ||
      value.confirmedAt > now ||
      now - value.confirmedAt > TASK_AGENT_PREFERENCE_TTL_MS
    ) {
      return null;
    }
    return { connectionId: value.connectionId, confirmedAt: value.confirmedAt };
  } catch {
    return null;
  }
}

export function rememberTaskAgentPreference(
  scope: TaskAgentPreferenceScope,
  connectionId: string,
  confirmedAt = Date.now()
): void {
  const target = storage();
  if (!target || !connectionId) return;
  try {
    target.setItem(taskAgentPreferenceKey(scope), JSON.stringify({ connectionId, confirmedAt }));
  } catch {
    // Preference storage is optional. A blocked/full store must not block hand-off.
  }
}

export function clearTaskAgentPreference(scope: TaskAgentPreferenceScope): void {
  try {
    storage()?.removeItem(taskAgentPreferenceKey(scope));
  } catch {
    // Best-effort cleanup for browsers that revoke storage while the tab lives.
  }
}

export function readTaskAgentPreference(
  scope: TaskAgentPreferenceScope,
  connections: readonly AgentConnectionResponse[],
  now = Date.now()
): AgentConnectionResponse | null {
  const eligible = connections.filter((connection) => connection.ready_for_handoff);
  const fallback = eligible[0] ?? null;
  const target = storage();
  if (!target) return fallback;

  const key = taskAgentPreferenceKey(scope);
  const record = parseRecord(target.getItem(key), now);
  if (!record) {
    target.removeItem(key);
    return fallback;
  }
  const preferred = eligible.find((connection) => connection.id === record.connectionId);
  if (!preferred) {
    target.removeItem(key);
    return fallback;
  }
  return preferred;
}

export function sweepTaskAgentPreferences(now = Date.now()): void {
  const target = storage();
  if (!target) return;
  const staleKeys: string[] = [];
  for (let index = 0; index < target.length; index += 1) {
    const key = target.key(index);
    if (key?.startsWith(STORAGE_PREFIX) && !parseRecord(target.getItem(key), now)) {
      staleKeys.push(key);
    }
  }
  for (const key of staleKeys) target.removeItem(key);
}

function ownerFrom(state: { user: { id: string } | null; status: AuthStatus }): string | null {
  return state.status === "authed" ? state.user?.id ?? null : null;
}

/** Production lifecycle binding: expiry sweep plus synchronous owner cleanup. */
export function bindTaskAgentPreferenceSession(apiOrigin = getApiBaseUrl()): () => void {
  let previousOwner = ownerFrom(useAuthStore.getState());
  const sweep = () => sweepTaskAgentPreferences();
  sweep();

  const unsubscribe = useAuthStore.subscribe((state) => {
    const currentOwner = ownerFrom(state);
    if (previousOwner && previousOwner !== currentOwner) {
      clearTaskAgentPreference({ ownerId: previousOwner, apiOrigin });
    }
    previousOwner = currentOwner;
  });
  window.addEventListener("focus", sweep);
  const timer = window.setInterval(sweep, SWEEP_INTERVAL_MS);

  return () => {
    unsubscribe();
    window.removeEventListener("focus", sweep);
    window.clearInterval(timer);
  };
}
