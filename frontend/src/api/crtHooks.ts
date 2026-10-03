import { getApiBaseUrl } from "./client";
import { useAuthStore } from "../stores/authStore";

/**
 * Scope for CRT server data. The API origin is part of the key because the
 * process-global React Query cache can outlive a deployment or tenant switch.
 */
export type CrtCacheScope = Readonly<{
  ownerId: string | null;
  apiOrigin: string;
}>;

export type CrtKeyset = {
  all: readonly ["crt", CrtCacheScope];
  exposure: () => readonly ["crt", "exposure", CrtCacheScope];
  trees: () => readonly ["crt", "trees", CrtCacheScope];
  list: () => readonly ["crt", "trees", CrtCacheScope, "list"];
  detail: (treeId: string) => readonly ["crt", "trees", CrtCacheScope, "detail", string];
  export: (treeId: string) => readonly ["crt", "trees", CrtCacheScope, "export", string];
};

/** Read the current auth/origin scope without subscribing a component. */
export function getCrtCacheScope(ownerId = useAuthStore.getState().user?.id ?? null): CrtCacheScope {
  return { ownerId, apiOrigin: getApiBaseUrl() };
}

/**
 * Build all CRT keys for one captured owner/origin scope.
 *
 * Capturing the scope when a query is created prevents a response from one
 * account or API origin from being read through another account's key.
 */
export function crtKeysFor(scope: CrtCacheScope): CrtKeyset {
  const all = ["crt", scope] as const;
  const trees = ["crt", "trees", scope] as const;
  return {
    all,
    exposure: () => ["crt", "exposure", scope] as const,
    trees: () => trees,
    list: () => [...trees, "list"] as const,
    detail: (treeId) => [...trees, "detail", treeId] as const,
    export: (treeId) => [...trees, "export", treeId] as const
  };
}

/** Root plus convenience methods for the active authenticated scope. */
export const crtKeys = {
  all: ["crt"] as const,
  forScope: crtKeysFor,
  exposure: (scope = getCrtCacheScope()) => crtKeysFor(scope).exposure(),
  trees: (scope = getCrtCacheScope()) => crtKeysFor(scope).trees(),
  list: (scope = getCrtCacheScope()) => crtKeysFor(scope).list(),
  detail: (treeId: string, scope = getCrtCacheScope()) => crtKeysFor(scope).detail(treeId),
  export: (treeId: string, scope = getCrtCacheScope()) => crtKeysFor(scope).export(treeId)
};
