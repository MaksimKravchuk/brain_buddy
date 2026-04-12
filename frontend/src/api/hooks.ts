import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "./client";
import { buildTreeDetailFromStore, useTreeStore } from "../stores/treeStore";
import type {
  AiFeedbackRequest,
  AiFeedbackResponse,
  NodeCreateRequest,
  NodeResponse,
  NodeUpdateRequest,
  RelationCreateRequest,
  RelationResponse,
  RelationUpdateRequest,
  TreeCreateRequest,
  TreeDetailResponse,
  TreeListItem,
  TreeUpdateRequest,
  TreeImportPayload,
  ValidationHistoryResponse,
  ValidationRequest,
  ValidationResponse,
  VersionCreateRequest,
  VersionListItem
} from "./types";
import { useUiStore } from "../stores/uiStore";
import { getErrorMessage } from "../utils/error";

export const treeKeys = {
  all: ["trees"] as const,
  list: () => [...treeKeys.all, "list"] as const,
  detail: (treeId: string) => [...treeKeys.all, "detail", treeId] as const,
  versions: (treeId: string) => [...treeKeys.detail(treeId), "versions"] as const,
  validationHistory: (treeId: string, nodeId: string) =>
    [...treeKeys.detail(treeId), "validation", nodeId] as const
};

function isTreeListItem(value: unknown): value is TreeListItem {
  if (!value || typeof value !== "object") {
    return false;
  }

  const item = value as Partial<TreeListItem> & { owner_id?: unknown };
  const hasValidOwnerId =
    item.owner_id === undefined || item.owner_id === null || typeof item.owner_id === "string";

  return (
    typeof item.id === "string" &&
    typeof item.name === "string" &&
    typeof item.updated_at === "string" &&
    hasValidOwnerId
  );
}

function validateTreeListResponse(trees: unknown): TreeListItem[] {
  if (!Array.isArray(trees) || trees.some((tree) => !isTreeListItem(tree))) {
    throw new Error("Invalid tree list response");
  }
  return trees;
}

export function useTrees() {
  return useQuery<TreeListItem[]>({
    queryKey: treeKeys.list(),
    queryFn: async ({ signal }) => {
      const data = await apiClient.listTrees(signal);
      return validateTreeListResponse(data);
    }
  });
}

export function useTree(treeId: string | null) {
  return useQuery<TreeDetailResponse>({
    queryKey: treeId ? treeKeys.detail(treeId) : treeKeys.detail(""),
    queryFn: ({ signal }) => {
      if (!treeId) {
        throw new Error("Tree ID is required");
      }

      return apiClient.getTree(treeId, signal);
    },
    enabled: Boolean(treeId)
  });
}

export function useCreateTree() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: TreeCreateRequest) => apiClient.createTree(payload),
    onSuccess: (tree) => {
      queryClient.invalidateQueries({ queryKey: treeKeys.list() });
      queryClient.setQueryData(treeKeys.detail(tree.id), tree);
    }
  });
}

export function useUpdateTree(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: TreeUpdateRequest) => apiClient.updateTree(treeId, payload),
    onSuccess: (tree) => {
      queryClient.invalidateQueries({ queryKey: treeKeys.list() });
      queryClient.setQueryData(treeKeys.detail(treeId), tree);
    }
  });
}

/**
 * Renames the currently active tree. Rebuilds the full `TreeUpdateRequest`
 * payload from the live tree store (the backend requires a complete tree on
 * PUT). On success, it refreshes React Query caches and seeds the store with
 * the server response so the header name updates immediately.
 */
export function useRenameTree(treeId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (newName: string) => {
      if (!treeId) {
        throw new Error("No active tree to rename");
      }
      const detail = buildTreeDetailFromStore(useTreeStore.getState());
      if (!detail) {
        throw new Error("Active tree is not loaded");
      }
      const payload: TreeUpdateRequest = {
        name: newName,
        metadata: detail.metadata,
        nodes: detail.nodes,
        relations: detail.relations,
        owner_id: detail.owner_id ?? null
      };
      return apiClient.updateTree(treeId, payload);
    },
    onSuccess: (tree) => {
      useTreeStore.getState().setTree(tree);
      queryClient.setQueryData(treeKeys.detail(tree.id), tree);
      queryClient.invalidateQueries({ queryKey: treeKeys.list() });
    }
  });
}

export function useDeleteTree() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (treeId: string) => apiClient.deleteTree(treeId),
    onSuccess: (_, treeId) => {
      queryClient.setQueryData<TreeListItem[] | undefined>(treeKeys.list(), (trees) =>
        trees ? trees.filter((tree) => tree.id !== treeId) : trees
      );
      queryClient.invalidateQueries({ queryKey: treeKeys.list() });
      queryClient.removeQueries({ queryKey: treeKeys.detail(treeId) });
    }
  });
}

export function useCreateNode(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: NodeCreateRequest) => apiClient.createNode(treeId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: treeKeys.detail(treeId) });
    }
  });
}

export function useUpdateNode(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ nodeId, payload }: { nodeId: string; payload: NodeUpdateRequest }) =>
      apiClient.updateNode(treeId, nodeId, payload),
    onSuccess: (_data, { nodeId }) => {
      queryClient.invalidateQueries({ queryKey: treeKeys.detail(treeId) });
      queryClient.invalidateQueries({ queryKey: treeKeys.validationHistory(treeId, nodeId) });
    }
  });
}

export function useDeleteNode(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ nodeId, cascade }: { nodeId: string; cascade?: boolean }) =>
      apiClient.deleteNode(treeId, nodeId, cascade),
    onSuccess: (_data, { nodeId }) => {
      queryClient.invalidateQueries({ queryKey: treeKeys.detail(treeId) });
      queryClient.invalidateQueries({ queryKey: treeKeys.validationHistory(treeId, nodeId) });
    }
  });
}

export function useCreateRelation(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RelationCreateRequest) => apiClient.createRelation(treeId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: treeKeys.detail(treeId) });
    }
  });
}

export function useUpdateRelation(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ relationId, payload }: { relationId: string; payload: RelationUpdateRequest }) =>
      apiClient.updateRelation(treeId, relationId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: treeKeys.detail(treeId) });
    }
  });
}

export function useDeleteRelation(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (relationId: string) => apiClient.deleteRelation(treeId, relationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: treeKeys.detail(treeId) });
    }
  });
}

export function useCreateVersion(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: VersionCreateRequest) => apiClient.createVersion(treeId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: treeKeys.detail(treeId) });
      queryClient.invalidateQueries({ queryKey: treeKeys.versions(treeId) });
    }
  });
}

export function useDeleteVersion(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (versionId: string) => apiClient.deleteVersion(treeId, versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: treeKeys.detail(treeId) });
      queryClient.invalidateQueries({ queryKey: treeKeys.versions(treeId) });
    }
  });
}

export function useRestoreVersion(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (versionId: string) => apiClient.restoreVersion(treeId, versionId),
    onSuccess: (tree) => {
      queryClient.setQueryData(treeKeys.detail(treeId), tree);
    }
  });
}

export function useExportTree(treeId: string) {
  return useMutation({
    mutationFn: () => apiClient.exportTree(treeId)
  });
}

export function useImportTree() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (tree: TreeImportPayload) => apiClient.importTree(tree),
    onSuccess: (tree) => {
      queryClient.invalidateQueries({ queryKey: treeKeys.list() });
      queryClient.setQueryData(treeKeys.detail(tree.id), tree);
    }
  });
}

export function useValidation(treeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ nodeId, payload }: { nodeId: string; payload: ValidationRequest }) =>
      apiClient.triggerValidation(treeId, nodeId, payload),
    onSuccess: (_result, { nodeId }) => {
      queryClient.invalidateQueries({ queryKey: treeKeys.detail(treeId) });
      queryClient.invalidateQueries({ queryKey: treeKeys.validationHistory(treeId, nodeId) });
    }
  });
}

export function useValidationHistory(treeId: string, nodeId: string | null) {
  return useQuery<ValidationHistoryResponse>({
    queryKey: nodeId ? treeKeys.validationHistory(treeId, nodeId) : treeKeys.validationHistory(treeId, ""),
    queryFn: ({ signal }) => {
      if (!nodeId) {
        throw new Error("Node ID is required");
      }

      return apiClient.getValidationHistory(treeId, nodeId, signal);
    },
    enabled: Boolean(nodeId)
  });
}

export function useAiFeedback(treeId: string | null) {
  const pushToast = useUiStore((state) => state.pushToast);
  return useMutation<AiFeedbackResponse, unknown, AiFeedbackRequest>({
    mutationFn: (payload: AiFeedbackRequest) => {
      if (!treeId) {
        throw new Error("Tree ID is required");
      }

      return apiClient.aiFeedback(treeId, payload);
    },
    onError: (error) => {
      pushToast({
        title: "AI feedback failed",
        description: getErrorMessage(error),
        variant: "error",
        duration: 6000
      });
    }
  });
}

export function useTreeDownload(treeId: string | null) {
  const pushToast = useUiStore((state) => state.pushToast);
  const exportTreeMutation = useExportTree(treeId ?? "");

  const download = () => {
    if (!treeId) {
      pushToast({
        title: "Select a tree first",
        description: "Choose a tree to export before downloading.",
        variant: "warning",
        duration: 4000
      });
      return;
    }

    const toastId = pushToast({
      title: "Preparing download…",
      variant: "info",
      duration: 0
    });

    exportTreeMutation.mutate(undefined, {
      onSuccess: ({ tree }) => {
        const filename = `${tree.name}-${tree.metadata.updated_at.replace(/[:]/g, "")}.json`;
        const content = JSON.stringify(tree, null, 2);
        if (typeof window !== "undefined") {
          const blob = new Blob([content], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement("a");
          anchor.href = url;
          anchor.download = filename;
          document.body.appendChild(anchor);
          anchor.click();
          anchor.remove();
          window.setTimeout(() => URL.revokeObjectURL(url), 0);
        }
        pushToast({
          id: toastId,
          title: "Download ready",
          description: filename,
          variant: "success",
          duration: 4000
        });
      },
      onError: (error) => {
        pushToast({
          id: toastId,
          title: "Download failed",
          description: getErrorMessage(error),
          variant: "error",
          duration: 6000
        });
      }
    });
  };

  return { download, isDownloading: exportTreeMutation.isPending };
}

function parseImportPayload(raw: unknown): TreeImportPayload {
  if (!raw || typeof raw !== "object") {
    throw new Error("Import file must be JSON");
  }
  const candidate = raw as Partial<TreeImportPayload>;
  if (!candidate.id || !candidate.name || !candidate.metadata || !candidate.nodes || !candidate.relations) {
    throw new Error("Import file is missing required fields");
  }
  return candidate as TreeImportPayload;
}

export function useTreeImportWithToasts(onImported?: (tree: TreeDetailResponse) => void) {
  const importTreeMutation = useImportTree();
  const pushToast = useUiStore((state) => state.pushToast);

  const importFromFile = async (file: File) => {
    const toastId = pushToast({
      title: "Importing tree…",
      description: file.name,
      variant: "info",
      duration: 0
    });

    let parsed: unknown;
    try {
      const content = await file.text();
      parsed = JSON.parse(content);
    } catch (error) {
      pushToast({
        id: toastId,
        title: "Invalid import file",
        description: error instanceof Error ? error.message : "Could not read file",
        variant: "error",
        duration: 6000
      });
      return;
    }

    let payload: TreeImportPayload;
    try {
      payload = parseImportPayload(parsed);
    } catch (error) {
      pushToast({
        id: toastId,
        title: "Import failed",
        description: error instanceof Error ? error.message : "Import file is not valid",
        variant: "error",
        duration: 6000
      });
      return;
    }

    try {
      const tree = await importTreeMutation.mutateAsync(payload);
      onImported?.(tree);
      pushToast({
        id: toastId,
        title: "Imported tree",
        description: tree.name,
        variant: "success",
        duration: 4000
      });
    } catch (error) {
      pushToast({
        id: toastId,
        title: "Import failed",
        description: getErrorMessage(error),
        variant: "error",
        duration: 6000
      });
    }
  };

  return { importFromFile, isImporting: importTreeMutation.isPending };
}
