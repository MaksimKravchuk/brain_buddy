import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { accountKeys, useAccountQuery } from "../accountHooks";
import type { AccountResponse } from "../accountTypes";
import { apiClient } from "../client";

const account: AccountResponse = {
  id: "user_1",
  email: "a@b.c",
  display_name: "Maks",
  created_at: "2026-08-01T00:00:00Z",
  deletion_requested_at: null,
  purge_at: null
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("accountHooks", () => {
  afterEach(() => vi.restoreAllMocks());

  it("exposes a stable key factory", () => {
    expect(accountKeys.detail()).toEqual(["account", "detail"]);
  });

  it("useAccountQuery fetches the caller's account", async () => {
    const spy = vi.spyOn(apiClient, "getAccount").mockResolvedValue(account);

    const { result } = renderHook(() => useAccountQuery(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(account);
    expect(spy).toHaveBeenCalled();
  });
});
