import { describe, expect, beforeEach, it } from "vitest";

import type { TreeDetailResponse } from "../../api/types";
import { useTreeStore } from "../treeStore";

const sampleTree: TreeDetailResponse = {
  id: "tree-1",
  title: "Sample Tree",
  description: "Research notes",
  created_at: "2024-04-01T10:00:00Z",
  updated_at: "2024-04-01T10:00:00Z",
  nodes: [
    {
      id: "node-1",
      label: "Root hypothesis",
      position: { x: 0, y: 0 },
      metadata: {
        created_at: "2024-04-01T10:00:00Z",
        updated_at: "2024-04-01T10:00:00Z",
        author: "mario"
      },
      visual: null,
      validation: {
        confidence: 78,
        provider: "mock",
        last_checked: "2024-04-01T10:30:00Z"
      },
      incoming_count: 0,
      outgoing_count: 0
    }
  ],
  relations: [],
  versions: [
    {
      id: "tree-1::abc",
      label: "Initial",
      author: "mario",
      notes: "Baseline snapshot",
      created_at: "2024-04-01T10:00:00Z",
      diff_summary: {
        nodes_added: 1,
        nodes_removed: 0,
        nodes_modified: 0,
        relations_added: 0,
        relations_removed: 0,
        relations_modified: 0
      },
      conflict_count: 0
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
    expect(state.metadata?.title).toBe("Sample Tree");
    expect(state.nodes).toHaveLength(1);
    expect(state.nodes[0].label).toBe("Root hypothesis");
    expect(state.nodes[0].metadata.author).toBe("mario");
    expect(state.versions).toHaveLength(1);
    expect(state.versions[0].diffSummary?.nodesAdded).toBe(1);
  });

  it("preserves validation metadata on hydration", () => {
    useTreeStore.getState().setTree(sampleTree);
    const node = useTreeStore.getState().nodes[0];

    expect(node.validation?.confidence).toBe(78);
    expect(node.validation?.provider).toBe("mock");
    expect(new Date(node.validation?.lastChecked ?? "").toISOString()).toBe("2024-04-01T10:30:00.000Z");
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
