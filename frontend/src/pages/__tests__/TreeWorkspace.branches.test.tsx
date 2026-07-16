import { act, fireEvent, render, screen } from "@testing-library/react";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import TreeWorkspace from "../TreeWorkspace";

const hookMocks = vi.hoisted(() => ({
  treesResult: {} as Record<string, unknown>,
  treeResult: {} as Record<string, unknown>,
  downloadResult: {} as Record<string, unknown>,
  importFromFile: vi.fn(),
  isImporting: false,
  importCallback: undefined as ((tree: unknown) => void) | undefined
}));

vi.mock("../../api/hooks", () => ({
  useTrees: () => hookMocks.treesResult,
  useTree: (treeId: string | null) =>
    treeId ? hookMocks.treeResult : { ...hookMocks.treeResult, data: undefined, error: null },
  useTreeDownload: () => hookMocks.downloadResult,
  useTreeImportWithToasts: (onImported: (tree: unknown) => void) => {
    hookMocks.importCallback = onImported;
    return { importFromFile: hookMocks.importFromFile, isImporting: hookMocks.isImporting };
  }
}));

vi.mock("../../components/canvas/TreeCanvas", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  return {
    TreeCanvas: React.forwardRef(function MockTreeCanvas(
      { treeId }: { treeId: string },
      ref: React.ForwardedRef<{ zoomIn: () => void; zoomOut: () => void; centerOnSelection: () => void }>
    ) {
      React.useImperativeHandle(ref, () => ({
        zoomIn: vi.fn(),
        zoomOut: vi.fn(),
        centerOnSelection: vi.fn()
      }));
      return React.createElement("div", { "data-testid": "tree-canvas" }, `Canvas ${treeId}`);
    })
  };
});

vi.mock("../../components/modals/CreateTreeModal", () => ({ CreateTreeModal: () => null }));
vi.mock("../../components/modals/RenameTreeModal", () => ({ RenameTreeModal: () => null }));

const deleteModalProps = vi.hoisted(() => ({ onDeleted: vi.fn() as (treeId: string) => Promise<void> }));
vi.mock("../../components/modals/DeleteTreeModal", () => ({
  DeleteTreeModal: (props: { trees: unknown; onDeleted: (treeId: string) => Promise<void> }) => {
    deleteModalProps.onDeleted = props.onDeleted;
    return null;
  }
}));

describe("TreeWorkspace branch coverage", () => {
  beforeEach(() => {
    hookMocks.treesResult = {
      data: [
        { id: "tree-1", name: "Tree One", updated_at: "2025-01-01T00:00:00Z", owner_id: null }
      ],
      error: null,
      refetch: vi.fn()
    };
    hookMocks.treeResult = {
      data: {
        id: "tree-1",
        name: "Tree One",
        metadata: {
          version: 1,
          created_at: "2025-01-01T00:00:00Z",
          updated_at: "2025-01-02T00:00:00Z",
          owner_id: null,
          layout: null
        },
        nodes: [],
        relations: [],
        owner_id: null
      },
      error: null,
      isLoading: false,
      isFetching: false,
      refetch: vi.fn()
    };
    hookMocks.downloadResult = { download: vi.fn(), isDownloading: false };
    hookMocks.importFromFile.mockReset();
    hookMocks.isImporting = false;
    hookMocks.importCallback = undefined;
    act(() => {
      useAuthStore.setState({ user: { id: "u1", email: "test@example.com" }, status: "authed", logout: vi.fn() });
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
      useUiStore.setState({ modals: { createTree: false, renameTree: false, deleteTree: false, manageVersions: false } });
    });
  });

  it("resets the store and selects next tree when the active tree is deleted and no trees remain", async () => {
    hookMocks.treesResult = {
      data: [
        { id: "tree-1", name: "Tree One", updated_at: "2025-01-01T00:00:00Z", owner_id: null }
      ],
      error: null,
      refetch: vi.fn().mockResolvedValue({ data: [] })
    };
    render(<TreeWorkspace />);
    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBe("tree-1"));

    // Delete the only tree — remaining becomes empty, nextId is null
    hookMocks.treesResult = { data: [], error: null, refetch: vi.fn().mockResolvedValue({ data: [] }) };
    await act(async () => {
      await deleteModalProps.onDeleted("tree-1");
    });

    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBeNull());
  });

  it("renders a loading state in the empty canvas when tree is loading", async () => {
    hookMocks.treesResult = { data: [], error: null, refetch: vi.fn() };
    hookMocks.treeResult = { data: undefined, error: null, isLoading: true, isFetching: false, refetch: vi.fn() };
    render(<TreeWorkspace />);
    expect(screen.getByText("Loading tree…")).toBeInTheDocument();
  });

  it("shows error detail without correlation when error is a plain Error", async () => {
    hookMocks.treeResult = {
      data: undefined,
      error: new Error("Something broke"),
      isLoading: false,
      isFetching: false,
      refetch: vi.fn()
    };
    render(<TreeWorkspace />);
    expect(screen.getAllByText("Something broke")).toHaveLength(2);
    expect(screen.queryByText(/^Reference:/)).not.toBeInTheDocument();
  });

  it("shows tree detail error toast with retry action", async () => {
    const refetch = vi.fn();
    hookMocks.treeResult = {
      data: undefined,
      error: new Error("Detail unavailable"),
      isLoading: false,
      isFetching: false,
      refetch
    };
    render(<TreeWorkspace />);

    // Wait for the toast to appear
    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => {
      const toast = useUiStore.getState().toasts.find((t) => t.title === "Unable to load tree");
      expect(toast).toBeTruthy();
      toast?.action?.onClick();
    });
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("uses cached trees when a delete refetch has no data", async () => {
    const nextTree = { id: "tree-2", name: "Tree Two", updated_at: "2025-01-03T00:00:00Z", owner_id: null };
    hookMocks.treesResult = {
      data: [
        { id: "tree-1", name: "Tree One", updated_at: "2025-01-01T00:00:00Z", owner_id: null },
        nextTree
      ],
      error: null,
      refetch: vi.fn().mockResolvedValue({})
    };
    render(<TreeWorkspace />);
    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBe("tree-1"));

    await act(async () => {
      await deleteModalProps.onDeleted("tree-1");
    });

    expect(hookMocks.treesResult.refetch).toHaveBeenCalledOnce();
  });

  it("ignores an empty import file selection", () => {
    render(<TreeWorkspace />);

    fireEvent.change(screen.getByLabelText("Import tree"), { target: { files: [] } });

    expect(hookMocks.importFromFile).not.toHaveBeenCalled();
  });

  it("omits the reference label for an ApiError without a correlation ID", () => {
    hookMocks.treeResult = {
      data: undefined,
      error: new ApiError("Unavailable", 503, {}, undefined),
      isLoading: false,
      isFetching: false,
      refetch: vi.fn()
    };
    render(<TreeWorkspace />);

    expect(screen.queryByText(/^Reference:/)).not.toBeInTheDocument();
  });
});
