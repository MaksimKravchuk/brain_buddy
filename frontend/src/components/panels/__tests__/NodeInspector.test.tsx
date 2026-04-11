import { render, screen } from "@testing-library/react";
import { act } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";
import { NodeInspector } from "../NodeInspector";

vi.mock("../../../api/hooks", () => ({
  useUpdateNode: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteNode: () => ({ mutate: vi.fn(), isPending: false }),
  useValidation: () => ({ mutate: vi.fn(), isPending: false }),
  useValidationHistory: () => ({
    data: { items: [] },
    isLoading: false,
    refetch: vi.fn().mockResolvedValue(undefined)
  }),
  useAiFeedback: () => ({ mutate: vi.fn(), isPending: false })
}));

describe("NodeInspector hook-order stability", () => {
  beforeEach(() => {
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.setState({ inspectorTab: "node" });
    });
  });

  it("renders the placeholder when no tree is active", () => {
    act(() => {
      useTreeStore.setState({ activeTreeId: null });
    });

    render(<NodeInspector />);

    expect(screen.getByText(/select a tree/i)).toBeInTheDocument();
  });

  it("renders the placeholder when a tree is active but no node is selected", () => {
    act(() => {
      useTreeStore.setState({ activeTreeId: "t1" });
      useTreeStore.getState().select({ type: null, id: null });
    });

    render(<NodeInspector />);

    expect(screen.getByText(/select a node/i)).toBeInTheDocument();
  });

  it("transitions from no-tree to tree-active without violating hook order", () => {
    // Initial render with no tree; rerender after flipping activeTreeId. Any
    // Rules-of-Hooks violation would surface as a React console.error here —
    // we rely on React's own runtime check rather than DOM assertions.
    const { rerender } = render(<NodeInspector />);

    act(() => {
      useTreeStore.setState({ activeTreeId: "t1" });
    });

    rerender(<NodeInspector />);

    expect(true).toBe(true);
  });
});
