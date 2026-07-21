import type { QueryClient } from "@tanstack/react-query";

import { useAuthStore } from "../stores/authStore";
import { taskKeys, taskOwnerKey } from "./taskHooks";

/**
 * Wires the task-tracker cache to the signed-in principal. login, signup,
 * logout, an unauthorized-session clear, and a hydrate resolution that
 * changes who's signed in all fire a zustand `set()`, and zustand's default
 * listener dispatch runs synchronously inside that same call -- so this
 * purge always completes before any component can re-render against the new
 * principal and observe a cache entry left by the outgoing one. Owner-
 * qualified cache keys (see taskKeys) already stop a *new* principal from
 * reading an old one's entries by key collision; this purge additionally
 * reclaims them so nothing still resolving against the outgoing owner's key
 * (e.g. a mutation's own onSuccess) lingers in the cache to be read later.
 */
export function installTaskCacheOwnerGuard(queryClient: QueryClient): () => void {
  return useAuthStore.subscribe((state, previousState) => {
    const nextOwner = taskOwnerKey(state.user);
    const previousOwner = taskOwnerKey(previousState.user);
    if (nextOwner !== previousOwner) {
      queryClient.removeQueries({ queryKey: taskKeys.all(previousOwner) });
    }
  });
}
