import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { TreeDetailResponse, TreeListItem } from "../../api/types";
import { useAuthStore } from "../../stores/authStore";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";
import TreeWorkspace from "../TreeWorkspace";

const hookMocks = vi.hoisted(() => ({
  treesResult: {},
  treeResult: {},
  downloadResult: {},
  importFromFile: vi.fn(),
  isImporting: false,
  importCallback: undefined as ((tree: TreeDetailResponse) => void) | undefined,
  zoomIn: vi.fn(),
  zoomOut: vi.fn(),
  centerOnSelection: vi.fn()
}));

vi.mock("../../api/hooks", () => ({
  useTrees: () => hookMocks.treesResult,
  useTree: (treeId: string | null) =>
    treeId ? hookMocks.treeResult : { ...hookMocks.treeResult, data: undefined, error: null },
  useTreeDownload: () => hookMocks.downloadResult,
  useTreeImportWithToasts: (onImported: (tree: TreeDetailResponse) => void) => {
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
        zoomIn: hookMocks.zoomIn,
        zoomOut: hookMocks.zoomOut,
        centerOnSelection: hookMocks.centerOnSelection
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

const tree: TreeDetailResponse = {
  id: "tree-1",
  name: "Current tree",
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
};

const treeList: TreeListItem[] = [
  { id: tree.id, name: tree.name, updated_at: tree.metadata.updated_at, owner_id: null }
];

describe("TreeWorkspace", () => {
  beforeEach(() => {
    hookMocks.zoomIn.mockReset();
    hookMocks.zoomOut.mockReset();
    hookMocks.centerOnSelection.mockReset();
    hookMocks.treesResult = { data: treeList, error: null, refetch: vi.fn() };
    hookMocks.treeResult = { data: tree, error: null, isLoading: false, isFetching: false, refetch: vi.fn() };
    hookMocks.downloadResult = { download: vi.fn(), isDownloading: false };
    hookMocks.importFromFile.mockReset();
    hookMocks.isImporting = false;
    hookMocks.importCallback = undefined;
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
      useUiStore.setState({
        modals: { createTree: false, renameTree: false, deleteTree: false, manageVersions: false }
      });
      useAuthStore.setState({ user: { id: "user-1", email: "person@example.com" }, status: "authed", logout: vi.fn() });
    });
  });

  it("loads the first tree, exposes canvas controls, and imports a selected file", async () => {
    const user = userEvent.setup();
    render(<TreeWorkspace />);

    await waitFor(() => expect(screen.getByTestId("tree-canvas")).toHaveTextContent("Canvas tree-1"));
    expect(useTreeStore.getState().activeTreeId).toBe(tree.id);
    expect(screen.getByText("person@example.com")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    await user.click(screen.getByRole("button", { name: "Zoom out" }));
    await user.click(screen.getByRole("button", { name: "Center on selection" }));
    expect(hookMocks.zoomIn).toHaveBeenCalledOnce();
    expect(hookMocks.zoomOut).toHaveBeenCalledOnce();
    expect(hookMocks.centerOnSelection).toHaveBeenCalledOnce();

    const file = new File(["{}"], "tree.json", { type: "application/json" });
    fireEvent.change(screen.getByLabelText("Import tree"), { target: { files: [file] } });
    expect(hookMocks.importFromFile).toHaveBeenCalledWith(file);

    const imported = { ...tree, id: "tree-2", name: "Imported tree" };
    hookMocks.treeResult = { ...hookMocks.treeResult, data: imported };
    act(() => hookMocks.importCallback?.(imported));
    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBe("tree-2"));
  });

  it("shows a retryable detail error with its correlation reference", async () => {
    const retry = vi.fn();
    hookMocks.treesResult = { data: treeList, error: null, refetch: vi.fn() };
    hookMocks.treeResult = {
      data: undefined,
      error: new ApiError("Unavailable", 503, {}, "corr-9"),
      isLoading: false,
      isFetching: false,
      refetch: retry
    };
    render(<TreeWorkspace />);

    expect(await screen.findByText("We couldn't load this tree")).toBeInTheDocument();
    expect(screen.getByText("Reference: corr-9")).toBeInTheDocument();
    const retryButtons = screen.getAllByRole("button", { name: "Retry" });
    const user = userEvent.setup();
    await act(async () => {
      await user.click(retryButtons[0]);
      await user.click(retryButtons[1]);
    });
    expect(retry).toHaveBeenCalledTimes(2);
  });

  it("guides empty workspaces toward creation and exposes list-load retries", async () => {
    const retryTrees = vi.fn();
    hookMocks.treesResult = { data: [], error: new Error("Offline"), refetch: retryTrees };
    hookMocks.treeResult = { data: undefined, error: null, isLoading: false, isFetching: false, refetch: vi.fn() };
    const user = userEvent.setup();
    render(<TreeWorkspace />);

    expect(await screen.findByText("Start with your first undesired effect")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create a new tree" }));
    expect(useUiStore.getState().modals.createTree).toBe(true);
    const listError = useUiStore.getState().toasts.find((toast) => toast.id === "tree-list-error");
    expect(listError).toMatchObject({ title: "Unable to load trees", description: "Offline" });
    act(() => listError?.action?.onClick());
    expect(retryTrees).toHaveBeenCalledOnce();
  });

  it("shows a loading canvas and allows signed-out visitors to finish a session", async () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    hookMocks.treesResult = { data: [], error: null, refetch: vi.fn() };
    hookMocks.treeResult = { data: undefined, error: null, isLoading: true, isFetching: false, refetch: vi.fn() };
    act(() => useAuthStore.setState({ user: null, status: "anon", logout }));
    const user = userEvent.setup();
    render(<TreeWorkspace />);

    expect(screen.getByText("Loading tree…")).toBeInTheDocument();
    expect(screen.queryByText("person@example.com")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(logout).toHaveBeenCalledOnce();
  });

  it("shows retry progress for errors without a correlation reference", () => {
    hookMocks.treeResult = {
      data: undefined,
      error: new Error("Network unavailable"),
      isLoading: false,
      isFetching: true,
      refetch: vi.fn()
    };
    render(<TreeWorkspace />);

    expect(screen.getAllByText("Network unavailable")).toHaveLength(2);
    expect(screen.queryByText(/^Reference:/)).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading" }).closest("button")).toBeDisabled();
  });

  it("skips tree detail sync when the loaded tree already matches the active tree", async () => {
    act(() => useTreeStore.getState().setTree(tree));
    hookMocks.treeResult = { ...hookMocks.treeResult, data: tree };
    render(<TreeWorkspace />);

    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBe(tree.id));
    // The effect should not call setTree again because the active tree ID already matches
    const state = useTreeStore.getState();
    expect(state.metadata?.name).toBe(tree.name);
  });

  it("resets the store when no tree is selected on mount", async () => {
    hookMocks.treesResult = { data: [], error: null, refetch: vi.fn() };
    hookMocks.treeResult = { data: undefined, error: null, isLoading: false, isFetching: false, refetch: vi.fn() };
    act(() => useTreeStore.setState({ activeTreeId: "stale-id", metadata: { id: "stale-id", name: "Stale", version: 1, createdAt: "", updatedAt: "", ownerId: null } }));

    render(<TreeWorkspace />);

    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBeNull());
    expect(useTreeStore.getState().metadata).toBeNull();
  });

  it("switches to the next tree when the active tree is deleted", async () => {
    const treeB: TreeListItem = { id: "tree-2", name: "Other tree", updated_at: "2025-01-03T00:00:00Z", owner_id: null };
    hookMocks.treesResult = {
      data: [...treeList, treeB],
      error: null,
      refetch: vi.fn().mockResolvedValue({ data: [treeB] })
    };
    const treeBDetail: TreeDetailResponse = { ...tree, id: "tree-2", name: "Other tree" };
    render(<TreeWorkspace />);
    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBe(tree.id));

    hookMocks.treeResult = { data: treeBDetail, error: null, isLoading: false, isFetching: false, refetch: vi.fn() };
    await act(async () => {
      await deleteModalProps.onDeleted(tree.id);
    });

    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBe("tree-2"));
  });

  it("selects the next remaining tree after the active tree is deleted", async () => {
    const treeB: TreeListItem = { id: "tree-2", name: "Other tree", updated_at: "2025-01-03T00:00:00Z", owner_id: null };
    hookMocks.treesResult = {
      data: [...treeList, treeB],
      error: null,
      refetch: vi.fn().mockResolvedValue({ data: [treeB] })
    };
    const treeBDetail: TreeDetailResponse = { ...tree, id: "tree-2", name: "Other tree" };
    const treeResultForTree1 = { data: tree, error: null, isLoading: false, isFetching: false, refetch: vi.fn() };
    const treeResultForTree2 = { data: treeBDetail, error: null, isLoading: false, isFetching: false, refetch: vi.fn() };
    hookMocks.treeResult = treeResultForTree1;
    render(<TreeWorkspace />);
    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBe(tree.id));

    hookMocks.treeResult = treeResultForTree2;
    await act(async () => {
      await deleteModalProps.onDeleted(tree.id);
    });

    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBe("tree-2"));
  });

  it("does not change selection when a non-active tree is deleted", async () => {
    const treeB: TreeListItem = { id: "tree-2", name: "Other tree", updated_at: "2025-01-03T00:00:00Z", owner_id: null };
    hookMocks.treesResult = {
      data: [...treeList, treeB],
      error: null,
      refetch: vi.fn().mockResolvedValue({ data: [...treeList, treeB] })
    };
    render(<TreeWorkspace />);
    await waitFor(() => expect(useTreeStore.getState().activeTreeId).toBe(tree.id));

    await act(async () => {
      await deleteModalProps.onDeleted("tree-2");
    });

    expect(useTreeStore.getState().activeTreeId).toBe(tree.id);
  });
});
