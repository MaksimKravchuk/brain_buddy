import { useQuery } from "@tanstack/react-query";

import { apiClient } from "./client";

export const accountKeys = {
  all: ["account"] as const,
  detail: () => [...accountKeys.all, "detail"] as const
};

export function useAccountQuery() {
  return useQuery({
    queryKey: accountKeys.detail(),
    queryFn: ({ signal }) => apiClient.getAccount(signal)
  });
}
