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
 * Removes account-private external-agent state on behalf of one session scope.
 *
 * Cancellation comes first so a request that was already in flight cannot put
 * its old owner's data back after removal. Cancelling suspends, though, and
 * that suspension is wide enough for the account being torn down to be replaced
 * by a different one and for the replacement to repopulate the cache. So
 * `ownsScope` is asked again on the way back, and every removal after that
 * answer runs in a single synchronous block — nothing can slip between the
 * check and the purge it authorises.
 *
 * A cleanup that lost the scope while suspended therefore removes nothing. That
 * is not a leak: the scope that replaced it ran this same cleanup on its way in,
 * so everything still in the cache belongs to the account now signed in.
 * `ownsScope` is required rather than defaulted precisely because an unowned
 * purge is the bug this guards against.
 *
 * Mutation records are removed too; mutation functions themselves are not
 * abortable, so every mutation also captures its owner in its key and
 * invalidates only that owner's queries.
 */
export async function resetPrivateAgentState(
  queryClient: QueryClient,
  ownsScope: () => boolean,
): Promise<void> {
  if (!ownsScope()) {
    return;
  }
  await queryClient.cancelQueries({ queryKey: PRIVATE_AGENT_ROOT });
  if (!ownsScope()) {
    return;
  }

  queryClient.removeQueries({ queryKey: PRIVATE_AGENT_ROOT });
  const mutationCache = queryClient.getMutationCache();
  for (const mutation of mutationCache.getAll()) {
    if (hasPrivateAgentPrefix(mutation.options.mutationKey)) {
      mutationCache.remove(mutation);
    }
  }
}
