import { performance } from "node:perf_hooks";
import { beforeEach, describe, expect, it } from "vitest";

import type { TreeDetailResponse } from "../../../api/types";
import { useTreeStore } from "../../../stores/treeStore";

function ensureLocalStorage() {
  if (typeof localStorage !== "undefined" && typeof localStorage.getItem === "function") {
    return localStorage;
  }

  const memory = new Map<string, string>();
  const mockStorage = {
    getItem: (key: string) => (memory.has(key) ? memory.get(key)! : null),
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

function buildLargeTree(nodeCount: number): TreeDetailResponse {
  const nodes = Array.from({ length: nodeCount }, (_, index) => ({
    id: `node-${index}`,
    label: `Node ${index}`,
    type: "child" as const,
    position: { x: index * 10, y: index * 4 },
    highlight_state: "none" as const,
    relation_counts: { up_count: 0, down_count: 0 }
  }));

  const relations = Array.from({ length: Math.max(0, nodeCount - 1) }, (_, index) => ({
    id: `rel-${index}`,
    source_node_id: `node-${index}`,
    target_node_id: `node-${index + 1}`,
    kind: "why" as const,
    created_at: "2025-01-01T00:00:00Z"
  }));

  return {
    id: "large-tree",
    name: "Large Tree",
    metadata: {
      version: 1,
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
      owner_id: null,
      layout: null
    },
    nodes,
    relations,
    owner_id: null
  };
}

describe("TreeCanvas performance", () => {
  beforeEach(() => {
    ensureLocalStorage();
    useTreeStore.getState().reset();
  });

  it("keeps highlighting responsive on ~200-node graphs", () => {
    const largeTree = buildLargeTree(200);

    const start = performance.now();
    useTreeStore.getState().setTree(largeTree);
    const elapsed = performance.now() - start;

    expect(elapsed).toBeLessThan(200);

    const state = useTreeStore.getState();
    expect(state.nodes).toHaveLength(largeTree.nodes.length);
    expect(state.relations).toHaveLength(largeTree.relations.length);
    expect(state.relations[0].fromId).toBe("node-0");
    expect(state.relations[0].toId).toBe("node-1");
  });
});
