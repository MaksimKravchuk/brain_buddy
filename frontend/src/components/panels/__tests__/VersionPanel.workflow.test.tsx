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
});
