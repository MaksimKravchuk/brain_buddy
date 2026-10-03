import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";

export type CrtRecoveryAction = () => void | Promise<void>;

export type CrtRecoveryDialogBaseProps = {
  onCancel: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
  onReturnFocus?: () => void;
};

export type CrtStaleDraftDialogProps = CrtRecoveryDialogBaseProps & {
  kind: "stale-draft" | "fresh-draft";
  treeName: string;
  onRecover: CrtRecoveryAction;
  onDownloadBackup: CrtRecoveryAction;
  onDiscard: CrtRecoveryAction;
};

export type CrtCopyPreview = {
  label: string;
  revision?: number;
  updatedAt?: string;
  summary?: string;
  differences?: readonly string[];
};

export type CrtConflictDialogProps = CrtRecoveryDialogBaseProps & {
  kind: "conflict";
  treeName: string;
  serverCopy: CrtCopyPreview;
  localCopy: CrtCopyPreview;
  localEditCount: number;
  comparisonStatus?: "ready" | "loading" | "error";
  comparisonError?: string;
  onRetryComparison?: CrtRecoveryAction;
  onKeepLocalAndRetry: CrtRecoveryAction;
  onUseServerCopy: CrtRecoveryAction;
  onDownloadBackup?: CrtRecoveryAction;
  onDefer: () => void;
};

export type CrtRecoveryDialogProps = CrtStaleDraftDialogProps | CrtConflictDialogProps;

type ActionKey = "recover" | "backup" | "discard" | "keep-local" | "use-server" | "retry-comparison";
type ActionState = { active: ActionKey | null; error: string | null; announcement: string };

const focusableSelector =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function useDialogBehavior(
  panelRef: RefObject<HTMLElement | null>,
  initialFocusRef: RefObject<HTMLElement | null>,
  initialFocusKey: string,
  onCancel: () => void,
  returnFocusRef?: RefObject<HTMLElement | null>,
  onReturnFocus?: () => void,
  busy = false
): { cancel: () => void } {
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;
  const returnFocusRefValue = useRef(returnFocusRef);
  returnFocusRefValue.current = returnFocusRef;
  const returnFocusCallbackRef = useRef(onReturnFocus);
  returnFocusCallbackRef.current = onReturnFocus;
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const restoredFocusRef = useRef(false);
  const restoreFocusRef = useRef<() => void>(() => undefined);
  restoreFocusRef.current = () => {
    if (restoredFocusRef.current) return;
    restoredFocusRef.current = true;
    const target = returnFocusRefValue.current?.current ?? previousFocusRef.current;
    if (target?.isConnected) target.focus();
    returnFocusCallbackRef.current?.();
  };
  const cancel = useCallback(() => {
    cancelRef.current();
    restoreFocusRef.current();
  }, []);

  useEffect(() => {
    previousFocusRef.current = returnFocusRefValue.current?.current ?? (
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    );

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
      restoreFocusRef.current();
    };
  }, [cancel, panelRef]);

  useEffect(() => {
    const focusTarget = initialFocusRef.current;
    if (focusTarget && !focusTarget.hasAttribute("disabled")) focusTarget.focus();
    else panelRef.current?.focus();
  }, [initialFocusKey, initialFocusRef, panelRef]);

  return { cancel };
}

function RecoveryDialogFrame({
  title,
  description,
  labelledBy,
  describedBy,
  panelRef,
  children,
  busy
}: {
  title: string;
  description: string;
  labelledBy: string;
  describedBy: string;
  panelRef: RefObject<HTMLElement | null>;
  children: ReactNode;
  busy: boolean;
}): React.JSX.Element {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/35 p-6" data-testid="crt-recovery-scrim">
      <section
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        aria-busy={busy}
        tabIndex={-1}
        className="w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-6 shadow-floating outline-none"
      >
        <h1 id={labelledBy} className="text-xl font-semibold text-slate-900">{title}</h1>
        <p id={describedBy} className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
        {children}
      </section>
    </div>
  );
}

function useActionState(): {
  state: ActionState;
  run: (key: ActionKey, action: CrtRecoveryAction, success: string, failure: string) => Promise<void>;
} {
  const [state, setState] = useState<ActionState>({ active: null, error: null, announcement: "" });
  const mountedRef = useRef(true);

  useEffect(() => () => {
    mountedRef.current = false;
  }, []);

  const run = useCallback(async (key: ActionKey, action: CrtRecoveryAction, success: string, failure: string) => {
    if (!mountedRef.current) return;
    setState({ active: key, error: null, announcement: "" });
    try {
      await action();
      if (!mountedRef.current) return;
      setState({ active: null, error: null, announcement: success });
    } catch {
      if (!mountedRef.current) return;
      setState({ active: null, error: failure, announcement: failure });
    }
  }, []);

  return { state, run };
}

function LiveAnnouncement({ message }: { message: string }): React.JSX.Element {
  return <p className="sr-only" aria-live="polite" aria-atomic="true">{message}</p>;
}

function ActionError({ message }: { message: string | null }): React.JSX.Element | null {
  return message ? <p className="mt-3 text-sm text-rose-700" role="alert">{message}</p> : null;
}

function actionLabel(key: ActionKey, active: ActionKey | null): string {
  if (key === "recover" && active === key) return "Recovering draft…";
  if (key === "backup" && active === key) return "Preparing local backup…";
  if (key === "discard" && active === key) return "Discarding draft…";
  if (key === "keep-local" && active === key) return "Retrying sync…";
  if (key === "use-server" && active === key) return "Opening server copy…";
  if (key === "retry-comparison" && active === key) return "Retrying comparison…";
  return key === "recover" ? "Recover draft" : key === "backup" ? "Download local backup" : key === "discard" ? "Discard draft" : key === "keep-local" ? "Keep local and retry" : key === "retry-comparison" ? "Retry comparison" : "Discard local edits and use server copy";
}

export function CrtStaleDraftDialog({
  kind,
  treeName,
  onRecover,
  onDownloadBackup,
  onDiscard,
  onCancel,
  returnFocusRef,
  onReturnFocus
}: CrtStaleDraftDialogProps): React.JSX.Element {
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const initialFocusRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const { state, run } = useActionState();
  const { cancel } = useDialogBehavior(panelRef, initialFocusRef, confirmDiscard ? "discard-confirmation" : "stale-draft", onCancel, returnFocusRef, onReturnFocus, state.active !== null);

  return (
    <RecoveryDialogFrame
      panelRef={panelRef}
      labelledBy="crt-stale-draft-title"
      describedBy="crt-stale-draft-description"
      title={confirmDiscard ? "Discard draft?" : kind === "fresh-draft" ? "Recover local draft" : "Recover stale draft"}
      description={confirmDiscard
        ? `Discarding the local draft for “${treeName}” cannot be undone.`
        : kind === "fresh-draft"
          ? `A newer local draft for “${treeName}” is available. Choose whether to recover it before editing.`
          : `The local draft for “${treeName}” is over 30 days old. Choose what to do before it is removed.`}
      busy={state.active !== null}
    >
      {confirmDiscard ? (
        <>
          <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
            Any edits that are not on the server will be permanently lost from this browser.
          </p>
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <button ref={initialFocusRef} type="button" className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white" onClick={cancel}>
              Keep draft
            </button>
            <button
              type="button"
              className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={state.active !== null}
              onClick={() => void run("discard", onDiscard, "Draft discarded.", "We couldn't discard the draft. Nothing was discarded.")}
            >
              {actionLabel("discard", state.active)}
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <button ref={initialFocusRef} type="button" className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60" disabled={state.active !== null} onClick={() => void run("recover", onRecover, "Draft recovered.", "We couldn't recover the draft. Nothing was changed.")}>
              {actionLabel("recover", state.active)}
            </button>
            <button type="button" className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-60" disabled={state.active !== null} onClick={() => void run("backup", onDownloadBackup, "Local backup downloaded.", "We couldn't prepare the local backup.")}>
              {actionLabel("backup", state.active)}
            </button>
            <button type="button" className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800 disabled:cursor-not-allowed disabled:opacity-60" disabled={state.active !== null} onClick={() => setConfirmDiscard(true)}>
              {actionLabel("discard", state.active)}
            </button>
          </div>
        </>
      )}
      <ActionError message={state.error} />
      <LiveAnnouncement message={state.announcement} />
    </RecoveryDialogFrame>
  );
}

function copyDetails(copy: CrtCopyPreview): React.JSX.Element {
  return (
    <article className="rounded-lg border border-slate-200 bg-slate-50 p-4" aria-label={copy.label}>
      <h2 className="font-semibold text-slate-900">{copy.label}</h2>
      {copy.summary ? <p className="mt-1 text-sm text-slate-600">{copy.summary}</p> : null}
      {copy.revision !== undefined ? <p className="mt-1 text-xs text-slate-500">Revision {copy.revision}{copy.updatedAt ? ` · ${copy.updatedAt}` : ""}</p> : null}
    </article>
  );
}

export function CrtConflictDialog({
  treeName,
  serverCopy,
  localCopy,
  localEditCount,
  comparisonStatus = "ready",
  comparisonError,
  onRetryComparison,
  onKeepLocalAndRetry,
  onUseServerCopy,
  onDownloadBackup,
  onDefer,
  onCancel,
  returnFocusRef,
  onReturnFocus
}: CrtConflictDialogProps): React.JSX.Element {
  const [confirmServer, setConfirmServer] = useState(false);
  const [showDifferences, setShowDifferences] = useState(false);
  const initialFocusRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const { state, run } = useActionState();
  const editLabel = `${localEditCount} local edit${localEditCount === 1 ? "" : "s"}`;
  const differences = localCopy.differences ?? [];
  const comparisonBusy = comparisonStatus !== "ready";
  const actionsDisabled = state.active !== null || comparisonBusy;
  useDialogBehavior(panelRef, initialFocusRef, confirmServer ? "server-confirmation" : "conflict", onCancel, returnFocusRef, onReturnFocus, state.active !== null || comparisonBusy);

  return (
    <RecoveryDialogFrame
      panelRef={panelRef}
      labelledBy="crt-conflict-title"
      describedBy="crt-conflict-description"
      title={confirmServer ? `Discard ${editLabel}?` : "Review the sync conflict"}
      description={confirmServer
        ? `Using the server copy of “${treeName}” will permanently remove these local edits from this browser.`
        : `The server and local copies of “${treeName}” are both preserved. Review the differences before choosing which copy to continue from.`}
      busy={state.active !== null || comparisonStatus === "loading"}
    >
      {comparisonStatus === "loading" ? <p className="mt-4 text-sm text-slate-600" role="status">Comparing local draft with server copy…</p> : null}
      {comparisonStatus === "error" && comparisonError ? <p className="mt-4 text-sm text-rose-700" role="alert">{comparisonError}</p> : null}
      {comparisonStatus === "error" && onRetryComparison ? (
        <button type="button" className="mt-3 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-60" disabled={state.active !== null} onClick={() => void run("retry-comparison", onRetryComparison, "Comparison retry requested.", "We couldn't compare these versions again.")}>
          {actionLabel("retry-comparison", state.active)}
        </button>
      ) : null}
      {confirmServer ? (
        <>
          <ul className="mt-4 list-disc rounded-lg border border-rose-200 bg-rose-50 p-4 pl-8 text-sm leading-6 text-rose-900" aria-label="Local edits that will be lost">
            {differences.length > 0 ? differences.map((difference) => <li key={difference}>{difference}</li>) : <li>{editLabel} will be lost.</li>}
          </ul>
          {onDownloadBackup ? (
            <button type="button" className="mt-4 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-60" disabled={state.active !== null} onClick={() => void run("backup", onDownloadBackup, "Local backup downloaded.", "We couldn't prepare the local backup.")}>
              {actionLabel("backup", state.active)}
            </button>
          ) : null}
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <button ref={initialFocusRef} type="button" className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white" onClick={() => setConfirmServer(false)}>
              Back to comparison
            </button>
            <button type="button" className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800 disabled:cursor-not-allowed disabled:opacity-60" disabled={state.active !== null} onClick={() => void run("use-server", onUseServerCopy, "Server copy opened.", "Nothing was discarded. We couldn't open the server copy.")}>
              {state.active === "use-server" ? "Opening server copy…" : `Discard ${editLabel} and use server copy`}
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {copyDetails(serverCopy)}
            {copyDetails(localCopy)}
          </div>
          <div className="mt-4 rounded-lg border border-slate-200 p-4">
            <h2 className="font-semibold text-slate-900">Review differences</h2>
            <button ref={initialFocusRef} type="button" className="mt-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-60" disabled={actionsDisabled} aria-expanded={showDifferences} onClick={() => setShowDifferences((visible) => !visible)}>
              Review differences
            </button>
            {showDifferences ? (
              differences.length > 0 ? <ul className="mt-3 list-disc pl-5 text-sm leading-6 text-slate-700">{differences.map((difference) => <li key={difference}>{difference}</li>)}</ul> : <p className="mt-3 text-sm text-slate-600">No local differences were provided.</p>
            ) : null}
          </div>
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <button type="button" className="rounded-lg bg-brand-primary px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60" disabled={actionsDisabled} onClick={() => void run("keep-local", onKeepLocalAndRetry, "Local copy retained. Retry started.", "We couldn't retry the local copy. Both copies remain preserved.")}>
              {actionLabel("keep-local", state.active)}
            </button>
            <button type="button" className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-60" disabled={actionsDisabled} onClick={() => setConfirmServer(true)}>
              Use server copy
            </button>
            <button type="button" className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-60" disabled={actionsDisabled} onClick={onDefer}>
              Defer
            </button>
          </div>
        </>
      )}
      <ActionError message={state.error} />
      <LiveAnnouncement message={state.announcement} />
    </RecoveryDialogFrame>
  );
}

export function CrtRecoveryDialog(props: CrtRecoveryDialogProps): React.JSX.Element {
  return props.kind === "conflict" ? <CrtConflictDialog {...props} /> : <CrtStaleDraftDialog {...props} />;
}

export type CrtStorageUnavailableAlertProps = {
  onRetry?: CrtRecoveryAction;
};

export function CrtStorageUnavailableAlert({ onRetry }: CrtStorageUnavailableAlertProps): React.JSX.Element {
  const { state, run } = useActionState();
  return (
    <div className="border-y border-amber-200 bg-amber-50 px-4 py-3 text-amber-950" role="alert" aria-live="polite" aria-busy={state.active === "keep-local"}>
      <p className="font-semibold">Saved online only</p>
      <p className="mt-1 max-w-3xl text-sm leading-6">
        Browser storage is unavailable, so local recovery is unavailable. Changes can be retried while the editor stays open. Resizing below the supported width, signing out, or an access change can close the editor and lose unsynchronized changes; a reload or browser crash can lose them too.
      </p>
      {onRetry ? (
        <button type="button" className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm font-semibold text-amber-900 disabled:cursor-not-allowed disabled:opacity-60" disabled={state.active !== null} onClick={() => void run("keep-local", onRetry, "Retry requested.", "We couldn't retry the save. Keep this page open and try again.")}>
          {state.active === "keep-local" ? "Retrying save…" : "Retry save"}
        </button>
      ) : null}
      <ActionError message={state.error} />
      <LiveAnnouncement message={state.announcement} />
    </div>
  );
}

export const CrtOnlineOnlyWarning = CrtStorageUnavailableAlert;
