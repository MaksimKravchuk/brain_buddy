import { type ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../api/client";
import { TreeCanvas } from "../TreeCanvas";
import { useTreeStore } from "../../../stores/treeStore";

let onConnectSpy: ((connection: { source?: string; target?: string }) => void) | undefined;

vi.mock("reactflow", () => {
  const ReactFlowMock = ({
    children,
    onConnect
  }: {
    children?: ReactNode;
    onConnect?: (connection: { source?: string; target?: string }) => void;
  }) => {
    onConnectSpy = onConnect;
    return <div data-testid="reactflow">{children}</div>;
  };

  return {
    __esModule: true,
    default: ReactFlowMock,
    Background: () => <div data-testid="background" />,
    MarkerType: { ArrowClosed: "arrow" },
    Position: { Top: "top", Bottom: "bottom" }
  };
});

vi.mock("../../../hooks/useGraphProfiler", () => ({
  useGraphProfiler: () => {}
}));

vi.mock("../BrainNode", () => ({
  BrainNode: () => <div data-testid="brain-node" />
}));

const createRelationMutate = vi.fn();

vi.mock("../../../api/hooks", () => ({
  useCreateNode: () => ({ mutate: vi.fn() }),
  useUpdateNode: () => ({ mutate: vi.fn() }),
  useDeleteNode: () => ({ mutate: vi.fn() }),
  useCreateRelation: () => ({ mutate: createRelationMutate }),
  useDeleteRelation: () => ({ mutate: vi.fn() })
}));

describe("TreeCanvas relation error accessibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createRelationMutate.mockReset();
    onConnectSpy = undefined;
    useTreeStore.getState().reset();
  });

  it("focuses inline error and announces via live region when link fails", async () => {
    const apiError = new ApiError(
      "Bad Request",
      400,
      {
        message: "Relations create a cycle; ensure direction flows from cause to effect.",
        detail: { reason: "cycle_detected" },
        reference_id: "ref-cycle"
      },
      "ref-cycle"
    );
    createRelationMutate.mockImplementation((_payload, options) => {
      options?.onError?.(apiError);
    });

    await act(async () => {
      render(<TreeCanvas treeId="tree-a11y" isLoading={false} />);
    });

    await act(async () => {
      onConnectSpy?.({ source: "node-a", target: "node-b" });
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/unable to create link/i);
    expect(screen.getByTestId("relation-error-message")).toHaveTextContent(/cycle/);
    expect(screen.getByTestId("relation-error-live")).toHaveTextContent(/cycle/);

    await waitFor(() => {
      expect(document.activeElement).toBe(alert);
    });
  });

  it("shows correlation reference with copy affordance for relation errors", async () => {
    const apiError = new ApiError(
      "Bad Request",
      400,
      {
        message: "Relation already exists between these nodes.",
        detail: { reason: "duplicate_relation" },
        reference_id: "ref-duplicate"
      },
      "ref-duplicate"
    );
    createRelationMutate.mockImplementation((_payload, options) => {
      options?.onError?.(apiError);
    });

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText }
    });

    await act(async () => {
      render(<TreeCanvas treeId="tree-copy-ref" isLoading={false} />);
    });

    await act(async () => {
      onConnectSpy?.({ source: "node-a", target: "node-b" });
    });

    const referenceTag = await screen.findByText(/ref:/i);
    expect(referenceTag).toHaveTextContent("ref-duplicate");
    const copyButton = screen.getByRole("button", { name: /copy reference/i });

    await act(async () => {
      fireEvent.click(copyButton);
    });
    expect(writeText).toHaveBeenCalledWith("ref-duplicate");
    expect(screen.getByText(/copied/i)).toBeInTheDocument();
  });
});
