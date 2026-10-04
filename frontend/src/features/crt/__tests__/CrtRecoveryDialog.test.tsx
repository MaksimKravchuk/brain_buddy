import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CrtRecoveryDialog, CrtStorageUnavailableAlert, type CrtConflictDialogProps } from "../CrtRecoveryDialog";

describe("CrtRecoveryDialog stale draft recovery", () => {
  it("starts with the safe Recover draft action focused and names the tree", () => {
    render(
      <CrtRecoveryDialog
        kind="stale-draft"
        treeName="Supply chain CRT"
        onRecover={vi.fn()}
        onDownloadBackup={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByRole("dialog", { name: "Recover stale draft" })).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText(/Supply chain CRT/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recover draft" })).toHaveFocus();
  });

  it("requires explicit discard confirmation and closes on Escape without discarding", async () => {
    const user = userEvent.setup();
    const onDiscard = vi.fn();
    const onCancel = vi.fn();
    const trigger = document.createElement("button");
    trigger.type = "button";
    document.body.append(trigger);
    trigger.focus();
    const rendered = render(
      <CrtRecoveryDialog
        kind="stale-draft"
        treeName="Supply chain CRT"
        onRecover={vi.fn()}
        onDownloadBackup={vi.fn()}
        onDiscard={onDiscard}
        onCancel={onCancel}
        returnFocusRef={{ current: trigger }}
      />
    );

    await user.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(screen.getByRole("heading", { name: "Discard draft?" })).toBeInTheDocument();
    expect(onDiscard).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Keep draft" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(onDiscard).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledOnce();
    rendered.unmount();
    expect(trigger).toHaveFocus();
    trigger.remove();
  });

  it("traps focus and keeps backup separate from recovery and discard mutations", async () => {
    const user = userEvent.setup();
    const onRecover = vi.fn();
    const onBackup = vi.fn();
    const onDiscard = vi.fn();
    render(
      <CrtRecoveryDialog
        kind="stale-draft"
        treeName="Draft tree"
        onRecover={onRecover}
        onDownloadBackup={onBackup}
        onDiscard={onDiscard}
        onCancel={vi.fn()}
      />
    );

    const recover = screen.getByRole("button", { name: "Recover draft" });
    const discard = screen.getByRole("button", { name: "Discard draft" });
    discard.focus();
    await user.tab();
    expect(recover).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Download local backup" }));
    expect(onBackup).toHaveBeenCalledOnce();
    expect(onRecover).not.toHaveBeenCalled();
    expect(onDiscard).not.toHaveBeenCalled();
  });

  it("shows async progress, disables competing actions, announces success, and ignores a late response", async () => {
    const user = userEvent.setup();
    let resolveRecover!: () => void;
    const recover = vi.fn(() => new Promise<void>((resolve) => { resolveRecover = resolve; }));
    const rendered = render(
      <CrtRecoveryDialog
        kind="stale-draft"
        treeName="Draft tree"
        onRecover={recover}
        onDownloadBackup={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "Recover draft" }));
    await user.keyboard("{Tab}");
    expect(screen.getByRole("button", { name: "Recovering draft…" })).toBeDisabled();
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Download local backup" })).toBeDisabled();
    resolveRecover();
    expect(await screen.findByText("Draft recovered.", { selector: "[aria-live]" })).toBeInTheDocument();

    let resolveLate!: () => void;
    const late = vi.fn(() => new Promise<void>((resolve) => { resolveLate = resolve; }));
    rendered.rerender(
      <CrtRecoveryDialog
        kind="stale-draft"
        treeName="Draft tree"
        onRecover={late}
        onDownloadBackup={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: "Recover draft" }));
    rendered.unmount();
    await act(async () => {
      resolveLate();
      await Promise.resolve();
    });
    expect(document.body).not.toHaveTextContent("Draft recovered.");
  });

  it("keeps the draft on an action error and allows retry", async () => {
    const user = userEvent.setup();
    const recover = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(undefined);
    render(
      <CrtRecoveryDialog
        kind="stale-draft"
        treeName="Draft tree"
        onRecover={recover}
        onDownloadBackup={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was changed");
    await user.click(screen.getByRole("button", { name: "Recover draft" }));
    expect(recover).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Draft recovered.", { selector: "[aria-live]" })).toBeInTheDocument();
  });
});

describe("CrtRecoveryDialog conflict review", () => {
  function renderConflict(overrides: Partial<CrtConflictDialogProps> = {}) {
    return render(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Supply chain CRT"
        serverCopy={{ label: "Server copy", revision: 42, summary: "5 cards" }}
        localCopy={{ label: "Local draft", revision: 41, summary: "5 cards", differences: ["Renamed a card", "Moved a card"] }}
        localEditCount={2}
        onKeepLocalAndRetry={vi.fn()}
        onUseServerCopy={vi.fn()}
        onDownloadBackup={vi.fn()}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
        {...overrides}
      />
    );
  }

  it("retains both copies, focuses Review differences, and exposes the summary", async () => {
    const user = userEvent.setup();
    renderConflict();

    expect(screen.getByRole("dialog", { name: "Review the sync conflict" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Server copy" })).toHaveTextContent("Revision 42");
    expect(screen.getByRole("article", { name: "Local draft" })).toHaveTextContent("5 cards");
    const review = screen.getByRole("button", { name: "Review differences" });
    expect(review).toHaveFocus();
    await user.click(review);
    expect(screen.getByText("Renamed a card")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review differences" })).toHaveAttribute("aria-expanded", "true");
    const keepLocal = screen.getByRole("button", { name: "Keep local and retry" });
    keepLocal.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(keepLocal).toHaveFocus();
  });

  it("keeps local and defers without replacing either copy", async () => {
    const user = userEvent.setup();
    const onKeep = vi.fn();
    const onDefer = vi.fn();
    const onUseServer = vi.fn();
    renderConflict({ onKeepLocalAndRetry: onKeep, onDefer, onUseServerCopy: onUseServer });

    await user.click(screen.getByRole("button", { name: "Keep local and retry" }));
    expect(onKeep).toHaveBeenCalledOnce();
    expect(onUseServer).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Defer" }));
    expect(onDefer).toHaveBeenCalledOnce();
    expect(screen.getByRole("article", { name: "Local draft" })).toBeInTheDocument();
  });

  it("keeps choices disabled while comparison is loading and exposes a retryable comparison error", async () => {
    const user = userEvent.setup();
    const onRetryComparison = vi.fn();
    const { rerender } = renderConflict({ comparisonStatus: "loading", onRetryComparison });

    expect(screen.getByRole("status")).toHaveTextContent("Comparing local draft with server copy");
    expect(screen.getByRole("button", { name: "Use server copy" })).toBeDisabled();
    screen.getByRole("dialog").focus();
    fireEvent.keyDown(document, { key: "Tab" });

    rerender(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Supply chain CRT"
        serverCopy={{ label: "Server copy", revision: 42 }}
        localCopy={{ label: "Local draft", revision: 41 }}
        localEditCount={2}
        onKeepLocalAndRetry={vi.fn()}
        onUseServerCopy={vi.fn()}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
        comparisonStatus="error"
        comparisonError="We couldn't compare these versions."
        onRetryComparison={onRetryComparison}
      />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn't compare these versions");
    await user.click(screen.getByRole("button", { name: "Retry comparison" }));
    expect(onRetryComparison).toHaveBeenCalledOnce();
  });

  it("requires named-loss confirmation before using the server copy and offers a backup", async () => {
    const user = userEvent.setup();
    const onUseServer = vi.fn();
    const onBackup = vi.fn();
    renderConflict({ onUseServerCopy: onUseServer, onDownloadBackup: onBackup });

    await user.click(screen.getByRole("button", { name: "Use server copy" }));
    expect(screen.getByRole("heading", { name: "Discard 2 local edits?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to comparison" })).toHaveFocus();
    expect(onUseServer).not.toHaveBeenCalled();
    expect(screen.getByRole("list", { name: "Local edits that will be lost" })).toHaveTextContent("Renamed a card");

    await user.click(screen.getByRole("button", { name: "Download local backup" }));
    expect(onBackup).toHaveBeenCalledOnce();
    expect(onUseServer).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Discard 2 local edits and use server copy" }));
    expect(onUseServer).toHaveBeenCalledOnce();
  });
});

describe("additional recovery branches", () => {
  it("confirms stale discard, reports failure, and retries successfully", async () => {
    const user = userEvent.setup();
    const onDiscard = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(undefined);
    render(
      <CrtRecoveryDialog
        kind="fresh-draft"
        treeName="Fresh tree"
        onRecover={vi.fn()}
        onDownloadBackup={vi.fn()}
        onDiscard={onDiscard}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByRole("dialog", { name: "Recover local draft" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard draft" }));
    await user.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was discarded");
    await user.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(onDiscard).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Draft discarded.", { selector: "[aria-live]" })).toBeInTheDocument();
  });

  it("wraps recovery focus backwards from the first action and handles a missing backup callback", async () => {
    const user = userEvent.setup();
    render(
      <CrtRecoveryDialog
        kind="stale-draft"
        treeName="No backup tree"
        onRecover={vi.fn()}
        onDownloadBackup={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    const recover = screen.getByRole("button", { name: "Recover draft" });
    recover.focus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Discard draft" })).toHaveFocus();

    const { rerender } = render(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Conflict tree"
        serverCopy={{ label: "Server copy" }}
        localCopy={{ label: "Local draft", differences: [] }}
        localEditCount={1}
        onKeepLocalAndRetry={vi.fn()}
        onUseServerCopy={vi.fn()}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: "Review differences" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Review differences" }));
    expect(screen.getByText("No local differences were provided.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use server copy" }));
    await user.click(screen.getByRole("button", { name: "Back to comparison" }));
    rerender(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Conflict tree"
        serverCopy={{ label: "Server copy" }}
        localCopy={{ label: "Local draft", differences: [] }}
        localEditCount={1}
        onKeepLocalAndRetry={vi.fn()}
        onUseServerCopy={vi.fn()}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
        comparisonStatus="ready"
      />
    );
  });

  it("reports comparison and server-choice failures without losing the local copy", async () => {
    const user = userEvent.setup();
    const retryComparison = vi.fn().mockRejectedValue(new Error("compare failed"));
    const useServer = vi.fn().mockRejectedValue(new Error("server failed"));
    const { rerender } = render(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Conflict tree"
        serverCopy={{ label: "Server copy", summary: "Canonical" }}
        localCopy={{ label: "Local draft", summary: "Local" }}
        localEditCount={3}
        comparisonStatus="error"
        comparisonError="Comparison unavailable"
        onRetryComparison={retryComparison}
        onKeepLocalAndRetry={vi.fn()}
        onUseServerCopy={useServer}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: "Retry comparison" }));
    expect(screen.getAllByRole("alert").some((alert) => alert.textContent?.includes("couldn't compare"))).toBe(true);
    rerender(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Conflict tree"
        serverCopy={{ label: "Server copy", summary: "Canonical" }}
        localCopy={{ label: "Local draft", summary: "Local" }}
        localEditCount={3}
        onKeepLocalAndRetry={vi.fn()}
        onUseServerCopy={useServer}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: "Use server copy" }));
    await user.click(screen.getByRole("button", { name: "Discard 3 local edits and use server copy" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was discarded");
    await user.click(screen.getByRole("button", { name: "Back to comparison" }));
    expect(screen.getByRole("article", { name: "Local draft" })).toBeInTheDocument();
  });

  it("reports a failed optional storage retry and allows it to recover", async () => {
    const user = userEvent.setup();
    const retry = vi.fn().mockRejectedValueOnce(new Error("still offline")).mockResolvedValueOnce(undefined);
    render(<CrtStorageUnavailableAlert onRetry={retry} />);
    await user.click(screen.getByRole("button", { name: "Retry save" }));
    expect((await screen.findAllByRole("alert")).some((alert) => alert.textContent?.includes("couldn't retry the save"))).toBe(true);
    await user.click(screen.getByRole("button", { name: "Retry save" }));
    expect(retry).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Retry requested.", { selector: "[aria-live]" })).toBeInTheDocument();
  });

  it("shows the storage warning without an optional retry action", () => {
    render(<CrtStorageUnavailableAlert />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry save" })).not.toBeInTheDocument();
  });

  it("covers conflict focus wrapping and late rejected recovery", async () => {
    const user = userEvent.setup();
    const returnFocus = document.createElement("button");
    document.body.append(returnFocus);
    const onReturnFocus = vi.fn();
    render(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Focus tree"
        serverCopy={{ label: "Server copy" }}
        localCopy={{ label: "Local draft", differences: [] }}
        localEditCount={1}
        onKeepLocalAndRetry={vi.fn()}
        onUseServerCopy={vi.fn()}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
        returnFocusRef={{ current: returnFocus }}
        onReturnFocus={onReturnFocus}
      />
    );
    const review = screen.getByRole("button", { name: "Review differences" });
    review.focus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Defer" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(onReturnFocus).toHaveBeenCalledOnce();

    let rejectRecover!: (reason?: unknown) => void;
    const rendered = render(
      <CrtRecoveryDialog
        kind="fresh-draft"
        treeName="Late error"
        onRecover={() => new Promise<void>((_resolve, reject) => { rejectRecover = reject; })}
        onDownloadBackup={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: "Recover draft" }));
    rendered.unmount();
    await act(async () => { rejectRecover(new Error("late")); await Promise.resolve(); });
    returnFocus.remove();
  });

  it("labels the server-copy action while it is still opening", async () => {
    const user = userEvent.setup();
    let resolveUseServer!: () => void;
    const onUseServerCopy = vi.fn(() => new Promise<void>((resolve) => { resolveUseServer = resolve; }));
    render(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Opening server"
        serverCopy={{ label: "Server copy", revision: 3 }}
        localCopy={{ label: "Local draft", differences: ["Changed label"] }}
        localEditCount={1}
        onKeepLocalAndRetry={vi.fn()}
        onUseServerCopy={onUseServerCopy}
        onDownloadBackup={vi.fn()}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "Use server copy" }));
    await user.click(screen.getByRole("button", { name: "Discard 1 local edit and use server copy" }));
    expect(screen.getByRole("button", { name: "Opening server copy…" })).toBeDisabled();
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-busy", "true");
    resolveUseServer();
    expect(await screen.findByText("Server copy opened.", { selector: "[aria-live]" })).toBeInTheDocument();
  });

  it("uses the panel as the focus fallback when the initial action is unavailable", async () => {
    const user = userEvent.setup();
    const rendered = render(
      <CrtRecoveryDialog
        kind="stale-draft"
        treeName="Focus fallback"
        onRecover={vi.fn()}
        onDownloadBackup={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    const dialog = screen.getByRole("dialog", { name: "Recover stale draft" });
    expect(dialog).toHaveAttribute("tabindex", "-1");
    dialog.focus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByRole("button", { name: "Discard draft" })).toHaveFocus();
    rendered.unmount();
  });

  it("announces each asynchronous recovery action while it is pending", async () => {
    const user = userEvent.setup();
    let resolveBackup!: () => void;
    const backupView = render(
      <CrtRecoveryDialog
        kind="fresh-draft"
        treeName="Pending backup"
        onRecover={vi.fn()}
        onDownloadBackup={() => new Promise<void>((resolve) => { resolveBackup = resolve; })}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: "Download local backup" }));
    expect(screen.getByRole("button", { name: "Preparing local backup…" })).toBeDisabled();
    resolveBackup();
    await screen.findByText("Local backup downloaded.", { selector: "[aria-live]" });
    backupView.unmount();

    let resolveKeep!: () => void;
    const keepView = render(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Pending keep"
        serverCopy={{ label: "Server copy" }}
        localCopy={{ label: "Local draft", differences: ["Changed"] }}
        localEditCount={1}
        onKeepLocalAndRetry={() => new Promise<void>((resolve) => { resolveKeep = resolve; })}
        onUseServerCopy={vi.fn()}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: "Keep local and retry" }));
    expect(screen.getByRole("button", { name: "Retrying sync…" })).toBeDisabled();
    await act(async () => { resolveKeep(); await Promise.resolve(); });
    await screen.findByText("Local copy retained. Retry started.", { selector: "[aria-live]" });
    keepView.unmount();

    let resolveComparison!: () => void;
    const comparisonView = render(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Pending comparison"
        serverCopy={{ label: "Server copy" }}
        localCopy={{ label: "Local draft", differences: [] }}
        localEditCount={1}
        comparisonStatus="error"
        comparisonError="Comparison unavailable"
        onRetryComparison={() => new Promise<void>((resolve) => { resolveComparison = resolve; })}
        onKeepLocalAndRetry={vi.fn()}
        onUseServerCopy={vi.fn()}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: "Retry comparison" }));
    expect(screen.getByRole("button", { name: "Retrying comparison…" })).toBeDisabled();
    await act(async () => { resolveComparison(); await Promise.resolve(); });
    await screen.findByText("Comparison retry requested.", { selector: "[aria-live]" });
    comparisonView.unmount();
  });

  it("does not cancel recovery while an async action is busy", async () => {
    const user = userEvent.setup();
    let resolveRecover!: () => void;
    const onCancel = vi.fn();
    render(
      <CrtRecoveryDialog
        kind="stale-draft"
        treeName="Busy draft"
        onRecover={() => new Promise<void>((resolve) => { resolveRecover = resolve; })}
        onDownloadBackup={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={onCancel}
      />
    );
    await user.click(screen.getByRole("button", { name: "Recover draft" }));
    await user.keyboard("{Escape}");
    expect(onCancel).not.toHaveBeenCalled();
    resolveRecover();
    await screen.findByText("Draft recovered.", { selector: "[aria-live]" });
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
        <CrtRecoveryDialog
          kind="stale-draft"
          treeName="Non-HTML focus"
          onRecover={vi.fn()}
          onDownloadBackup={vi.fn()}
          onDiscard={vi.fn()}
          onCancel={onCancel}
        />
      );
      fireEvent.keyDown(document, { key: "Escape" });
      expect(onCancel).toHaveBeenCalledOnce();
    } finally {
      if (previousDescriptor) Object.defineProperty(document, "activeElement", previousDescriptor);
      else Reflect.deleteProperty(document, "activeElement");
    }
  });

  it("ignores a Tab event delivered after the recovery panel unmounts", () => {
    const rendered = render(
      <CrtRecoveryDialog
        kind="stale-draft"
        treeName="Unmounted panel"
        onRecover={vi.fn()}
        onDownloadBackup={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
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

  it("renders an updated-at timestamp when a copy provides one", () => {
    render(
      <CrtRecoveryDialog
        kind="conflict"
        treeName="Timestamped copy"
        serverCopy={{ label: "Server copy", revision: 42, updatedAt: "2026-09-22T12:00:00Z" }}
        localCopy={{ label: "Local draft" }}
        localEditCount={1}
        onKeepLocalAndRetry={vi.fn()}
        onUseServerCopy={vi.fn()}
        onDefer={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByRole("article", { name: "Server copy" })).toHaveTextContent("Revision 42 · 2026-09-22T12:00:00Z");
  });
});
