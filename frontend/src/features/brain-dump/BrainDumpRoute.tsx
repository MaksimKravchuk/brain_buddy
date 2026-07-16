import { ChevronLeft, Inbox, Mic, Pause, Play, Square, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { apiClient } from "../../api/client";
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
  user_edited: "Edited"
};

function idempotencyKey(suffix: string) {
  return `brain-dump-${suffix}-${Date.now()}`;
}

export function BrainDumpRoute(): JSX.Element {
  const location = useLocation();
  const params = useParams();
  const navigate = useNavigate();
  const [operation, setOperation] = useState<BrainDumpOperationResponse | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastTranscript, setLastTranscript] = useState("");
  const [savedCount, setSavedCount] = useState<number | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const sequenceRef = useRef(0);
  const isReviewPath = location.pathname.endsWith("/review");
  const activeProposals = useMemo(() => (operation?.proposals ?? []).filter((proposal) => !proposal.deleted), [operation]);

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
    };
  }, []);

  useEffect(() => {
    const operationId = params.operationId;
    if (!operationId || operationId === "new" || operation?.id === operationId) {
      return;
    }
    const controller = new AbortController();
    apiClient.getBrainDump(operationId, controller.signal).then(setOperation).catch((caught: unknown) => {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : "Could not resume brain dump.");
      }
    });
    return () => controller.abort();
  }, [operation?.id, params.operationId]);

  function speechRecognitionConstructor() {
    const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Recognition) {
      setError("Browser speech recognition is unavailable; try Chrome or Edge.");
      return null;
    }
    return Recognition;
  }

  function stopRecognition() {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
  }

  async function probeMicrophone() {
    const permissionProbe = await navigator.mediaDevices.getUserMedia({ audio: true });
    permissionProbe.getTracks().forEach((track) => track.stop());
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
      setLastTranscript(transcript);
      sequenceRef.current += 1;
      void apiClient
        .appendBrainDumpTranscript(
          started.id,
          { segments: [{ sequence: sequenceRef.current, text: transcript, stability: latest.isFinal === false ? "interim" : "stable" }] },
          idempotencyKey(`segment-${sequenceRef.current}`)
        )
        .then(setOperation)
        .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Transcript upload failed."));
    };
    recognition.onerror = (event) => setError(event.error === "not-allowed" ? "Microphone permission was denied." : `Microphone error: ${event.error}`);
    recognition.start();
    recognitionRef.current = recognition;
  }

  async function startRecording() {
    setError(null);
    const Recognition = speechRecognitionConstructor();
    if (!Recognition) {
      return;
    }
    setIsStarting(true);
    try {
      await probeMicrophone();
      const started = operation ?? (await apiClient.startBrainDump({ consent: { microphone: true, external_processing_allowed: false } }, idempotencyKey("start")));
      setOperation(started);
      startRecognitionFor(started, Recognition);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Microphone permission was denied.");
    } finally {
      setIsStarting(false);
    }
  }

  async function command(action: "pause" | "resume" | "finish" | "cancel" | "commit") {
    if (!operation) {
      return;
    }
    setError(null);
    const Recognition = action === "resume" ? speechRecognitionConstructor() : null;
    if (action === "resume") {
      if (!Recognition) {
        return;
      }
      try {
        await probeMicrophone();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Microphone permission was denied.");
        return;
      }
    }
    if (action === "pause" || action === "finish" || action === "cancel") {
      stopRecognition();
    }
    try {
      const updated = await apiClient.commandBrainDump(operation.id, action, operation.revision, idempotencyKey(action));
      setOperation(updated);
      if (action === "resume" && Recognition) {
        startRecognitionFor(updated, Recognition);
      }
      if (action === "finish") {
        navigate(`/brain-dump/${operation.id}/review`, { replace: true });
      }
      if (action === "cancel") {
        setOperation(null);
        setLastTranscript("");
        navigate("/brain-dump/new", { replace: true });
      }
      if (action === "commit") {
        setSavedCount(updated.committed_task_ids.length);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Brain dump command failed.");
    }
  }

  async function updateProposal(proposal: BrainDumpProposal, title: string) {
    if (!operation || !title.trim() || title === proposal.title) {
      return;
    }
    const updated = await apiClient.updateBrainDumpProposal(
      operation.id,
      proposal.id,
      { title: title.trim(), expected_revision: operation.revision },
      idempotencyKey(`edit-${proposal.id}`)
    );
    setOperation(updated);
  }

  async function deleteProposal(proposal: BrainDumpProposal) {
    if (!operation) {
      return;
    }
    const updated = await apiClient.updateBrainDumpProposal(
      operation.id,
      proposal.id,
      { deleted: true, expected_revision: operation.revision },
      idempotencyKey(`delete-${proposal.id}`)
    );
    setOperation(updated);
  }

  if (savedCount !== null) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-base px-4 text-slate-900">
        <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-floating">
          <Inbox className="mx-auto h-8 w-8 text-brand-primary" aria-hidden />
          <h1 className="mt-3 text-xl font-semibold">Saved {savedCount} {savedCount === 1 ? "task" : "tasks"} to Inbox</h1>
          <p className="mt-2 text-sm text-slate-500">No duplicate tasks are created if this save is retried.</p>
        </section>
      </div>
    );
  }

  if (isReviewPath || operation?.status === "awaiting_confirmation") {
    return (
      <ReviewSurface
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
    <article className={`flex items-center gap-2 rounded-[10px] border px-3.5 py-2.5 shadow-soft ${proposal.status === "wording_changing" ? "border-dashed border-slate-300 bg-slate-50" : "border-slate-200 bg-white"}`}>
      <span className="text-[11px] font-semibold text-slate-500">#{proposal.ordinal}</span>
      <div className="min-w-0 flex-1 text-sm font-medium text-slate-900">{proposal.title}</div>
      <span className={proposal.status === "wording_changing" ? "text-[11px] text-slate-500" : "rounded-full bg-sky-50 px-2 py-0.5 text-[11px] text-sky-700"}>{statusLabels[proposal.status]}</span>
    </article>
  );
}

function ReviewSurface({
  proposals,
  onBack,
  onDelete,
  onDiscard,
  onSave,
  onUpdateTitle
}: {
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
                  </div>
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
        <button type="button" className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-brand-primary text-[15px] font-semibold text-white shadow-glow" onClick={onSave}>
          <Inbox className="h-4 w-4" aria-hidden />
          Save {proposals.length} to inbox
        </button>
      </footer>
    </div>
  );
}
