import type { CrtTreeListItem } from "../../api/crt";
import { useAuthStore, type AuthStatus } from "../../stores/authStore";

export const CRT_LAST_TREE_PREFERENCE_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const STORAGE_PREFIX = "bb.crt.lastTree.v1.";
const SWEEP_INTERVAL_MS = 15 * 60 * 1000;

export interface CrtLastTreePreferenceScope {
  ownerId: string;
  origin: string;
}

export type LastTreePreferenceScope = CrtLastTreePreferenceScope;

type StoredLastTreePreference = Readonly<{
  last_tree_id: string;
  updated_at: string;
}>;

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function normalizedOrigin(origin: string): string {
  try {
    const parsed = new URL(origin);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.origin : "";
  } catch {
    return "";
  }
}

export function crtLastTreePreferenceKey(scope: CrtLastTreePreferenceScope): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(normalizedOrigin(scope.origin))}:${encodeURIComponent(scope.ownerId)}`;
}

function asNow(value: number | string): number {
  return typeof value === "number" ? value : Date.parse(value);
}

function parseRecord(raw: string | null, now: number): StoredLastTreePreference | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<StoredLastTreePreference>;
    const updatedAt = typeof value.updated_at === "string" ? Date.parse(value.updated_at) : Number.NaN;
    if (
      typeof value.last_tree_id !== "string" || value.last_tree_id.length === 0 ||
      !Number.isFinite(updatedAt) || !Number.isFinite(now) || updatedAt > now ||
      now - updatedAt >= CRT_LAST_TREE_PREFERENCE_TTL_MS
    ) return null;
    return { last_tree_id: value.last_tree_id, updated_at: new Date(updatedAt).toISOString() };
  } catch {
    return null;
  }
}

function eligibleTrees(scope: CrtLastTreePreferenceScope, trees: readonly CrtTreeListItem[]): CrtTreeListItem[] {
  return trees.filter((tree) => tree.owner_id === scope.ownerId);
}

function newestTree(trees: readonly CrtTreeListItem[]): CrtTreeListItem | null {
  return [...trees].sort((left, right) => {
    const timestampOrder = Date.parse(right.updated_at) - Date.parse(left.updated_at);
    return timestampOrder || left.id.localeCompare(right.id);
  })[0] ?? null;
}

export function rememberCrtLastTreePreference(
  scope: CrtLastTreePreferenceScope,
  treeId: string,
  updatedAt: number | string = Date.now()
): void {
  const target = storage();
  const origin = normalizedOrigin(scope.origin);
  const timestamp = asNow(updatedAt);
  if (!target || !scope.ownerId || !origin || !treeId || !Number.isFinite(timestamp)) return;
  try {
    target.setItem(crtLastTreePreferenceKey({ ...scope, origin }), JSON.stringify({
      last_tree_id: treeId,
      updated_at: new Date(timestamp).toISOString()
    } satisfies StoredLastTreePreference));
  } catch {
    // Preference storage is optional and must not block tree navigation.
  }
}

export function clearCrtLastTreePreference(scope: CrtLastTreePreferenceScope): void {
  try {
    storage()?.removeItem(crtLastTreePreferenceKey(scope));
  } catch {
    // Best-effort cleanup when storage is revoked during a session.
  }
}

export function readCrtLastTreePreference(
  scope: CrtLastTreePreferenceScope,
  trees: readonly CrtTreeListItem[],
  now: number | string = Date.now()
): CrtTreeListItem | null {
  const eligible = eligibleTrees(scope, trees);
  const fallback = newestTree(eligible);
  const target = storage();
  if (!target) return fallback;
  const key = crtLastTreePreferenceKey(scope);
  let raw: string | null;
  try {
    raw = target.getItem(key);
  } catch {
    return fallback;
  }
  const record = parseRecord(raw, asNow(now));
  if (!record) {
    try { if (raw !== null) target.removeItem(key); } catch { /* optional cleanup */ }
    return fallback;
  }
  const preferred = eligible.find((tree) => tree.id === record.last_tree_id);
  if (!preferred) {
    try { target.removeItem(key); } catch { /* optional cleanup */ }
    return fallback;
  }
  return preferred;
}

export function sweepCrtLastTreePreferences(now: number | string = Date.now()): void {
  const target = storage();
  if (!target) return;
  const staleKeys: string[] = [];
  try {
    for (let index = 0; index < target.length; index += 1) {
      const key = target.key(index);
      if (key?.startsWith(STORAGE_PREFIX) && !parseRecord(target.getItem(key), asNow(now))) staleKeys.push(key);
    }
    for (const key of staleKeys) target.removeItem(key);
  } catch {
    // Storage cleanup is opportunistic.
  }
}

function ownerFrom(state: { user: { id: string } | null; status: AuthStatus }): string | null {
  return state.status === "authed" ? state.user?.id ?? null : null;
}

export function bindCrtLastTreePreferenceSession(origin = globalThis.location?.origin ?? ""): () => void {
  let previousOwner = ownerFrom(useAuthStore.getState());
  const sweep = () => sweepCrtLastTreePreferences();
  sweep();
  const unsubscribe = useAuthStore.subscribe((state) => {
    const currentOwner = ownerFrom(state);
    if (previousOwner && previousOwner !== currentOwner) {
      clearCrtLastTreePreference({ ownerId: previousOwner, origin });
    }
    previousOwner = currentOwner;
  });
  if (typeof window === "undefined") return unsubscribe;
  window.addEventListener("focus", sweep);
  const timer = window.setInterval(sweep, SWEEP_INTERVAL_MS);
  return () => {
    unsubscribe();
    window.removeEventListener("focus", sweep);
    window.clearInterval(timer);
  };
}

// Short aliases keep the module convenient for CRT callers without exposing storage details.
export const lastTreePreferenceKey = crtLastTreePreferenceKey;
export const rememberLastTreePreference = rememberCrtLastTreePreference;
export const clearLastTreePreference = clearCrtLastTreePreference;
export const readLastTreePreference = readCrtLastTreePreference;
export const sweepLastTreePreferences = sweepCrtLastTreePreferences;
export const bindLastTreePreferenceSession = bindCrtLastTreePreferenceSession;
