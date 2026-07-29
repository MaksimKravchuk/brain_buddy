import { useCallback, useEffect, useRef, useState } from "react";
import { ShieldCheck, Trash2 } from "lucide-react";
import { useParams } from "react-router-dom";

import { apiClient } from "../../api/client";
import type { BrainDumpOperationResponse } from "../../api/taskTypes";

// Human-readable operation status for the privacy surface. Mirrors the phrasing
// the main route uses so the two never disagree about what a status means.
const operationStatusLabels: Record<string, string> = {
  recording: "Recording",
  paused: "Paused",
  sealing: "Sealing audio",
  fast_processing: "Building provisional tasks",
  accurate_transcribing: "Improving transcript",
  reconciling: "Reconciling tasks",
  committing: "Saving tasks",
  awaiting_confirmation: "Awaiting review",
  retryable_error: "Needs attention",
  terminal_error: "Could not be processed",
  completed: "Saved to Inbox",
  cancelled: "Discarded"
};

// Once an operation is cancelled or committed there is no retained transcript,
// audio, or in-flight egress left to act on, so no privacy control applies.
const terminalStatuses = new Set(["completed", "cancelled"]);

function privacyIdempotencyKey(action: string) {
  return `brain-dump-privacy-${action}-${Date.now()}`;
}

// Minimal, capture-free surface shown when the `voice_brain_dump` flag is OFF but
// the URL still references an existing operation (the only operation reference
// the client recovers across reloads — there is no localStorage/session record,
// so an operation the user cannot reach by URL is genuinely unknown to the
// client). It exercises the owner's standing rights over that operation — read
// status, withdraw cloud-processing consent, delete retained raw audio, and
// discard — all of which the backend keeps reachable with the flag OFF. It
// deliberately renders no Record button and no new-capture consent checkbox.
export function BrainDumpPrivacyControls(): JSX.Element {
  const params = useParams();
  const operationId = params.operationId && params.operationId !== "new" ? params.operationId : null;
  const [operation, setOperation] = useState<BrainDumpOperationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(operationId));
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const operationRef = useRef<BrainDumpOperationResponse | null>(null);

  const applyOperation = useCallback((next: BrainDumpOperationResponse) => {
    operationRef.current = next;
    setOperation(next);
  }, []);

  useEffect(() => {
    if (!operationId) {
      return;
    }
    const controller = new AbortController();
    setIsLoading(true);
    apiClient
      .getBrainDump(operationId, controller.signal)
      .then((next) => {
        applyOperation(next);
        setIsLoading(false);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Could not load this voice brain dump.");
          setIsLoading(false);
        }
      });
    return () => controller.abort();
  }, [applyOperation, operationId]);

  const runCommand = useCallback(
    async (action: "withdraw_consent" | "delete_raw_audio" | "cancel") => {
      const current = operationRef.current;
      if (!current || busyAction) {
        return;
      }
      setBusyAction(action);
      setError(null);
      try {
        const updated = await apiClient.commandBrainDump(current.id, action, current.revision, privacyIdempotencyKey(action));
        applyOperation(updated);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "That privacy action could not be completed.");
      } finally {
        setBusyAction(null);
      }
    },
    [applyOperation, busyAction]
  );

  const isTerminal = operation ? terminalStatuses.has(operation.status) : false;
  const canWithdrawConsent = Boolean(operation?.consent.external_processing_allowed) && !isTerminal;
  const canDeleteRawAudio = Boolean(operation?.raw_audio_present);
  const canDiscard = Boolean(operation) && !isTerminal;

  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-base px-4 text-slate-900">
      <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-floating">
        <p className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-brand-primary">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
          Voice brain dump · privacy controls
        </p>
        <h1 className="mt-2 text-xl font-semibold">You stay in control of this recording</h1>
        <p className="mt-2 text-sm text-slate-600">
          New voice recordings are turned off for this workspace, but you can still manage the recording you already
          started.
        </p>

        {error ? <p role="alert" className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

        {isLoading ? (
          <p role="status" className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">
            Loading this recording…
          </p>
        ) : !operationId ? (
          <p className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">
            There is no recording to manage here.
          </p>
        ) : operation ? (
          <>
            <dl className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</dt>
              <dd className="mt-0.5 font-medium text-slate-900">{operationStatusLabels[operation.status] ?? operation.status}</dd>
            </dl>
            <div className="mt-4 flex flex-col gap-2">
              {canWithdrawConsent ? (
                <button
                  type="button"
                  className="h-11 rounded-xl border border-amber-200 bg-white px-4 text-sm font-semibold text-amber-800 disabled:opacity-50"
                  disabled={busyAction !== null}
                  onClick={() => void runCommand("withdraw_consent")}
                >
                  Withdraw cloud-processing consent
                </button>
              ) : null}
              {canDeleteRawAudio ? (
                <button
                  type="button"
                  className="inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-rose-200 bg-white px-4 text-sm font-semibold text-rose-700 disabled:opacity-50"
                  disabled={busyAction !== null}
                  onClick={() => void runCommand("delete_raw_audio")}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                  Delete raw audio now
                </button>
              ) : null}
              {canDiscard ? (
                <button
                  type="button"
                  className="h-11 rounded-xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 disabled:opacity-50"
                  disabled={busyAction !== null}
                  onClick={() => void runCommand("cancel")}
                >
                  Discard recording
                </button>
              ) : null}
              {!canWithdrawConsent && !canDeleteRawAudio && !canDiscard ? (
                <p className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">
                  Nothing is retained for this recording — there is no audio or transcript left to remove.
                </p>
              ) : null}
            </div>
          </>
        ) : null}
      </section>
    </main>
  );
}
