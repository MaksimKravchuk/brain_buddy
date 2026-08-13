import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { useAuthStore, type AuthStatus } from "../stores/authStore";
import { agentKeysFor } from "./agentHooks";

function isRelayKey(queryKey: QueryKey | undefined): boolean {
  return queryKey?.[0] === "agents";
}

function authenticatedScope(state: { user: { id: string } | null; status: AuthStatus }): string | null {
  return state.status === "authed" && state.user ? agentKeysFor(state.user.id).all[1] : null;
}

/** Remove only relay-owned records; task/account/public caches survive session changes. */
export function purgeRelayRecords(client: QueryClient): void {
  void client.cancelQueries({ predicate: (query) => isRelayKey(query.queryKey) });
  client.removeQueries({ predicate: (query) => isRelayKey(query.queryKey) });
  for (const mutation of client.getMutationCache().getAll()) {
    if (isRelayKey(mutation.options.mutationKey)) {
      client.getMutationCache().remove(mutation);
    }
  }
}

/**
 * Bind one process-global QueryClient to auth before React mounts. Zustand
 * subscribers run synchronously with the session write, so cleanup cannot be
 * skipped when ProtectedRoute unmounts relay components on logout or a 401.
 */
export function bindRelaySession(client: QueryClient): () => void {
  let previous = authenticatedScope(useAuthStore.getState());
  return useAuthStore.subscribe((state) => {
    const current = authenticatedScope(state);
    if (previous !== null && previous !== current) {
      purgeRelayRecords(client);
    }
    previous = current;
  });
}
