import { useQuery } from "@tanstack/react-query";

import { apiClient } from "./client";
import { useAuthStore } from "../stores/authStore";

export const adminKeys = {
  status: () => ["admin", "status"] as const
};

// Server-issued operator capability check (009-FR-002), shared by AccountMenu
// and AdminPage so both gate on the same source of truth. Only enabled once a
// session exists; a 401/403 is terminal (not an operator), so it is never
// retried -- retrying would just repeat the same denial.
export function useAdminStatus() {
  const isAuthed = useAuthStore((state) => state.status === "authed");
  return useQuery({
    enabled: isAuthed,
    queryKey: adminKeys.status(),
    queryFn: ({ signal }) => apiClient.getAdminStatus(signal),
    retry: false
  });
}
