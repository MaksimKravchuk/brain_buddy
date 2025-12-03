import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "./client";
import type {
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
  ValidationHistoryResponse,
  ValidationRequest,
  ValidationResponse,
  VersionCreateRequest,
  VersionListItem
} from "./types";

export const treeKeys = {
  all: ["trees"] as const,
  list: () => [...treeKeys.all, "list"] as const,
  detail: (treeId: string) => [...treeKeys.all, "detail", treeId] as const,
  versions: (treeId: string) => [...treeKeys.detail(treeId), "versions"] as const,
  validationHistory: (treeId: string, nodeId: string) =>
    [...treeKeys.detail(treeId), "validation", nodeId] as const
};

export function useTrees() {
  return useQuery<TreeListItem[]>({
    queryKey: treeKeys.list(),
    queryFn: ({ signal }) => apiClient.listTrees(signal)
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

export function useDeleteTree() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (treeId: string) => apiClient.deleteTree(treeId),
    onSuccess: (_, treeId) => {
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
