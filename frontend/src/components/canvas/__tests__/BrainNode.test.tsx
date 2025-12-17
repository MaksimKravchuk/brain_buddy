import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactFlowProvider, Position } from "reactflow";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BrainNode, type BrainNodeData } from "../BrainNode";
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

    await user.dblClick(screen.getByRole("button", { name: "Original" }));
    const textarea = await screen.findByRole("textbox");
    await user.clear(textarea);
    await user.type(textarea, "  Updated label  ");
    await user.tab();

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

    await user.dblClick(screen.getByRole("button", { name: "Original" }));
    const textarea = await screen.findByRole("textbox");
    await user.type(textarea, "Changed");
    await user.keyboard("{Escape}");

    expect(mutateSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Original" })).toBeInTheDocument();
  });
});
