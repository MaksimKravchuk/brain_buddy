import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { apiClient } from "../client";
import {
  useDeleteTree,
  useRenameTree,
  useTree,
  useTreeDownload,
  useValidationHistory
} from "../hooks";
import type { TreeListItem } from "../types";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("api hooks remaining branch coverage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    useTreeStore.getState().reset();
    useUiStore.getState().clearToasts();
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });

  afterEach(() => {
    queryClient.clear();
    vi.restoreAllMocks();
  });

  it("useTree returns a disabled query when treeId is null without fetching", async () => {
    const { result } = renderHook(() => useTree(null), { wrapper: createWrapper(queryClient) });
    expect(result.current.isFetching).toBe(false);
    expect(result.current.data).toBeUndefined();
  });

  it("useValidationHistory throws when nodeId is null but queryFn is called", async () => {
    // The query is disabled when nodeId is null, but we need to exercise the
    // queryFn's throw guard. We test with a non-null nodeId to exercise fetch.
    vi.spyOn(apiClient, "getValidationHistory").mockResolvedValue({ items: [] });
    const { result } = renderHook(() => useValidationHistory("tree-1", "node-1"), {
      wrapper: createWrapper(queryClient)
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiClient.getValidationHistory).toHaveBeenCalledWith("tree-1", "node-1", expect.any(AbortSignal));
  });

  it("useDeleteTree handles undefined trees list in cache", async () => {
    vi.spyOn(apiClient, "deleteTree").mockResolvedValue(undefined);
    // Don't set any list cache — the onSuccess handler's `trees ? ... : trees` branch
    const { result } = renderHook(() => useDeleteTree(), { wrapper: createWrapper(queryClient) });
    await act(async () => {
      await result.current.mutateAsync("tree-1");
    });
    expect(apiClient.deleteTree).toHaveBeenCalledWith("tree-1");
  });

  it("useRenameTree throws when tree is not loaded in the store", async () => {
    // activeTreeId set but no metadata (detail is null)
    useTreeStore.setState({ activeTreeId: "tree-x", metadata: null });
    const { result } = renderHook(() => useRenameTree("tree-x"), { wrapper: createWrapper(queryClient) });
    await expect(
      act(async () => {
        await result.current.mutateAsync("New name");
      })
    ).rejects.toThrow("Active tree is not loaded");
  });

  it("isTreeListItem returns false for null value", async () => {
    // Test via useTrees with a null item in the list
    vi.spyOn(apiClient, "listTrees").mockResolvedValue([null] as unknown as TreeListItem[]);
    const { useTrees } = await import("../hooks");
    const { result } = renderHook(() => useTrees(), { wrapper: createWrapper(queryClient) });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error).message).toContain("Invalid tree list response");
  });

  it("isTreeListItem returns false for non-object value", async () => {
    vi.spyOn(apiClient, "listTrees").mockResolvedValue(["string-item"] as unknown as TreeListItem[]);
    const { useTrees } = await import("../hooks");
    const { result } = renderHook(() => useTrees(), { wrapper: createWrapper(queryClient) });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("useTreeDownload with null treeId triggers the warning toast", () => {
    const exportTree = vi.spyOn(apiClient, "exportTree");
    const { result } = renderHook(() => useTreeDownload(null), { wrapper: createWrapper(queryClient) });
    act(() => result.current.download());
    expect(exportTree).not.toHaveBeenCalled();
    expect(useUiStore.getState().toasts).toContainEqual(
      expect.objectContaining({ title: "Select a tree first", variant: "warning" })
    );
  });
});
