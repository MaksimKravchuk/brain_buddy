import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { apiClient } from "../client";
import { useExportTree, useImportTree, useTrees } from "../hooks";
import type { TreeDetailResponse, TreeImportPayload, TreeListItem } from "../types";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("api hooks", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false
        }
      }
    });
  });

  afterEach(() => {
    queryClient.clear();
    vi.restoreAllMocks();
  });

  it("uses listTrees for useTrees", async () => {
    const trees: TreeListItem[] = [
      { id: "tree-1", name: "One", updated_at: "2025-01-01T00:00:00Z", owner_id: null }
    ];
    const spy = vi.spyOn(apiClient, "listTrees").mockResolvedValue(trees);

    const { result } = renderHook(() => useTrees(), { wrapper: createWrapper(queryClient) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(trees);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("exports a tree via useExportTree", async () => {
    const payload: TreeDetailResponse = {
      id: "tree-2",
      name: "Exportable",
      metadata: {
        version: 1,
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-01-01T00:00:00Z",
        owner_id: null,
        layout: null
      },
      nodes: [],
      relations: [],
      owner_id: null
    };
    const spy = vi.spyOn(apiClient, "exportTree").mockResolvedValue({ tree: payload });
    const { result } = renderHook(() => useExportTree("tree-2"), { wrapper: createWrapper(queryClient) });

    let response: { tree: TreeDetailResponse } | undefined;
    await act(async () => {
      response = await result.current.mutateAsync();
    });

    expect(spy).toHaveBeenCalledWith("tree-2");
    expect(response?.tree).toEqual(payload);
  });

  it("imports a tree and caches detail via useImportTree", async () => {
    const importPayload: TreeImportPayload = {
      id: "tree-3",
      name: "Imported",
      metadata: {
        version: 1,
        created_at: "2025-01-02T00:00:00Z",
        updated_at: "2025-01-02T00:00:00Z",
        owner_id: null,
        layout: null
      },
      nodes: [],
      relations: [],
      owner_id: null
    };
    const spy = vi.spyOn(apiClient, "importTree").mockResolvedValue(importPayload);
    const { result } = renderHook(() => useImportTree(), { wrapper: createWrapper(queryClient) });

    await act(async () => {
      await result.current.mutateAsync(importPayload);
    });

    expect(spy).toHaveBeenCalledWith(importPayload);
    const cached = queryClient.getQueryData<TreeDetailResponse>(["trees", "detail", "tree-3"]);
    expect(cached).toEqual(importPayload);
  });
});
