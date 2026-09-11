import { cloneElement, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactElement } from "react";

const focusableSelector = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

/** Retain only the outgoing view for its exit; routing and autosave never wait. */
export function TaskSideSheet({ children, onClose, onPresenceChange }: { children: ReactElement<{ active?: boolean }> | null; onClose: () => void; onPresenceChange: (present: boolean) => void }): React.JSX.Element | null {
  const open = children !== null;
  const [present, setPresent] = useState(open);
  const [entered, setEntered] = useState(false);
  const previousChildren = useRef(children);
  const sheetRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (open) previousChildren.current = children;
  }, [children, open]);

  useEffect(() => {
    if (open) {
      setPresent(true);
      onPresenceChange(true);
      if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        setEntered(true);
        return;
      }
      let frame = requestAnimationFrame(() => {
        frame = requestAnimationFrame(() => setEntered(true));
      });
      return () => cancelAnimationFrame(frame);
    }
    // The small fallback also completes exits in a background tab. Reopening
    // cancels it, preserving the same panel instance and its active draft.
    const timeout = setTimeout(() => {
      setPresent(false);
      setEntered(false);
      onPresenceChange(false);
    }, window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? 0 : 160);
    return () => clearTimeout(timeout);
  }, [open, onPresenceChange]);

  useEffect(() => {
    const sheet = sheetRef.current;
    if (!open || !sheet) return;
    const anotherModal = () => Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"]')).some((modal) => modal !== sheet && !modal.closest('[inert], [aria-hidden="true"]'));
    const focusHeading = () => sheet.querySelector<HTMLElement>("#task-detail-title")?.focus({ preventScroll: true });
    const onFocus = (event: FocusEvent) => {
      if (!anotherModal() && !sheet.contains(event.target as Node)) focusHeading();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || anotherModal()) return;
      const target = event.target as HTMLElement;
      if (event.key === "Escape") {
        if (target.closest('select, [data-escape-keeps-draft], [role="combobox"], [role="listbox"]') || sheet.querySelector('[role="listbox"]') || target.closest('[role="dialog"]') !== sheet) return;
        event.preventDefault();
        target.blur();
        onClose();
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(sheet.querySelectorAll<HTMLElement>(focusableSelector)).filter((control) => !control.closest('[hidden], [inert], [aria-hidden="true"]'));
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first) {
        event.preventDefault();
        focusHeading();
      } else if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement as HTMLElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !sheet.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("focusin", onFocus);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose]);

  if (!open && !present) return null;
  return (
    <div className="task-side-sheet fixed inset-0 z-40 overflow-hidden" data-state={open && entered ? "open" : "closing"}>
      <div className="task-side-sheet-scrim absolute inset-0 bg-slate-900/15" data-testid="task-sheet-scrim" aria-hidden onClick={() => { if (open) onClose(); }} />
      <div ref={sheetRef} role="dialog" aria-modal="true" aria-labelledby="task-detail-title" aria-hidden={!open || undefined} inert={!open} className="task-side-sheet-panel absolute inset-y-0 right-0 w-full bg-white shadow-floating sm:w-[460px]">
        {children ?? (previousChildren.current && cloneElement(previousChildren.current, { active: false }))}
      </div>
    </div>
  );
}
