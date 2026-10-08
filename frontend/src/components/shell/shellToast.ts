import { createContext, useContext } from "react";

/**
 * The shell's transient toast. Text-only calls keep their original shape
 * (`notify("…")`, about 2.6 s). Spec 020 (FR-048) adds an optional action —
 * the decision Undo — shown about 5 s, announced politely, paused while the
 * toast has hover or focus, and reachable with Ctrl/Cmd+Z outside text fields.
 * Lives outside AppShell.tsx so that file only exports components
 * (react-refresh constraint); AppShell provides the value.
 */
export interface ShellToastAction {
  /** Visible button text ("Undo"). */
  label: string;
  /** Accessible name: "Undo: <what it reverts> <title>" (design "Keyboard and focus"). */
  accessibleLabel: string;
  onAction: () => void;
}

export interface ShellToastOptions {
  action?: ShellToastAction;
}

/** Shows the toast; the returned call takes it away again if it is still the one showing. */
export type ShellNotify = (message: string, options?: ShellToastOptions) => () => void;

export const TEXT_TOAST_MS = 2600;
export const ACTION_TOAST_MS = 5000;

export const ShellToastContext = createContext<ShellNotify>(() => () => undefined);

export function useShellToast(): ShellNotify {
  return useContext(ShellToastContext);
}

/**
 * Ctrl+Z / Cmd+Z with no other modifier. On a non-Latin layout (Russian "я")
 * the Z key types another letter, so its physical code decides there; a Latin
 * layout that puts another character on that key (Dvorak's ";") is read by
 * the character it types, as the browser's own undo does.
 */
export function isUndoShortcut(event: KeyboardEvent): boolean {
  if (!(event.ctrlKey || event.metaKey) || event.shiftKey || event.altKey) {
    return false;
  }
  const key = event.key.toLowerCase();
  return key === "z" || (event.code === "KeyZ" && !/^[\x20-\x7e]$/.test(key));
}

/** Text fields keep Ctrl/Cmd+Z for their own typing undo. */
export function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return target.matches("input, textarea, select, [contenteditable]:not([contenteditable='false'])");
}

export function undoShortcutLabel(userAgent: string = globalThis.navigator.userAgent): string {
  return /Mac|iPhone|iPad/.test(userAgent) ? "Cmd+Z" : "Ctrl+Z";
}
