import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";


import type { TreeDetailResponse } from "../../../api/types";
import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";
import { NodeInspector } from "../NodeInspector";

const hookMocks = vi.hoisted(() => ({
  update: { mutate: vi.fn(), isPending: false },
  remove: { mutate: vi.fn(), isPending: false },
  validate: { mutate: vi.fn(), isPending: false },
  history: {
    data: { items: [] as unknown[] } as { items: unknown[] } | undefined,
    isLoading: false,
    refetch: vi.fn().mockResolvedValue(undefined)
  },
  feedback: { mutate: vi.fn(), isPending: false }
}));

vi.mock("../../../api/hooks", () => ({
  useUpdateNode: () => hookMocks.update,
  useDeleteNode: () => hookMocks.remove,
  useValidation: () => hookMocks.validate,
  useValidationHistory: () => hookMocks.history,
  useAiFeedback: () => hookMocks.feedback
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
  nodes: [
    {
      id: "node-1",
      label: "Initial cause",
      type: "child",
      position: { x: 1, y: 2 },
      highlight_state: "none",
      relation_counts: { up_count: 1, down_count: 2 }
    }
  ],
  relations: [],
  owner_id: null
};

function selectNode() {
  act(() => {
    useTreeStore.getState().setTree(tree);
    useTreeStore.getState().select({ type: "node", id: "node-1" });
  });
}

function lastToast() {
  const { toasts } = useUiStore.getState();
  return toasts[toasts.length - 1];
}

describe("NodeInspector branch coverage", () => {
  beforeEach(() => {
    for (const mutation of [hookMocks.update, hookMocks.remove, hookMocks.validate, hookMocks.feedback]) {
      mutation.mutate.mockReset();
    }
    hookMocks.history = { data: { items: [] }, isLoading: false, refetch: vi.fn().mockResolvedValue(undefined) };
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
    });
  });

  it("does not submit when the label is unchanged from the current node label", async () => {
    const user = userEvent.setup();
    hookMocks.update.mutate.mockImplementation((_payload, options) => options?.onSuccess());
    selectNode();
    render(<NodeInspector />);

    // Tab away without changing — should hit the "trimmed === node.label" guard
    await act(async () => {
      await user.tab();
    });
    expect(hookMocks.update.mutate).not.toHaveBeenCalled();
  });

  it("submits the label via Enter key press", async () => {
    const user = userEvent.setup();
    hookMocks.update.mutate.mockImplementation((_payload, options) => options?.onSuccess());
    selectNode();
    render(<NodeInspector />);

    const label = screen.getByLabelText("Node label");
    await act(async () => {
      await user.clear(label);
      await user.type(label, "New label{Enter}");
    });
    expect(hookMocks.update.mutate).toHaveBeenCalledWith(
      { nodeId: "node-1", payload: { label: "New label" } },
      expect.any(Object)
    );
  });

  it("requires consent before sending AI feedback", async () => {
    const user = userEvent.setup();
    selectNode();
    render(<NodeInspector />);

    // Click the request feedback button without checking the consent checkbox
    // The button is disabled when !consent, but we can call the handler directly
    // by first checking then unchecking
    await act(async () => {
      await user.click(screen.getByRole("checkbox"));
      await user.click(screen.getByRole("checkbox"));
    });
    // Now consent is false again; button should be disabled
    expect(screen.getByRole("button", { name: "Request feedback" })).toBeDisabled();
  });

  it("renders AI feedback with null summary fallback", async () => {
    const user = userEvent.setup();
    hookMocks.feedback.mutate.mockImplementation((_payload, options) =>
      options?.onSuccess({ status: "success", summary: null, recommendations: [] })
    );
    selectNode();
    render(<NodeInspector />);

    await act(async () => {
      await user.click(screen.getByRole("checkbox"));
      await user.click(screen.getByRole("button", { name: "Request feedback" }));
    });
    // summary is null, should not render a <p> with summary text
    // but should still render the feedback box
    expect(screen.getByText("0 tips ready")).toBeInTheDocument();
  });

  it("renders AI feedback with empty recommendations list", async () => {
    const user = userEvent.setup();
    hookMocks.feedback.mutate.mockImplementation((_payload, options) =>
      options?.onSuccess({ status: "success", summary: "Summary text", recommendations: [] })
    );
    selectNode();
    render(<NodeInspector />);

    await act(async () => {
      await user.click(screen.getByRole("checkbox"));
      await user.click(screen.getByRole("button", { name: "Request feedback" }));
    });
    expect(screen.getByText("Summary text")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("renders AI feedback error toast on failure", async () => {
    const user = userEvent.setup();
    hookMocks.feedback.mutate.mockImplementation((_payload, options) =>
      options?.onError(new Error("AI service down"))
    );
    selectNode();
    render(<NodeInspector />);

    await act(async () => {
      await user.click(screen.getByRole("checkbox"));
      await user.click(screen.getByRole("button", { name: "Request feedback" }));
    });
    expect(lastToast()).toMatchObject({ title: "AI feedback failed", description: "AI service down" });
  });

  it("shows loading state for validation history", () => {
    hookMocks.history = { data: undefined, isLoading: true, refetch: vi.fn().mockResolvedValue(undefined) };
    selectNode();
    render(<NodeInspector />);

    expect(screen.getByText("Loading validation history…")).toBeInTheDocument();
  });

  it("shows empty validation history with refresh button", async () => {
    const user = userEvent.setup();
    hookMocks.history = { data: { items: [] }, isLoading: false, refetch: vi.fn().mockResolvedValue(undefined) };
    selectNode();
    render(<NodeInspector />);

    expect(screen.getByText("No previous validations recorded.")).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Refresh" }));
    });
    expect(hookMocks.history.refetch).toHaveBeenCalled();
  });

  it("renders validation history items", () => {
    hookMocks.history = {
      data: {
        items: [
          {
            node_id: "node-1",
            provider: "mock",
            confidence: 95,
            summary: "Strong link",
            checked_at: "2025-01-01T00:00:00Z"
          }
        ]
      },
      isLoading: false,
      refetch: vi.fn().mockResolvedValue(undefined)
    };
    selectNode();
    render(<NodeInspector />);

    expect(screen.getByText("Strong link")).toBeInTheDocument();
    expect(screen.getByText("95%")).toBeInTheDocument();
    expect(screen.getByText("Provider: mock")).toBeInTheDocument();
  });

  it("renders null history data gracefully", () => {
    hookMocks.history = { data: undefined, isLoading: false, refetch: vi.fn().mockResolvedValue(undefined) };
    selectNode();
    render(<NodeInspector />);

    expect(screen.getByText("No previous validations recorded.")).toBeInTheDocument();
  });
});
