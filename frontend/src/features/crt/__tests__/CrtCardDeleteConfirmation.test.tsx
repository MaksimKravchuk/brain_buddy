import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CrtCardDeleteConfirmation } from "../CrtCardDeleteConfirmation";

function control(element: HTMLElement | null): HTMLElement {
  if (!element) throw new Error("Expected dialog control to be mounted");
  return element;
}

function renderConfirmation(overrides: Partial<React.ComponentProps<typeof CrtCardDeleteConfirmation>> = {}) {
  return render(
    <CrtCardDeleteConfirmation
      cardLabel="Launch plan"
      relationConsequences={["Blocks the onboarding card", "Linked to the Q4 objective"]}
      onCancel={vi.fn()}
      onConfirm={vi.fn().mockResolvedValue(true)}
      {...overrides}
    />
  );
}

describe("CrtCardDeleteConfirmation", () => {
  it("starts safely focused and names every connected relation consequence", () => {
    renderConfirmation();

    expect(screen.getByRole("alertdialog", { name: "Delete Launch plan?" })).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("This will delete the card and its connected relations.")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Connected relations that will be deleted" })).toHaveTextContent(
      "Blocks the onboarding cardLinked to the Q4 objective"
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("cancels with Escape and restores focus to the invoking control", async () => {
    const user = userEvent.setup();
    const trigger = document.createElement("button");
    trigger.type = "button";
    document.body.append(trigger);
    trigger.focus();
    const onCancel = vi.fn();
    renderConfirmation({ onCancel, returnFocusRef: { current: trigger } });

    await user.keyboard("{Escape}");

    expect(onCancel).toHaveBeenCalledOnce();
    expect(trigger).toHaveFocus();
    trigger.remove();
  });

  it("wraps focus in both directions and ignores unrelated keys", async () => {
    const user = userEvent.setup();
    renderConfirmation();
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Delete card" });

    confirm.focus();
    await user.keyboard("{Tab}");
    expect(cancel).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(confirm).toHaveFocus();

    cancel.focus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(confirm).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(cancel).toHaveFocus();
    await user.keyboard("a");
    expect(cancel).toHaveFocus();
  });

  it("keeps both actions blocked while deletion is pending and closes after success", async () => {
    const user = userEvent.setup();
    let resolveDelete!: (value: boolean) => void;
    const controls: { confirm: HTMLElement | null; cancel: HTMLElement | null } = { confirm: null, cancel: null };
    const onConfirm = vi.fn(() => {
      // Both handlers can receive a same-turn event before React commits disabled state.
      fireEvent.click(control(controls.confirm));
      fireEvent.click(control(controls.cancel));
      return new Promise<boolean>((resolve) => { resolveDelete = resolve; });
    });
    const onCancel = vi.fn();
    renderConfirmation({ onConfirm, onCancel });

    controls.confirm = screen.getByRole("button", { name: "Delete card" });
    controls.cancel = screen.getByRole("button", { name: "Cancel" });
    await user.click(control(controls.confirm));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Deleting card…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("alertdialog")).toHaveAttribute("aria-busy", "true");

    fireEvent.keyDown(document, { key: "Tab" });
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(control(controls.confirm));
    expect(onCancel).not.toHaveBeenCalled();
    expect(onConfirm).toHaveBeenCalledOnce();

    await act(async () => {
      resolveDelete(true);
      await Promise.resolve();
    });
    expect(onCancel).toHaveBeenCalledOnce();
    expect(screen.getByRole("alertdialog")).toHaveAttribute("aria-busy", "true");
  });

  it("shows a recoverable failure and allows a successful retry", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(false);
    const onCancel = vi.fn();
    renderConfirmation({ onConfirm, onCancel });

    await user.click(screen.getByRole("button", { name: "Delete card" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was deleted.");
    expect(screen.getByRole("button", { name: "Delete card" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(screen.getByRole("alertdialog")).toHaveAttribute("aria-busy", "false");

    await user.click(screen.getByRole("button", { name: "Delete card" }));
    expect(onConfirm).toHaveBeenCalledTimes(2);
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("does not restore focus to a disconnected return target and handles an empty focus trap", async () => {
    const user = userEvent.setup();
    const trigger = document.createElement("button");
    trigger.type = "button";
    document.body.append(trigger);
    trigger.focus();
    const onCancel = vi.fn();
    const first = renderConfirmation({ onCancel, returnFocusRef: { current: trigger } });
    trigger.remove();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(document.body).not.toContainElement(trigger);
    first.unmount();

    let resolveDelete!: (value: boolean) => void;
    const pending = renderConfirmation({
      onConfirm: () => new Promise<boolean>((resolve) => { resolveDelete = resolve; })
    });
    await user.click(screen.getByRole("button", { name: "Delete card" }));
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Deleting card…" })).toBeDisabled();
    pending.unmount();
    await act(async () => {
      resolveDelete(true);
      await Promise.resolve();
    });
  });

  it("falls back to the previously focused element when no return ref target exists", async () => {
    const user = userEvent.setup();
    const trigger = document.createElement("button");
    trigger.type = "button";
    document.body.append(trigger);
    trigger.focus();
    const onCancel = vi.fn();
    renderConfirmation({ onCancel, returnFocusRef: { current: null } });

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalledOnce();
    expect(trigger).toHaveFocus();
    trigger.remove();
  });

  it("handles a non-HTMLElement active element without attempting to focus it", () => {
    const previousDescriptor = Object.getOwnPropertyDescriptor(document, "activeElement");
    const textNode = document.createTextNode("not focusable");
    Object.defineProperty(document, "activeElement", { configurable: true, get: () => textNode });
    try {
      const onCancel = vi.fn();
      const rendered = renderConfirmation({ onCancel });
      fireEvent.keyDown(document, { key: "Escape" });
      expect(onCancel).toHaveBeenCalledOnce();
      rendered.unmount();
    } finally {
      if (previousDescriptor) Object.defineProperty(document, "activeElement", previousDescriptor);
      else Reflect.deleteProperty(document, "activeElement");
    }
  });

  it("does not process a late Tab event after the panel has unmounted", () => {
    const rendered = renderConfirmation();
    const removeListener = vi.spyOn(document, "removeEventListener").mockImplementation(() => undefined);
    rendered.unmount();
    try {
      expect(() => fireEvent.keyDown(document, { key: "Tab" })).not.toThrow();
    } finally {
      removeListener.mockRestore();
    }
  });
});
