import { useCallback, useEffect, useState } from "react";
import { ShieldCheck, Trash2, X } from "lucide-react";
import { useParams } from "react-router-dom";

import { apiClient } from "../../api/client";
import type { BrainDumpOperationResponse } from "../../api/taskTypes";
import { BrainDumpOverlay } from "./BrainDumpOverlay";
import { useCloseBrainDump } from "./brainDumpNavigation";
import { operationStatusLabels } from "./brainDumpStatusLabels";

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
export function BrainDumpPrivacyControls(): React.JSX.Element {
  const params = useParams();
  const closeOverlay = useCloseBrainDump();
  const operationId = params.operationId && params.operationId !== "new" ? params.operationId : null;
  const [operation, setOperation] = useState<BrainDumpOperationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(operationId));
  const [busyAction, setBusyAction] = useState<string | null>(null);

  useEffect(() => {
    if (!operationId) {
      return;
    }
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data-loading effect: switching to another operation id re-enters the loading state ahead of the fetch it starts, and only that fetch's callbacks leave it.
    setIsLoading(true);
    apiClient
      .getBrainDump(operationId, controller.signal)
      .then((next) => {
        setOperation(next);
        setIsLoading(false);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Could not load this voice brain dump.");
          setIsLoading(false);
        }
      });
    return () => controller.abort();
  }, [operationId]);

  // The command buttons only render for a loaded operation and are disabled
  // while a command is in flight, so the caller always passes a current
  // operation and never overlaps commands — `current` carries the freshest
  // revision each time (state re-renders between awaited commands).
  const runCommand = useCallback(async (action: "withdraw_consent" | "delete_raw_audio" | "cancel", current: BrainDumpOperationResponse) => {
    setBusyAction(action);
    setError(null);
    try {
      const updated = await apiClient.commandBrainDump(current.id, action, current.revision, privacyIdempotencyKey(action));
      setOperation(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That privacy action could not be completed.");
    } finally {
      setBusyAction(null);
    }
  }, []);

  const isTerminal = operation ? terminalStatuses.has(operation.status) : false;
  const canWithdrawConsent = Boolean(operation?.consent.external_processing_allowed) && !isTerminal;
  const canDeleteRawAudio = Boolean(operation?.raw_audio_present);
  const canDiscard = Boolean(operation) && !isTerminal;

  return (
    <BrainDumpOverlay labelledBy="brain-dump-privacy-title" onClose={closeOverlay} size="narrow">
      <header className="flex shrink-0 items-start gap-3 px-5 pt-[max(16px,env(safe-area-inset-top))] pb-3 sm:px-6 sm:pt-5">
        <div className="min-w-0 flex-1">
          <p className="inline-flex items-center gap-1.5 text-co-meta font-semibold text-ink">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
            Voice brain dump · privacy controls
          </p>
          <h1 id="brain-dump-privacy-title" className="font-voice text-co-title text-ink">
            You stay in control of this recording
          </h1>
        </div>
        <button
          type="button"
          aria-label="Close brain dump"
          className="-mr-1.5 -mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-control text-ink-muted transition-colors duration-200 ease-smooth hover:bg-quiet hover:text-ink"
          onClick={closeOverlay}
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 sm:px-6">
        <p className="text-co-meta text-ink-muted">
          New voice recordings are turned off for this workspace, but you can still manage the recording you already
          started.
        </p>

        {error ? <p role="alert" className="mt-3 rounded-card bg-quiet px-3 py-2 text-co-meta text-danger">{error}</p> : null}

        {isLoading ? (
          <p role="status" className="mt-4 rounded-card bg-quiet px-3 py-2 text-co-meta text-ink-muted">
            Loading this recording…
          </p>
        ) : !operationId ? (
          <p className="mt-4 rounded-card bg-quiet px-3 py-2 text-co-meta text-ink-muted">
            There is no recording to manage here.
          </p>
        ) : operation ? (
          <>
            <dl className="mt-4 rounded-card bg-quiet px-3 py-2 text-co-meta">
              <dt className="text-co-meta font-semibold text-ink-muted">Status</dt>
              <dd className="mt-0.5 font-medium text-ink">{operationStatusLabels[operation.status] ?? operation.status}</dd>
            </dl>
            <div className="mt-4 flex flex-col gap-2">
              {canWithdrawConsent ? (
                <button
                  type="button"
                  className="h-11 rounded-control bg-quiet px-4 text-co-meta font-semibold text-warning disabled:opacity-50 hover:bg-quiet-pressed"
                  disabled={busyAction !== null}
                  onClick={() => void runCommand("withdraw_consent", operation)}
                >
                  Withdraw cloud-processing consent
                </button>
              ) : null}
              {canDeleteRawAudio ? (
                <button
                  type="button"
                  className="inline-flex h-11 items-center justify-center gap-2 rounded-control bg-quiet px-4 text-co-meta font-semibold text-danger disabled:opacity-50 hover:bg-quiet-pressed"
                  disabled={busyAction !== null}
                  onClick={() => void runCommand("delete_raw_audio", operation)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                  Delete raw audio now
                </button>
              ) : null}
              {canDiscard ? (
                <button
                  type="button"
                  className="h-11 rounded-control bg-quiet px-4 text-co-meta font-medium text-ink disabled:opacity-50 hover:bg-quiet-pressed"
                  disabled={busyAction !== null}
                  onClick={() => void runCommand("cancel", operation)}
                >
                  Discard recording
                </button>
              ) : null}
              {!canWithdrawConsent && !canDeleteRawAudio && !canDiscard ? (
                <p className="rounded-card bg-quiet px-3 py-2 text-co-meta text-ink-muted">
                  Nothing is retained for this recording — there is no audio or transcript left to remove.
                </p>
              ) : null}
            </div>
          </>
        ) : null}
      </div>
    </BrainDumpOverlay>
  );
}
