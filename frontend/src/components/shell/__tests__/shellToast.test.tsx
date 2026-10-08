import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ACTION_TOAST_MS,
  isTextEntryTarget,
  isUndoShortcut,
  ShellToastContext,
  TEXT_TOAST_MS,
  undoShortcutLabel,
  useShellToast
} from "../shellToast";

function Notifier(): React.JSX.Element {
  const notify = useShellToast();

  return (
    <button type="button" onClick={() => notify("Thinking canvas isn't built yet — placeholder")}>
      Notify
    </button>
  );
}

describe("useShellToast", () => {
  it("delivers the message to the shell that provided the toast sink", async () => {
    const user = userEvent.setup();
    const notify = vi.fn();

    render(
      <ShellToastContext.Provider value={notify}>
        <Notifier />
      </ShellToastContext.Provider>
    );
    await user.click(screen.getByRole("button", { name: "Notify" }));

    expect(notify).toHaveBeenCalledWith("Thinking canvas isn't built yet — placeholder");
  });

  it("is inert outside a shell, so a panel rendered on its own cannot throw on notify", async () => {
    const user = userEvent.setup();

    render(<Notifier />);

    await expect(user.click(screen.getByRole("button", { name: "Notify" }))).resolves.toBeUndefined();
  });

  it("020-FR-048 passes an optional action through while the text-only call stays a single argument", async () => {
    const user = userEvent.setup();
    const notify = vi.fn();
    const onAction = vi.fn();
    function ActionNotifier(): React.JSX.Element {
      const toast = useShellToast();
      return (
        <button
          type="button"
          onClick={() => toast("“Renovate the bathroom” released to Someday", {
            action: { label: "Undo", accessibleLabel: "Undo: Released to Someday Renovate the bathroom", onAction }
          })}
        >
          Decide
        </button>
      );
    }

    render(
      <ShellToastContext.Provider value={notify}>
        <Notifier />
        <ActionNotifier />
      </ShellToastContext.Provider>
    );
    await user.click(screen.getByRole("button", { name: "Notify" }));
    await user.click(screen.getByRole("button", { name: "Decide" }));

    expect(notify.mock.calls[0]).toEqual(["Thinking canvas isn't built yet — placeholder"]);
    expect(notify.mock.calls[1][1].action.onAction).toBe(onAction);
  });
});

describe("020-FR-048 undo toast timing and keyboard rules", () => {
  it("020-FR-048 keeps an action toast about 5 s and a plain toast as before", () => {
    expect(ACTION_TOAST_MS).toBe(5000);
    expect(TEXT_TOAST_MS).toBe(2600);
  });

  it.each([
    [{ key: "z", ctrlKey: true }, true],
    [{ key: "Z", metaKey: true }, true],
    [{ key: "z", ctrlKey: true, shiftKey: true }, false],
    [{ key: "z", ctrlKey: true, altKey: true }, false],
    [{ key: "z" }, false],
    [{ key: "y", ctrlKey: true }, false],
    // Non-Latin layouts: the Z key types another letter, so its physical code decides.
    [{ key: "я", code: "KeyZ", ctrlKey: true }, true],
    [{ key: "Я", code: "KeyZ", metaKey: true }, true],
    [{ key: "я", code: "KeyZ" }, false],
    [{ key: "я", code: "KeyZ", ctrlKey: true, shiftKey: true }, false],
    // A Latin layout that puts another character on the Z key (Dvorak's ";") is not Undo.
    [{ key: ";", code: "KeyZ", ctrlKey: true }, false],
    [{ key: "z", code: "Slash", ctrlKey: true }, true]
  ])("020-FR-048 reads %o as Undo: %s", (init, expected) => {
    expect(isUndoShortcut(new KeyboardEvent("keydown", init))).toBe(expected);
  });

  it("020-FR-048 leaves Ctrl/Cmd+Z to text fields, which own their own undo", () => {
    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    const select = document.createElement("select");
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "");
    const notEditable = document.createElement("div");
    notEditable.setAttribute("contenteditable", "false");
    const button = document.createElement("button");
    expect(isTextEntryTarget(notEditable)).toBe(false);
    expect(isTextEntryTarget(input)).toBe(true);
    expect(isTextEntryTarget(textarea)).toBe(true);
    expect(isTextEntryTarget(select)).toBe(true);
    expect(isTextEntryTarget(editable)).toBe(true);
    expect(isTextEntryTarget(button)).toBe(false);
    expect(isTextEntryTarget(document)).toBe(false);
    expect(isTextEntryTarget(null)).toBe(false);
  });

  it("020-FR-048 names the shortcut the person's platform uses", () => {
    expect(undoShortcutLabel("Mozilla/5.0 (Windows NT 10.0)")).toBe("Ctrl+Z");
    expect(undoShortcutLabel("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)")).toBe("Cmd+Z");
    expect(undoShortcutLabel("Mozilla/5.0 (iPad; CPU OS 17_0)")).toBe("Cmd+Z");
    expect(undoShortcutLabel()).toBe("Ctrl+Z");
  });
});
