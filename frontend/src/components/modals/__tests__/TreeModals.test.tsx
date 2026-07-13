import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TreeDetailResponse, TreeListItem } from "../../../api/types";
import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";
import { CreateTreeModal } from "../CreateTreeModal";
import { DeleteTreeModal } from "../DeleteTreeModal";
import { RenameTreeModal } from "../RenameTreeModal";

const hookMocks = vi.hoisted(() => ({
  createTree: vi.fn(),
  renameTree: vi.fn(),
  deleteTree: vi.fn()
}));

vi.mock("../../../api/hooks", () => ({
  useCreateTree: () => ({ isPending: false, mutate: hookMocks.createTree }),
  useRenameTree: () => ({ isPending: false, mutate: hookMocks.renameTree }),
  useDeleteTree: () => ({ isPending: false, mutate: hookMocks.deleteTree })
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
  nodes: [],
  relations: [],
  owner_id: null
};

const trees: TreeListItem[] = [
  { id: tree.id, name: tree.name, updated_at: tree.metadata.updated_at, owner_id: null }
];

function setModal(name: "createTree" | "renameTree" | "deleteTree", isOpen: boolean) {
  act(() => {
    useUiStore.setState({
      modals: { createTree: false, renameTree: false, deleteTree: false, manageVersions: false, [name]: isOpen }
    });
  });
}

function lastToast() {
  const { toasts } = useUiStore.getState();
  return toasts[toasts.length - 1];
}

describe("tree management modals", () => {
  beforeEach(() => {
    hookMocks.createTree.mockReset();
    hookMocks.renameTree.mockReset();
    hookMocks.deleteTree.mockReset();
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
      useUiStore.setState({
        modals: { createTree: false, renameTree: false, deleteTree: false, manageVersions: false }
      });
    });
  });

  it("requires a non-blank tree name before creating", async () => {
    const user = userEvent.setup();
    setModal("createTree", true);
    render(<CreateTreeModal onCreated={vi.fn()} />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Create tree" }));
    });

    expect(hookMocks.createTree).not.toHaveBeenCalled();
    expect(lastToast()).toMatchObject({ title: "Name required", variant: "warning" });
  });

  it("creates a trimmed tree name and gives the workspace the created tree", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    hookMocks.createTree.mockImplementation((_payload, options) => options?.onSuccess(tree));
    setModal("createTree", true);
    render(<CreateTreeModal onCreated={onCreated} />);

    await act(async () => {
      await user.type(screen.getByLabelText("Name"), "  Current tree  ");
      await user.click(screen.getByRole("button", { name: "Create tree" }));
    });

    expect(hookMocks.createTree).toHaveBeenCalledWith({ name: "Current tree" }, expect.any(Object));
    expect(onCreated).toHaveBeenCalledWith(tree);
    expect(useUiStore.getState().modals.createTree).toBe(false);
    expect(lastToast()).toMatchObject({ title: "Tree created", variant: "success" });
  });

  it("closes unchanged renames without sending an update", async () => {
    const user = userEvent.setup();
    act(() => useTreeStore.getState().setTree(tree));
    setModal("renameTree", true);
    render(<RenameTreeModal />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Save name" }));
    });

    expect(hookMocks.renameTree).not.toHaveBeenCalled();
    expect(useUiStore.getState().modals.renameTree).toBe(false);
  });

  it("renames and deletes the active tree through confirmed modal actions", async () => {
    const user = userEvent.setup();
    act(() => useTreeStore.getState().setTree(tree));
    hookMocks.renameTree.mockImplementation((_name, options) => options?.onSuccess());
    setModal("renameTree", true);
    const { unmount } = render(<RenameTreeModal />);

    const input = screen.getByLabelText("Name");
    await act(async () => {
      await user.clear(input);
      await user.type(input, "Renamed tree");
      await user.click(screen.getByRole("button", { name: "Save name" }));
    });

    expect(hookMocks.renameTree).toHaveBeenCalledWith("Renamed tree", expect.any(Object));
    expect(lastToast()).toMatchObject({ title: "Tree renamed", variant: "success" });
    unmount();

    const onDeleted = vi.fn();
    hookMocks.deleteTree.mockImplementation((_id, options) => options?.onSuccess());
    setModal("deleteTree", true);
    render(<DeleteTreeModal trees={trees} onDeleted={onDeleted} />);
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Delete" }));
    });

    expect(hookMocks.deleteTree).toHaveBeenCalledWith(tree.id, expect.any(Object));
    expect(onDeleted).toHaveBeenCalledWith(tree.id);
    expect(useUiStore.getState().modals.deleteTree).toBe(false);
    expect(lastToast()).toMatchObject({ title: "Tree deleted", variant: "success" });
  });

  it("keeps management modals open and explains mutation failures", async () => {
    const user = userEvent.setup();
    hookMocks.createTree.mockImplementation((_payload, options) => options?.onError(new Error("Cannot create")));
    setModal("createTree", true);
    const { unmount } = render(<CreateTreeModal onCreated={vi.fn()} />);
    await act(async () => {
      await user.type(screen.getByLabelText("Name"), "New tree");
      await user.click(screen.getByRole("button", { name: "Create tree" }));
    });
    expect(lastToast()).toMatchObject({ title: "Failed to create tree", description: "Cannot create" });
    expect(useUiStore.getState().modals.createTree).toBe(true);
    unmount();

    act(() => useTreeStore.getState().setTree(tree));
    hookMocks.renameTree.mockImplementation((_name, options) => options?.onError(new Error("Cannot rename")));
    setModal("renameTree", true);
    const renameView = render(<RenameTreeModal />);
    await act(async () => {
      await user.clear(screen.getByLabelText("Name"));
      await user.type(screen.getByLabelText("Name"), "New name");
      await user.click(screen.getByRole("button", { name: "Save name" }));
    });
    expect(lastToast()).toMatchObject({ title: "Failed to rename tree", description: "Cannot rename" });
    expect(useUiStore.getState().modals.renameTree).toBe(true);
    renameView.unmount();

    hookMocks.deleteTree.mockImplementation((_id, options) => options?.onError(new Error("Cannot delete")));
    setModal("deleteTree", true);
    render(<DeleteTreeModal trees={trees} onDeleted={vi.fn()} />);
    await act(async () => await user.click(screen.getByRole("button", { name: "Delete" })));
    expect(lastToast()).toMatchObject({ title: "Failed to delete tree", description: "Cannot delete" });
    expect(useUiStore.getState().modals.deleteTree).toBe(true);
  });

  it("cancels creation and rejects empty renamed tree names", async () => {
    const user = userEvent.setup();
    setModal("createTree", true);
    const createView = render(<CreateTreeModal onCreated={vi.fn()} />);
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Cancel" }));
    });
    expect(useUiStore.getState().modals.createTree).toBe(false);
    createView.unmount();

    act(() => useTreeStore.getState().setTree(tree));
    setModal("renameTree", true);
    render(<RenameTreeModal />);
    await act(async () => {
      await user.clear(screen.getByLabelText("Name"));
      await user.click(screen.getByRole("button", { name: "Save name" }));
    });
    expect(hookMocks.renameTree).not.toHaveBeenCalled();
    expect(lastToast()).toMatchObject({ title: "Name required", variant: "warning" });
  });
});
