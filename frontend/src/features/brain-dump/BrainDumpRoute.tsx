import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Inbox, Mic, Pause, Play, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { apiClient } from "../../api/client";
import { taskKeys } from "../../api/taskHooks";
import type { BrainDumpOperationResponse, BrainDumpProposal, BrainDumpProposalStatus } from "../../api/taskTypes";

type SpeechRecognitionResultEventLike = {
  results: ArrayLike<{ 0: { transcript: string }; isFinal?: boolean }>;
};

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  onresult: ((event: SpeechRecognitionResultEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  }
}

const statusLabels: Record<BrainDumpProposalStatus, string> = {
  provisional: "Provisional",
  wording_changing: "Wording still changing",
  ready_to_review: "Ready to review",
  user_edited: "Edited",
  reconciled: "Reconciled",
  conflicted: "Needs review"
};

const processingStatusLabels = new Map<string, string>([
  ["sealing", "Sealing audio"],
  ["fast_processing", "Building provisional tasks"],
  ["accurate_transcribing", "Improving transcript"],
  ["reconciling", "Reconciling tasks"],
  ["committing", "Saving tasks"]
]);

function idempotencyKey(suffix: string) {
  return `brain-dump-${suffix}-${Date.now()}`;
}

export function BrainDumpRoute(): JSX.Element {
  const location = useLocation();
  const params = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [operation, setOperation] = useState<BrainDumpOperationResponse | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastTranscript, setLastTranscript] = useState("");
  const [savedCount, setSavedCount] = useState<number | null>(null);
  const [showProvisionalReview, setShowProvisionalReview] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunkNumberRef = useRef(0);
  const audioUploadQueueRef = useRef<Promise<void>>(Promise.resolve());
  const sequenceRef = useRef(0);
  const pendingInterimSequenceRef = useRef<number | null>(null);
  const operationRef = useRef<BrainDumpOperationResponse | null>(null);
  const proposalMutationQueueRef = useRef<Promise<void>>(Promise.resolve());
  const isReviewPath = location.pathname.endsWith("/review");
  const activeProposals = useMemo(() => (operation?.proposals ?? []).filter((proposal) => !proposal.deleted), [operation]);
  const hasUnresolvedConflicts = activeProposals.some((proposal) => (proposal.conflicts ?? []).length > 0);

  const applyOperation = useCallback((next: BrainDumpOperationResponse | null) => {
    const current = operationRef.current;
    if (next && current?.id === next.id && next.revision < current.revision) {
      return;
    }
    operationRef.current = next;
    setOperation(next);
  }, []);

  useEffect(() => {
    if (!operation) {
      return;
    }
    sequenceRef.current = Math.max(sequenceRef.current, ...operation.segments.map((segment) => segment.sequence), 0);
  }, [operation]);

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      recognitionRef.current = null;
      mediaRecorderRef.current?.stop();
      mediaRecorderRef.current = null;
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    };
  }, []);

  useEffect(() => {
    const operationId = params.operationId;
    if (!operationId || operationId === "new" || operation?.id === operationId) {
      return;
    }
    const controller = new AbortController();
    apiClient.getBrainDump(operationId, controller.signal).then(applyOperation).catch((caught: unknown) => {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : "Could not resume brain dump.");
      }
    });
    return () => controller.abort();
  }, [applyOperation, operation?.id, params.operationId]);

  function speechRecognitionConstructor() {
    const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    return Recognition ?? null;
  }

  function stopRecognition() {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    pendingInterimSequenceRef.current = null;
  }

  async function probeMicrophone() {
    return navigator.mediaDevices.getUserMedia({ audio: true });
  }

  function startRecognitionFor(started: BrainDumpOperationResponse, Recognition: SpeechRecognitionConstructor) {
    stopRecognition();
    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";
    recognition.onresult = (event) => {
      const latest = event.results[event.results.length - 1];
      const transcript = latest?.[0]?.transcript?.trim();
      if (!transcript) {
        return;
      }
      const stability = latest.isFinal === false ? "interim" : "stable";
      let sequence = pendingInterimSequenceRef.current;
      if (sequence === null) {
        sequenceRef.current += 1;
        sequence = sequenceRef.current;
      }
      pendingInterimSequenceRef.current = stability === "interim" ? sequence : null;
      setLastTranscript(transcript);
      void apiClient
        .appendBrainDumpTranscript(
          started.id,
          { segments: [{ sequence, text: transcript, stability }] },
          idempotencyKey(`segment-${sequence}`)
        )
        .then(applyOperation)
        .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Transcript upload failed."));
    };
    recognition.onerror = (event) => setError(event.error === "not-allowed" ? "Microphone permission was denied." : `Microphone error: ${event.error}`);
    recognition.start();
    recognitionRef.current = recognition;
  }

  async function sha256(bytes: ArrayBuffer) {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function manifestHash(operation: BrainDumpOperationResponse, expectedChunks: number) {
    const chunks = (operation.audio_chunks ?? [])
      .filter((chunk) => chunk.chunk_number < expectedChunks)
      .sort((left, right) => left.chunk_number - right.chunk_number)
      .map(({ chunk_number, sha256: digest, size_bytes }) => ({ chunk_number, sha256: digest, size_bytes }));
    return sha256(new TextEncoder().encode(JSON.stringify(chunks)).buffer);
  }

  function startMediaRecorderFor(started: BrainDumpOperationResponse, stream: MediaStream) {
    const recorder = new MediaRecorder(stream);
    audioChunkNumberRef.current = 0;
    audioUploadQueueRef.current = Promise.resolve();
    recorder.ondataavailable = (event) => {
      if (event.data.size === 0) {
        return;
      }
      const chunkNumber = audioChunkNumberRef.current++;
      audioUploadQueueRef.current = audioUploadQueueRef.current.then(async () => {
        const bytes = await event.data.arrayBuffer();
        const updated = await apiClient.uploadBrainDumpAudio(
          started.id,
          chunkNumber,
          bytes,
          await sha256(bytes)
        );
        applyOperation(updated);
      });
      void audioUploadQueueRef.current.catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : "Original audio upload failed.");
      });
    };
    recorder.start(1000);
    mediaRecorderRef.current = recorder;
    mediaStreamRef.current = stream;
  }

  async function stopMediaRecorder() {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      return;
    }
    await new Promise<void>((resolve) => {
      const previousStop = recorder.onstop;
      recorder.onstop = (event) => {
        previousStop?.call(recorder, event);
        resolve();
      };
      recorder.stop();
    });
    mediaRecorderRef.current = null;
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
  }

  async function startRecording() {
    setError(null);
    const Recognition = speechRecognitionConstructor();
    if (typeof MediaRecorder === "undefined") {
      setError("Original audio recording is unavailable in this browser.");
      return;
    }
    setIsStarting(true);
    try {
      const stream = await probeMicrophone();
      const started = operationRef.current ?? (await apiClient.startBrainDump({ consent: { microphone: true, external_processing_allowed: false } }, idempotencyKey("start")));
      applyOperation(started);
      if (params.operationId === "new") {
        navigate(`/brain-dump/${started.id}`, { replace: true });
      }
      startMediaRecorderFor(started, stream);
      if (Recognition) {
        startRecognitionFor(started, Recognition);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Microphone permission was denied.");
    } finally {
      setIsStarting(false);
    }
  }

  async function command(action: "pause" | "resume" | "finish" | "cancel" | "commit" | "retry") {
    if (!operationRef.current) {
      return;
    }
    setError(null);
    const Recognition = action === "resume" ? speechRecognitionConstructor() : null;
    if (action === "resume") {
      if (!Recognition) {
        setError("Browser speech recognition is unavailable; try Chrome or Edge.");
        return;
      }
      try {
        const permissionProbe = await probeMicrophone();
        if (!mediaRecorderRef.current) {
          permissionProbe.getTracks().forEach((track) => track.stop());
        }
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Microphone permission was denied.");
        return;
      }
    }
    try {
      // Let in-flight proposal edits settle so the command carries the freshest revision.
      await proposalMutationQueueRef.current;
      const current = operationRef.current;
      if (!current) {
        return;
      }
      if (action === "finish") {
        stopRecognition();
        await stopMediaRecorder();
        await audioUploadQueueRef.current;
        const sealedInput = operationRef.current;
        if (!sealedInput) {
          return;
        }
        const expectedChunks = audioChunkNumberRef.current;
        const sealed = await apiClient.sealBrainDump(
          sealedInput.id,
          {
            expected_revision: sealedInput.revision,
            expected_chunks: expectedChunks,
            manifest_hash: await manifestHash(sealedInput, expectedChunks)
          },
          idempotencyKey("seal")
        );
        applyOperation(sealed);
        navigate(`/brain-dump/${sealed.id}/review`, { replace: true });
        return;
      }
      const updated = await apiClient.commandBrainDump(current.id, action, current.revision, idempotencyKey(action));
      applyOperation(updated);
      if (action === "pause" || action === "cancel") {
        stopRecognition();
      }
      if (action === "pause" && mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.pause();
      }
      if (action === "resume" && Recognition) {
        startRecognitionFor(updated, Recognition);
      }
      if (action === "resume" && mediaRecorderRef.current?.state === "paused") {
        mediaRecorderRef.current.resume();
      }
      if (action === "cancel") {
        applyOperation(null);
        setLastTranscript("");
        navigate("/brain-dump/new", { replace: true });
      }
      if (action === "commit") {
        setSavedCount(updated.committed_task_ids.length);
        void queryClient.invalidateQueries({ queryKey: taskKeys.all });
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Brain dump command failed.");
    }
  }

  async function patchProposal(proposal: BrainDumpProposal, payload: { title?: string; deleted?: boolean }, kind: "edit" | "delete") {
    const current = operationRef.current;
    if (!current) {
      return;
    }
    setError(null);
    try {
      const updated = await apiClient.updateBrainDumpProposal(
        current.id,
        proposal.id,
        { ...payload, expected_revision: current.revision },
        idempotencyKey(`${kind}-${proposal.id}`)
      );
      applyOperation(updated);
    } catch (caught) {
      const fallback = kind === "edit" ? "Could not update the task title." : "Could not delete the task.";
      setError(caught instanceof Error ? caught.message : fallback);
    }
  }

  function queueProposalMutation(mutate: () => Promise<void>) {
    // Serialize proposal edits so each PATCH reads the revision produced by the previous one.
    const chained = proposalMutationQueueRef.current.then(mutate);
    proposalMutationQueueRef.current = chained;
    return chained;
  }

  function updateProposal(proposal: BrainDumpProposal, title: string) {
    if (!title.trim() || title === proposal.title) {
      return;
    }
    void queueProposalMutation(() => patchProposal(proposal, { title: title.trim() }, "edit"));
  }

  function deleteProposal(proposal: BrainDumpProposal) {
    void queueProposalMutation(() => patchProposal(proposal, { deleted: true }, "delete"));
  }

  if (savedCount !== null) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-base px-4 text-slate-900">
        <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-floating">
          <Inbox className="mx-auto h-8 w-8 text-brand-primary" aria-hidden />
          <h1 className="mt-3 text-xl font-semibold">Saved {savedCount} {savedCount === 1 ? "task" : "tasks"} to Inbox</h1>
          <p className="mt-2 text-sm text-slate-500">No duplicate tasks are created if this save is retried.</p>
          <button
            type="button"
            className="mt-4 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand-primary px-5 text-[15px] font-semibold text-white shadow-glow hover:bg-brand-primary-hover"
            onClick={() => navigate("/tasks/inbox", { replace: true })}
          >
            <Inbox className="h-4 w-4" aria-hidden />
            View inbox
          </button>
        </section>
      </div>
    );
  }

  if (operation && processingStatusLabels.has(operation.status) && operation.status !== "committing") {
    return <ProcessingSurface error={error} operation={operation} proposals={activeProposals} />;
  }

  if (operation && (operation.status === "retryable_error" || operation.status === "terminal_error") && !showProvisionalReview) {
    const providerRuns = operation.provider_runs ?? [];
    const providerError = providerRuns[providerRuns.length - 1]?.error ?? null;
    return (
      <RecoverySurface
        error={error}
        operation={operation}
        providerError={providerError}
        onDelete={() => void command("cancel")}
        onReview={() => setShowProvisionalReview(true)}
        onRetry={() => void command("retry")}
      />
    );
  }

  if (isReviewPath || operation?.status === "awaiting_confirmation") {
    return (
      <ReviewSurface
        error={error}
        hasUnresolvedConflicts={hasUnresolvedConflicts}
        proposals={activeProposals}
        onBack={() => navigate(`/brain-dump/${operation?.id ?? "new"}`, { replace: true })}
        onDelete={deleteProposal}
        onDiscard={() => void command("cancel")}
        onSave={() => void command("commit")}
        onUpdateTitle={updateProposal}
      />
    );
  }

  return (
    <RecordingSurface
      error={error}
      isStarting={isStarting}
      lastTranscript={lastTranscript}
      operation={operation}
      proposals={activeProposals}
      onCancel={() => void command("cancel")}
      onFinish={() => void command("finish")}
      onPause={() => void command("pause")}
      onResume={() => void command("resume")}
      onStart={() => void startRecording()}
    />
  );
}

function RecoverySurface({
  error,
  operation,
  providerError,
  onDelete,
  onReview,
  onRetry
}: {
  error: string | null;
  operation: BrainDumpOperationResponse;
  providerError: string | null;
  onDelete: () => void;
  onReview: () => void;
  onRetry: () => void;
}): JSX.Element {
  const retryable = operation.status === "retryable_error";
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-base px-4 text-slate-900">
      <section role="alert" className="w-full max-w-md rounded-2xl border border-amber-200 bg-white p-6 shadow-floating">
        <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-amber-700">Voice brain dump</p>
        <h1 className="mt-2 text-xl font-semibold">{retryable ? "Accurate transcription paused" : "Accurate transcription failed"}</h1>
        <p className="mt-2 text-sm text-slate-600">
          {providerError ?? (retryable ? "The provider can be retried from the sealed recording." : "The recording could not be processed accurately.")}
        </p>
        {error ? <p className="mt-3 text-sm text-rose-700">{error}</p> : null}
        <div className="mt-5 flex flex-col gap-2">
          {retryable ? <button type="button" className="h-11 rounded-xl bg-brand-primary px-4 text-sm font-semibold text-white" onClick={onRetry}>Retry accurate transcription</button> : null}
          {operation.proposals.some((proposal) => !proposal.deleted) ? <button type="button" className="h-11 rounded-xl border border-slate-200 px-4 text-sm font-medium text-slate-700" onClick={onReview}>Review provisional tasks</button> : null}
          <button type="button" className="h-11 rounded-xl border border-rose-200 px-4 text-sm font-medium text-rose-700" onClick={onDelete}>Delete recording</button>
        </div>
      </section>
    </div>
  );
}

function RecordingSurface({
  error,
  isStarting,
  lastTranscript,
  operation,
  proposals,
  onCancel,
  onFinish,
  onPause,
  onResume,
  onStart
}: {
  error: string | null;
  isStarting: boolean;
  lastTranscript: string;
  operation: BrainDumpOperationResponse | null;
  proposals: BrainDumpProposal[];
  onCancel: () => void;
  onFinish: () => void;
  onPause: () => void;
  onResume: () => void;
  onStart: () => void;
}): JSX.Element {
  const count = proposals.length;
  const isPaused = operation?.status === "paused";
  const isRecording = operation?.status === "recording";
  return (
    <div className="min-h-screen bg-surface-base text-slate-900" data-operation-id={operation?.id ?? "new"}>
      <div className="fixed inset-0 flex items-center justify-center bg-slate-50/80 p-0 backdrop-blur-sm sm:p-4">
        <section role="dialog" aria-modal="true" aria-labelledby="brain-dump-title" className="flex h-[100dvh] w-full flex-col overflow-hidden bg-white shadow-floating sm:h-[640px] sm:w-[min(720px,calc(100vw-32px))] sm:rounded-[20px] sm:border sm:border-slate-200">
          <header className="flex shrink-0 items-center gap-2 border-b border-slate-100 px-5 py-4 sm:px-6">
            <h1 id="brain-dump-title" className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-600">Brain dump</h1>
            <span className="text-xs text-slate-400">·</span>
            <span className="text-xs font-semibold text-slate-900">{count} {count === 1 ? "task" : "tasks"} captured</span>
            <span className={`ml-auto inline-flex items-center gap-1.5 text-xs font-medium ${isRecording ? "text-rose-600" : "text-slate-500"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${isRecording ? "bg-rose-600" : "bg-slate-400"}`} aria-hidden />
              {isPaused ? "Paused" : isRecording ? "Recording" : "Ready"}
            </span>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 sm:px-6" aria-live="polite">
            {error ? <div role="alert" className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div> : null}
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-600">Headed to inbox · {count}</div>
            <div className="flex flex-col gap-2">
              {proposals.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} />)}
              {proposals.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 p-4 text-sm text-slate-500">Press Record and speak. Provisional Inbox tasks will grow here while you talk.</p> : null}
            </div>
          </div>

          <footer className="shrink-0 border-t border-slate-100 bg-slate-50/80 px-4 py-3 sm:px-5">
            <div className="flex items-center gap-3">
              <div className="relative h-10 w-10 shrink-0" aria-label="Voice level">
                <span className={`absolute inset-0 rounded-full bg-sky-200/70 ${isRecording ? "animate-[bbPulse_1.8s_cubic-bezier(.22,1,.36,1)_infinite]" : ""}`} />
                <div className="absolute inset-0 flex items-center justify-center rounded-full bg-brand-primary text-white">
                  <Mic className="h-4 w-4" aria-hidden />
                </div>
              </div>
              <details className="min-w-0 flex-1 text-[13px] leading-normal text-slate-500">
                <summary className="cursor-pointer list-none overflow-hidden text-ellipsis whitespace-nowrap">{lastTranscript || "Transcript stays collapsed while tasks remain primary"}</summary>
                <p className="mt-2 whitespace-pre-wrap rounded-lg bg-white p-2 text-xs text-slate-500">{lastTranscript || "No transcript yet."}</p>
              </details>
              {!operation ? (
                <button type="button" className="inline-flex h-10 items-center gap-2 rounded-lg bg-brand-primary px-4 text-sm font-semibold text-white shadow-soft" disabled={isStarting} onClick={onStart}>
                  <Mic className="h-4 w-4" aria-hidden />
                  Record
                </button>
              ) : isPaused ? (
                <button type="button" className="inline-flex h-10 items-center gap-2 rounded-lg bg-brand-primary px-4 text-sm font-semibold text-white shadow-soft" onClick={onResume}>
                  <Play className="h-4 w-4" aria-hidden />
                  Resume
                </button>
              ) : (
                <button type="button" className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700" onClick={onPause}>
                  <Pause className="h-4 w-4" aria-hidden />
                  Pause
                </button>
              )}
              <button type="button" className="hidden h-10 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 sm:inline-flex sm:items-center" onClick={onCancel}>Discard</button>
              <button type="button" className="inline-flex h-10 items-center gap-2 rounded-lg bg-brand-primary px-4 text-sm font-semibold text-white shadow-soft hover:bg-brand-primary-hover sm:px-5" disabled={!operation} onClick={onFinish}>
                <Square className="h-3.5 w-3.5" aria-hidden />
                Stop & review
              </button>
            </div>
            <p className="mt-2 text-center text-xs text-slate-500">Nothing is saved until review</p>
          </footer>
        </section>
      </div>
    </div>
  );
}

function ProposalCard({ proposal }: { proposal: BrainDumpProposal }): JSX.Element {
  return (
    <article aria-label={`Draft task ${proposal.ordinal}: ${proposal.title}`} className={`flex items-center gap-2 rounded-[10px] border px-3.5 py-2.5 shadow-soft ${proposal.status === "wording_changing" ? "border-dashed border-slate-300 bg-slate-50" : "border-slate-200 bg-white"}`}>
      <span className="text-[11px] font-semibold text-slate-500">#{proposal.ordinal}</span>
      <div className="min-w-0 flex-1 text-sm font-medium text-slate-900">{proposal.title}</div>
      <span className={proposal.status === "wording_changing" ? "text-[11px] text-slate-500" : "rounded-full bg-sky-50 px-2 py-0.5 text-[11px] text-sky-700"}>{statusLabels[proposal.status]}</span>
    </article>
  );
}

function ProcessingSurface({
  error,
  operation,
  proposals
}: {
  error: string | null;
  operation: BrainDumpOperationResponse;
  proposals: BrainDumpProposal[];
}): JSX.Element {
  const label = processingStatusLabels.get(operation.status) ?? "Processing";
  return (
    <div className="min-h-screen bg-surface-base text-slate-900" data-operation-id={operation.id}>
      <div className="fixed inset-0 flex items-center justify-center bg-slate-50/80 p-4 backdrop-blur-sm">
        <section role="status" aria-live="polite" className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-floating">
          {error ? <div role="alert" className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div> : null}
          <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-600">Voice brain dump</p>
          <h1 className="mt-2 text-xl font-semibold text-slate-900">{label}</h1>
          <p className="mt-1 text-sm text-slate-500">{operation.status}</p>
          <div className="mt-4 flex flex-col gap-2">
            {proposals.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} />)}
            {proposals.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 p-4 text-sm text-slate-500">We are keeping the task list first while the accurate transcript catches up.</p> : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function ReviewSurface({
  error,
  hasUnresolvedConflicts,
  proposals,
  onBack,
  onDelete,
  onDiscard,
  onSave,
  onUpdateTitle
}: {
  error: string | null;
  hasUnresolvedConflicts: boolean;
  proposals: BrainDumpProposal[];
  onBack: () => void;
  onDelete: (proposal: BrainDumpProposal) => void;
  onDiscard: () => void;
  onSave: () => void;
  onUpdateTitle: (proposal: BrainDumpProposal, title: string) => void;
}): JSX.Element {
  return (
    <div className="flex min-h-screen flex-col bg-surface-base text-slate-900">
      <header className="flex shrink-0 items-center gap-3 border-b border-slate-100 bg-white/95 px-4 pt-[max(16px,env(safe-area-inset-top))] pb-3">
        <button type="button" className="flex h-11 w-11 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600" aria-label="Back to recording" onClick={onBack}>
          <ChevronLeft className="h-5 w-5" aria-hidden />
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="text-[17px] font-semibold tracking-[-0.015em] text-slate-900">Review {proposals.length} {proposals.length === 1 ? "task" : "tasks"}</h1>
          <p className="mt-0.5 text-xs text-slate-500">Edit before they land in your inbox</p>
        </div>
      </header>

      <main aria-label="Review brain dump proposals" className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {error ? <div role="alert" className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div> : null}
        <div className="flex flex-col gap-2.5">
          {proposals.map((proposal) => (
            <article key={proposal.id} className="rounded-[14px] border border-slate-200 bg-white px-3.5 py-3 shadow-soft">
              <div className="flex items-start gap-2.5">
                <span className="mt-1 text-xs font-semibold text-slate-500">#{proposal.ordinal}</span>
                <div className="min-w-0 flex-1">
                  <label className="sr-only" htmlFor={`proposal-title-${proposal.id}`}>Task title #{proposal.ordinal}</label>
                  <input id={`proposal-title-${proposal.id}`} defaultValue={proposal.title} onBlur={(event) => void onUpdateTitle(proposal, event.currentTarget.value)} className="w-full border-0 border-b-[1.5px] border-sky-200 bg-transparent pb-1 text-[15px] font-medium text-slate-900 outline-none" />
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700">Inbox</span>
                    <span className="rounded-full bg-sky-50 px-2.5 py-1 text-xs text-sky-700">{statusLabels[proposal.status]}</span>
                    {(proposal.locked_fields ?? []).map((field) => (
                      <span key={field} className="rounded-full bg-amber-50 px-2.5 py-1 text-xs text-amber-700">Locked: {field}</span>
                    ))}
                    {(proposal.predecessor_ids ?? []).length > 0 ? (
                      <span className="rounded-full bg-violet-50 px-2.5 py-1 text-xs text-violet-700">
                        {(proposal.predecessor_ids ?? []).length > 1
                          ? `Merged from ${(proposal.predecessor_ids ?? []).length} tasks`
                          : "Split from an earlier task"}
                      </span>
                    ) : null}
                  </div>
                  {(proposal.conflicts ?? []).map((conflict) => (
                    <div key={`${conflict.field}-${conflict.suggested_value ?? ""}`} className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                      <div className="font-semibold">Conflict: {conflict.field}</div>
                      <div>Mine: {conflict.current_value ?? "—"}</div>
                      <div>Suggestion: {conflict.suggested_value ?? "—"}</div>
                    </div>
                  ))}
                </div>
                <button type="button" className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 hover:bg-rose-50 hover:text-rose-500" aria-label={`Delete ${proposal.title}`} onClick={() => onDelete(proposal)}>
                  <Trash2 className="h-4 w-4" aria-hidden />
                </button>
              </div>
            </article>
          ))}
        </div>
      </main>

      <footer className="flex shrink-0 items-center gap-3 border-t border-slate-100 bg-white/95 px-4 py-3 pb-[max(12px,env(safe-area-inset-bottom))]">
        <button type="button" className="h-11 rounded-xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-600" onClick={onDiscard}>
          Discard
        </button>
        <button type="button" className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-brand-primary text-[15px] font-semibold text-white shadow-glow disabled:cursor-not-allowed disabled:opacity-50" disabled={hasUnresolvedConflicts} onClick={onSave}>
          <Inbox className="h-4 w-4" aria-hidden />
          Save {proposals.length} to inbox
        </button>
      </footer>
    </div>
  );
}
