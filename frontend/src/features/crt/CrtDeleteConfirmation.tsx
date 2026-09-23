import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

export type CrtConfirmationAction = () => void | Promise<void>;

type FocusablePanel = HTMLElement;

const focusableSelector =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function useModalBehavior(
  panelRef: RefObject<FocusablePanel | null>,
  initialFocusRef: RefObject<HTMLButtonElement | null>,
  onCancel?: () => void,
  returnFocusRef?: RefObject<HTMLElement | null>,
  busy = false
): void {
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;
  const returnRef = useRef(returnFocusRef);
  returnRef.current = returnFocusRef;
  const previousFocus = useRef<HTMLElement | null>(null);
  const restored = useRef(false);

  const restoreFocus = useCallback(() => {
    if (restored.current) return;
    restored.current = true;
    const target = returnRef.current?.current ?? previousFocus.current;
    if (target?.isConnected) target.focus();
  }, []);

  useEffect(() => {
    previousFocus.current = returnRef.current?.current ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        event.preventDefault();
        event.stopPropagation();
        cancelRef.current?.();
        restoreFocus();
        return;
      }
      if (event.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(focusableSelector));
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
  }, [busy, panelRef, restoreFocus]);

  useEffect(() => {
    if (!busy) initialFocusRef.current?.focus();
  }, [busy, initialFocusRef]);
}

function useAsyncAction(): {
  pending: boolean;
  progressVisible: boolean;
  error: string | null;
  announcement: string;
  run: (action: CrtConfirmationAction, success: string, failure: string) => Promise<void>;
} {
  const [pending, setPending] = useState(false);
  const [progressVisible, setProgressVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const mounted = useRef(true);
  const progressTimer = useRef<number | undefined>(undefined);

  useEffect(() => () => {
    mounted.current = false;
    if (progressTimer.current !== undefined) window.clearTimeout(progressTimer.current);
  }, []);

  const run = useCallback(async (action: CrtConfirmationAction, success: string, failure: string) => {
    if (pending || !mounted.current) return;
    setPending(true);
    setProgressVisible(false);
    setError(null);
    setAnnouncement("");
    progressTimer.current = window.setTimeout(() => {
      if (mounted.current) setProgressVisible(true);
    }, 300);
    try {
      await action();
      if (!mounted.current) return;
      setPending(false);
      setProgressVisible(false);
      setAnnouncement(success);
    } catch {
      if (!mounted.current) return;
      setPending(false);
      setProgressVisible(false);
      setError(failure);
      setAnnouncement(failure);
    } finally {
      if (progressTimer.current !== undefined) window.clearTimeout(progressTimer.current);
    }
  }, [pending]);

  return { pending, progressVisible, error, announcement, run };
}

function SupportReference({ reference }: { reference?: string }): React.JSX.Element | null {
  return reference ? <p className="mt-3 font-mono text-xs text-slate-500">Support reference: {reference}</p> : null;
}

export type CrtDeleteTreeDialogProps = Readonly<{
  treeName: string;
  cardCount: number;
  relationCount: number;
  onCancel: () => void;
  onConfirm: CrtConfirmationAction;
  returnFocusRef?: RefObject<HTMLElement | null>;
  supportReference?: string;
  offline?: boolean;
}>;

export function CrtDeleteTreeDialog({
  treeName,
  cardCount,
  relationCount,
  onCancel,
  onConfirm,
  returnFocusRef,
  supportReference,
  offline = false
}: CrtDeleteTreeDialogProps): React.JSX.Element {
  const panelRef = useRef<HTMLElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const { pending, progressVisible, error, announcement, run } = useAsyncAction();
  useModalBehavior(panelRef, cancelRef, onCancel, returnFocusRef, pending);

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-slate-950/40 p-6" data-crt-native="true">
      <section
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="crt-delete-tree-title"
        aria-describedby="crt-delete-tree-description"
        aria-busy={pending}
        tabIndex={-1}
        className="w-full max-w-lg rounded-2xl border border-rose-200 bg-white p-6 shadow-floating outline-none"
      >
        <p className="text-xs font-bold uppercase tracking-[0.08em] text-rose-700">Delete tree</p>
        <h1 id="crt-delete-tree-title" className="mt-2 text-xl font-semibold text-slate-900">Delete ‘{treeName}’?</h1>
        <p id="crt-delete-tree-description" className="mt-2 text-sm leading-6 text-slate-600">
          Deletes {cardCount} {cardCount === 1 ? "card" : "cards"} and {relationCount} {relationCount === 1 ? "relation" : "relations"} from BrainBuddy.
        </p>
        {offline ? <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Reconnect before deleting this tree.</p> : null}
        {progressVisible ? <p className="mt-4 text-sm text-slate-600" role="status" aria-label="Deleting tree…">Deleting tree…</p> : null}
        {error ? <p className="mt-4 text-sm text-rose-700" role="alert">{error}</p> : null}
        <SupportReference reference={supportReference} />
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button
            ref={cancelRef}
            type="button"
            className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            disabled={pending}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            aria-label="Delete tree"
            className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={pending || offline}
            onClick={() => void run(onConfirm, "Tree deletion completed.", "We couldn't delete this tree. Nothing was deleted. Retry when ready.")}
          >
            {pending ? "Deleting tree…" : "Delete tree"}
          </button>
        </div>
        <p className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</p>
      </section>
    </div>
  );
}

export type CrtPendingTree = Readonly<{ id: string; name: string; editCount: number }>;

export type CrtPendingWorkDialogProps = Readonly<{
  affectedTrees: readonly CrtPendingTree[];
  onStayAndRetry: CrtConfirmationAction;
  onDownloadBackup: CrtConfirmationAction;
  onDiscardAndContinue: CrtConfirmationAction;
  onCancel?: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
  offline?: boolean;
  error?: string;
  supportReference?: string;
}>;

export function CrtPendingWorkDialog({
  affectedTrees,
  onStayAndRetry,
  onDownloadBackup,
  onDiscardAndContinue,
  onCancel,
  returnFocusRef,
  offline = false,
  error,
  supportReference
}: CrtPendingWorkDialogProps): React.JSX.Element {
  const panelRef = useRef<HTMLElement | null>(null);
  const safeActionRef = useRef<HTMLButtonElement | null>(null);
  const { pending, progressVisible, announcement, error: actionError, run } = useAsyncAction();
  useModalBehavior(panelRef, safeActionRef, onCancel, returnFocusRef, pending);

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-slate-950/40 p-6" data-crt-native="true">
      <section
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="crt-pending-work-title"
        aria-describedby="crt-pending-work-description"
        aria-busy={pending}
        tabIndex={-1}
        className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 shadow-floating outline-none"
      >
        <h1 id="crt-pending-work-title" className="text-xl font-semibold text-slate-900">Resolve unsynced changes before continuing</h1>
        <p id="crt-pending-work-description" className="mt-2 text-sm leading-6 text-slate-600">
          These trees have local work that has not been saved online. Resolve it before leaving, switching trees, importing, signing out, or changing accounts.
        </p>
        <ul aria-label="Affected trees" className="mt-4 space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          {affectedTrees.map((tree) => (
            <li key={tree.id}>{tree.name} · {tree.editCount} unsynced {tree.editCount === 1 ? "edit" : "edits"}</li>
          ))}
        </ul>
        {offline ? <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Reconnect before discarding or continuing.</p> : null}
        {progressVisible ? <p className="mt-4 text-sm text-slate-600" role="status">Working…</p> : null}
        {error ? <p className="mt-4 text-sm text-rose-700" role="alert">{error}</p> : null}
        {actionError ? <p className="mt-4 text-sm text-rose-700" role="alert">{actionError}</p> : null}
        <SupportReference reference={supportReference} />
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button
            ref={safeActionRef}
            type="button"
            className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            disabled={pending}
            onClick={() => void run(onStayAndRetry, "Save retry started.", "We couldn't retry the save. Nothing was discarded.")}
          >
            {pending ? "Working…" : "Stay and retry"}
          </button>
          <button
            type="button"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={pending}
            onClick={() => void run(onDownloadBackup, "Backup download started.", "We couldn't prepare the backup. Nothing was discarded.")}
          >
            {pending ? "Preparing backup…" : "Download backup"}
          </button>
          <button
            type="button"
            className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={pending || offline}
            onClick={() => void run(onDiscardAndContinue, "Unsynced changes discarded.", "We couldn't discard the unsynced changes. Transition cancelled.")}
          >
            Discard and continue
          </button>
        </div>
        <p className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</p>
      </section>
    </div>
  );
}

export const CrtDeleteConfirmation = CrtDeleteTreeDialog;
