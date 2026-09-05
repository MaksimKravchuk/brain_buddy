import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskSideSheet } from "../TaskSideSheet";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function SheetContent({ active = true }: { active?: boolean }) {
  return <div data-testid="sheet-content" data-active={active}>
    <h2 id="task-detail-title" tabIndex={-1}>Task detail</h2>
    <button>First control</button>
    <input aria-label="Draft" defaultValue="Original" />
    <input aria-label="New comment" data-escape-keeps-draft />
    <select aria-label="List"><option>Inbox</option></select>
    <button disabled>Unavailable</button>
    <button hidden>Hidden</button>
    <button>Last control</button>
  </div>;
}

describe("Task side sheet", () => {
  it("keeps the same draft through an interrupted exit and completes a later exit", () => {
    vi.useFakeTimers();
    const onClose = vi.fn();
    const onPresenceChange = vi.fn();
    const view = render(<TaskSideSheet onClose={onClose} onPresenceChange={onPresenceChange}>{<SheetContent />}</TaskSideSheet>);
    act(() => vi.advanceTimersByTime(40));
    const draft = screen.getByLabelText("Draft");
    const sheet = screen.getByRole("dialog");
    fireEvent.change(draft, { target: { value: "Unsent draft" } });
    expect(sheet.parentElement).toHaveAttribute("data-state", "open");
    fireEvent.click(screen.getByTestId("task-sheet-scrim"));
    expect(onClose).toHaveBeenCalledOnce();

    view.rerender(<TaskSideSheet onClose={onClose} onPresenceChange={onPresenceChange}>{null}</TaskSideSheet>);
    expect(sheet).toHaveAttribute("inert");
    expect(screen.getByTestId("sheet-content")).toHaveAttribute("data-active", "false");
    expect(sheet.parentElement).toHaveAttribute("data-state", "closing");
    act(() => vi.advanceTimersByTime(80));
    expect(sheet).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("task-sheet-scrim"));
    expect(onClose).toHaveBeenCalledOnce();

    view.rerender(<TaskSideSheet onClose={onClose} onPresenceChange={onPresenceChange}>{<SheetContent />}</TaskSideSheet>);
    expect(screen.getByRole("dialog")).toBe(sheet);
    expect(sheet.parentElement).toHaveAttribute("data-state", "open");
    expect(screen.getByLabelText("Draft")).toBe(draft);
    expect(draft).toHaveValue("Unsent draft");
    act(() => vi.advanceTimersByTime(180));
    expect(sheet).toBeInTheDocument();
    view.rerender(<TaskSideSheet onClose={onClose} onPresenceChange={onPresenceChange}>{null}</TaskSideSheet>);
    act(() => vi.advanceTimersByTime(160));
    expect(sheet).not.toBeInTheDocument();
    expect(onPresenceChange).toHaveBeenLastCalledWith(false);
  });

  it("opens and releases immediately when reduced motion is requested", () => {
    vi.useFakeTimers();
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));
    const onPresenceChange = vi.fn();
    const view = render(<TaskSideSheet onClose={vi.fn()} onPresenceChange={onPresenceChange}>{<SheetContent />}</TaskSideSheet>);
    expect(screen.getByRole("dialog").parentElement).toHaveAttribute("data-state", "open");
    view.rerender(<TaskSideSheet onClose={vi.fn()} onPresenceChange={onPresenceChange}>{null}</TaskSideSheet>);
    act(() => vi.advanceTimersByTime(0));
    expect(screen.queryByRole("dialog", { hidden: true })).not.toBeInTheDocument();
  });

  it("contains keyboard focus, skips unavailable controls, and releases listeners on unmount", () => {
    const external = document.createElement("button");
    document.body.append(external);
    const view = render(<TaskSideSheet onClose={vi.fn()} onPresenceChange={vi.fn()}>{<SheetContent />}</TaskSideSheet>);
    const first = screen.getByRole("button", { name: "First control" });
    const last = screen.getByRole("button", { name: "Last control" });
    external.focus();
    expect(screen.getByRole("heading")).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("heading"), { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
    view.unmount();
    external.focus();
    expect(external).toHaveFocus();
    external.remove();
  });

  it("defers Escape to native selection, composition, suggestions, draft capture and nested dialogs", () => {
    const onClose = vi.fn();
    render(<TaskSideSheet onClose={onClose} onPresenceChange={vi.fn()}>{<SheetContent />}</TaskSideSheet>);
    const draft = screen.getByLabelText("Draft");
    fireEvent.keyDown(screen.getByLabelText("List"), { key: "Escape" });
    fireEvent.keyDown(screen.getByLabelText("New comment"), { key: "Escape" });
    fireEvent.keyDown(draft, { key: "Escape", isComposing: true });
    const prevented = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    prevented.preventDefault();
    draft.dispatchEvent(prevented);
    const suggestions = document.createElement("div");
    suggestions.setAttribute("role", "listbox");
    screen.getByRole("dialog").append(suggestions);
    fireEvent.keyDown(draft, { key: "Escape" });
    suggestions.remove();
    const modal = document.createElement("div");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.tabIndex = -1;
    document.body.append(modal);
    modal.focus();
    fireEvent.keyDown(modal, { key: "Escape" });
    expect(modal).toHaveFocus();
    expect(onClose).not.toHaveBeenCalled();
    modal.setAttribute("inert", "");
    fireEvent.keyDown(document.body, { key: "Tab" });
    expect(screen.getByRole("button", { name: "First control" })).toHaveFocus();
    draft.focus();
    const blur = vi.fn();
    draft.addEventListener("blur", blur);
    fireEvent.keyDown(draft, { key: "Escape" });
    expect(blur).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
    modal.remove();
  });

  it("keeps focus in a loading sheet with no available controls", () => {
    render(<TaskSideSheet onClose={vi.fn()} onPresenceChange={vi.fn()}><h2 id="task-detail-title" tabIndex={-1}>Task detail</h2></TaskSideSheet>);
    const heading = screen.getByRole("heading");
    heading.focus();
    fireEvent.keyDown(heading, { key: "Tab" });
    expect(heading).toHaveFocus();
  });
});
