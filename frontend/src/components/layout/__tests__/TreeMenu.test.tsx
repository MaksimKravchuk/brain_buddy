import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TreeMenu } from "../TreeMenu";

const trees = [
  { id: "tree-1", name: "Current tree", updated_at: "2025-01-01T00:00:00Z", owner_id: null },
  { id: "tree-2", name: "Other tree", updated_at: "invalid", owner_id: null }
];

function renderTreeMenu(overrides: Partial<React.ComponentProps<typeof TreeMenu>> = {}) {
  const props = {
    treeName: "Current tree",
    activeTreeId: "tree-1",
    trees,
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

describe("TreeMenu", () => {
  afterEach(() => vi.restoreAllMocks());

  it("routes each active-tree action and switches to another tree", async () => {
    const user = userEvent.setup();
    const { props } = renderTreeMenu();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Tree menu" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: /New tree/ }));
    });
    expect(props.onCreateTree).toHaveBeenCalledOnce();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Tree menu" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: /Rename tree/ }));
    });
    expect(props.onRenameTree).toHaveBeenCalledOnce();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Tree menu" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: /Export to file/ }));
    });
    expect(props.onDownload).toHaveBeenCalledOnce();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Tree menu" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: /Import from file/ }));
    });
    expect(props.onImportClick).toHaveBeenCalledOnce();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Tree menu" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: /Delete tree/ }));
    });
    expect(props.onDeleteTree).toHaveBeenCalledOnce();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Tree menu" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("menuitem", { name: /Other tree/ }));
    });
    expect(props.onSwitchTree).toHaveBeenCalledWith("tree-2");
  });

  it("disables actions requiring an active tree and reports empty switch lists", async () => {
    const user = userEvent.setup();
    renderTreeMenu({ activeTreeId: null, trees: [] });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Tree menu" }));
    });
    expect(screen.getByRole("menuitem", { name: /Rename tree/ })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: /Export to file/ })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: /Delete tree/ })).toBeDisabled();
    expect(screen.getByText("No other trees yet")).toBeInTheDocument();
  });

  it("communicates downloading, importing, and the no-other-trees state", async () => {
    const user = userEvent.setup();
    renderTreeMenu({ trees: [trees[0]], isDownloading: true, isImporting: true });

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Tree menu" }));
    });
    expect(screen.getByRole("menuitem", { name: /Exporting/ })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: /Importing/ })).toBeDisabled();
    expect(screen.getByText("No other trees")).toBeInTheDocument();
  });
});
