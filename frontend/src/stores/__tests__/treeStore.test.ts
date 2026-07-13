import { describe, expect, beforeEach, afterEach, it, vi } from "vitest";

import { apiClient } from "../../api/client";
import type { TreeDetailResponse } from "../../api/types";
import { TREE_DRAFT_PREFIX, buildTreeDetailFromStore, useTreeStore } from "../treeStore";

function ensureLocalStorage() {
  if (typeof localStorage === "undefined" || typeof localStorage.getItem !== "function") {
    const memory = new Map<string, string>();
    const mockStorage = {
      getItem: (key: string) => memory.get(key) ?? null,
      setItem: (key: string, value: string) => {
        memory.set(key, value);
      },
      removeItem: (key: string) => {
        memory.delete(key);
      },
      clear: () => memory.clear()
    } as Storage;

    Object.defineProperty(globalThis, "localStorage", {
      value: mockStorage,
      writable: true
    });
    return mockStorage;
  }

  return localStorage;
}

const sampleTree: TreeDetailResponse = {
  id: "tree-1",
  name: "Sample Tree",
  metadata: {
    version: 1,
    created_at: "2024-04-01T10:00:00Z",
    updated_at: "2024-04-01T10:00:00Z",
    owner_id: null,
    layout: null
  },
  nodes: [
    {
      id: "node-1",
      label: "Root hypothesis",
      type: "child",
      position: { x: 0, y: 0 },
      highlight_state: "none",
      relation_counts: {
        up_count: 0,
        down_count: 0
      }
    }
  ],
  relations: [],
  owner_id: null
};

const sampleTreeWithRelations: TreeDetailResponse = {
  ...sampleTree,
  nodes: [
    sampleTree.nodes[0],
    {
      id: "node-2",
      label: "Undesired effect",
      type: "child",
      position: { x: 10, y: 20 },
      highlight_state: "none",
      relation_counts: {
        up_count: 0,
        down_count: 0
      }
    }
  ],
  relations: [
    {
      id: "relation-1",
      source_node_id: "node-1",
      target_node_id: "node-2",
      kind: "why",
      created_at: "2024-04-01T10:00:00Z"
    }
  ]
};

const causeCandidateTree: TreeDetailResponse = {
  ...sampleTree,
  nodes: [
    {
      id: "root-cause",
      label: "Root cause",
      type: "parent",
      position: { x: 0, y: 0 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    },
    {
      id: "branch-1",
      label: "Branch 1",
      type: "child",
      position: { x: 10, y: 10 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    },
    {
      id: "branch-2",
      label: "Branch 2",
      type: "child",
      position: { x: 20, y: 20 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    },
    {
      id: "branch-3",
      label: "Branch 3",
      type: "child",
      position: { x: 30, y: 30 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    }
  ],
  relations: [
    {
      id: "rel-1",
      source_node_id: "root-cause",
      target_node_id: "branch-1",
      kind: "why",
      created_at: "2024-04-01"
    },
    {
      id: "rel-2",
      source_node_id: "root-cause",
      target_node_id: "branch-2",
      kind: "why",
      created_at: "2024-04-01"
    },
    {
      id: "rel-3",
      source_node_id: "root-cause",
      target_node_id: "branch-3",
      kind: "why",
      created_at: "2024-04-01"
    }
  ]
};

const effectSpanningTree: TreeDetailResponse = {
  ...sampleTree,
  nodes: [
    {
      id: "root",
      label: "Root cause",
      type: "parent",
      position: { x: 0, y: 0 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    },
    {
      id: "mid",
      label: "Intermediate",
      type: "child",
      position: { x: 10, y: 10 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    },
    {
      id: "effect-1",
      label: "Effect 1",
      type: "child",
      position: { x: 20, y: 20 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    },
    {
      id: "effect-2",
      label: "Effect 2",
      type: "child",
      position: { x: 30, y: 30 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    }
  ],
  relations: [
    { id: "rel-a", source_node_id: "root", target_node_id: "mid", kind: "why", created_at: "2024-04-01" },
    {
      id: "rel-b",
      source_node_id: "mid",
      target_node_id: "effect-1",
      kind: "why",
      created_at: "2024-04-01"
    },
    {
      id: "rel-c",
      source_node_id: "mid",
      target_node_id: "effect-2",
      kind: "why",
      created_at: "2024-04-01"
    }
  ]
};

describe("treeStore", () => {
  beforeEach(() => {
    const storage = ensureLocalStorage();
    useTreeStore.getState().reset();
    if (typeof storage.clear === "function") {
      storage.clear();
    }
    // Silence the cloud-sync path: tests exercise local autosave only.
    vi.spyOn(apiClient, "updateTree").mockResolvedValue(sampleTree);
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });

  afterEach(() => {
    useTreeStore.getState().reset();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("hydrates tree metadata and nodes from API response", () => {
    useTreeStore.getState().setTree(sampleTree);

    const state = useTreeStore.getState();

    expect(state.activeTreeId).toBe("tree-1");
    expect(state.metadata?.name).toBe("Sample Tree");
    expect(state.nodes).toHaveLength(1);
    expect(state.nodes[0].label).toBe("Root hypothesis");
    expect(state.nodes[0].relationCounts.up).toBe(0);
    expect(state.versions).toHaveLength(0);
  });

  it("supports undo/redo for node updates", () => {
    useTreeStore.getState().setTree(sampleTree);
    const store = useTreeStore.getState();
    const originalLabel = store.nodes[0].label;

    store.pushSnapshot();
    store.upsertNode({ ...store.nodes[0], label: "Updated label" });
    expect(useTreeStore.getState().nodes[0].label).toBe("Updated label");

    store.undo();
    expect(useTreeStore.getState().nodes[0].label).toBe(originalLabel);

    store.redo();
    expect(useTreeStore.getState().nodes[0].label).toBe("Updated label");
  });

  it("rolls back optimistic changes correctly", () => {
    useTreeStore.getState().setTree(sampleTree);
    const store = useTreeStore.getState();
    const originalLabel = store.nodes[0].label;

    const token = store.beginOptimisticChange("rename");
    store.upsertNode({ ...store.nodes[0], label: "Temp rename" });
    store.rollbackOptimisticChange(token);

    expect(useTreeStore.getState().nodes[0].label).toBe(originalLabel);
  });

  it("recalculates relation counts when relations are added and removed", () => {
    useTreeStore.getState().setTree(sampleTreeWithRelations);
    let store = useTreeStore.getState();

    expect(store.nodes.find((n) => n.id === "node-1")?.relationCounts.up).toBe(1);
    expect(store.nodes.find((n) => n.id === "node-2")?.relationCounts.down).toBe(1);

    store.removeRelation("relation-1");
    store = useTreeStore.getState();

    expect(store.nodes.find((n) => n.id === "node-1")?.relationCounts.up).toBe(0);
    expect(store.nodes.find((n) => n.id === "node-2")?.relationCounts.down).toBe(0);

    store.upsertRelation({
      id: "relation-2",
      fromId: "node-2",
      toId: "node-1",
      kind: "why",
      createdAt: "2024-04-01T10:00:01Z"
    });

    store = useTreeStore.getState();

    expect(store.nodes.find((n) => n.id === "node-2")?.relationCounts.up).toBe(1);
    expect(store.nodes.find((n) => n.id === "node-1")?.relationCounts.down).toBe(1);
  });

  it("preserves relation direction after node drag and persistence", async () => {
    useTreeStore.getState().setTree(sampleTreeWithRelations);
    const store = useTreeStore.getState();

    const movedNode = { ...store.nodes[0], position: { x: 42, y: -7 } };
    store.pushSnapshot();
    store.upsertNode(movedNode);

    await store.flushPendingPersistence();

    const state = useTreeStore.getState();
    expect(state.relations[0].fromId).toBe("node-1");
    expect(state.relations[0].toId).toBe("node-2");

    const saved = localStorage.getItem(`${TREE_DRAFT_PREFIX}${sampleTreeWithRelations.id}`);
    expect(saved).toBeTruthy();
    const parsed = saved ? JSON.parse(saved) : null;
    expect(parsed?.relations?.[0]?.source_node_id).toBe("node-1");
    expect(parsed?.relations?.[0]?.target_node_id).toBe("node-2");
  });

  it("keeps the last server timestamp in full-tree save payloads for stale-write detection", () => {
    useTreeStore.getState().setTree(sampleTree);
    const store = useTreeStore.getState();

    store.upsertNode({ ...store.nodes[0], label: "Local edit" });

    const detail = buildTreeDetailFromStore(useTreeStore.getState());
    expect(detail?.metadata.updated_at).toBe(sampleTree.metadata.updated_at);
  });

  it("tracks selection and clears it when the selected entity is removed", () => {
    const store = useTreeStore.getState();
    store.setTree(sampleTreeWithRelations);
    store.select({ type: "node", id: "node-2" });
    expect(useTreeStore.getState().selection).toEqual({ type: "node", id: "node-2" });

    store.removeNode("node-2");
    expect(useTreeStore.getState().selection).toEqual({ type: null, id: null });

    store.select({ type: "relation", id: "relation-1" });
    expect(useTreeStore.getState().selection).toEqual({ type: "relation", id: "relation-1" });

    store.removeRelation("relation-1");
    expect(useTreeStore.getState().selection).toEqual({ type: null, id: null });
  });

  it("preserves selection on refresh when the same tree is reloaded", () => {
    const store = useTreeStore.getState();
    store.setTree(sampleTreeWithRelations);
    store.select({ type: "node", id: "node-2" });

    store.setTree({
      ...sampleTreeWithRelations,
      metadata: { ...sampleTreeWithRelations.metadata, updated_at: "2024-04-01T10:05:00Z" }
    });

    expect(useTreeStore.getState().selection).toEqual({ type: "node", id: "node-2" });

    store.select({ type: "relation", id: "relation-1" });
    store.setTree({
      ...sampleTreeWithRelations,
      metadata: { ...sampleTreeWithRelations.metadata, updated_at: "2024-04-01T10:06:00Z" }
    });

    expect(useTreeStore.getState().selection).toEqual({ type: "relation", id: "relation-1" });

    store.setTree(sampleTree);
    expect(useTreeStore.getState().selection).toEqual({ type: null, id: null });
  });

  it("recomputes highlighting state via upsert based on derived rules", () => {
    useTreeStore.getState().setTree(sampleTree);

    const node = useTreeStore.getState().nodes[0];
    const store = useTreeStore.getState();
    store.upsertNode({ ...node, highlightState: "cause_candidate" });

    // Derived rules keep highlight at none because there are no relations
    expect(useTreeStore.getState().nodes[0].highlightState).toBe("none");
  });

  it("marks nodes with three or more upstream relations as cause candidates", () => {
    useTreeStore.getState().setTree(causeCandidateTree);

    const node = useTreeStore.getState().nodes.find((n) => n.id === "root-cause");
    expect(node?.relationCounts.up).toBe(3);
    expect(node?.highlightState).toBe("cause_candidate");
  });

  it("marks nodes whose paths reach all undesired effects as effect spanning", () => {
    useTreeStore.getState().setTree(effectSpanningTree);

    const root = useTreeStore.getState().nodes.find((n) => n.id === "root");
    const mid = useTreeStore.getState().nodes.find((n) => n.id === "mid");

    expect(root?.highlightState).toBe("effect_spanning");
    // intermediate node also reaches both effects via its outgoing edges
    expect(mid?.highlightState).toBe("effect_spanning");
  });

  it("auto-saves drafts locally after edits with a debounce", async () => {
    vi.useFakeTimers();
    useTreeStore.getState().setTree(sampleTree);

    const store = useTreeStore.getState();
    store.upsertNode({ ...store.nodes[0], label: "Updated label" });

    expect(useTreeStore.getState().pendingSync).toBe(true);

    await vi.runOnlyPendingTimersAsync();

    const saved = localStorage.getItem(`${TREE_DRAFT_PREFIX}${sampleTree.id}`);
    expect(saved).toBeTruthy();
    const parsed = saved ? JSON.parse(saved) : null;
    expect(parsed?.nodes?.[0]?.label).toBe("Updated label");
    expect(useTreeStore.getState().pendingSync).toBe(false);
  });

  it("flushes pending persistence immediately when requested", async () => {
    vi.useFakeTimers();
    useTreeStore.getState().setTree(sampleTree);

    const store = useTreeStore.getState();
    store.upsertNode({ ...store.nodes[0], label: "Immediate save" });

    await store.flushPendingPersistence();

    const saved = localStorage.getItem(`${TREE_DRAFT_PREFIX}${sampleTree.id}`);
    expect(saved).toContain("Immediate save");
    expect(useTreeStore.getState().pendingSync).toBe(false);
  });
});
