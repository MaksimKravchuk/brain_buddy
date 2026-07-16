import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TreeDetailResponse } from "../../../api/types";
import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";
import { RelationInspector } from "../RelationInspector";

const deleteMutation = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));

vi.mock("../../../api/hooks", () => ({
  useDeleteRelation: () => deleteMutation
}));

const tree: TreeDetailResponse = {
  id: "tree-1",
  name: "Current tree",
  metadata: {
    version: 1,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    owner_id: null,
    layout: null
  },
  nodes: [],
  relations: [
    {
      id: "relation-1",
      source_node_id: "cause-1",
      target_node_id: "effect-1",
      kind: "why",
      created_at: "2025-01-01T00:00:00Z"
    }
  ],
  owner_id: null
};

function lastToast() {
  const { toasts } = useUiStore.getState();
  return toasts[toasts.length - 1];
}

describe("RelationInspector", () => {
  beforeEach(() => {
    deleteMutation.mutate.mockReset();
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
    });
  });

  it("explains why selection is required before relation details are available", () => {
    render(<RelationInspector />);
    expect(screen.getByText("Select a tree to inspect relations.")).toBeInTheDocument();

    act(() => useTreeStore.getState().setTree(tree));
    expect(screen.getByText("Select a relation by clicking an edge on the canvas.")).toBeInTheDocument();
  });

  it("shows the selected relation and removes it after a successful confirmation", async () => {
    const user = userEvent.setup();
    act(() => {
      useTreeStore.getState().setTree(tree);
      useTreeStore.getState().select({ type: "relation", id: "relation-1" });
    });
    deleteMutation.mutate.mockImplementation((_id, options) => options?.onSuccess());
    render(<RelationInspector />);

    expect(screen.getByText("cause-1")).toBeInTheDocument();
    expect(screen.getByText("effect-1")).toBeInTheDocument();
    expect(screen.getByText("WHY")).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Delete relation" }));
    });

    expect(deleteMutation.mutate).toHaveBeenCalledWith("relation-1", expect.any(Object));
    expect(useTreeStore.getState().selection).toEqual({ type: null, id: null });
    expect(lastToast()).toMatchObject({ title: "Relation removed", variant: "info" });
  });

  it("restores the relation and explains a failed deletion", async () => {
    const user = userEvent.setup();
    act(() => {
      useTreeStore.getState().setTree(tree);
      useTreeStore.getState().select({ type: "relation", id: "relation-1" });
    });
    deleteMutation.mutate.mockImplementation((_id, options) => options?.onError(new Error("Offline")));
    render(<RelationInspector />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Delete relation" }));
    });

    expect(useTreeStore.getState().relations).toHaveLength(1);
    expect(lastToast()).toMatchObject({ title: "Failed to delete relation", description: "Offline" });
  });
});
