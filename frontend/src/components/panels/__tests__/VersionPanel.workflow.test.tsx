import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TreeDetailResponse, VersionListItem } from "../../../api/types";
import { useTreeStore } from "../../../stores/treeStore";
import { useUiStore } from "../../../stores/uiStore";
import { VersionPanel } from "../VersionPanel";

const hookMocks = vi.hoisted(() => ({
  create: { mutate: vi.fn(), isPending: false },
  remove: { mutate: vi.fn(), isPending: false },
  restore: { mutate: vi.fn(), isPending: false },
  exportTree: { mutate: vi.fn(), isPending: false }
}));

vi.mock("../../../api/hooks", () => ({
  useCreateVersion: () => hookMocks.create,
  useDeleteVersion: () => hookMocks.remove,
  useRestoreVersion: () => hookMocks.restore,
  useExportTree: () => hookMocks.exportTree
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

const version: VersionListItem = {
  id: "version-1",
  label: "Before changes",
  author: "Max",
  notes: "Baseline",
  created_at: "2025-01-01T00:00:00Z",
  conflict_count: 2,
  diff_summary: {
    nodes_added: 1,
    nodes_removed: 2,
    nodes_modified: 3,
    relations_added: 4,
    relations_removed: 5,
    relations_modified: 6
  }
};

function lastToast() {
  const { toasts } = useUiStore.getState();
  return toasts[toasts.length - 1];
}

describe("VersionPanel workflows", () => {
  beforeEach(() => {
    for (const mutation of [hookMocks.create, hookMocks.remove, hookMocks.restore, hookMocks.exportTree]) {
      mutation.mutate.mockReset();
    }
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
      useTreeStore.getState().setTree(tree);
      useTreeStore.getState().setVersions([
        {
          id: version.id,
          label: version.label,
          author: version.author,
          notes: version.notes,
          createdAt: version.created_at,
          conflictCount: version.conflict_count,
          diffSummary: {
            nodesAdded: 1,
            nodesRemoved: 2,
            nodesModified: 3,
            relationsAdded: 4,
            relationsRemoved: 5,
            relationsModified: 6
          }
        }
      ]);
    });
  });

  it("describes an initial unlabeled snapshot and renders versions without optional metadata", async () => {
    const user = userEvent.setup();
    const initialVersion = { ...version, label: "Initial", author: null, notes: null, conflict_count: 0, diff_summary: null };
    hookMocks.create.mutate.mockImplementation((_payload, options) => options?.onSuccess(initialVersion));
    render(<VersionPanel />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Capture snapshot" }));
    });

    expect(hookMocks.create.mutate).toHaveBeenCalledWith(
      { label: null, author: null, notes: null },
      expect.any(Object)
    );
    expect(lastToast()).toMatchObject({ description: "Initial snapshot captured." });
    expect(screen.getByText("Initial snapshot of this tree.")).toBeInTheDocument();
    expect(screen.queryByText(/potential conflicts/)).not.toBeInTheDocument();
  });

  it("captures a labeled snapshot and reports its change summary", async () => {
    const user = userEvent.setup();
    hookMocks.create.mutate.mockImplementation((_payload, options) => options?.onSuccess(version));
    render(<VersionPanel />);

    await act(async () => {
      await user.type(screen.getByLabelText("Snapshot label"), "  Before changes  ");
      await user.type(screen.getByLabelText(/Author/), "  Max  ");
      await user.type(screen.getByLabelText(/Notes/), "  Baseline  ");
      await user.click(screen.getByRole("button", { name: "Capture snapshot" }));
    });

    expect(hookMocks.create.mutate).toHaveBeenCalledWith(
      { label: "Before changes", author: "Max", notes: "Baseline" },
      expect.any(Object)
    );
    expect(lastToast()).toMatchObject({ title: "Snapshot captured", description: "Nodes +1/-2/~3, Relations +4/-5/~6" });
    expect(screen.getByLabelText("Snapshot label")).toHaveValue("");
    expect(screen.getByLabelText(/Author/)).toHaveValue("");
    expect(screen.getByLabelText(/Notes/)).toHaveValue("");
  });

  it("confirms restore and deletion actions for a selected snapshot", async () => {
    const user = userEvent.setup();
    hookMocks.restore.mutate.mockImplementation((_id, options) => options?.onSuccess({ ...tree, name: "Restored tree" }));
    hookMocks.remove.mutate.mockImplementation((_id, options) => options?.onSuccess());
    render(<VersionPanel />);

    expect(screen.getByText("2 potential conflicts detected when this snapshot was saved.")).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Restore" }));
    });
    expect(screen.getByRole("heading", { name: "Restore snapshot" })).toBeInTheDocument();
    expect(screen.getByText(/2 potential conflicts will be overwritten/)).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getAllByRole("button", { name: "Restore" })[1]);
    });
    expect(hookMocks.restore.mutate).toHaveBeenCalledWith(version.id, expect.any(Object));
    expect(useTreeStore.getState().metadata?.name).toBe("Restored tree");
    act(() => {
      useTreeStore.getState().setVersions([
        {
          id: version.id,
          label: version.label,
          author: version.author,
          notes: version.notes,
          createdAt: version.created_at,
          conflictCount: version.conflict_count,
          diffSummary: null
        }
      ]);
    });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Delete" }));
    });
    expect(screen.getByRole("heading", { name: "Delete snapshot" })).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getAllByRole("button", { name: "Delete" })[1]);
    });
    expect(hookMocks.remove.mutate).toHaveBeenCalledWith(version.id, expect.any(Object));
    expect(useTreeStore.getState().versions).toEqual([]);
    expect(lastToast()).toMatchObject({ title: "Snapshot deleted" });
  });

  it("explains an empty snapshot history and mutation failures", async () => {
    const user = userEvent.setup();
    act(() => useTreeStore.getState().setVersions([]));
    hookMocks.create.mutate.mockImplementation((_payload, options) => options?.onError(new Error("Capture unavailable")));
    hookMocks.exportTree.mutate.mockImplementation((_payload, options) => options?.onError(new Error("Export unavailable")));
    render(<VersionPanel />);

    expect(screen.getByText("No versions captured yet.")).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Capture snapshot" }));
    });
    expect(lastToast()).toMatchObject({ title: "Failed to create snapshot", description: "Capture unavailable" });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Export" }));
    });
    expect(lastToast()).toMatchObject({ title: "Export failed", description: "Export unavailable" });
  });

  it("downloads an exported tree using its current update timestamp", async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn(() => "blob:tree-export");
    const revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    hookMocks.exportTree.mutate.mockImplementation((_payload, options) => options?.onSuccess({ tree }));
    render(<VersionPanel />);

    await act(async () => {
      await user.click(screen.getAllByRole("button", { name: "Export" })[0]);
    });

    expect(hookMocks.exportTree.mutate).toHaveBeenCalledWith(undefined, expect.any(Object));
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:tree-export");
    expect(lastToast()).toMatchObject({ title: "Export ready", description: "Current tree-2025-01-02T000000Z.json" });
  });

  it("keeps snapshot data intact when restore or deletion fails", async () => {
    const user = userEvent.setup();
    hookMocks.restore.mutate.mockImplementation((_id, options) => options?.onError(new Error("Restore unavailable")));
    hookMocks.remove.mutate.mockImplementation((_id, options) => options?.onError(new Error("Delete unavailable")));
    render(<VersionPanel />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Restore" }));
    });
    await act(async () => {
      await user.click(screen.getAllByRole("button", { name: "Restore" })[1]);
    });
    expect(lastToast()).toMatchObject({ title: "Failed to restore version", description: "Restore unavailable" });
    expect(useTreeStore.getState().versions).toHaveLength(1);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Delete" }));
    });
    await act(async () => {
      await user.click(screen.getAllByRole("button", { name: "Delete" })[1]);
    });
    expect(lastToast()).toMatchObject({ title: "Failed to delete snapshot", description: "Delete unavailable" });
    expect(useTreeStore.getState().versions).toHaveLength(1);
  });
});
