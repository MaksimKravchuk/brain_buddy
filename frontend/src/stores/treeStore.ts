import { create } from "zustand";

import type {
  NodeResponse,
  RelationResponse,
  TreeDetailResponse,
  ValidationState,
  VersionListItem
} from "../api/types";

export interface GraphNode {
  id: string;
  label: string;
  position: { x: number; y: number };
  metadata: {
    createdAt: string;
    updatedAt: string;
    author?: string | null;
  };
  visual?: {
    color?: string | null;
    highlight?: boolean;
  } | null;
  validation?: {
    confidence: number;
    provider: string;
    lastChecked: string;
  } | null;
  incomingCount: number;
  outgoingCount: number;
}

export interface GraphRelation {
  id: string;
  sourceId: string;
  targetId: string;
  questionLabel: string;
  notes?: string | null;
  metadata: {
    createdAt: string;
    updatedAt: string;
    author?: string | null;
  };
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
  title: string;
  description?: string | null;
  createdAt: string;
  updatedAt: string;
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
}

export function mapNodeResponse(node: NodeResponse): GraphNode {
  return {
    id: node.id,
    label: node.label,
    position: { ...node.position },
    metadata: {
      createdAt: node.metadata.created_at,
      updatedAt: node.metadata.updated_at,
      author: node.metadata.author ?? null
    },
    visual: node.visual
      ? {
          color: node.visual.color ?? null,
          highlight: node.visual.highlight ?? false
        }
      : null,
    validation: mapValidation(node.validation),
    incomingCount: node.incoming_count,
    outgoingCount: node.outgoing_count
  };
}

function mapValidation(validation?: ValidationState | null) {
  if (!validation) {
    return null;
  }

  return {
    confidence: validation.confidence,
    provider: validation.provider,
    lastChecked: validation.last_checked
  };
}

export function mapRelationResponse(relation: RelationResponse): GraphRelation {
  return {
    id: relation.id,
    sourceId: relation.source_id,
    targetId: relation.target_id,
    questionLabel: relation.question_label,
    notes: relation.notes ?? null,
    metadata: {
      createdAt: relation.metadata.created_at,
      updatedAt: relation.metadata.updated_at,
      author: relation.metadata.author ?? null
    }
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
    metadata: state.metadata ? { ...state.metadata } : null,
    nodes: state.nodes.map((node) => ({
      ...node,
      position: { ...node.position },
      metadata: { ...node.metadata },
      visual: node.visual ? { ...node.visual } : null,
      validation: node.validation ? { ...node.validation } : null
    })),
    relations: state.relations.map((relation) => ({
      ...relation,
      metadata: { ...relation.metadata }
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
    metadata: snapshot.metadata ? { ...snapshot.metadata } : null,
    nodes: snapshot.nodes.map((node) => ({
      ...node,
      position: { ...node.position },
      metadata: { ...node.metadata },
      visual: node.visual ? { ...node.visual } : null,
      validation: node.validation ? { ...node.validation } : null
    })),
    relations: snapshot.relations.map((relation) => ({
      ...relation,
      metadata: { ...relation.metadata }
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

  setTree(tree) {
    set(() => ({
      activeTreeId: tree.id,
      metadata: {
        id: tree.id,
        title: tree.title,
        description: tree.description ?? null,
        createdAt: tree.created_at,
        updatedAt: tree.updated_at
      },
      nodes: tree.nodes.map(mapNodeResponse),
      relations: tree.relations.map(mapRelationResponse),
      versions: tree.versions.map(mapVersionResponse),
      selection: initialSelection,
      undoStack: [],
      redoStack: [],
      optimisticQueue: []
    }));
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
      optimisticQueue: []
    }));
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
      if (exists >= 0) {
        const nextNodes = [...state.nodes];
        nextNodes[exists] = node;
        return { nodes: nextNodes };
      }
      return { nodes: [...state.nodes, node] };
    });
  },

  removeNode(nodeId) {
    set((state) => ({
      nodes: state.nodes.filter((node) => node.id !== nodeId),
      relations: state.relations.filter(
        (relation) => relation.sourceId !== nodeId && relation.targetId !== nodeId
      ),
      selection:
        state.selection.type === "node" && state.selection.id === nodeId ? initialSelection : state.selection
    }));
  },

  upsertRelation(relation) {
    set((state) => {
      const exists = state.relations.findIndex((item) => item.id === relation.id);
      if (exists >= 0) {
        const nextRelations = [...state.relations];
        nextRelations[exists] = relation;
        return { relations: nextRelations };
      }
      return { relations: [...state.relations, relation] };
    });
  },

  removeRelation(relationId) {
    set((state) => ({
      relations: state.relations.filter((relation) => relation.id !== relationId),
      selection:
        state.selection.type === "relation" && state.selection.id === relationId
          ? initialSelection
          : state.selection
    }));
  },

  setVersions(versions) {
    set(() => ({
      versions
    }));
  }
}));
