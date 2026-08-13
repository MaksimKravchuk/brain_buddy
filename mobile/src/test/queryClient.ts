import type { QueryClient } from "@tanstack/react-query";

/** Release every timer and cache entry owned by a test-only QueryClient. */
export function disposeQueryClient(client: QueryClient): void {
  for (const mutation of client.getMutationCache().getAll()) {
    mutation.destroy();
  }
  client.clear();
}
