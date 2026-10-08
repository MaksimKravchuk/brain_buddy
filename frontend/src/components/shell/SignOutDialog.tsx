/**
 * The sign-out confirmation (spec 020, FR-052): signing out is no longer one
 * click. The words mirror the native apps' sign-out dialog: a short base
 * sentence, then one sentence per kind of unsaved work this browser would lose.
 * "Cancel" has the initial focus and Esc cancels; "Sign out" is not styled as
 * destructive, because the account's data stays on the server.
 */
import { useEffect, useId, useRef } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { trapTab } from "../../features/review/focusTrap";
import { signOutSentences, type SignOutSummary } from "./signOutSummary";

export function SignOutDialog({
  summary,
  pending,
  notice,
  onCancel,
  onConfirm
}: {
  summary: SignOutSummary;
  /** Signing out is under way: Esc and both buttons wait. */
  pending: boolean;
  /**
   * `failed`: the last attempt did not sign out and the person is still signed in.
   * `changed`: unsaved work appeared after the dialog opened; nothing was removed.
   */
  notice: "failed" | "changed" | null;
  onCancel: () => void;
  onConfirm: () => void;
}): React.JSX.Element {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // The safe action has the focus on open and again when an attempt ends. Both
    // buttons are disabled while signing out: focus then parks on the panel so
    // Tab has somewhere to stay (see `trapTab`).
    (pending ? panelRef.current : cancelRef.current)?.focus();
  }, [pending]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !pending) {
        event.preventDefault();
        event.stopPropagation();
        onCancel();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [pending, onCancel]);

  const onPanelKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Tab") {
      trapTab(event, panelRef.current as HTMLElement);
    }
  };

  return (
    <div className="fixed inset-0 z-[150] flex items-center justify-center bg-slate-900/30 p-4 motion-safe:animate-fade-in">
      <section
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={pending}
        tabIndex={-1}
        onKeyDown={onPanelKeyDown}
        className="w-full max-w-md outline-hidden rounded-[20px] border border-slate-200 bg-white p-5 shadow-floating motion-safe:animate-scale-fade-in"
      >
        <h2 id={titleId} className="m-0 text-[20px] font-semibold leading-[1.3] text-slate-900">
          Sign out?
        </h2>
        <div id={descriptionId} className="mt-3 flex flex-col gap-2 text-sm leading-relaxed text-slate-700">
          {signOutSentences(summary).map((sentence) => (
            <p key={sentence} className="m-0">
              {sentence}
            </p>
          ))}
        </div>
        {notice ? (
          <p role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            {notice === "changed"
              ? "Something changed since this opened. Check and confirm again."
              : "Sign-out didn't finish. You're still signed in. Try again."}
          </p>
        ) : null}
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            disabled={pending}
            className="min-h-11 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-700 hover:border-slate-300 disabled:opacity-50"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={pending}
            className="min-h-11 rounded-lg bg-sky-700 px-5 text-sm font-semibold text-white hover:bg-sky-800 disabled:opacity-50"
            onClick={onConfirm}
          >
            {pending ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </section>
    </div>
  );
}
