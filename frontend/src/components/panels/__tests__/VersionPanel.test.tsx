import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TreeDetailResponse } from "../../../api/types";
import { useTreeStore } from "../../../stores/treeStore";
import { VersionPanel } from "../VersionPanel";

vi.mock("../../../api/hooks", () => ({
  useCreateVersion: () => ({ isPending: false, mutate: vi.fn() }),
  useDeleteVersion: () => ({ isPending: false, mutate: vi.fn() }),
  useExportTree: () => ({ isPending: false, mutate: vi.fn() }),
  useRestoreVersion: () => ({ isPending: false, mutate: vi.fn() })
}));

const tree: TreeDetailResponse = {
  id: "tree-1",
  name: "Versioned tree",
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

afterEach(() => {
  act(() => useTreeStore.getState().reset());
});

describe("VersionPanel", () => {
  it("renders its controls when a tree is selected after the placeholder", async () => {
    render(<VersionPanel />);
    expect(screen.getByText("Select a tree to manage versions.")).toBeInTheDocument();

    act(() => useTreeStore.getState().setTree(tree));

    expect(await screen.findByLabelText("Snapshot label")).toBeInTheDocument();
  });
});
