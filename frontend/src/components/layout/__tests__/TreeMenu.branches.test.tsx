import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TreeMenu } from "../TreeMenu";

const baseTrees = [
  { id: "tree-1", name: "Current tree", updated_at: "2025-01-01T00:00:00Z", owner_id: null },
  { id: "tree-2", name: "Other tree", updated_at: "2024-12-01T00:00:00Z", owner_id: null }
];

function renderTreeMenu(overrides: Partial<React.ComponentProps<typeof TreeMenu>> = {}) {
  const props = {
    treeName: "Current tree",
    activeTreeId: "tree-1",
    trees: baseTrees,
    isDownloading: false,
    isImporting: false,
    onCreateTree: vi.fn(),
    onRenameTree: vi.fn(),
    onDownload: vi.fn(),
    onImportClick: vi.fn(),
    onDeleteTree: vi.fn(),
    onSwitchTree: vi.fn(),
    ...overrides
  };
  return { ...render(<TreeMenu {...props} />), props };
}

describe("TreeMenu formatRelativeTime branches", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows relative time labels for recent, minutes, hours, days, and months", async () => {
    const user = userEvent.setup();
    const now = Date.now();
    const minute = 1000 * 60;
    const hour = minute * 60;
    const day = hour * 24;

    const trees = [
      { id: "t1", name: "Recent", updated_at: new Date(now - 30 * 1000).toISOString(), owner_id: null },
      { id: "t2", name: "Minutes", updated_at: new Date(now - 5 * minute).toISOString(), owner_id: null },
      { id: "t3", name: "Hours", updated_at: new Date(now - 3 * hour).toISOString(), owner_id: null },
      { id: "t4", name: "Days", updated_at: new Date(now - 5 * day).toISOString(), owner_id: null },
      { id: "t5", name: "Months", updated_at: new Date(now - 40 * day).toISOString(), owner_id: null },
      { id: "t6", name: "Years", updated_at: new Date(now - 400 * day).toISOString(), owner_id: null },
      { id: "tree-1", name: "Current tree", updated_at: new Date(now).toISOString(), owner_id: null }
    ];

    renderTreeMenu({ activeTreeId: "tree-1", trees });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Tree menu" }));
    });

    expect(screen.getByText(/just now/)).toBeInTheDocument();
    expect(screen.getByText(/5m ago/)).toBeInTheDocument();
    expect(screen.getByText(/3h ago/)).toBeInTheDocument();
    expect(screen.getByText(/5d ago/)).toBeInTheDocument();
    expect(screen.getByText(/1mo ago/)).toBeInTheDocument();
    expect(screen.getByText(/1y ago/)).toBeInTheDocument();
  });

  it("shows the raw timestamp when the date is invalid", async () => {
    const user = userEvent.setup();
    renderTreeMenu({ trees: [{ id: "bad", name: "Bad date", updated_at: "not-a-date", owner_id: null }] });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Tree menu" }));
    });

    expect(screen.getByText(/Updated not-a-date/)).toBeInTheDocument();
  });
});
