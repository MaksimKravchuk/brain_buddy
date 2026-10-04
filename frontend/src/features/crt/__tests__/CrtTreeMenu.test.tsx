import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CrtTreeMenu } from "../CrtTreeMenu";

const trees = [
  { id: "tree-1", name: "Supply chain CRT", updated_at: "2026-09-20T10:00:00Z" },
  { id: "tree-2", name: "Onboarding CRT", updated_at: "2026-09-19T10:00:00Z" }
];

describe("CRT D-02 tree menu", () => {
  it("opens a truthful first-run menu and focuses the enabled create action", async () => {
    const user = userEvent.setup();
    render(
      <CrtTreeMenu
        currentTree={null}
        trees={[]}
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onImport={vi.fn()}
        onExport={vi.fn()}
        onDelete={vi.fn()}
        onSelectTree={vi.fn()}
      />
    );

    const trigger = screen.getByRole("button", { name: /choose a tree to continue/i });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu", { name: "Tree menu" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Create a new tree" })).toHaveFocus();
    expect(screen.getByRole("menuitem", { name: "Rename tree" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Export saved server copy" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Delete tree" })).toBeDisabled();
    expect(screen.getByText("No other trees yet")).toBeInTheDocument();
  });

  it("keeps tree actions keyboard reachable and restores focus when Escape closes", async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    const onExport = vi.fn();
    const onDelete = vi.fn();
    const onSelectTree = vi.fn();
    render(
      <CrtTreeMenu
        currentTree={{ id: "tree-1", name: "Supply chain CRT" }}
        trees={trees}
        onCreate={vi.fn()}
        onRename={onRename}
        onImport={vi.fn()}
        onExport={onExport}
        onDelete={onDelete}
        onSelectTree={onSelectTree}
      />
    );

    const trigger = screen.getByRole("button", { name: /supply chain crt/i });
    await user.click(trigger);
    expect(screen.getByRole("menuitem", { name: "Rename tree" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Export saved server copy" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Delete tree" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Current tree: Supply chain CRT" })).toHaveAttribute("aria-current", "true");

    await user.click(screen.getByRole("menuitem", { name: "Rename tree" }));
    expect(onRename).toHaveBeenCalledOnce();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.keyboard("x");
    await user.keyboard("{ArrowDown}");
    await user.keyboard("{End}");
    await user.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("menu", { name: "Tree menu" })).not.toBeInTheDocument();

    await user.click(trigger);
    await user.click(screen.getByRole("menuitem", { name: "Switch to Onboarding CRT" }));
    expect(onSelectTree).toHaveBeenCalledWith("tree-2");
    expect(onExport).not.toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("passes the selected JSON file to import without exposing a second menu action", async () => {
    const user = userEvent.setup();
    const onImport = vi.fn();
    render(
      <CrtTreeMenu
        currentTree={null}
        trees={[]}
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onImport={onImport}
        onExport={vi.fn()}
        onDelete={vi.fn()}
        onSelectTree={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: /choose a tree/i }));
    await user.click(screen.getByRole("menuitem", { name: "Import tree JSON" }));
    const file = new File([JSON.stringify({ tree: "fixture" })], "tree.json", { type: "application/json" });
    await user.upload(screen.getByLabelText("Choose tree JSON file"), file);
    expect(onImport).toHaveBeenCalledWith(file);
    fireEvent.change(screen.getByLabelText("Choose tree JSON file"), { target: { files: [] } });
    expect(onImport).toHaveBeenCalledOnce();
  });

  it("closes on an outside pointer, supports Home and reverse navigation, and reports busy errors", async () => {
    const user = userEvent.setup();
    const firstRender = render(
      <div>
        <CrtTreeMenu
          currentTree={{ id: "tree-1", name: "Supply chain CRT" }}
          trees={trees}
          busy
          error="Tree operation failed"
          onCreate={vi.fn()}
          onRename={vi.fn()}
          onImport={vi.fn()}
          onExport={vi.fn()}
          onDelete={vi.fn()}
          onSelectTree={vi.fn()}
        />
        <button type="button">Outside</button>
      </div>
    );
    const trigger = screen.getByRole("button", { name: /supply chain crt/i });
    expect(trigger).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Tree operation failed");
    firstRender.unmount();

    // Re-render with an enabled trigger so the document-level handlers are exercised.
    const rerender = render(
      <CrtTreeMenu
        currentTree={{ id: "tree-1", name: "Supply chain CRT" }}
        trees={trees}
        error="Tree operation failed"
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onImport={vi.fn()}
        onExport={vi.fn()}
        onDelete={vi.fn()}
        onSelectTree={vi.fn()}
      />
    );
    const enabledTrigger = rerender.getByRole("button", { name: /supply chain crt/i });
    await user.click(enabledTrigger);
    fireEvent.keyDown(document, { key: "End" });
    await user.keyboard("{End}");
    await user.keyboard("{Home}");
    expect(screen.getByRole("menuitem", { name: "Create a new tree" })).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitem", { name: "Switch to Onboarding CRT" })).toHaveFocus();
    fireEvent.pointerDown(document.body);
    expect(enabledTrigger).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("shows busy progress when work starts after the menu is open", async () => {
    const user = userEvent.setup();
    const view = render(
      <CrtTreeMenu
        currentTree={{ id: "tree-1", name: "Supply chain CRT" }}
        trees={trees}
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onImport={vi.fn()}
        onExport={vi.fn()}
        onDelete={vi.fn()}
        onSelectTree={vi.fn()}
      />
    );
    const trigger = screen.getByRole("button", { name: /supply chain crt/i });
    await user.click(trigger);
    view.rerender(
      <CrtTreeMenu
        currentTree={{ id: "tree-1", name: "Supply chain CRT" }}
        trees={trees}
        busy
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onImport={vi.fn()}
        onExport={vi.fn()}
        onDelete={vi.fn()}
        onSelectTree={vi.fn()}
      />
    );
    expect(screen.getByRole("menu", { name: "Tree menu" })).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Working…");
    await user.keyboard("{ArrowDown}");
  });

  it("runs export, delete, and create actions from the menu", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn();
    const onExport = vi.fn();
    const onDelete = vi.fn();
    render(
      <CrtTreeMenu
        currentTree={{ id: "tree-1", name: "Supply chain CRT" }}
        trees={trees}
        onCreate={onCreate}
        onRename={vi.fn()}
        onImport={vi.fn()}
        onExport={onExport}
        onDelete={onDelete}
        onSelectTree={vi.fn()}
      />
    );
    const trigger = screen.getByRole("button", { name: /supply chain crt/i });
    await user.click(trigger);
    fireEvent.keyDown(document, { key: "Enter" });
    await user.click(screen.getByRole("menuitem", { name: "Export saved server copy" }));
    await user.click(trigger);
    await user.click(screen.getByRole("menuitem", { name: "Delete tree" }));
    await user.click(trigger);
    await user.click(screen.getByRole("menuitem", { name: "Create a new tree" }));
    expect(onExport).toHaveBeenCalledOnce();
    expect(onDelete).toHaveBeenCalledOnce();
    expect(onCreate).toHaveBeenCalledOnce();
  });

  it("keeps keyboard navigation safe when every menu item becomes disabled", async () => {
    const user = userEvent.setup();
    const view = render(
      <CrtTreeMenu
        currentTree={null}
        trees={[]}
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onImport={vi.fn()}
        onExport={vi.fn()}
        onDelete={vi.fn()}
        onSelectTree={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: /choose a tree/i }));
    view.rerender(
      <CrtTreeMenu
        currentTree={null}
        trees={[]}
        busy
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onImport={vi.fn()}
        onExport={vi.fn()}
        onDelete={vi.fn()}
        onSelectTree={vi.fn()}
      />
    );
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("status")).toHaveTextContent("Working…");
  });

  it("ignores document navigation after the menu unmounts", async () => {
    const user = userEvent.setup();
    const rendered = render(
      <CrtTreeMenu
        currentTree={{ id: "tree-1", name: "Supply chain CRT" }}
        trees={trees}
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onImport={vi.fn()}
        onExport={vi.fn()}
        onDelete={vi.fn()}
        onSelectTree={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: /supply chain crt/i }));
    const removeListener = vi.spyOn(document, "removeEventListener").mockImplementation(() => undefined);
    rendered.unmount();
    try {
      expect(() => fireEvent.keyDown(document, { key: "End" })).not.toThrow();
    } finally {
      removeListener.mockRestore();
    }
  });
});
