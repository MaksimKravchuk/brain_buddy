import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateNodeButton } from "../CreateNodeButton";
import { Layout } from "../layout/Layout";
import { SidePanel } from "../layout/SidePanel";
import { TreeSelector } from "../topbar/TreeSelector";
import { ToastStack } from "../ui/ToastStack";
import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";

const trees = [
  { id: "tree-1", name: "Current tree", updated_at: "2025-01-01T00:00:00Z", owner_id: null },
  { id: "tree-2", name: "Another tree", updated_at: "2025-01-02T00:00:00Z", owner_id: null }
];

describe("basic workspace interactions", () => {
  beforeEach(() => {
    act(() => {
      useTreeStore.getState().reset();
      useUiStore.getState().clearToasts();
      useUiStore.setState({
        modals: { createTree: false, renameTree: false, deleteTree: false, manageVersions: false }
      });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates named and default parent nodes from the creation controls", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn();
    render(<CreateNodeButton onCreate={onCreate} />);

    await act(async () => {
      await user.type(screen.getByPlaceholderText("Node label"), "  Root cause  ");
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Parent" }));
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add" }));
    });

    expect(onCreate).toHaveBeenLastCalledWith({ type: "parent", label: "Root cause" });
    expect(screen.getByPlaceholderText("Node label")).toHaveValue("");

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add" }));
    });
    expect(onCreate).toHaveBeenLastCalledWith({ type: "parent", label: "Parent" });
  });

  it("keeps node creation disabled when requested", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn();
    render(<CreateNodeButton disabled onCreate={onCreate} />);

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("selects trees, opens creation, and forwards import files", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onSave = vi.fn();
    const onDownload = vi.fn();
    const onImport = vi.fn();
    render(
      <TreeSelector
        trees={trees}
        value="tree-1"
        onChange={onChange}
        onSave={onSave}
        onDownload={onDownload}
        onImport={onImport}
      />
    );

    await act(async () => {
      await user.selectOptions(screen.getByRole("combobox"), "tree-2");
    });
    expect(onChange).toHaveBeenCalledWith("tree-2");

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "New" }));
    });
    expect(useUiStore.getState().modals.createTree).toBe(true);
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Save" }));
      await user.click(screen.getByRole("button", { name: "Download" }));
    });
    expect(onSave).toHaveBeenCalledOnce();
    expect(onDownload).toHaveBeenCalledOnce();

    const file = new File(["{}"], "tree.json", { type: "application/json" });
    const importInput = document.querySelector<HTMLInputElement>("#tree-import-input");
    if (!importInput) {
      throw new Error("Expected the import input to be rendered");
    }
    fireEvent.change(importInput, { target: { files: [file] } });
    expect(onImport).toHaveBeenCalledWith(file);
  });

  it("renders loading controls as unavailable", () => {
    render(
      <TreeSelector
        trees={[]}
        value={null}
        onChange={vi.fn()}
        isLoading
        isSaving
        isDownloading
        isImporting
      />
    );

    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Preparing…" })).toBeDisabled();
    expect(screen.getByText("Importing…")).toBeInTheDocument();
  });

  it("renders all side panel slots only when supplied", () => {
    const { rerender } = render(<SidePanel>Panel content</SidePanel>);
    expect(screen.getByText("Panel content")).toBeInTheDocument();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();

    rerender(
      <SidePanel title="Inspector" toolbar={<button type="button">Filter</button>} footer="Footer text">
        Panel content
      </SidePanel>
    );
    expect(screen.getByRole("heading", { name: "Inspector" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Filter" })).toBeInTheDocument();
    expect(screen.getByText("Footer text")).toBeInTheDocument();
  });

  it("warns on unload only while a tree has unsynced changes", () => {
    const { rerender, unmount } = render(
      <Layout header="Header" sidebar="Sidebar" footer="Footer">
        Main
      </Layout>
    );
    const cleanEvent = new Event("beforeunload", { cancelable: true });
    expect(window.dispatchEvent(cleanEvent)).toBe(true);

    act(() => useTreeStore.setState({ pendingSync: true }));
    rerender(
      <Layout header="Header" sidebar="Sidebar" footer="Footer">
        Main
      </Layout>
    );
    const dirtyEvent = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
    expect(window.dispatchEvent(dirtyEvent)).toBe(false);
    // jsdom represents a cancelled beforeunload event as `returnValue === false`.
    expect(dirtyEvent.defaultPrevented).toBe(true);
    unmount();
    expect(window.dispatchEvent(new Event("beforeunload", { cancelable: true }))).toBe(true);
  });

  it("runs toast actions and dismisses notifications", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    act(() => {
      useUiStore.getState().pushToast({
        id: "warning",
        title: "Needs attention",
        description: "Review this tree",
        variant: "warning",
        duration: 0,
        action: { label: "Review", onClick: onAction }
      });
      useUiStore.getState().pushToast({
        id: "failure",
        title: "Failed",
        variant: "error",
        duration: 0
      });
    });
    render(<ToastStack />);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Review" }));
    });
    expect(onAction).toHaveBeenCalledOnce();
    expect(useUiStore.getState().toasts.find((toast) => toast.id === "warning")?.dismissing).toBe(true);

    await act(async () => {
      await user.click(screen.getAllByRole("button", { name: "Dismiss notification" })[1]);
    });
    expect(useUiStore.getState().toasts.find((toast) => toast.id === "failure")?.dismissing).toBe(true);
  });
});
