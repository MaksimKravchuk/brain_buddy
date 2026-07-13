import { act, render, screen, waitFor } from "@testing-library/react";
import { createRef, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TreeDetailResponse } from "../../../api/types";
import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";
import { TreeCanvas, type TreeCanvasHandle } from "../TreeCanvas";

type FlowHandlers = Record<string, (...args: unknown[]) => unknown>;

let flowProps: FlowHandlers = {};

vi.mock("reactflow", () => ({
  __esModule: true,
  default: ({ children, ...props }: { children?: ReactNode }) => {
    flowProps = props as unknown as FlowHandlers;
    return <div data-testid="reactflow">{children}</div>;
  },
  Background: () => <div data-testid="background" />,
  MarkerType: { ArrowClosed: "arrow" },
  Position: { Top: "top", Bottom: "bottom" }
}));

vi.mock("../../../hooks/useGraphProfiler", () => ({ useGraphProfiler: () => {} }));
vi.mock("../BrainNode", () => ({ BrainNode: () => <div data-testid="brain-node" /> }));

const mutations = vi.hoisted(() => ({
  createNode: vi.fn(),
  updateNode: vi.fn(),
  deleteNode: vi.fn(),
  createRelation: vi.fn(),
  deleteRelation: vi.fn()
}));

vi.mock("../../../api/hooks", () => ({
  useCreateNode: () => ({ mutate: mutations.createNode }),
  useUpdateNode: () => ({ mutate: mutations.updateNode }),
  useDeleteNode: () => ({ mutate: mutations.deleteNode }),
  useCreateRelation: () => ({ mutate: mutations.createRelation }),
  useDeleteRelation: () => ({ mutate: mutations.deleteRelation })
}));

const tree: TreeDetailResponse = {
  id: "tree-1",
  name: "Canvas tree",
  metadata: {
    version: 1,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    owner_id: null,
    layout: null
  },
  nodes: [
    {
      id: "node-1",
      label: "Cause",
      type: "parent",
      position: { x: 10, y: 20 },
      highlight_state: "none",
      relation_counts: { up_count: 0, down_count: 1 }
    },
    {
      id: "node-2",
      label: "Effect",
      type: "child",
      position: { x: 30, y: 40 },
      highlight_state: "none",
      relation_counts: { up_count: 1, down_count: 0 }
    }
  ],
  relations: [
    {
      id: "relation-1",
      source_node_id: "node-1",
      target_node_id: "node-2",
      kind: "why",
      created_at: "2025-01-01T00:00:00Z"
    }
  ],
  owner_id: null
};

function renderCanvas() {
  return render(<TreeCanvas treeId={tree.id} isLoading={false} />);
}

describe("TreeCanvas interaction callbacks", () => {
  beforeEach(() => {
    flowProps = {};
    for (const mutation of Object.values(mutations)) mutation.mockReset();
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
      useTreeStore.getState().setTree(tree);
    });
  });

  it("keeps canvas selection in sync for node, edge, pane, and React Flow multi-selection actions", () => {
    renderCanvas();

    act(() => flowProps.onNodeClick?.({}, { id: "node-1" }));
    expect(useTreeStore.getState().selection).toEqual({ type: "node", id: "node-1" });
    act(() => flowProps.onEdgeClick?.({}, { id: "relation-1" }));
    expect(useTreeStore.getState().selection).toEqual({ type: "relation", id: "relation-1" });
    act(() => flowProps.onSelectionChange?.({ nodes: [{ id: "node-2" }], edges: [] }));
    expect(useTreeStore.getState().selection).toEqual({ type: "node", id: "node-2" });
    act(() => flowProps.onSelectionChange?.({ nodes: [], edges: [{ id: "relation-1" }] }));
    expect(useTreeStore.getState().selection).toEqual({ type: "relation", id: "relation-1" });
    act(() => flowProps.onPaneClick?.());
    expect(useTreeStore.getState().selection).toEqual({ type: null, id: null });
  });

  it("persists node movement and deletion through optimistic canvas actions", () => {
    mutations.updateNode.mockImplementation((_payload, options) => options?.onSuccess());
    mutations.deleteNode.mockImplementation((_payload, options) => options?.onSuccess());
    renderCanvas();

    act(() => flowProps.onNodeDragStop?.({}, { id: "node-1", position: { x: 120, y: 220 } }));
    expect(mutations.updateNode).toHaveBeenCalledWith(
      { nodeId: "node-1", payload: { position: { x: 120, y: 220 } } },
      expect.any(Object)
    );
    expect(useTreeStore.getState().nodes.find((node) => node.id === "node-1")?.position).toEqual({ x: 120, y: 220 });

    act(() => flowProps.onNodesDelete?.([{ id: "node-2", data: { node: { label: "Effect" } } }]));
    expect(mutations.deleteNode).toHaveBeenCalledWith({ nodeId: "node-2", cascade: true }, expect.any(Object));
    expect(useTreeStore.getState().nodes.map((node) => node.id)).not.toContain("node-2");
    expect(useUiStore.getState().toasts.find((toast) => toast.title === "Node deleted")).toBeTruthy();
  });

  it("reports failed canvas mutations and offers relation retry feedback", () => {
    mutations.updateNode.mockImplementation((_payload, options) => options?.onError(new Error("position unavailable")));
    mutations.deleteNode.mockImplementation((_payload, options) => options?.onError(new Error("delete unavailable")));
    mutations.createRelation.mockImplementation((_payload, options) => options?.onError(new Error("relation unavailable")));
    mutations.deleteRelation.mockImplementation((_payload, options) => options?.onError(new Error("edge unavailable")));
    renderCanvas();

    act(() => flowProps.onNodeDragStop?.({}, { id: "node-1", position: { x: 120, y: 220 } }));
    act(() => flowProps.onNodesDelete?.([{ id: "node-2", data: { node: { label: "Effect" } } }]));
    act(() => flowProps.onConnect?.({ source: "node-1", target: "node-2" }));
    act(() => flowProps.onEdgesDelete?.([{ id: "relation-1" }]));

    expect(useUiStore.getState().toasts.map((toast) => toast.title)).toEqual(
      expect.arrayContaining([
        "Unable to update node position",
        "Failed to delete node",
        "Failed to create relation",
        "Failed to delete relation"
      ])
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Unable to create link");
  });

  it("does not delete a node from its context menu when confirmation is declined", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderCanvas();

    act(() => flowProps.onNodeContextMenu?.({ preventDefault: vi.fn() }, { id: "node-1" }));

    expect(mutations.deleteNode).not.toHaveBeenCalled();
    expect(useTreeStore.getState().selection).toEqual({ type: "node", id: "node-1" });
  });

  it("replaces a temporary relation after a successful connection", () => {
    mutations.createRelation.mockImplementation((_payload, options) =>
      options?.onSuccess({
        id: "relation-new",
        source_node_id: "node-1",
        target_node_id: "node-2",
        kind: "why",
        created_at: "2025-01-02T00:00:00Z"
      })
    );
    renderCanvas();

    act(() => flowProps.onConnect?.({ source: "node-1", target: "node-2" }));

    expect(mutations.createRelation).toHaveBeenCalledWith(
      { source_node_id: "node-1", target_node_id: "node-2", kind: "why" },
      expect.any(Object)
    );
    expect(useTreeStore.getState().relations.map((relation) => relation.id)).toContain("relation-new");
  });

  it("guides keyboard link mode from a selected source to a different target", async () => {
    mutations.createRelation.mockImplementation((_payload, options) =>
      options?.onSuccess({
        id: "keyboard-relation",
        source_node_id: "node-1",
        target_node_id: "node-2",
        kind: "why",
        created_at: "2025-01-02T00:00:00Z"
      })
    );
    renderCanvas();

    const initialLinkHandler = useUiStore.getState().hotkeys["link-nodes-ctrl"]?.handler;
    act(() => useUiStore.getState().hotkeys["link-nodes-ctrl"]?.handler());
    expect(useUiStore.getState().toasts.find((toast) => toast.title === "Select a node first")).toBeTruthy();

    act(() => {
      useTreeStore.getState().select({ type: "node", id: "node-1" });
    });
    await waitFor(() =>
      expect(useUiStore.getState().hotkeys["link-nodes-ctrl"]?.handler).not.toBe(initialLinkHandler)
    );
    const sourceLinkHandler = useUiStore.getState().hotkeys["link-nodes-ctrl"]?.handler;
    act(() => sourceLinkHandler?.());
    expect(useUiStore.getState().toasts.find((toast) => toast.title === "Link mode")).toBeTruthy();

    act(() => {
      useTreeStore.getState().select({ type: "node", id: "node-2" });
    });
    await waitFor(() =>
      expect(useUiStore.getState().hotkeys["link-nodes-ctrl"]?.handler).not.toBe(sourceLinkHandler)
    );
    act(() => useUiStore.getState().hotkeys["link-nodes-ctrl"]?.handler());
    expect(mutations.createRelation).toHaveBeenCalledWith(
      { source_node_id: "node-1", target_node_id: "node-2", kind: "why" },
      expect.any(Object)
    );
  });

  it("creates a default cause when an initialized canvas has no nodes", async () => {
    mutations.createNode.mockImplementation((_payload, options) =>
      options?.onSuccess({
        id: "node-default",
        label: "Cause",
        type: "parent",
        position: { x: 50, y: 60 },
        highlight_state: "none",
        relation_counts: { up_count: 0, down_count: 0 }
      })
    );
    act(() => useTreeStore.getState().reset());
    render(<TreeCanvas treeId="empty-tree" isLoading={false} />);

    act(() =>
      flowProps.onInit?.({
        screenToFlowPosition: () => ({ x: 50, y: 60 }),
        zoomIn: vi.fn(),
        zoomOut: vi.fn(),
        fitView: vi.fn(),
        setCenter: vi.fn()
      })
    );

    expect(mutations.createNode).toHaveBeenCalledWith(
      expect.objectContaining({ label: "Cause", type: "parent", highlight_state: "none" }),
      expect.any(Object)
    );
    expect(useTreeStore.getState().nodes.map((node) => node.id)).toContain("node-default");
  });

  it("deletes selected edges through the relation mutation", () => {
    mutations.deleteRelation.mockImplementation((_id, options) => options?.onSuccess());
    renderCanvas();

    act(() => flowProps.onEdgesDelete?.([{ id: "relation-1" }]));

    expect(mutations.deleteRelation).toHaveBeenCalledWith("relation-1", expect.any(Object));
    expect(useTreeStore.getState().relations).toEqual([]);
  });

  it("ignores incomplete connections and empty delete batches", () => {
    renderCanvas();

    act(() => {
      flowProps.onConnect?.({ source: "node-1", target: null });
      flowProps.onNodesDelete?.([]);
      flowProps.onEdgesDelete?.([]);
    });

    expect(mutations.createRelation).not.toHaveBeenCalled();
    expect(mutations.deleteNode).not.toHaveBeenCalled();
    expect(mutations.deleteRelation).not.toHaveBeenCalled();
  });

  it("exposes viewport controls for the selected node and the whole canvas", () => {
    const ref = createRef<TreeCanvasHandle>();
    const zoomIn = vi.fn();
    const zoomOut = vi.fn();
    const setCenter = vi.fn();
    const fitView = vi.fn();
    render(<TreeCanvas ref={ref} treeId={tree.id} isLoading={false} />);

    act(() =>
      flowProps.onInit?.({
        screenToFlowPosition: () => ({ x: 0, y: 0 }),
        zoomIn,
        zoomOut,
        setCenter,
        fitView
      })
    );
    act(() => ref.current?.zoomIn());
    act(() => ref.current?.zoomOut());
    expect(zoomIn).toHaveBeenCalledWith({ duration: 150 });
    expect(zoomOut).toHaveBeenCalledWith({ duration: 150 });

    act(() => useTreeStore.getState().select({ type: "node", id: "node-1" }));
    act(() => ref.current?.centerOnSelection());
    expect(setCenter).toHaveBeenCalledWith(10, 20, { zoom: 1.1, duration: 250 });

    act(() => useTreeStore.getState().select({ type: "relation", id: "relation-1" }));
    act(() => ref.current?.centerOnSelection());
    expect(fitView).toHaveBeenCalledWith({ padding: 0.2, duration: 250 });
  });

  it("distinguishes an empty canvas from a loading canvas", () => {
    act(() => useTreeStore.getState().reset());
    const { rerender } = render(<TreeCanvas treeId="empty-tree" isLoading={false} />);
    expect(screen.getByText("An empty canvas")).toBeInTheDocument();

    rerender(<TreeCanvas treeId="empty-tree" isLoading />);
    expect(screen.getByText("Loading tree…")).toBeInTheDocument();
    expect(screen.queryByText("An empty canvas")).not.toBeInTheDocument();
  });
});
