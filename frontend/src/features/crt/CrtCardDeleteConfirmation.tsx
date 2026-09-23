import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

export type CrtCardDeleteConfirmationProps = Readonly<{
  cardLabel: string;
  relationConsequences: readonly string[];
  onCancel: () => void;
  onConfirm: () => boolean | Promise<boolean>;
  returnFocusRef?: RefObject<HTMLElement | null>;
}>;

type FocusableElement = HTMLElement;

const focusableSelector =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function CrtCardDeleteConfirmation({
  cardLabel,
  relationConsequences,
  onCancel,
  onConfirm,
  returnFocusRef
}: CrtCardDeleteConfirmationProps): React.JSX.Element {
  const panelRef = useRef<HTMLElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const restoredFocusRef = useRef(false);
  const onCancelRef = useRef(onCancel);
  const onConfirmRef = useRef(onConfirm);
  const returnFocusRefValue = useRef(returnFocusRef);
  const busyRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  onCancelRef.current = onCancel;
  onConfirmRef.current = onConfirm;
  returnFocusRefValue.current = returnFocusRef;
  busyRef.current = busy;

  const restoreFocus = useCallback(() => {
    if (restoredFocusRef.current) return;
    restoredFocusRef.current = true;
    const target = returnFocusRefValue.current?.current ?? previousFocusRef.current;
    if (target?.isConnected) target.focus();
  }, []);

  const cancel = useCallback(() => {
    if (busyRef.current) return;
    onCancelRef.current();
    restoreFocus();
  }, [restoreFocus]);

  useEffect(() => {
    previousFocusRef.current = returnFocusRefValue.current?.current ?? (
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    );
    cancelRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (busyRef.current) return;
        event.preventDefault();
        event.stopPropagation();
        cancel();
        return;
      }
      if (event.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = Array.from(panel.querySelectorAll<FocusableElement>(focusableSelector));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
        event.preventDefault();
        last.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      restoreFocus();
    };
  }, [cancel, restoreFocus]);

  const confirm = async (): Promise<void> => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      await onConfirmRef.current();
      onCancelRef.current();
      restoreFocus();
    } catch {
      busyRef.current = false;
      setBusy(false);
      setError("We couldn't delete this card. Nothing was deleted.");
    }
  };

  const title = `Delete ${cardLabel}?`;
  const descriptionId = "crt-card-delete-description";

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-slate-950/40 p-6" data-crt-native="true">
      <section
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="crt-card-delete-title"
        aria-describedby={descriptionId}
        aria-busy={busy}
        tabIndex={-1}
        className="w-full max-w-lg rounded-2xl border border-rose-200 bg-white p-6 shadow-floating outline-none"
      >
        <p className="text-xs font-bold uppercase tracking-[0.08em] text-rose-700">Delete card</p>
        <h1 id="crt-card-delete-title" className="mt-2 text-xl font-semibold text-slate-900">{title}</h1>
        <p id={descriptionId} className="mt-2 text-sm leading-6 text-slate-600">
          This will delete the card and its connected relations.
        </p>
        <ul aria-label="Connected relations that will be deleted" className="mt-4 list-disc rounded-lg border border-rose-200 bg-rose-50 p-4 pl-8 text-sm leading-6 text-rose-900">
          {relationConsequences.map((consequence) => <li key={consequence}>{consequence}</li>)}
        </ul>
        {error ? <p className="mt-4 text-sm text-rose-700" role="alert">{error}</p> : null}
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button
            ref={cancelRef}
            type="button"
            className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy}
            onClick={cancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy}
            onClick={() => void confirm()}
          >
            {busy ? "Deleting card…" : "Delete card"}
          </button>
        </div>
      </section>
    </div>
  );
}
