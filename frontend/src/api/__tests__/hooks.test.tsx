import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import * as clientModule from "../client";
import { apiClient } from "../client";
import { useExportTree, useImportTree, useTrees, useTreeImportWithToasts } from "../hooks";
import type { TreeDetailResponse, TreeImportPayload, TreeListItem } from "../types";
import { useUiStore } from "../../stores/uiStore";

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
    useUiStore.getState().clearToasts();
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

  it("imports from file with owner mapping and success toast", async () => {
    const tree: TreeDetailResponse = {
      id: "tree-9",
      name: "File Import",
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

    const ownerSpy = vi.spyOn(clientModule, "getOwnerId").mockReturnValue("owner-123");
    const importSpy = vi.spyOn(apiClient, "importTree").mockResolvedValue(tree);
    const onImported = vi.fn();

    const { result } = renderHook(() => useTreeImportWithToasts(onImported), {
      wrapper: createWrapper(queryClient)
    });

    const file = {
      name: "tree.json",
      text: () => Promise.resolve(JSON.stringify(tree))
    } as unknown as File;

    await act(async () => {
      await result.current.importFromFile(file);
    });

    await waitFor(() =>
      expect(importSpy).toHaveBeenCalledWith({
        ...tree,
        owner_id: "owner-123",
        metadata: { ...tree.metadata, owner_id: "owner-123" }
      })
    );
    expect(onImported).toHaveBeenCalledWith(tree);
    const toast = useUiStore.getState().toasts.find((t) => t.title === "Imported tree");
    expect(toast?.description).toBe("File Import");
    ownerSpy.mockRestore();
  });
});
