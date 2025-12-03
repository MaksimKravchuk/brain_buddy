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
});
