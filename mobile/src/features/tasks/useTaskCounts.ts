import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/auth/SessionProvider";
import { useSession } from "@/auth/SessionProvider";
import type { TaskCounts } from "@/api/types";

/**
 * Open counts by state for tab badges. Lives under the `["tasks"]` query
 * root so every task mutation refreshes it.
 */
export function useTaskCounts(): TaskCounts | undefined {
  const api = useApi();
  const { status } = useSession();
  const query = useQuery({
    queryKey: ["tasks", "counts"],
    queryFn: async ({ signal }) => {
      const page = await api.listTasks({ limit: 1 }, signal);
      return page.counts_by_state;
    },
    enabled: status === "signed-in",
    staleTime: 15_000,
  });
  return query.data;
}
