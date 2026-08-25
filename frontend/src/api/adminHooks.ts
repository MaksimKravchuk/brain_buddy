import { useQuery, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { useMemo } from "react";

import { apiClient } from "./client";
import { useAuthStore, type AuthStatus } from "../stores/authStore";

export interface AdminKeyset {
  all: readonly ["admin", string];
  status: () => readonly ["admin", string, "status"];
  featureFlags: () => readonly ["admin", string, "feature-flags"];
  accounts: () => readonly ["admin", string, "accounts"];
}

/**
 * Keys scoped to the signed-in account, exactly as the relay keys are.
 *
 * The capability answer is an authorization fact about *one* account. A
 * constant key would let the process-global cache hand a later caller the
 * previous caller's `is_operator` with no server request at all, which is the
 * 009-FR-005 server-side check being skipped.
 */
export function adminKeysFor(ownerId: string | null): AdminKeyset {
  const all = ["admin", ownerId ?? "anonymous"] as const;
  return {
    all,
    status: () => [...all, "status"] as const,
    featureFlags: () => [...all, "feature-flags"] as const,
    accounts: () => [...all, "accounts"] as const
  };
}

export const adminKeys = {
  forOwner: adminKeysFor
};

function isAdminKey(queryKey: QueryKey | undefined): boolean {
  return queryKey?.[0] === "admin";
}

function authenticatedScope(state: { user: { id: string } | null; status: AuthStatus }): string | null {
  return state.status === "authed" && state.user ? state.user.id : null;
}

/** Remove only admin-owned records; task/account/relay caches are untouched. */
export function purgeAdminRecords(client: QueryClient): void {
  void client.cancelQueries({ predicate: (query) => isAdminKey(query.queryKey) });
  client.removeQueries({ predicate: (query) => isAdminKey(query.queryKey) });
}

/**
 * Bind one process-global QueryClient to auth before React mounts.
 *
 * Identity-scoped keys alone would already stop a *different* account reading
 * a stale answer, but the cache is held with `staleTime: Infinity`, so the
 * same account signing back in would still be served the pre-logout answer
 * with no server check — and the allow-list can change between sessions.
 * Zustand subscribers run synchronously with the session write, so this
 * cannot be skipped by component unmount ordering.
 */
export function bindAdminSession(client: QueryClient): () => void {
  let previous = authenticatedScope(useAuthStore.getState());
  return useAuthStore.subscribe((state) => {
    const current = authenticatedScope(state);
    if (previous !== null && previous !== current) {
      purgeAdminRecords(client);
    }
    previous = current;
  });
}

/**
 * Route-scoped operator capability check (009-FR-011).
 *
 * `AdminPage` is the only caller, deliberately: under PD-1 there is no menu
 * entry and no other screen may run this check, so a member who never types
 * `/admin` issues no admin request at all (009-FR-010, 009-SC-006) and the
 * denial log stays a signal rather than a stream of ordinary navigation.
 *
 * Cached for the session and never refetched on focus or remount: the answer
 * is an authorization fact about the signed-in account, not data that drifts,
 * and a focus-driven refetch storm would manufacture exactly the denial noise
 * FR-011 exists to prevent. "The session" is bounded by `bindAdminSession`
 * above — the cache does not survive a logout or an account switch. A denial
 * is terminal and is never retried; retrying would just repeat it.
 */
export function useAdminStatus() {
  const isAuthed = useAuthStore((state) => state.status === "authed");
  const ownerId = useAuthStore((state) => state.user?.id ?? null);
  const keys = useMemo(() => adminKeysFor(ownerId), [ownerId]);
  return useQuery({
    enabled: isAuthed,
    queryKey: keys.status(),
    queryFn: ({ signal }) => apiClient.getAdminStatus(signal),
    retry: false,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: false
  });
}

/**
 * Runtime feature-flag state for the operator screen (010-FR-010).
 *
 * Under the same owner-scoped `adminKeys`, so `purgeAdminRecords` and
 * `bindAdminSession` already cover it. Unlike `useAdminStatus` this query *is*
 * refetchable — flag state genuinely drifts, because another operator (or
 * another tab) can change it — but only `AdminPage` ever mounts it, so
 * 009-FR-011's "no admin request from any other screen" still holds.
 */
export function useAdminFeatureFlags() {
  const isAuthed = useAuthStore((state) => state.status === "authed");
  const ownerId = useAuthStore((state) => state.user?.id ?? null);
  const keys = useMemo(() => adminKeysFor(ownerId), [ownerId]);
  return useQuery({
    enabled: isAuthed,
    queryKey: keys.featureFlags(),
    queryFn: ({ signal }) => apiClient.getAdminFeatureFlags(signal),
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false
  });
}

export function useAdminAccounts() {
  const isAuthed = useAuthStore((state) => state.status === "authed");
  const ownerId = useAuthStore((state) => state.user?.id ?? null);
  const keys = useMemo(() => adminKeysFor(ownerId), [ownerId]);
  return useQuery({
    enabled: isAuthed,
    queryKey: keys.accounts(),
    queryFn: ({ signal }) => apiClient.listAdminAccounts(signal),
    retry: false,
    refetchOnWindowFocus: false
  });
}