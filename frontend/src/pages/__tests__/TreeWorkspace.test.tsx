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
vi.mock("../../components/modals/DeleteTreeModal", () => ({ DeleteTreeModal: () => null }));

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
});
