import { useQuery } from "@tanstack/react-query";

import { apiClient } from "./client";
import { useAuthStore } from "../stores/authStore";

export const adminKeys = {
  status: () => ["admin", "status"] as const
};

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
 * FR-011 exists to prevent. A denial is terminal and is never retried —
 * retrying would just repeat it.
 */
export function useAdminStatus() {
  const isAuthed = useAuthStore((state) => state.status === "authed");
  return useQuery({
    enabled: isAuthed,
    queryKey: adminKeys.status(),
    queryFn: ({ signal }) => apiClient.getAdminStatus(signal),
    retry: false,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: false
  });
}
