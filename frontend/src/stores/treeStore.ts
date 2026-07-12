import { create } from "zustand";

import { apiClient } from "../api/client";
import { nowMs, recordTelemetry } from "../utils/telemetry";

import type {
  NodeResponse,
  RelationResponse,
  TreeDetailResponse,
  TreeUpdateRequest,
  VersionListItem
} from "../api/types";

export interface GraphNode {
  id: string;
  label: string;
  type: NodeResponse["type"];
  position: { x: number; y: number };
  highlightState: NodeResponse["highlight_state"];
  relationCounts: { up: number; down: number };
}

export interface GraphRelation {
  id: string;
  fromId: string;
  toId: string;
  kind: RelationResponse["kind"];
  createdAt: string;
}

export interface GraphVersion {
  id: string;
  label: string;
  author?: string | null;
  notes?: string | null;
  createdAt: string;
  diffSummary?: {
    nodesAdded: number;
    nodesRemoved: number;
    nodesModified: number;
    relationsAdded: number;
    relationsRemoved: number;
    relationsModified: number;
  } | null;
  conflictCount: number;
}

export interface TreeMetadata {
  id: string;
  name: string;
  version: number;
  createdAt: string;
  updatedAt: string;
  ownerId?: string | null;
  layout?: Record<string, unknown> | null;
}

interface GraphSnapshot {
  metadata: TreeMetadata | null;
  nodes: GraphNode[];
  relations: GraphRelation[];
  versions: GraphVersion[];
  selection: SelectionState;
}

interface OptimisticChange {
  id: string;
  description: string;
  snapshot: GraphSnapshot;
}

type SelectionState =
  | { type: "node"; id: string }
  | { type: "relation"; id: string }
  | { type: "version"; id: string }
  | { type: null; id: null };

interface TreeStoreState {
  activeTreeId: string | null;
  metadata: TreeMetadata | null;
  nodes: GraphNode[];
  relations: GraphRelation[];
  versions: GraphVersion[];
  selection: SelectionState;
  undoStack: GraphSnapshot[];
  redoStack: GraphSnapshot[];
  optimisticQueue: OptimisticChange[];
  maxHistory: number;
  pendingSync: boolean;
  lastChangeAt: number | null;
  lastLocalSaveAt: string | null;
  lastCloudSyncAt: string | null;
  lastSyncError: string | null;
  setTree(tree: TreeDetailResponse): void;
  reset(): void;
  select(selection: SelectionState): void;
  pushSnapshot(): void;
  undo(): void;
  redo(): void;
  beginOptimisticChange(description: string): string;
  resolveOptimisticChange(id: string): void;
  rollbackOptimisticChange(id: string): void;
  upsertNode(node: GraphNode): void;
  removeNode(nodeId: string): void;
  upsertRelation(relation: GraphRelation): void;
  removeRelation(relationId: string): void;
  setVersions(versions: GraphVersion[]): void;
  flushPendingPersistence(): Promise<void>;
}

type TreeStoreSet = (partial: Partial<TreeStoreState> | ((state: TreeStoreState) => Partial<TreeStoreState>)) => void;

export function mapNodeResponse(node: NodeResponse): GraphNode {
  return {
    id: node.id,
    label: node.label,
    type: node.type,
    position: { ...node.position },
    highlightState: node.highlight_state,
    relationCounts: {
      up: node.relation_counts.up_count,
      down: node.relation_counts.down_count
    }
  };
}

export function mapRelationResponse(relation: RelationResponse): GraphRelation {
  const fromId =
    relation.source_node_id ?? relation.source_id ?? relation.from_id ?? "";
  const toId =
    relation.target_node_id ?? relation.target_id ?? relation.to_id ?? "";
  return {
    id: relation.id,
    fromId,
    toId,
    kind: relation.kind,
    createdAt: relation.created_at
  };
}

export const TREE_DRAFT_PREFIX = "brainbuddy:tree-draft:";

const AUTOSAVE_DEBOUNCE_MS = 5000;

function toNodeResponse(node: GraphNode): NodeResponse {
  return {
    id: node.id,
    label: node.label,
    type: node.type,
    position: { ...node.position },
    highlight_state: node.highlightState,
    relation_counts: {
      up_count: node.relationCounts.up,
      down_count: node.relationCounts.down
    }
  };
}

function toRelationResponse(relation: GraphRelation): RelationResponse {
  return {
    id: relation.id,
    source_node_id: relation.fromId,
    target_node_id: relation.toId,
    kind: relation.kind,
    created_at: relation.createdAt
  };
}

export function mapVersionResponse(version: VersionListItem): GraphVersion {
  return {
    id: version.id,
    label: version.label,
    author: version.author ?? null,
    notes: version.notes ?? null,
    createdAt: version.created_at,
    diffSummary: version.diff_summary
      ? {
          nodesAdded: version.diff_summary.nodes_added,
          nodesRemoved: version.diff_summary.nodes_removed,
          nodesModified: version.diff_summary.nodes_modified,
          relationsAdded: version.diff_summary.relations_added,
          relationsRemoved: version.diff_summary.relations_removed,
          relationsModified: version.diff_summary.relations_modified
        }
      : null,
    conflictCount: version.conflict_count ?? 0
  };
}

function snapshotFromState(state: TreeStoreState): GraphSnapshot {
  return {
    metadata: state.metadata
      ? {
          ...state.metadata,
          layout: state.metadata.layout ? { ...state.metadata.layout } : state.metadata.layout
        }
      : null,
    nodes: state.nodes.map((node) => ({
      ...node,
      position: { ...node.position },
      relationCounts: { ...node.relationCounts }
    })),
    relations: state.relations.map((relation) => ({
      ...relation
    })),
    versions: state.versions.map((version) => ({
      ...version,
      diffSummary: version.diffSummary ? { ...version.diffSummary } : null
    })),
    selection: { ...state.selection }
  };
}

function applySnapshot(snapshot: GraphSnapshot) {
  return {
    metadata: snapshot.metadata
      ? {
          ...snapshot.metadata,
          layout: snapshot.metadata.layout ? { ...snapshot.metadata.layout } : snapshot.metadata.layout
        }
      : null,
    nodes: snapshot.nodes.map((node) => ({
      ...node,
      position: { ...node.position },
      relationCounts: { ...node.relationCounts }
    })),
    relations: snapshot.relations.map((relation) => ({
      ...relation
    })),
    versions: snapshot.versions.map((version) => ({
      ...version,
      diffSummary: version.diffSummary ? { ...version.diffSummary } : null
    })),
    selection: { ...snapshot.selection } as SelectionState
  };
}

function generateId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }

  return `opt-${Math.random().toString(36).slice(2, 10)}`;
}

const initialSelection: SelectionState = { type: null, id: null };

let autosaveTimer: ReturnType<typeof setTimeout> | null = null;

function clearAutosaveTimer() {
  if (autosaveTimer) {
    clearTimeout(autosaveTimer);
    autosaveTimer = null;
  }
}

export function buildTreeDetailFromStore(state: TreeStoreState): TreeDetailResponse | null {
  return mapTreeDetail(state);
}

function mapTreeDetail(state: TreeStoreState): TreeDetailResponse | null {
  if (!state.activeTreeId || !state.metadata) {
    return null;
  }

  const ownerId = state.metadata.ownerId ?? null;

  return {
    id: state.activeTreeId,
    name: state.metadata.name,
    metadata: {
      version: state.metadata.version,
      created_at: state.metadata.createdAt,
      updated_at: state.metadata.updatedAt,
      layout: state.metadata.layout ?? null,
      owner_id: ownerId
    },
    nodes: state.nodes.map(toNodeResponse),
    relations: state.relations.map(toRelationResponse),
    owner_id: ownerId
  };
}

function buildTreeUpdateRequest(detail: TreeDetailResponse) {
  return {
    name: detail.name,
    metadata: detail.metadata,
    nodes: detail.nodes,
    relations: detail.relations,
    owner_id: detail.owner_id ?? null
  } satisfies TreeUpdateRequest;
}

function persistDraft(detail: TreeDetailResponse) {
  if (typeof localStorage === "undefined") {
    return false;
  }
  try {
    localStorage.setItem(`${TREE_DRAFT_PREFIX}${detail.id}`, JSON.stringify(detail));
    return true;
  } catch (error) {
    console.warn("Failed to persist draft", error);
    return false;
  }
}

async function persistTree(get: () => TreeStoreState, set: TreeStoreSet) {
  const startMs = nowMs();
  const detail = mapTreeDetail(get());
  if (!detail) {
    return;
  }

  clearAutosaveTimer();

  const localStartMs = nowMs();
  const savedLocally = persistDraft(detail);
  recordTelemetry(
    {
      name: "tree.local_draft_save",
      durationMs: nowMs() - localStartMs,
      ok: savedLocally,
      details: { treeId: detail.id, nodes: detail.nodes.length, relations: detail.relations.length }
    },
    savedLocally ? "info" : "warn"
  );

  const localSaveAt = new Date().toISOString();
  let pendingSync = !savedLocally;
  let lastSyncError: string | null = savedLocally ? null : "Local draft save failed";
  let lastCloudSyncAt: string | null = null;
  let serverUpdatedAt: string | null = null;

  try {
    const syncedTree = await apiClient.updateTree(detail.id, buildTreeUpdateRequest(detail));
    serverUpdatedAt = syncedTree.metadata.updated_at;
    lastCloudSyncAt = serverUpdatedAt;
    pendingSync = false;
    lastSyncError = null;
  } catch (error) {
    pendingSync = true;
    lastSyncError = error instanceof Error ? error.message : "Cloud sync failed";
  }

  recordTelemetry(
    {
      name: "tree.cloud_sync",
      durationMs: nowMs() - startMs,
      ok: !pendingSync,
      details: {
        treeId: detail.id,
        nodes: detail.nodes.length,
        relations: detail.relations.length,
        error: lastSyncError
      }
    },
    pendingSync ? "warn" : "info"
  );

  set((state) => ({
    pendingSync,
    lastLocalSaveAt: savedLocally ? localSaveAt : null,
    lastCloudSyncAt,
    lastSyncError,
    metadata:
      state.metadata && serverUpdatedAt
        ? { ...state.metadata, updatedAt: serverUpdatedAt }
        : state.metadata
  }));
}

function scheduleAutosave(get: () => TreeStoreState, set: TreeStoreSet) {
  clearAutosaveTimer();
  if (!get().activeTreeId) {
    return;
  }
  autosaveTimer = setTimeout(() => {
    autosaveTimer = null;
    void persistTree(get, set);
  }, AUTOSAVE_DEBOUNCE_MS);
}

function withPendingSync(): Partial<TreeStoreState> {
  return {
    pendingSync: true,
    lastChangeAt: Date.now(),
    lastSyncError: null
  };
}

function calculateRelationCounts(nodes: GraphNode[], relations: GraphRelation[]) {
  const counts = new Map<string, { up: number; down: number }>();
  nodes.forEach((node) => counts.set(node.id, { up: 0, down: 0 }));

  relations.forEach((relation) => {
    const from = counts.get(relation.fromId);
    if (from) {
      from.up += 1;
    }
    const to = counts.get(relation.toId);
    if (to) {
      to.down += 1;
    }
  });

  return counts;
}

function reachesAllChildren(
  nodeId: string,
  adjacency: Map<string, string[]>,
  childNodes: Set<string>
) {
  if (childNodes.size === 0) {
    return false;
  }
  const visited = new Set<string>();
  const queue: string[] = [nodeId];

  while (queue.length > 0) {
    const current = queue.shift()!;
    if (visited.has(current)) {
      continue;
    }
    visited.add(current);
    const next = adjacency.get(current) ?? [];
    next.forEach((id) => {
      if (!visited.has(id)) {
        queue.push(id);
      }
    });
  }

  let covered = 0;
  childNodes.forEach((id) => {
    if (visited.has(id)) {
      covered += 1;
    }
  });

  return covered === childNodes.size;
}

function applyDerivedNodeState(nodes: GraphNode[], relations: GraphRelation[]) {
  const counts = calculateRelationCounts(nodes, relations);
  const adjacency = new Map<string, string[]>();
  const childNodes = new Set(nodes.filter((node) => node.type === "child").map((n) => n.id));

  relations.forEach((relation) => {
    const current = adjacency.get(relation.fromId) ?? [];
    current.push(relation.toId);
    adjacency.set(relation.fromId, current);
  });

  return nodes.map((node) => {
    const relationCounts = counts.get(node.id) ?? node.relationCounts;
    const hasCauseCandidateSignal = relationCounts.up >= 3;
    const hasOutgoing = (adjacency.get(node.id) ?? []).length > 0;
    const effectSpanning =
      hasOutgoing && childNodes.size > 0 && reachesAllChildren(node.id, adjacency, childNodes);

    let highlightState: GraphNode["highlightState"] = "none";
    if (hasCauseCandidateSignal) {
      highlightState = "cause_candidate";
    } else if (effectSpanning) {
      highlightState = "effect_spanning";
    }

    return {
      ...node,
      relationCounts,
      highlightState
    };
  });
}

export const useTreeStore = create<TreeStoreState>((set, get) => ({
  activeTreeId: null,
  metadata: null,
  nodes: [],
  relations: [],
  versions: [],
  selection: initialSelection,
  undoStack: [],
  redoStack: [],
  optimisticQueue: [],
  maxHistory: 20,
  pendingSync: false,
  lastChangeAt: null,
  lastLocalSaveAt: null,
  lastCloudSyncAt: null,
  lastSyncError: null,

  setTree(tree) {
    const mappedRelations = tree.relations.map(mapRelationResponse);
    const mappedNodes = applyDerivedNodeState(tree.nodes.map(mapNodeResponse), mappedRelations);
    const ownerId = tree.owner_id ?? tree.metadata.owner_id ?? null;

    set((state) => {
      let nextSelection = state.activeTreeId === tree.id ? state.selection : initialSelection;

      if (nextSelection.type === "node") {
        const exists = mappedNodes.some((node) => node.id === nextSelection.id);
        nextSelection = exists ? nextSelection : initialSelection;
      } else if (nextSelection.type === "relation") {
        const exists = mappedRelations.some((relation) => relation.id === nextSelection.id);
        nextSelection = exists ? nextSelection : initialSelection;
      }

      return {
        activeTreeId: tree.id,
        metadata: {
          id: tree.id,
          name: tree.name,
          version: tree.metadata.version,
          createdAt: tree.metadata.created_at,
          updatedAt: tree.metadata.updated_at,
          ownerId,
          layout: tree.metadata.layout ?? null
        },
        nodes: mappedNodes,
        relations: mappedRelations,
        versions: [],
        selection: nextSelection,
        undoStack: [],
        redoStack: [],
        optimisticQueue: [],
        pendingSync: false,
        lastChangeAt: null,
        lastLocalSaveAt: tree.metadata.updated_at,
        lastCloudSyncAt: tree.metadata.updated_at,
        lastSyncError: null
      };
    });
  },

  reset() {
    set(() => ({
      activeTreeId: null,
      metadata: null,
      nodes: [],
      relations: [],
      versions: [],
      selection: initialSelection,
      undoStack: [],
      redoStack: [],
      optimisticQueue: [],
      pendingSync: false,
      lastChangeAt: null,
      lastLocalSaveAt: null,
      lastCloudSyncAt: null,
      lastSyncError: null
    }));
    clearAutosaveTimer();
  },

  select(selection) {
    set(() => ({ selection }));
  },

  pushSnapshot() {
    const snapshot = snapshotFromState(get());
    set((state) => {
      const nextUndo = [...state.undoStack, snapshot].slice(-state.maxHistory);
      return {
        undoStack: nextUndo,
        redoStack: []
      };
    });
  },

  undo() {
    set((state) => {
      if (state.undoStack.length === 0) {
        return {};
      }
      const snapshot = state.undoStack[state.undoStack.length - 1];
      const remainder = state.undoStack.slice(0, -1);
      const redoSnapshot = snapshotFromState(state);
      return {
        ...applySnapshot(snapshot),
        undoStack: remainder,
        redoStack: [...state.redoStack, redoSnapshot].slice(-state.maxHistory)
      };
    });
  },

  redo() {
    set((state) => {
      if (state.redoStack.length === 0) {
        return {};
      }
      const snapshot = state.redoStack[state.redoStack.length - 1];
      const remainder = state.redoStack.slice(0, -1);
      const undoSnapshot = snapshotFromState(state);
      return {
        ...applySnapshot(snapshot),
        redoStack: remainder,
        undoStack: [...state.undoStack, undoSnapshot].slice(-state.maxHistory)
      };
    });
  },

  beginOptimisticChange(description) {
    const snapshot = snapshotFromState(get());
    const id = generateId();
    set((state) => ({
      optimisticQueue: [...state.optimisticQueue, { id, description, snapshot }]
    }));
    return id;
  },

  resolveOptimisticChange(id) {
    set((state) => ({
      optimisticQueue: state.optimisticQueue.filter((item) => item.id !== id)
    }));
  },

  rollbackOptimisticChange(id) {
    const match = get().optimisticQueue.find((item) => item.id === id);
    if (!match) {
      return;
    }
    set(() => ({
      ...applySnapshot(match.snapshot),
      optimisticQueue: get().optimisticQueue.filter((item) => item.id !== id)
    }));
  },

  upsertNode(node) {
    set((state) => {
      const exists = state.nodes.findIndex((item) => item.id === node.id);
      const nextNodes = exists >= 0 ? state.nodes.map((item, idx) => (idx === exists ? node : item)) : [...state.nodes, node];
      return {
        nodes: applyDerivedNodeState(nextNodes, state.relations),
        ...withPendingSync()
      };
    });
    scheduleAutosave(get, set);
  },

  removeNode(nodeId) {
    set((state) => {
      const remainingRelations = state.relations.filter(
        (relation) => relation.fromId !== nodeId && relation.toId !== nodeId
      );
      const remainingNodes = state.nodes.filter((node) => node.id !== nodeId);
      return {
        nodes: applyDerivedNodeState(remainingNodes, remainingRelations),
        relations: remainingRelations,
        selection:
          state.selection.type === "node" && state.selection.id === nodeId
            ? initialSelection
            : state.selection,
        ...withPendingSync()
      };
    });
    scheduleAutosave(get, set);
  },

  upsertRelation(relation) {
    set((state) => {
      const exists = state.relations.findIndex((item) => item.id === relation.id);
      const nextRelations =
        exists >= 0
          ? state.relations.map((item, idx) => (idx === exists ? relation : item))
          : [...state.relations, relation];
      return {
        relations: nextRelations,
        nodes: applyDerivedNodeState(state.nodes, nextRelations),
        ...withPendingSync()
      };
    });
    scheduleAutosave(get, set);
  },

  removeRelation(relationId) {
    set((state) => {
      const nextRelations = state.relations.filter((relation) => relation.id !== relationId);
      return {
        relations: nextRelations,
        nodes: applyDerivedNodeState(state.nodes, nextRelations),
        selection:
          state.selection.type === "relation" && state.selection.id === relationId
            ? initialSelection
            : state.selection,
        ...withPendingSync()
      };
    });
    scheduleAutosave(get, set);
  },

  setVersions(versions) {
    set(() => ({
      versions
    }));
  },

  async flushPendingPersistence() {
    await persistTree(get, set);
  }
}));
