import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { apiClient } from "../client";
import {
  treeKeys,
  useAiFeedback,
  useCreateNode,
  useCreateRelation,
  useCreateTree,
  useCreateVersion,
  useDeleteNode,
  useDeleteRelation,
  useDeleteTree,
  useDeleteVersion,
  useExportTree,
  useImportTree,
  useRenameTree,
  useRestoreVersion,
  useTree,
  useTreeDownload,
  useTreeImportWithToasts,
  useTrees,
  useUpdateNode,
  useUpdateRelation,
  useUpdateTree,
  useValidation,
  useValidationHistory
} from "../hooks";
import type {
  NodeResponse,
  RelationResponse,
  TreeDetailResponse,
  TreeImportPayload,
  TreeListItem,
  ValidationResponse,
  VersionListItem
} from "../types";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

const node: NodeResponse = {
  id: "node-1",
  label: "Root cause",
  type: "parent",
  position: { x: 10, y: 20 },
  highlight_state: "none",
  relation_counts: { up_count: 0, down_count: 1 }
};

const relation: RelationResponse = {
  id: "relation-1",
  source_node_id: "node-1",
  target_node_id: "node-2",
  kind: "why",
  created_at: "2025-01-01T00:00:00Z"
};

const detail: TreeDetailResponse = {
  id: "tree-1",
  name: "Current tree",
  metadata: {
    version: 1,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    owner_id: null,
    layout: null
  },
  nodes: [node],
  relations: [relation],
  owner_id: null
};

const version: VersionListItem = {
  id: "version-1",
  label: "Before change",
  created_at: "2025-01-01T00:00:00Z",
  conflict_count: 0
};

const validation: ValidationResponse = {
  node_id: node.id,
  provider: "mock",
  confidence: 90,
  summary: "Looks coherent",
  checked_at: "2025-01-01T00:00:00Z"
};

describe("api hooks", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    useTreeStore.getState().reset();
    useUiStore.getState().clearToasts();
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

  it("surfaces invalid tree list response", async () => {
    vi.spyOn(apiClient, "listTrees").mockResolvedValue({} as TreeListItem[]);

    const { result } = renderHook(() => useTrees(), { wrapper: createWrapper(queryClient) });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Error);
    expect((result.current.error as Error).message).toContain("Invalid tree list response");
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

  it("imports from file and emits success toast", async () => {
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

    await waitFor(() => expect(importSpy).toHaveBeenCalledWith(tree));
    expect(onImported).toHaveBeenCalledWith(tree);
    const toast = useUiStore.getState().toasts.find((t) => t.title === "Imported tree");
    expect(toast?.description).toBe("File Import");
  });

  it("keeps caches and the active tree synchronized across editing actions", async () => {
    const renamed = { ...detail, name: "Renamed tree" };
    const feedback = { status: "success" as const, summary: "Useful", recommendations: ["Follow the cause"] };
    useTreeStore.getState().setTree(detail);
    queryClient.setQueryData(treeKeys.list(), [
      { id: detail.id, name: detail.name, updated_at: detail.metadata.updated_at, owner_id: null }
    ]);

    vi.spyOn(apiClient, "createTree").mockResolvedValue(detail);
    vi.spyOn(apiClient, "getTree").mockResolvedValue(renamed);
    const updateSpy = vi.spyOn(apiClient, "updateTree").mockResolvedValue(renamed);
    vi.spyOn(apiClient, "deleteTree").mockResolvedValue(undefined);
    vi.spyOn(apiClient, "createNode").mockResolvedValue(node);
    vi.spyOn(apiClient, "updateNode").mockResolvedValue({ ...node, label: "Updated cause" });
    vi.spyOn(apiClient, "deleteNode").mockResolvedValue(undefined);
    vi.spyOn(apiClient, "createRelation").mockResolvedValue(relation);
    vi.spyOn(apiClient, "updateRelation").mockResolvedValue(relation);
    vi.spyOn(apiClient, "deleteRelation").mockResolvedValue(undefined);
    vi.spyOn(apiClient, "createVersion").mockResolvedValue(version);
    vi.spyOn(apiClient, "deleteVersion").mockResolvedValue(undefined);
    vi.spyOn(apiClient, "restoreVersion").mockResolvedValue(renamed);
    vi.spyOn(apiClient, "triggerValidation").mockResolvedValue(validation);
    vi.spyOn(apiClient, "aiFeedback").mockResolvedValue(feedback);

    const { result } = renderHook(
      () => ({
        createTree: useCreateTree(),
        updateTree: useUpdateTree(detail.id),
        renameTree: useRenameTree(detail.id),
        deleteTree: useDeleteTree(),
        createNode: useCreateNode(detail.id),
        updateNode: useUpdateNode(detail.id),
        deleteNode: useDeleteNode(detail.id),
        createRelation: useCreateRelation(detail.id),
        updateRelation: useUpdateRelation(detail.id),
        deleteRelation: useDeleteRelation(detail.id),
        createVersion: useCreateVersion(detail.id),
        deleteVersion: useDeleteVersion(detail.id),
        restoreVersion: useRestoreVersion(detail.id),
        validation: useValidation(detail.id),
        aiFeedback: useAiFeedback(detail.id)
      }),
      { wrapper: createWrapper(queryClient) }
    );

    await act(async () => {
      await result.current.createTree.mutateAsync({ name: detail.name });
      await result.current.updateTree.mutateAsync({
        name: renamed.name,
        metadata: detail.metadata,
        nodes: detail.nodes,
        relations: detail.relations
      });
      await result.current.renameTree.mutateAsync(renamed.name);
      await result.current.createNode.mutateAsync({ label: node.label, type: node.type, position: node.position });
      await result.current.updateNode.mutateAsync({ nodeId: node.id, payload: { label: "Updated cause" } });
      await result.current.deleteNode.mutateAsync({ nodeId: node.id, cascade: true });
      await result.current.createRelation.mutateAsync({
        source_node_id: relation.source_node_id,
        target_node_id: relation.target_node_id
      });
      await result.current.updateRelation.mutateAsync({ relationId: relation.id, payload: { kind: relation.kind } });
      await result.current.deleteRelation.mutateAsync(relation.id);
      await result.current.createVersion.mutateAsync({ label: version.label });
      await result.current.deleteVersion.mutateAsync(version.id);
      await result.current.restoreVersion.mutateAsync(version.id);
      await result.current.validation.mutateAsync({ nodeId: node.id, payload: {} });
      await result.current.aiFeedback.mutateAsync({ consent: true });
    });

    expect(updateSpy).toHaveBeenCalledWith(detail.id, expect.objectContaining({ name: renamed.name }));
    expect(apiClient.deleteNode).toHaveBeenCalledWith(detail.id, node.id, true);
    expect(apiClient.triggerValidation).toHaveBeenCalledWith(detail.id, node.id, {});
    expect(apiClient.aiFeedback).toHaveBeenCalledWith(detail.id, { consent: true });
    expect(useTreeStore.getState().metadata?.name).toBe(renamed.name);
    expect(queryClient.getQueryData(treeKeys.detail(detail.id))).toEqual(renamed);

    await act(async () => {
      await result.current.deleteTree.mutateAsync(detail.id);
    });
    expect(queryClient.getQueryData<TreeListItem[]>(treeKeys.list())).toEqual([]);
  });

  it("loads selected tree details and validation history without fetching unselected records", async () => {
    const treeSpy = vi.spyOn(apiClient, "getTree").mockResolvedValue(detail);
    const historySpy = vi.spyOn(apiClient, "getValidationHistory").mockResolvedValue({ items: [validation] });

    const { result } = renderHook(
      () => ({
        tree: useTree(detail.id),
        history: useValidationHistory(detail.id, node.id),
        unselectedTree: useTree(null),
        unselectedHistory: useValidationHistory(detail.id, null)
      }),
      { wrapper: createWrapper(queryClient) }
    );

    await waitFor(() => expect(result.current.tree.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.history.isSuccess).toBe(true));

    expect(treeSpy).toHaveBeenCalledWith(detail.id, expect.any(AbortSignal));
    expect(historySpy).toHaveBeenCalledWith(detail.id, node.id, expect.any(AbortSignal));
    expect(result.current.unselectedTree.isFetching).toBe(false);
    expect(result.current.unselectedHistory.isFetching).toBe(false);
  });

  it("warns instead of exporting when no tree is selected", () => {
    const exportSpy = vi.spyOn(apiClient, "exportTree");
    const { result } = renderHook(() => useTreeDownload(null), { wrapper: createWrapper(queryClient) });

    act(() => result.current.download());

    expect(exportSpy).not.toHaveBeenCalled();
    expect(useUiStore.getState().toasts).toContainEqual(
      expect.objectContaining({ title: "Select a tree first", variant: "warning" })
    );
  });

  it("downloads a selected tree with a timestamped JSON filename", async () => {
    const createObjectURL = vi.fn(() => "blob:tree");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.spyOn(apiClient, "exportTree").mockResolvedValue({ tree: detail });
    const { result } = renderHook(() => useTreeDownload(detail.id), { wrapper: createWrapper(queryClient) });

    act(() => result.current.download());

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledOnce());
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:tree");
    expect(useUiStore.getState().toasts).toContainEqual(
      expect.objectContaining({ title: "Download ready", description: "Current tree-2025-01-01T000000Z.json" })
    );
  });

  it("explains unreadable, incomplete, and rejected import files", async () => {
    const onImported = vi.fn();
    const importSpy = vi.spyOn(apiClient, "importTree").mockRejectedValue(new Error("Service unavailable"));
    const { result } = renderHook(() => useTreeImportWithToasts(onImported), {
      wrapper: createWrapper(queryClient)
    });

    const invalidJson = { name: "broken.json", text: () => Promise.resolve("{") } as unknown as File;
    await act(async () => result.current.importFromFile(invalidJson));
    expect(useUiStore.getState().toasts).toContainEqual(
      expect.objectContaining({ title: "Invalid import file", variant: "error" })
    );

    const incomplete = {
      name: "incomplete.json",
      text: () => Promise.resolve(JSON.stringify({ id: "tree-2", name: "Incomplete" }))
    } as unknown as File;
    await act(async () => result.current.importFromFile(incomplete));
    expect(useUiStore.getState().toasts).toContainEqual(
      expect.objectContaining({ title: "Import failed", description: "Import file is missing required fields" })
    );

    const validButRejected = { name: "tree.json", text: () => Promise.resolve(JSON.stringify(detail)) } as unknown as File;
    await act(async () => result.current.importFromFile(validButRejected));

    expect(importSpy).toHaveBeenCalledWith(detail);
    expect(onImported).not.toHaveBeenCalled();
    expect(useUiStore.getState().toasts).toContainEqual(
      expect.objectContaining({ title: "Import failed", description: "Service unavailable", variant: "error" })
    );
  });

  it("rejects rename attempts when no active tree is available", async () => {
    const { result } = renderHook(() => useRenameTree(null), { wrapper: createWrapper(queryClient) });

    await expect(
      act(async () => {
        await result.current.mutateAsync("New name");
      })
    ).rejects.toThrow("No active tree to rename");
  });

  it("rejects rename attempts when the tree is not loaded yet", async () => {
    useTreeStore.setState({ activeTreeId: "tree-2" });
    const { result } = renderHook(() => useRenameTree("tree-2"), { wrapper: createWrapper(queryClient) });

    await expect(
      act(async () => {
        await result.current.mutateAsync("New name");
      })
    ).rejects.toThrow("Active tree is not loaded");
  });

  it("rejects AI feedback when no tree id is set", async () => {
    const { result } = renderHook(() => useAiFeedback(null), { wrapper: createWrapper(queryClient) });

    await expect(
      act(async () => {
        await result.current.mutateAsync({ consent: true });
      })
    ).rejects.toThrow("Tree ID is required");
  });

  it("surfaces export download failures with a toast", async () => {
    vi.spyOn(apiClient, "exportTree").mockRejectedValue(new Error("Service unavailable"));
    const { result } = renderHook(() => useTreeDownload(detail.id), { wrapper: createWrapper(queryClient) });

    await act(async () => {
      result.current.download();
    });

    await waitFor(() =>
      expect(useUiStore.getState().toasts).toContainEqual(
        expect.objectContaining({ title: "Download failed", description: "Service unavailable" })
      )
    );
  });
});
