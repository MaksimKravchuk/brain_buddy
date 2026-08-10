import type { QueryClient, QueryKey } from "@tanstack/react-query";

export const PRIVATE_AGENT_ROOT = ["agents", "private"] as const;

function hasPrivateAgentPrefix(key: QueryKey | undefined): boolean {
  return (
    Array.isArray(key) &&
    key.length >= PRIVATE_AGENT_ROOT.length &&
    PRIVATE_AGENT_ROOT.every((part, index) => key[index] === part)
  );
}

/**
 * Removes only account-private external-agent state.
 *
 * Cancellation comes first so a request that was already in flight cannot put
 * its old owner's data back after removal. Mutation records are removed too;
 * mutation functions themselves are not abortable, so every mutation also
 * captures its owner in its key and invalidates only that owner's queries.
 */
export async function resetPrivateAgentState(queryClient: QueryClient): Promise<void> {
  await queryClient.cancelQueries({ queryKey: PRIVATE_AGENT_ROOT });
  queryClient.removeQueries({ queryKey: PRIVATE_AGENT_ROOT });

  const mutationCache = queryClient.getMutationCache();
  for (const mutation of mutationCache.getAll()) {
    if (hasPrivateAgentPrefix(mutation.options.mutationKey)) {
      mutationCache.remove(mutation);
    }
  }
}
