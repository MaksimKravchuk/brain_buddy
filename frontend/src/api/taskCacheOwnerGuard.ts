import type { QueryClient } from "@tanstack/react-query";

import { useAuthStore } from "../stores/authStore";
import { taskKeys, taskOwnerKey } from "./taskHooks";

/**
 * Wires the task-tracker cache to the signed-in principal. login, signup,
 * logout, an unauthorized-session clear, and a hydrate resolution all fire a
 * zustand `set()` that advances the auth epoch, and zustand's default
 * listener dispatch runs synchronously inside that same call -- so this
 * purge always completes before any component can re-render against the new
 * session and observe a cache entry left by the outgoing one.
 *
 * Triggered on every epoch change, not on whether the derived owner string
 * changed: two consecutive sessions for the same user (e.g. A -> anon -> the
 * same A again) resolve to the identical owner key, so owner equality alone
 * cannot tell the outgoing session's cache apart from the incoming one's.
 * Owner-qualified cache keys (see taskKeys) already stop a *new* principal
 * from reading a *different* outgoing principal's entries by key collision;
 * this purge additionally reclaims the outgoing owner's subtree so nothing
 * still resolving against it (e.g. a mutation's own onSuccess) lingers in
 * the cache to be read later by a same-owner successor session.
 */
export function installTaskCacheOwnerGuard(queryClient: QueryClient): () => void {
  return useAuthStore.subscribe((state, previousState) => {
    if (state.epoch === previousState.epoch) {
      return;
    }
    const previousOwner = taskOwnerKey(previousState.user);
    queryClient.removeQueries({ queryKey: taskKeys.all(previousOwner) });
  });
}
