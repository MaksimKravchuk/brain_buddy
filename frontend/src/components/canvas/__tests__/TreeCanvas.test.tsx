import { act, render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

import { TreeCanvas } from "../TreeCanvas";
import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";
import type { TreeDetailResponse } from "../../../api/types";

vi.mock("reactflow", () => ({
  __esModule: true,
  default: ({ children }: { children?: React.ReactNode }) => <div data-testid="reactflow">{children}</div>,
  Background: () => <div data-testid="background" />,
  MarkerType: { ArrowClosed: "arrow" },
  Position: { Top: "top", Bottom: "bottom" }
}));

vi.mock("../../../hooks/useGraphProfiler", () => ({
  useGraphProfiler: () => {}
}));

vi.mock("../BrainNode", () => ({
  BrainNode: () => <div data-testid="brain-node" />
}));

const createNodeMutate = vi.fn();
const createRelationMutate = vi.fn();

vi.mock("../../../api/hooks", () => ({
  useCreateNode: () => ({ mutate: createNodeMutate }),
  useUpdateNode: () => ({ mutate: vi.fn() }),
  useDeleteNode: () => ({ mutate: vi.fn() }),
  useCreateRelation: () => ({ mutate: createRelationMutate }),
  useDeleteRelation: () => ({ mutate: vi.fn() })
}));

describe("TreeCanvas sibling creation", () => {
  const sampleTree: TreeDetailResponse = {
    id: "tree-1",
    name: "Sample",
    metadata: {
      version: 1,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      owner_id: null,
      layout: null
    },
    nodes: [
      {
        id: "child-1",
        label: "Child",
        type: "child" as const,
        position: { x: 0, y: 100 },
        highlight_state: "none" as const,
        relation_counts: { up_count: 1, down_count: 0 }
      },
      {
        id: "parent-1",
        label: "Parent",
        type: "parent" as const,
        position: { x: 0, y: -100 },
        highlight_state: "none" as const,
        relation_counts: { up_count: 0, down_count: 1 }
      }
    ],
    relations: [
      {
        id: "rel-1",
        source_node_id: "child-1",
        target_node_id: "parent-1",
        kind: "why",
        created_at: "2024-01-01T00:00:00Z"
      }
    ],
    owner_id: null
  };

  beforeEach(() => {
    createNodeMutate.mockReset();
    createRelationMutate.mockReset();
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
      useTreeStore.getState().setTree(sampleTree);
      useTreeStore.getState().select({ type: "node", id: "child-1" });
    });

    createNodeMutate.mockImplementation((_payload, options) => {
      options?.onSuccess?.({
        id: "new-child",
        label: "Effect",
        type: "child",
        position: { x: 240, y: 100 },
        highlight_state: "none",
        relation_counts: { up_count: 0, down_count: 0 }
      });
    });

    createRelationMutate.mockImplementation((payload, options) => {
      options?.onSuccess?.({
        id: "rel-new",
        source_node_id: payload.source_node_id,
        target_node_id: payload.target_node_id,
        kind: "why",
        created_at: "2024-01-01T00:00:00Z"
      });
    });
  });

  function renderCanvas() {
    const queryClient = new QueryClient();
    return render(
      <QueryClientProvider client={queryClient}>
        <TreeCanvas treeId="tree-1" isLoading={false} />
      </QueryClientProvider>
    );
  }

  it("copies parent relations when creating a sibling via Tab hotkey", async () => {
    await act(async () => {
      renderCanvas();
    });
    const user = userEvent.setup();

    await waitFor(() =>
      expect(Object.keys(useUiStore.getState().hotkeys)).toContain("create-sibling-tab")
    );

    // Tab should trigger the sibling creation hotkey because a node is selected
    await act(async () => {
      await user.keyboard("{Tab}");
    });

    expect(createNodeMutate).toHaveBeenCalledTimes(1);
    expect(createRelationMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        source_node_id: "new-child",
        target_node_id: "parent-1",
        kind: "why"
      }),
      expect.any(Object)
    );

    // New node should be selected after creation
    const newSelection = useTreeStore.getState().selection;
    expect(newSelection).toEqual({ type: "node", id: "new-child" });

    // Parent still links to the original and the new sibling in store state
    const storedRelations = useTreeStore.getState().relations;
    const targets = storedRelations.filter((r) => r.fromId === "new-child").map((r) => r.toId);
    expect(targets).toContain("parent-1");
  });
});
