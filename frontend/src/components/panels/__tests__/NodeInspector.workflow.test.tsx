import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TreeDetailResponse, ValidationResponse } from "../../../api/types";
import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";
import { NodeInspector } from "../NodeInspector";

const hookMocks = vi.hoisted(() => ({
  update: { mutate: vi.fn(), isPending: false },
  remove: { mutate: vi.fn(), isPending: false },
  validate: { mutate: vi.fn(), isPending: false },
  history: { data: { items: [] as ValidationResponse[] }, isLoading: false, refetch: vi.fn().mockResolvedValue(undefined) },
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

describe("NodeInspector workflows", () => {
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

  it("persists a trimmed label and lets a user change its type and highlight", async () => {
    const user = userEvent.setup();
    hookMocks.update.mutate.mockImplementation((_payload, options) => options?.onSuccess());
    selectNode();
    render(<NodeInspector />);

    const label = screen.getByLabelText("Node label");
    await act(async () => {
      await user.clear(label);
      await user.type(label, "  Root cause  ");
      await user.tab();
    });
    expect(hookMocks.update.mutate).toHaveBeenCalledWith(
      { nodeId: "node-1", payload: { label: "Root cause" } },
      expect.any(Object)
    );
    expect(useTreeStore.getState().nodes[0]?.label).toBe("Root cause");
    expect(lastToast()).toMatchObject({ title: "Node updated", description: "Label saved." });

    await act(async () => {
      await user.selectOptions(screen.getByLabelText("Type"), "parent");
    });
    expect(useTreeStore.getState().nodes[0]).toMatchObject({ type: "parent" });
    await act(async () => {
      await user.selectOptions(screen.getByLabelText("Highlight"), "cause_candidate");
    });
    expect(hookMocks.update.mutate).toHaveBeenLastCalledWith(
      { nodeId: "node-1", payload: { highlight_state: "cause_candidate" } },
      expect.any(Object)
    );
  });

  it("runs validation, displays history, and renders consented AI recommendations", async () => {
    const user = userEvent.setup();
    hookMocks.history = {
      data: {
        items: [
          {
            node_id: "node-1",
            provider: "mock",
            confidence: 91,
            summary: "Strong connection",
            checked_at: "2025-01-01T00:00:00Z"
          }
        ]
      },
      isLoading: false,
      refetch: vi.fn().mockResolvedValue(undefined)
    };
    hookMocks.validate.mutate.mockImplementation((_payload, options) =>
      options?.onSuccess({ node_id: "node-1", provider: "mock", confidence: 88, summary: "Validation complete", checked_at: "2025-01-01T00:00:00Z" })
    );
    hookMocks.feedback.mutate.mockImplementation((_payload, options) =>
      options?.onSuccess({ status: "success", summary: "Review this branch", recommendations: ["Check assumptions"] })
    );
    selectNode();
    render(<NodeInspector />);

    expect(screen.getByText("Strong connection")).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Run validation" }));
    });
    expect(hookMocks.history.refetch).toHaveBeenCalledOnce();
    expect(lastToast()).toMatchObject({ title: "Validation updated", description: "Validation complete" });

    await act(async () => {
      await user.click(screen.getByRole("checkbox"));
      await user.click(screen.getByRole("button", { name: "Request feedback" }));
    });
    expect(hookMocks.feedback.mutate).toHaveBeenCalledWith(
      { consent: true, request_id: "req-tree-1" },
      expect.any(Object)
    );
    expect(screen.getByText("Review this branch")).toBeInTheDocument();
    expect(screen.getByText("Check assumptions")).toBeInTheDocument();
  });

  it("rolls back a failed deletion and reports the error", async () => {
    const user = userEvent.setup();
    hookMocks.remove.mutate.mockImplementation((_payload, options) => options?.onError(new Error("Offline")));
    selectNode();
    render(<NodeInspector />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Delete node" }));
    });

    expect(useTreeStore.getState().nodes).toHaveLength(1);
    expect(lastToast()).toMatchObject({ title: "Failed to delete node", description: "Offline" });
  });

  it("restores editable node fields after update failures", async () => {
    const user = userEvent.setup();
    hookMocks.update.mutate.mockImplementation((_payload, options) => options?.onError(new Error("Save unavailable")));
    selectNode();
    render(<NodeInspector />);

    const label = screen.getByLabelText("Node label");
    await act(async () => {
      await user.clear(label);
      await user.type(label, "Replacement label");
      await user.tab();
    });
    expect(label).toHaveValue("Initial cause");
    expect(lastToast()).toMatchObject({ title: "Failed to update node", description: "Save unavailable" });

    await act(async () => {
      await user.selectOptions(screen.getByLabelText("Type"), "parent");
    });
    expect(screen.getByLabelText("Type")).toHaveValue("child");
    expect(lastToast()).toMatchObject({ title: "Failed to update node", description: "Save unavailable" });

    await act(async () => {
      await user.selectOptions(screen.getByLabelText("Highlight"), "cause_candidate");
    });
    expect(screen.getByLabelText("Highlight")).toHaveValue("none");
    expect(lastToast()).toMatchObject({ title: "Failed to update highlight", description: "Save unavailable" });
  });

  it("clears selection after deleting a node and exposes validation recovery", async () => {
    const user = userEvent.setup();
    hookMocks.remove.mutate.mockImplementation((_payload, options) => options?.onSuccess());
    hookMocks.validate.mutate.mockImplementation((_payload, options) => options?.onError(new Error("Provider offline")));
    selectNode();
    render(<NodeInspector />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Run validation" }));
    });
    expect(lastToast()).toMatchObject({ title: "Validation failed", description: "Provider offline" });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Delete node" }));
    });
    expect(useTreeStore.getState().nodes).toEqual([]);
    expect(useTreeStore.getState().selection).toEqual({ type: null, id: null });
    expect(lastToast()).toMatchObject({ title: "Node removed", description: "Node deleted from the tree." });
  });
});
