import { describe, expect, beforeEach, afterEach, it, vi } from "vitest";

import { apiClient } from "../../api/client";
import type { TreeDetailResponse } from "../../api/types";
import { mapRelationResponse, useTreeStore } from "../treeStore";

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
  name: "Sample",
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
      label: "Root",
      type: "child",
      position: { x: 0, y: 0 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 0 }
    }
  ],
  relations: [],
  owner_id: null
};

describe("treeStore branch coverage", () => {
  beforeEach(() => {
    const storage = ensureLocalStorage();
    useTreeStore.getState().reset();
    if (typeof storage.clear === "function") {
      storage.clear();
    }
    vi.spyOn(apiClient, "updateTree").mockResolvedValue(sampleTree);
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });

  afterEach(() => {
    useTreeStore.getState().reset();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("maps relations using source_id and from_id fallbacks", () => {
    const relationWithoutEndpointAliases = mapRelationResponse({
      id: "rel-empty",
      kind: "why",
      created_at: "2024-04-01"
    } as unknown as TreeDetailResponse["relations"][number]);
    expect(relationWithoutEndpointAliases).toMatchObject({ fromId: "", toId: "" });

    const treeWithSourceId: TreeDetailResponse = {
      ...sampleTree,
      nodes: [
        sampleTree.nodes[0],
        {
          id: "node-2",
          label: "Target",
          type: "child",
          position: { x: 10, y: 10 },
          highlight_state: "none",
          relation_counts: { up_count: 0, down_count: 0 }
        }
      ],
      relations: [
        {
          id: "rel-1",
          source_id: "node-1",
          target_id: "node-2",
          kind: "why",
          created_at: "2024-04-01"
        } as unknown as TreeDetailResponse["relations"][number]
      ]
    };
    useTreeStore.getState().setTree(treeWithSourceId);
    expect(useTreeStore.getState().relations[0].fromId).toBe("node-1");
    expect(useTreeStore.getState().relations[0].toId).toBe("node-2");
  });

  it("maps relations using from_id and to_id fallbacks", () => {
    const treeWithFromId: TreeDetailResponse = {
      ...sampleTree,
      nodes: [
        sampleTree.nodes[0],
        {
          id: "node-2",
          label: "Target",
          type: "child",
          position: { x: 10, y: 10 },
          highlight_state: "none",
          relation_counts: { up_count: 0, down_count: 0 }
        }
      ],
      relations: [
        {
          id: "rel-1",
          from_id: "node-2",
          to_id: "node-1",
          kind: "why",
          created_at: "2024-04-01"
        } as unknown as TreeDetailResponse["relations"][number]
      ]
    };
    useTreeStore.getState().setTree(treeWithFromId);
    expect(useTreeStore.getState().relations[0].fromId).toBe("node-2");
    expect(useTreeStore.getState().relations[0].toId).toBe("node-1");
  });

  it("preserves null diffSummary through snapshot undo/redo", () => {
    useTreeStore.getState().setTree(sampleTree);
    useTreeStore.getState().setVersions([
      { id: "v1", label: "V1", createdAt: "2024", conflictCount: 0, diffSummary: null }
    ]);
    const store = useTreeStore.getState();
    store.pushSnapshot();
    store.upsertNode({ ...store.nodes[0], label: "Changed" });
    store.undo();
    expect(useTreeStore.getState().versions[0].diffSummary).toBeNull();
  });

  it("returns early from persistTree when there is no active tree detail", async () => {
    useTreeStore.getState().reset();
    // flushPendingPersistence should be a no-op with no active tree
    await useTreeStore.getState().flushPendingPersistence();
    expect(useTreeStore.getState().pendingSync).toBe(false);
  });

  it("returns false from reachesAllChildren when there are no child nodes in a graph with relations", () => {
    const allParentTree: TreeDetailResponse = {
      ...sampleTree,
      nodes: [
        {
          id: "p1",
          label: "Parent A",
          type: "parent",
          position: { x: 0, y: 0 },
          highlight_state: "none",
          relation_counts: { up_count: 0, down_count: 0 }
        },
        {
          id: "p2",
          label: "Parent B",
          type: "parent",
          position: { x: 10, y: 10 },
          highlight_state: "none",
          relation_counts: { up_count: 0, down_count: 0 }
        }
      ],
      relations: [
        {
          id: "rel-p",
          source_node_id: "p1",
          target_node_id: "p2",
          kind: "why",
          created_at: "2024"
        }
      ]
    };
    useTreeStore.getState().setTree(allParentTree);
    // No child nodes, so effect_spanning should not be set
    const p1 = useTreeStore.getState().nodes.find((n) => n.id === "p1");
    expect(p1?.highlightState).toBe("none");
  });

  it("handles cycle traversal in reachesAllChildren correctly", () => {
    const cyclicTree: TreeDetailResponse = {
      ...sampleTree,
      nodes: [
        {
          id: "child-a",
          label: "A",
          type: "child",
          position: { x: 0, y: 0 },
          highlight_state: "none",
          relation_counts: { up_count: 0, down_count: 0 }
        },
        {
          id: "child-b",
          label: "B",
          type: "child",
          position: { x: 10, y: 0 },
          highlight_state: "none",
          relation_counts: { up_count: 0, down_count: 0 }
        },
        {
          id: "parent-c",
          label: "C",
          type: "parent",
          position: { x: 5, y: -10 },
          highlight_state: "none",
          relation_counts: { up_count: 0, down_count: 0 }
        }
      ],
      relations: [
        // Cycle: A -> B -> A
        { id: "r1", source_node_id: "child-a", target_node_id: "child-b", kind: "why", created_at: "2024" },
        { id: "r2", source_node_id: "child-b", target_node_id: "child-a", kind: "why", created_at: "2024" },
        // C reaches both
        { id: "r3", source_node_id: "parent-c", target_node_id: "child-a", kind: "why", created_at: "2024" },
        { id: "r4", source_node_id: "parent-c", target_node_id: "child-b", kind: "why", created_at: "2024" }
      ]
    };
    useTreeStore.getState().setTree(cyclicTree);
    const c = useTreeStore.getState().nodes.find((n) => n.id === "parent-c");
    // C has outgoing edges to both children, and they are all children, so effect_spanning
    expect(c?.highlightState).toBe("effect_spanning");
  });

  it("uses fallback relationCounts when upserting a node with no matching relations", () => {
    useTreeStore.getState().setTree(sampleTree);
    // upsert a node that isn't in any relation — should use fallback counts
    useTreeStore.getState().upsertNode({
      ...useTreeStore.getState().nodes[0],
      id: "lonely-node",
      relationCounts: { up: 99, down: 88 }
    });
    const lonely = useTreeStore.getState().nodes.find((n) => n.id === "lonely-node");
    // The derived state recalculates; since no relations reference it, counts go to 0
    expect(lonely?.relationCounts).toEqual({ up: 0, down: 0 });
  });

  it("updates an existing relation in upsertRelation (update path)", () => {
    useTreeStore.getState().setTree({
      ...sampleTree,
      nodes: [
        sampleTree.nodes[0],
        {
          id: "node-2",
          label: "B",
          type: "child",
          position: { x: 10, y: 10 },
          highlight_state: "none",
          relation_counts: { up_count: 0, down_count: 0 }
        }
      ],
      relations: [
        {
          id: "rel-existing",
          source_node_id: "node-1",
          target_node_id: "node-2",
          kind: "why",
          created_at: "2024"
        }
      ]
    });
    const rel = useTreeStore.getState().relations[0];
    useTreeStore.getState().upsertRelation({ ...rel, toId: "node-1" });
    expect(useTreeStore.getState().relations[0].toId).toBe("node-1");
  });
});
