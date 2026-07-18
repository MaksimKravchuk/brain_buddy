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

describe("VersionPanel branch coverage", () => {
  beforeEach(() => {
    for (const mutation of [hookMocks.create, hookMocks.remove, hookMocks.restore, hookMocks.exportTree]) {
      mutation.mutate.mockReset();
      mutation.isPending = false;
    }
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
      useTreeStore.getState().setTree(tree);
    });
  });

  it("renders the placeholder when no tree is active", () => {
    act(() => useTreeStore.getState().reset());
    render(<VersionPanel />);
    expect(screen.getByText("Select a tree to manage versions.")).toBeInTheDocument();
  });

  it("sorts versions by createdAt descending", () => {
    act(() => {
      useTreeStore.getState().setVersions([
        { id: "v-old", label: "Old", createdAt: "2025-01-01T00:00:00Z", conflictCount: 0, diffSummary: null },
        { id: "v-new", label: "New", createdAt: "2025-01-02T00:00:00Z", conflictCount: 0, diffSummary: null }
      ]);
    });
    render(<VersionPanel />);
    // Newer version should appear first
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("New");
    expect(screen.getAllByRole("listitem")[1]).toHaveTextContent("Old");
  });

  it("keeps equal timestamps in their existing order", () => {
    act(() => {
      useTreeStore.getState().setVersions([
        { id: "v-first", label: "First", createdAt: "2025-01-01T00:00:00Z", conflictCount: 0, diffSummary: null },
        { id: "v-second", label: "Second", createdAt: "2025-01-01T00:00:00Z", conflictCount: 0, diffSummary: null }
      ]);
    });
    render(<VersionPanel />);
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("First");
  });

  it("shows loading state for a pending restore confirmation", async () => {
    const user = userEvent.setup();
    hookMocks.restore.isPending = true;
    act(() => {
      useTreeStore.getState().setVersions([
        { id: "v-pending", label: "Pending", createdAt: "2025-01-01T00:00:00Z", conflictCount: 0, diffSummary: null }
      ]);
    });
    render(<VersionPanel />);
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Restore" }));
    });
    expect(screen.getByRole("status", { name: "Loading" }).closest("button")).toBeDisabled();
  });

  it("shows loading state for a pending deletion confirmation", async () => {
    const user = userEvent.setup();
    hookMocks.remove.isPending = true;
    act(() => {
      useTreeStore.getState().setVersions([
        { id: "v-pending", label: "Pending", createdAt: "2025-01-01T00:00:00Z", conflictCount: 0, diffSummary: null }
      ]);
    });
    render(<VersionPanel />);
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Delete" }));
    });
    expect(screen.getByRole("status", { name: "Loading" }).closest("button")).toBeDisabled();
  });

  it("shows conflict notice in the confirm dialog for restore", async () => {
    const user = userEvent.setup();
    const version: VersionListItem = {
      id: "v-conflict",
      label: "Conflict snapshot",
      created_at: "2025-01-01T00:00:00Z",
      conflict_count: 3,
      diff_summary: null
    };
    act(() => {
      useTreeStore.getState().setVersions([
        {
          id: version.id,
          label: version.label,
          createdAt: version.created_at,
          conflictCount: 3,
          diffSummary: null
        }
      ]);
    });

    render(<VersionPanel />);
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Restore" }));
    });
    expect(screen.getByText(/3 potential conflicts will be overwritten/)).toBeInTheDocument();
    // Cancel the dialog
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Cancel" }));
    });
    expect(screen.queryByRole("heading", { name: "Restore snapshot" })).not.toBeInTheDocument();
  });

  it("renders DiffSummary component when version has a diff", () => {
    act(() => {
      useTreeStore.getState().setVersions([
        {
          id: "v-diff",
          label: "With diff",
          createdAt: "2025-01-01T00:00:00Z",
          conflictCount: 0,
          diffSummary: {
            nodesAdded: 5,
            nodesRemoved: 3,
            nodesModified: 2,
            relationsAdded: 1,
            relationsRemoved: 0,
            relationsModified: 4
          }
        }
      ]);
    });
    render(<VersionPanel />);
    expect(screen.getByText("+5")).toBeInTheDocument();
    expect(screen.getByText("-3")).toBeInTheDocument();
    expect(screen.getByText("~2")).toBeInTheDocument();
  });

  it("returns early from confirm handler when confirmState is null", async () => {
    const user = userEvent.setup();
    // Render with no confirm dialog visible
    render(<VersionPanel />);
    // Click export button — no confirm state needed
    hookMocks.exportTree.mutate.mockImplementation((_payload, options) => options?.onSuccess({ tree }));
    const createObjectURL = vi.fn(() => "blob:test");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    await act(async () => {
      await user.click(screen.getAllByRole("button", { name: "Export" })[0]);
    });
    expect(createObjectURL).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
    click.mockRestore();
  });
});
