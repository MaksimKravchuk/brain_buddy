import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CrtDeleteTreeDialog, CrtPendingWorkDialog } from "../CrtDeleteConfirmation";

describe("CRT destructive confirmations", () => {
  it("D-06-TD starts on the safe action and names the tree deletion consequences", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(
      <CrtDeleteTreeDialog
        treeName="Supply chain CRT"
        cardCount={12}
        relationCount={15}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />
    );

    const dialog = screen.getByRole("alertdialog", { name: "Delete ‘Supply chain CRT’?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("Deletes 12 cards and 15 relations from BrainBuddy.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("D-06-TD confirms once, reports delayed progress, and keeps errors recoverable", async () => {
    const user = userEvent.setup();
    let resolveDelete!: () => void;
    const onConfirm = vi.fn(() => new Promise<void>((resolve) => { resolveDelete = resolve; }));
    render(
      <CrtDeleteTreeDialog
        treeName="Supply chain CRT"
        cardCount={1}
        relationCount={0}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />
    );

    await user.click(screen.getByRole("button", { name: "Delete tree" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Delete tree" })).toBeDisabled();
    expect(screen.getByRole("alertdialog")).toHaveAttribute("aria-busy", "true");
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 320)); });
    expect(screen.getByRole("status", { name: "Deleting tree…" })).toBeInTheDocument();
    resolveDelete();
    expect(await screen.findByText("Tree deletion completed.", { selector: "[aria-live]" })).toBeInTheDocument();
  });

  it("D-06-PW keeps transition safe, identifies every affected tree, and blocks discard offline", async () => {
    const user = userEvent.setup();
    const onStay = vi.fn();
    const onBackup = vi.fn();
    const onDiscard = vi.fn();
    render(
      <CrtPendingWorkDialog
        affectedTrees={[{ id: "tree-1", name: "Supply chain CRT", editCount: 3 }, { id: "tree-2", name: "Onboarding CRT", editCount: 1 }]}
        offline
        onStayAndRetry={onStay}
        onDownloadBackup={onBackup}
        onDiscardAndContinue={onDiscard}
      />
    );

    expect(screen.getByRole("dialog", { name: "Resolve unsynced changes before continuing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stay and retry" })).toHaveFocus();
    expect(screen.getByText("Supply chain CRT · 3 unsynced edits")).toBeInTheDocument();
    expect(screen.getByText("Onboarding CRT · 1 unsynced edit")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard and continue" })).toBeDisabled();
    expect(screen.getByText("Reconnect before discarding or continuing.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Download backup" }));
    expect(onBackup).toHaveBeenCalledOnce();
    expect(onDiscard).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Stay and retry" }));
    expect(onStay).toHaveBeenCalledOnce();
  });

  it("covers modal tab wrapping, support references, and ignores Escape while busy", async () => {
    const user = userEvent.setup();
    let resolveDelete!: () => void;
    const returnFocus = document.createElement("button");
    returnFocus.type = "button";
    document.body.append(returnFocus);
    returnFocus.focus();
    const onCancel = vi.fn();
    render(
      <CrtDeleteTreeDialog
        treeName="One card"
        cardCount={1}
        relationCount={1}
        supportReference="delete-ref"
        returnFocusRef={{ current: returnFocus }}
        onCancel={onCancel}
        onConfirm={() => new Promise<void>((resolve) => { resolveDelete = resolve; })}
      />
    );
    expect(screen.getByText("Support reference: delete-ref")).toBeInTheDocument();
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Delete tree" });
    confirm.focus();
    await user.tab();
    expect(cancel).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();
    await user.click(confirm);
    await user.keyboard("{Tab}");
    await user.keyboard("{Escape}");
    expect(onCancel).not.toHaveBeenCalled();
    resolveDelete();
    await screen.findByText("Tree deletion completed.", { selector: "[aria-live]" });
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledOnce();
    returnFocus.remove();
  });

  it("shows a recoverable delete failure and permits a successful retry", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(undefined);
    render(
      <CrtDeleteTreeDialog
        treeName="Retry tree"
        cardCount={2}
        relationCount={2}
        offline={false}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />
    );
    await user.click(screen.getByRole("button", { name: "Delete tree" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was deleted");
    await user.click(screen.getByRole("button", { name: "Delete tree" }));
    expect(onConfirm).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Tree deletion completed.", { selector: "[aria-live]" })).toBeInTheDocument();
  });

  it("blocks delete while offline and supports pending-work errors and progress", async () => {
    const user = userEvent.setup();
    let resolveStay!: () => void;
    const onStay = vi.fn(() => new Promise<void>((resolve) => { resolveStay = resolve; }));
    const onBackup = vi.fn().mockRejectedValue(new Error("backup unavailable"));
    const onDiscard = vi.fn().mockRejectedValue(new Error("discard unavailable"));
    render(
      <CrtPendingWorkDialog
        affectedTrees={[]}
        onStayAndRetry={onStay}
        onDownloadBackup={onBackup}
        onDiscardAndContinue={onDiscard}
        offline={false}
        error="Enumeration failed"
        supportReference="pending-ref"
      />
    );
    expect(screen.getByText("Enumeration failed")).toBeInTheDocument();
    expect(screen.getByText("Support reference: pending-ref")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Download backup" }));
    expect(await screen.findAllByRole("alert")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Stay and retry" }));
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 320)); });
    expect(screen.getByRole("status")).toHaveTextContent("Working");
    resolveStay();
    expect(await screen.findByText("Save retry started.", { selector: "[aria-live]" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect(screen.getAllByRole("alert")[1]).toHaveTextContent("couldn't discard the unsynced changes");
  });

  it("renders the offline delete guard and keeps the destructive action disabled", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    render(
      <CrtDeleteTreeDialog
        treeName="Offline tree"
        cardCount={0}
        relationCount={2}
        offline
        onCancel={onCancel}
        onConfirm={onConfirm}
      />
    );

    expect(screen.getByText("Reconnect before deleting this tree.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete tree" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("does not start a second destructive action while the first is pending", async () => {
    const user = userEvent.setup();
    let resolveDelete!: () => void;
    const onConfirm = vi.fn(() => new Promise<void>((resolve) => { resolveDelete = resolve; }));
    render(
      <CrtDeleteTreeDialog
        treeName="Single flight"
        cardCount={2}
        relationCount={2}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />
    );

    const button = screen.getByRole("button", { name: "Delete tree" });
    await user.click(button);
    expect(button).toBeDisabled();
    expect(onConfirm).toHaveBeenCalledOnce();
    resolveDelete();
    expect(await screen.findByText("Tree deletion completed.", { selector: "[aria-live]" })).toBeInTheDocument();
  });

  it("falls back to the previously focused element when a return ref is empty", async () => {
    const user = userEvent.setup();
    const previous = document.createElement("button");
    document.body.append(previous);
    previous.focus();
    const onCancel = vi.fn();
    render(
      <CrtDeleteTreeDialog
        treeName="Focus fallback"
        cardCount={0}
        relationCount={0}
        returnFocusRef={{ current: null }}
        onCancel={onCancel}
        onConfirm={vi.fn()}
      />
    );
    const dialog = screen.getByRole("alertdialog");
    dialog.focus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByRole("button", { name: "Delete tree" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledOnce();
    previous.remove();
  });

  it("rejects duplicate synchronous clicks while a delete is starting", async () => {
    const user = userEvent.setup();
    let resolveDelete!: () => void;
    const onConfirm = vi.fn(() => new Promise<void>((resolve) => { resolveDelete = resolve; }));
    render(
      <CrtDeleteTreeDialog
        treeName="Duplicate click"
        cardCount={0}
        relationCount={0}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />
    );
    const button = screen.getByRole("button", { name: "Delete tree" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(onConfirm).toHaveBeenCalledOnce();
    resolveDelete();
    expect(await screen.findByText("Tree deletion completed.", { selector: "[aria-live]" })).toBeInTheDocument();
    void user;
  });

  it("covers the non-wrapping reverse tab path from the last destructive action", async () => {
    const user = userEvent.setup();
    render(
      <CrtDeleteTreeDialog
        treeName="Reverse tab"
        cardCount={1}
        relationCount={1}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />
    );
    const confirm = screen.getByRole("button", { name: "Delete tree" });
    confirm.focus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("ignores an Escape key while a pending-work action is active", async () => {
    const user = userEvent.setup();
    let resolveStay!: () => void;
    const onCancel = vi.fn();
    render(
      <CrtPendingWorkDialog
        affectedTrees={[]}
        onStayAndRetry={() => new Promise<void>((resolve) => { resolveStay = resolve; })}
        onDownloadBackup={vi.fn()}
        onDiscardAndContinue={vi.fn()}
        onCancel={onCancel}
      />
    );
    await user.click(screen.getByRole("button", { name: "Stay and retry" }));
    await user.keyboard("{Escape}");
    expect(onCancel).not.toHaveBeenCalled();
    await act(async () => { resolveStay(); await Promise.resolve(); });
  });

  it("ignores late async completion after either dialog unmounts and supports pending Escape cancellation", async () => {
    let resolveBackup!: () => void;
    const pending = render(
      <CrtPendingWorkDialog
        affectedTrees={[]}
        onStayAndRetry={vi.fn()}
        onDownloadBackup={() => new Promise<void>((resolve) => { resolveBackup = resolve; })}
        onDiscardAndContinue={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    await act(async () => {
      screen.getByRole("button", { name: "Download backup" }).click();
      await Promise.resolve();
    });
    pending.unmount();
    await act(async () => { resolveBackup(); await Promise.resolve(); });

    let rejectDelete!: (reason?: unknown) => void;
    const deleteDialog = render(
      <CrtDeleteTreeDialog
        treeName="Late delete"
        cardCount={0}
        relationCount={0}
        onCancel={vi.fn()}
        onConfirm={() => new Promise<void>((_resolve, reject) => { rejectDelete = reject; })}
      />
    );
    await act(async () => {
      screen.getByRole("button", { name: "Delete tree" }).click();
      await Promise.resolve();
    });
    deleteDialog.unmount();
    await act(async () => { rejectDelete(new Error("late failure")); await Promise.resolve(); });

    const onCancel = vi.fn();
    render(
      <CrtPendingWorkDialog
        affectedTrees={[]}
        onStayAndRetry={vi.fn()}
        onDownloadBackup={vi.fn()}
        onDiscardAndContinue={vi.fn()}
        onCancel={onCancel}
      />
    );
    const user = userEvent.setup();
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("does not restore focus through a non-HTMLElement active element", () => {
    const previousDescriptor = Object.getOwnPropertyDescriptor(document, "activeElement");
    const textNode = document.createTextNode("not focusable");
    Object.defineProperty(document, "activeElement", { configurable: true, get: () => textNode });
    try {
      const onCancel = vi.fn();
      render(
        <CrtDeleteTreeDialog
          treeName="Non-HTML focus"
          cardCount={0}
          relationCount={0}
          onCancel={onCancel}
          onConfirm={vi.fn()}
        />
      );
      fireEvent.keyDown(document, { key: "Escape" });
      expect(onCancel).toHaveBeenCalledOnce();
    } finally {
      if (previousDescriptor) Object.defineProperty(document, "activeElement", previousDescriptor);
      else Reflect.deleteProperty(document, "activeElement");
    }
  });

  it("ignores a delayed progress callback after unmount", async () => {
    vi.useFakeTimers();
    const clearTimeout = vi.spyOn(window, "clearTimeout").mockImplementation(() => undefined);
    let resolveDelete!: () => void;
    try {
      const rendered = render(
        <CrtDeleteTreeDialog
          treeName="Unmount before progress"
          cardCount={0}
          relationCount={0}
          onCancel={vi.fn()}
          onConfirm={() => new Promise<void>((resolve) => { resolveDelete = resolve; })}
        />
      );
      fireEvent.click(screen.getByRole("button", { name: "Delete tree" }));
      rendered.unmount();
      await act(async () => { vi.advanceTimersByTime(301); });
      expect(document.body).not.toHaveTextContent("Deleting tree…");
      resolveDelete();
      await act(async () => { await Promise.resolve(); });
    } finally {
      clearTimeout.mockRestore();
      vi.useRealTimers();
    }
  });

  it("ignores a Tab event delivered after the panel unmounts", () => {
    const rendered = render(
      <CrtDeleteTreeDialog
        treeName="Unmounted panel"
        cardCount={0}
        relationCount={0}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />
    );
    const removeListener = vi.spyOn(document, "removeEventListener").mockImplementation(() => undefined);
    rendered.unmount();
    try {
      expect(() => fireEvent.keyDown(document, { key: "Tab" })).not.toThrow();
    } finally {
      removeListener.mockRestore();
    }
  });
});
