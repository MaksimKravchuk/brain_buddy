import { describe, expect, beforeEach, it } from "vitest";

import type { TreeDetailResponse } from "../../api/types";
import { useTreeStore } from "../treeStore";

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
      type: "regular",
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
      type: "undesired_effect",
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
      from_id: "node-1",
      to_id: "node-2",
      kind: "why",
      created_at: "2024-04-01T10:00:00Z"
    }
  ]
};

describe("treeStore", () => {
  beforeEach(() => {
    useTreeStore.getState().reset();
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

  it("updates node highlighting state via upsert", () => {
    useTreeStore.getState().setTree(sampleTree);

    const node = useTreeStore.getState().nodes[0];
    const store = useTreeStore.getState();
    store.upsertNode({ ...node, highlightState: "cause_candidate" });

    expect(useTreeStore.getState().nodes[0].highlightState).toBe("cause_candidate");
  });
});
