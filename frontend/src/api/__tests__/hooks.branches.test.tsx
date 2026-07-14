import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { apiClient } from "../client";
import {
  treeKeys,
  useAiFeedback,
  useDeleteVersion,
  useImportTree,
  useTreeDownload,
  useTreeImportWithToasts,
  useValidationHistory
} from "../hooks";
import type {
  AiFeedbackResponse,
  TreeDetailResponse,
  TreeListItem,
  ValidationHistoryResponse,
  VersionListItem
} from "../types";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("api hooks branch coverage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    useTreeStore.getState().reset();
    useUiStore.getState().clearToasts();
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });
  afterEach(() => {
    queryClient.clear();
    vi.restoreAllMocks();
    useUiStore.getState().clearToasts();
  });

  it("removes the deleted tree from the list cache via useDeleteTree", async () => {
    const trees: TreeListItem[] = [
      { id: "tree-1", name: "One", updated_at: "2025-01-01T00:00:00Z", owner_id: null },
      { id: "tree-2", name: "Two", updated_at: "2025-01-02T00:00:00Z", owner_id: null }
    ];
    queryClient.setQueryData(treeKeys.list(), trees);
    vi.spyOn(apiClient, "deleteTree").mockResolvedValue(undefined);

    const { useDeleteTree } = await import("../hooks");
    const { result } = renderHook(() => useDeleteTree(), { wrapper: createWrapper(queryClient) });
    await act(async () => {
      await result.current.mutateAsync("tree-1");
    });
    expect(queryClient.getQueryData<TreeListItem[]>(treeKeys.list())).toEqual([
      { id: "tree-2", name: "Two", updated_at: "2025-01-02T00:00:00Z", owner_id: null }
    ]);
  });

  it("removes the version from cache via useDeleteVersion", async () => {
    vi.spyOn(apiClient, "deleteVersion").mockResolvedValue(undefined);
    const { useDeleteVersion } = await import("../hooks");
    const { result } = renderHook(() => useDeleteVersion("tree-1"), { wrapper: createWrapper(queryClient) });
    await act(async () => {
      await result.current.mutateAsync("version-1");
    });
    expect(apiClient.deleteVersion).toHaveBeenCalledWith("tree-1", "version-1");
  });

  it("surfaces AI feedback failures with a toast", async () => {
    vi.spyOn(apiClient, "aiFeedback").mockRejectedValue(new Error("AI unavailable"));
    const { result } = renderHook(() => useAiFeedback("tree-1"), { wrapper: createWrapper(queryClient) });

    await act(async () => {
      await expect(result.current.mutateAsync({ consent: true })).rejects.toThrow("AI unavailable");
    });
    expect(useUiStore.getState().toasts).toContainEqual(
      expect.objectContaining({ title: "AI feedback failed", description: "AI unavailable", variant: "error" })
    );
  });

  it("loads validation history with a null nodeId (disabled query)", async () => {
    const { result } = renderHook(() => useValidationHistory("tree-1", null), { wrapper: createWrapper(queryClient) });
    expect(result.current.isFetching).toBe(false);
  });

  it("rejects import file with non-object JSON", async () => {
    const onImported = vi.fn();
    const { result } = renderHook(() => useTreeImportWithToasts(onImported), { wrapper: createWrapper(queryClient) });
    const file = { name: "bad.json", text: () => Promise.resolve("123") } as unknown as File;

    await act(async () => {
      await result.current.importFromFile(file);
    });
    expect(useUiStore.getState().toasts).toContainEqual(
      expect.objectContaining({ title: "Import failed", description: "Import file must be JSON" })
    );
  });

  it("rejects import file when text() returns a non-JSON array", async () => {
    const onImported = vi.fn();
    const { result } = renderHook(() => useTreeImportWithToasts(onImported), { wrapper: createWrapper(queryClient) });
    const file = { name: "arr.json", text: () => Promise.resolve("[1,2,3]") } as unknown as File;

    await act(async () => {
      await result.current.importFromFile(file);
    });
    expect(useUiStore.getState().toasts).toContainEqual(
      expect.objectContaining({ title: "Import failed", description: "Import file is missing required fields" })
    );
  });

  it("rejects a tree list response where an item has an invalid owner_id type", async () => {
    vi.spyOn(apiClient, "listTrees").mockResolvedValue([
      { id: "tree-1", name: "Bad", updated_at: "2025-01-01T00:00:00Z", owner_id: 42 }
    ] as unknown as TreeListItem[]);

    const { useTrees } = await import("../hooks");
    const { result } = renderHook(() => useTrees(), { wrapper: createWrapper(queryClient) });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error).message).toContain("Invalid tree list response");
  });
});
