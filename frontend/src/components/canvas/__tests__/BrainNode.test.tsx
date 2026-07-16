import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactFlowProvider, Position } from "reactflow";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BrainNode, type BrainNodeData } from "../BrainNode";
import nodeColorConfig from "../../../config/nodeColors.json";
import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";

const mutateSpy = vi.fn();

vi.mock("../../../api/hooks", () => ({
  useUpdateNode: () => ({ mutate: mutateSpy })
}));

describe("BrainNode inline editing", () => {
  const baseNode = {
    id: "node-1",
    label: "Original",
    type: "child" as const,
    position: { x: 0, y: 0 },
    highlightState: "none" as const,
    relationCounts: { up: 0, down: 0 }
  };

  const defaultData: BrainNodeData = {
    node: baseNode,
    onCreateParent: vi.fn(),
    onCreateChild: vi.fn(),
    onCreateLeftSibling: vi.fn(),
    onCreateRightSibling: vi.fn()
  };

  const nodeProps = {
    id: baseNode.id,
    type: "brainNode",
    data: defaultData,
    position: baseNode.position,
    selected: true,
    dragging: false,
    isConnectable: false,
    zIndex: 0,
    measured: { width: 0, height: 0 },
    targetPosition: Position.Top,
    sourcePosition: Position.Bottom,
    xPos: baseNode.position.x,
    yPos: baseNode.position.y
  } as const;

  function RenderedBrainNode() {
    const nodeFromStore = useTreeStore((state) => state.nodes.find((n) => n.id === baseNode.id));
    if (!nodeFromStore) return null;

    return <BrainNode {...nodeProps} data={{ ...defaultData, node: nodeFromStore }} />;
  }

  beforeEach(() => {
    mutateSpy.mockReset();
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
      useTreeStore.setState({ activeTreeId: "tree-123" });
      useTreeStore.getState().upsertNode(baseNode);
    });
  });

  it("saves edits inline and trims text on blur", async () => {
    const user = userEvent.setup();
    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    await act(async () => {
      await user.dblClick(screen.getByRole("button", { name: "Original" }));
    });
    const textarea = await screen.findByRole("textbox");
    await act(async () => {
      await user.clear(textarea);
      await user.type(textarea, "  Updated label  ");
      await user.tab();
    });

    expect(mutateSpy).toHaveBeenCalledWith(
      { nodeId: "node-1", payload: { label: "Updated label" } },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
    expect(useTreeStore.getState().nodes[0].label).toBe("Updated label");
    expect(await screen.findByRole("button", { name: "Updated label" })).toBeInTheDocument();
  });

  it("cancels edits with Escape without mutating", async () => {
    const user = userEvent.setup();
    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    await act(async () => {
      await user.dblClick(screen.getByRole("button", { name: "Original" }));
    });
    const textarea = await screen.findByRole("textbox");
    await act(async () => {
      await user.type(textarea, "Changed");
      await user.keyboard("{Escape}");
    });

    expect(mutateSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Original" })).toBeInTheDocument();
  });

  it("applies configured colors for effect and root cause nodes", async () => {
    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    const node = screen.getByTestId("brain-node");
    expect(node).toHaveStyle({
      backgroundColor: nodeColorConfig.noIncoming.background,
      color: nodeColorConfig.noIncoming.text
    });

    act(() => {
      useTreeStore.getState().upsertRelation({
        id: "rel-1",
        fromId: "upstream-node",
        toId: baseNode.id,
        kind: "why",
        createdAt: "2024-04-01"
      });
    });

    await waitFor(() => {
      expect(node).toHaveStyle({
        backgroundColor: nodeColorConfig.noOutgoing.background,
        color: nodeColorConfig.noOutgoing.text
      });
    });
  });

  it("keeps unchanged and tree-less inline edits local", async () => {
    const user = userEvent.setup();
    act(() => useTreeStore.setState({ activeTreeId: null }));
    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    await act(async () => {
      await user.dblClick(screen.getByRole("button", { name: "Original" }));
    });
    await act(async () => {
      await user.tab();
    });
    expect(mutateSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Original" })).toBeInTheDocument();
  });

  it("rolls back a failed inline label save and tells the user why", async () => {
    const user = userEvent.setup();
    mutateSpy.mockImplementation((_payload, options) => options?.onError(new Error("Save unavailable")));
    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    await act(async () => {
      await user.dblClick(screen.getByRole("button", { name: "Original" }));
    });
    const textarea = await screen.findByRole("textbox");
    await act(async () => {
      await user.clear(textarea);
      await user.type(textarea, "Updated");
      await user.tab();
    });

    expect(useTreeStore.getState().nodes[0].label).toBe("Original");
    expect(useUiStore.getState().toasts).toContainEqual(
      expect.objectContaining({ title: "Failed to update node", description: "Save unavailable", variant: "error" })
    );
  });

  it("selects a hovered node and forwards relative creation controls", async () => {
    const user = userEvent.setup();
    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    const brainNode = screen.getByTestId("brain-node");
    await act(async () => {
      await user.hover(brainNode);
      await user.click(screen.getByRole("button", { name: "Create upstream node" }));
      await user.click(screen.getByRole("button", { name: "Create downstream node" }));
      await user.click(screen.getByRole("button", { name: "Create left sibling" }));
      await user.click(screen.getByRole("button", { name: "Create right sibling" }));
      await user.pointer({ target: brainNode, keys: "[MouseLeft]" });
    });

    expect(defaultData.onCreateParent).toHaveBeenCalledOnce();
    expect(defaultData.onCreateChild).toHaveBeenCalledOnce();
    expect(defaultData.onCreateLeftSibling).toHaveBeenCalledOnce();
    expect(defaultData.onCreateRightSibling).toHaveBeenCalledOnce();
    expect(useTreeStore.getState().selection).toEqual({ type: "node", id: baseNode.id });
  });

  it("renders default node colors when both incoming and outgoing relations exist", () => {
    act(() => {
      useTreeStore.getState().upsertRelation({
        id: "rel-in",
        fromId: "upstream-node",
        toId: baseNode.id,
        kind: "why",
        createdAt: "2024-04-01"
      });
      useTreeStore.getState().upsertRelation({
        id: "rel-out",
        fromId: baseNode.id,
        toId: "downstream-node",
        kind: "why",
        createdAt: "2024-04-01"
      });
    });

    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    const node = screen.getByTestId("brain-node");
    expect(node).toHaveStyle({
      backgroundColor: nodeColorConfig.default.background,
      color: nodeColorConfig.default.text
    });
  });

  it("hides control buttons when not selected or hovered", () => {
    render(
      <ReactFlowProvider>
        <BrainNode {...nodeProps} selected={false} data={{ ...defaultData }} />
      </ReactFlowProvider>
    );

    const createButton = screen.getByRole("button", { name: "Create upstream node" });
    expect(createButton).toHaveClass("opacity-0");
  });

  it("does not submit when the label is unchanged or empty", async () => {
    const user = userEvent.setup();
    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    await act(async () => {
      await user.dblClick(screen.getByRole("button", { name: "Original" }));
    });
    const textarea = await screen.findByRole("textbox");
    await act(async () => {
      await user.clear(textarea);
      await user.type(textarea, "   ");
      await user.tab();
    });
    expect(mutateSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Original" })).toBeInTheDocument();
  });

  it("starts editing with Enter on the label button", async () => {
    const user = userEvent.setup();
    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Original" }));
      await user.keyboard("{Enter}");
    });
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
  });

  it("submits inline edits with Enter (without shift) in the textarea", async () => {
    const user = userEvent.setup();
    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    await act(async () => {
      await user.dblClick(screen.getByRole("button", { name: "Original" }));
    });
    const textarea = await screen.findByRole("textbox");
    await act(async () => {
      await user.clear(textarea);
      await user.type(textarea, "New Label{Enter}");
    });
    expect(mutateSpy).toHaveBeenCalledWith(
      { nodeId: "node-1", payload: { label: "New Label" } },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
  });

  it("preserves newlines with Shift+Enter in the textarea", async () => {
    const user = userEvent.setup();
    render(
      <ReactFlowProvider>
        <RenderedBrainNode />
      </ReactFlowProvider>
    );

    await act(async () => {
      await user.dblClick(screen.getByRole("button", { name: "Original" }));
    });
    const textarea = await screen.findByRole("textbox");
    await act(async () => {
      await user.clear(textarea);
      await user.type(textarea, "Line 1{Shift>}{Enter}{/Shift}Line 2");
    });
    expect(textarea).toHaveValue("Line 1\nLine 2");
  });
});
