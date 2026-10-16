import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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

  useLayoutEffect(() => {
    onCancelRef.current = onCancel;
    onConfirmRef.current = onConfirm;
    returnFocusRefValue.current = returnFocusRef;
    busyRef.current = busy;
  });

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
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-ink/40 p-6" data-crt-native="true">
      <section
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="crt-card-delete-title"
        aria-describedby={descriptionId}
        aria-busy={busy}
        tabIndex={-1}
        className="w-full max-w-lg co-glass-dense rounded-card p-6 outline-hidden"
      >
        <p className="text-co-meta font-semibold text-danger">Delete card</p>
        <h1 id="crt-card-delete-title" className="mt-2 text-co-body font-semibold text-ink">{title}</h1>
        <p id={descriptionId} className="mt-2 text-co-meta leading-6 text-ink-muted">
          This will delete the card and its connected relations.
        </p>
        <ul aria-label="Connected relations that will be deleted" className="mt-4 list-disc rounded-lg bg-sunken p-4 pl-8 text-co-meta leading-6 text-danger">
          {relationConsequences.map((consequence) => <li key={consequence}>{consequence}</li>)}
        </ul>
        {error ? <p className="mt-4 text-co-meta text-danger" role="alert">{error}</p> : null}
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button
            ref={cancelRef}
            type="button"
            className="rounded-lg bg-ink px-4 py-2 text-co-meta font-semibold text-card disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy}
            onClick={cancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="rounded-lg bg-quiet hover:bg-quiet-pressed px-4 py-2 text-co-meta font-semibold text-danger disabled:cursor-not-allowed disabled:opacity-60"
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
