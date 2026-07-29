import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Inbox, Mic, Pause, Play, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { apiClient } from "../../api/client";
import { taskKeys, useBrainDumpProviders } from "../../api/taskHooks";
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

// A background lease-recovery sweep or another process can advance one of
// these statuses server-side without any client action; the poll keeps a
// stale processing/recovery projection moving without a manual reload. It
// stops the moment the operation reaches review (awaiting_confirmation),
// completed/cancelled, or the genuinely terminal `terminal_error` state.
const pollableStatuses = new Set<string>([...processingStatusLabels.keys(), "retryable_error"]);
const POLL_INITIAL_MS = 1500;
const POLL_MAX_MS = 8000;

const languageOptions = {
  ru: { hints: ["ru"] },
  "ru-en": { hints: ["ru", "en"] },
  en: { hints: ["en"] }
} as const;

type LanguageMode = keyof typeof languageOptions;

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
  const [consentWithdrawnMidCapture, setConsentWithdrawnMidCapture] = useState(false);
  const [languageMode, setLanguageMode] = useState<LanguageMode>("ru-en");
  const [externalProcessingAllowed, setExternalProcessingAllowed] = useState(false);
  const [vocabularyText, setVocabularyText] = useState("BrainBuddy, production smoke");
  const [isSaving, setIsSaving] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunkNumberRef = useRef(0);
  const audioUploadQueueRef = useRef<Promise<void>>(Promise.resolve());
  const sequenceRef = useRef(0);
  const pendingInterimSequenceRef = useRef<number | null>(null);
  const operationRef = useRef<BrainDumpOperationResponse | null>(null);
  const localCaptureOperationIdRef = useRef<string | null>(null);
  const proposalMutationQueueRef = useRef<Promise<void>>(Promise.resolve());
  const isReviewPath = location.pathname.endsWith("/review");
  // Only the fresh-recording screen needs the configured providers, to seed the
  // consent the user grants at Record time. Resuming an existing operation
  // already carries its recorded consent, so the fetch stays off those paths.
  const isNewRecording = params.operationId === "new" && !isReviewPath;
  const providersQuery = useBrainDumpProviders(isNewRecording);
  const brainDumpProviders = providersQuery.data ?? null;
  // Fail-closed provider discovery: consent and Record are gated on
  // GET /api/brain-dump-providers resolving to a named audio destination. Until
  // discovery succeeds and names the configured vendors, no consent may be
  // granted and no microphone/recorder/upload may start (FR-012, privacy
  // boundary). A discovery that succeeds but names no accurate-STT vendor is
  // treated as failed: we will not record when the audio destination is unknown.
  const providersReady = providersQuery.isSuccess && Boolean(brainDumpProviders?.accurate_stt);
  const providersFailed = providersQuery.isError || (providersQuery.isSuccess && !brainDumpProviders?.accurate_stt);
  const activeProposals = useMemo(() => (operation?.proposals ?? []).filter((proposal) => !proposal.deleted), [operation]);
  const segmentsById = useMemo(() => {
    const map = new Map<string, BrainDumpOperationResponse["segments"][number]>();
    for (const segment of operation?.segments ?? []) {
      map.set(segment.id, segment);
    }
    return map;
  }, [operation]);
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
    if (operation.status === "completed") {
      setSavedCount(operation.committed_task_ids.length);
    }
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

  useEffect(() => {
    const operationId = operation?.id;
    const operationStatus = operation?.status;
    if (!operationId || !operationStatus || !pollableStatuses.has(operationStatus)) {
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    let delay = POLL_INITIAL_MS;

    const poll = () => {
      apiClient
        .getBrainDump(operationId, controller.signal)
        .then((next) => {
          if (stopped) {
            return;
          }
          applyOperation(next);
          if (!pollableStatuses.has(next.status)) {
            return;
          }
          delay = Math.min(delay * 2, POLL_MAX_MS);
          timer = setTimeout(poll, delay);
        })
        .catch(() => {
          if (stopped || controller.signal.aborted) {
            return;
          }
          delay = Math.min(delay * 2, POLL_MAX_MS);
          timer = setTimeout(poll, delay);
        });
    };
    timer = setTimeout(poll, delay);

    return () => {
      stopped = true;
      controller.abort();
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [applyOperation, operation?.id, operation?.status]);

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
    const firstHint = started.consent.language_hints?.[0]?.toLowerCase();
    recognition.lang = firstHint === "ru" ? "ru-RU" : firstHint === "en" ? "en-US" : navigator.language || "en-US";
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
    // Normalize cross-realm ArrayBuffers (for example MediaRecorder/Blob data
    // supplied by jsdom or an embedded browser) into this realm's BufferSource.
    const digest = await crypto.subtle.digest("SHA-256", new Uint8Array(bytes));
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
          await sha256(bytes),
          recorder.mimeType
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

  async function stopMediaRecorder({ discardPendingAudio = false } = {}) {
    const recorder = mediaRecorderRef.current;
    try {
      if (recorder && recorder.state !== "inactive") {
        if (discardPendingAudio) {
          // `stop()` may synchronously emit a final dataavailable event. Once the
          // user discards capture or revokes cloud-processing consent that final
          // blob must not enter the upload queue after the server has revoked it.
          recorder.ondataavailable = null;
        }
        await new Promise<void>((resolve) => {
          const previousStop = recorder.onstop;
          recorder.onstop = (event) => {
            previousStop?.call(recorder, event);
            resolve();
          };
          recorder.stop();
        });
      }
    } finally {
      // Every live MediaStream track must be released even when there is no
      // recorder at all, or it is already inactive (e.g. it stopped itself,
      // or a previous cleanup already ran) -- otherwise the browser keeps the
      // microphone indicator (and the underlying device) held open.
      mediaRecorderRef.current = null;
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
  }

  async function startRecording() {
    setError(null);
    setConsentWithdrawnMidCapture(false);
    if (!externalProcessingAllowed) {
      setError("Secure cloud transcription consent is required before recording.");
      return;
    }
    // Fail-closed: never touch the microphone until provider discovery has
    // resolved the real vendor names the consent above was granted against.
    // The consent checkbox and Record button are already gated on
    // `providersReady`; this guard is the enforcement point that keeps
    // getUserMedia / MediaRecorder / audio upload off a degraded or unresolved
    // discovery, so audio can never egress to an unnamed provider (FR-012).
    if (!brainDumpProviders?.accurate_stt) {
      setError("Configured voice providers are still loading. Wait until they appear before recording.");
      return;
    }
    const Recognition = speechRecognitionConstructor();
    if (typeof MediaRecorder === "undefined") {
      setError("Original audio recording is unavailable in this browser.");
      return;
    }
    setIsStarting(true);
    let stream: MediaStream | null = null;
    try {
      stream = await probeMicrophone();
      const vocabulary = vocabularyText.split(",").map((value) => value.trim()).filter(Boolean);
      // Consent names every external provider the configured pipeline uses so a
      // mixed-vendor setup (e.g. Deepgram STT + OpenAI reconciler) is authorized
      // per role. `provider` stays the accurate-STT name for legacy compatibility.
      const externalProviderNames = externalProcessingAllowed
        ? Array.from(
            new Set(
              [brainDumpProviders?.accurate_stt, brainDumpProviders?.reconciler].filter(
                (name): name is string => Boolean(name)
              )
            )
          )
        : [];
      const legacyProvider = externalProcessingAllowed
        ? brainDumpProviders?.accurate_stt ?? externalProviderNames[0] ?? null
        : null;
      const started = operationRef.current ?? (await apiClient.startBrainDump({
        consent: {
          microphone: true,
          external_processing_allowed: externalProcessingAllowed,
          provider: legacyProvider,
          providers: externalProviderNames,
          language_hints: [...languageOptions[languageMode].hints],
          vocabulary
        }
      }, idempotencyKey("start")));
      localCaptureOperationIdRef.current = started.id;
      applyOperation(started);
      if (params.operationId === "new") {
        navigate(`/brain-dump/${started.id}`, { replace: true });
      }
      startMediaRecorderFor(started, stream);
      if (Recognition) {
        startRecognitionFor(started, Recognition);
      }
    } catch (caught) {
      // getUserMedia may have already granted the microphone even though a
      // later step (operation creation, MediaRecorder construction/start, or
      // recognition startup) failed; every acquired track must still be
      // released or the browser keeps the microphone indicator held open.
      stopRecognition();
      const streamIsManagedByRecorder = mediaStreamRef.current === stream;
      await stopMediaRecorder({ discardPendingAudio: true });
      if (!streamIsManagedByRecorder) {
        stream?.getTracks().forEach((track) => track.stop());
      }
      setError(caught instanceof Error ? caught.message : "Microphone permission was denied.");
    } finally {
      setIsStarting(false);
    }
  }

  async function command(action: "pause" | "resume" | "finish" | "cancel" | "commit" | "retry" | "review_provisional" | "withdraw_consent" | "delete_raw_audio") {
    if (!operationRef.current) {
      return;
    }
    setError(null);
    if (action === "commit") {
      if (isSaving) {
        return;
      }
      setIsSaving(true);
    }
    if (action === "withdraw_consent") {
      // Fail-closed: release the microphone, recognizer, and any future
      // transcript/audio uploads locally before the server round-trip. A
      // slow or rejected withdraw_consent response must never leave local
      // capture still running -- see the retry affordance below, which
      // stays available for as long as the server has not confirmed.
      stopRecognition();
      await stopMediaRecorder({ discardPendingAudio: true });
      setConsentWithdrawnMidCapture(true);
    }
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
        if (!sealedInput.consent.external_processing_allowed) {
          // Without external-processing consent no audio was ever uploaded, so
          // there is nothing to seal. Still record the "finish" transition
          // server-side before routing to review: the server must never be
          // left thinking the operation is still recording/paused while the
          // UI shows Review. The operation lands in the same
          // "awaiting_confirmation" status finish always produces, but with
          // no sealed/reconciled checkpoint, so the backend's commit gate
          // keeps it provisional-only (review/discard, never save-as-tasks).
          const finished = await apiClient.commandBrainDump(
            sealedInput.id,
            "finish",
            sealedInput.revision,
            idempotencyKey("finish")
          );
          applyOperation(finished);
          navigate(`/brain-dump/${finished.id}/review`, { replace: true });
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
      if (action === "pause" || action === "cancel" || action === "withdraw_consent") {
        stopRecognition();
      }
      if (action === "cancel" || action === "withdraw_consent") {
        // Discarding a recording must release the microphone immediately:
        // stop the MediaRecorder and every live MediaStream track, not just
        // browser speech recognition, or the browser keeps the mic indicator
        // (and the underlying device) held open after the user cancels.
        await stopMediaRecorder({ discardPendingAudio: true });
      }
      if (action === "withdraw_consent") {
        setConsentWithdrawnMidCapture(true);
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
        localCaptureOperationIdRef.current = null;
        applyOperation(null);
        setConsentWithdrawnMidCapture(false);
        setLastTranscript("");
        navigate("/brain-dump/new", { replace: true });
      }
      if (action === "commit") {
        setSavedCount(updated.committed_task_ids.length);
        void queryClient.invalidateQueries({ queryKey: taskKeys.all });
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Brain dump command failed.");
    } finally {
      if (action === "commit") {
        setIsSaving(false);
      }
    }
  }

  async function patchProposal(
    proposal: BrainDumpProposal,
    payload: { title?: string; deleted?: boolean; conflict_resolution?: "keep" | "accept" },
    kind: "edit" | "delete" | "resolve"
  ) {
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
      const fallback =
        kind === "edit"
          ? "Could not update the task title."
          : kind === "resolve"
            ? "Could not resolve the conflict."
            : "Could not delete the task.";
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

  function resolveConflict(proposal: BrainDumpProposal, resolution: "keep" | "accept") {
    void queueProposalMutation(() => patchProposal(proposal, { conflict_resolution: resolution }, "resolve"));
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

  if (operation && processingStatusLabels.has(operation.status)) {
    return <ProcessingSurface error={error} operation={operation} proposals={activeProposals} />;
  }

  if (operation && (operation.status === "retryable_error" || operation.status === "terminal_error")) {
    const providerRuns = operation.provider_runs ?? [];
    const providerError = providerRuns[providerRuns.length - 1]?.error ?? null;
    return (
      <RecoverySurface
        error={error}
        operation={operation}
        providerError={providerError}
        onDelete={() => void command("cancel")}
        onReview={() => void command("review_provisional")}
        onRetry={() => void command("retry")}
      />
    );
  }

  if (isReviewPath || operation?.status === "awaiting_confirmation") {
    return (
      <ReviewSurface
        error={error}
        hasUnresolvedConflicts={hasUnresolvedConflicts}
        isSaving={isSaving}
        committable={operation?.committable ?? false}
        proposals={activeProposals}
        segmentsById={segmentsById}
        reconciliationQuality={operation?.reconciliation_quality ?? "none"}
        rawAudioExpiresAt={operation?.raw_audio_expires_at}
        rawAudioPresent={operation?.raw_audio_present ?? false}
        onBack={() => navigate(`/brain-dump/${operation?.id ?? "new"}`, { replace: true })}
        onDelete={deleteProposal}
        onDeleteRawAudio={() => void command("delete_raw_audio")}
        onDiscard={() => void command("cancel")}
        onResolveConflict={resolveConflict}
        onSave={() => void command("commit")}
        onUpdateTitle={updateProposal}
      />
    );
  }

  return (
    <RecordingSurface
      accurateSttProvider={brainDumpProviders?.accurate_stt ?? null}
      reconcilerProvider={brainDumpProviders?.reconciler ?? null}
      consentWithdrawnMidCapture={consentWithdrawnMidCapture}
      externalProcessingAllowed={externalProcessingAllowed}
      error={error}
      isNewRecording={isNewRecording}
      isStarting={isStarting}
      languageMode={languageMode}
      lastTranscript={lastTranscript}
      locallyStartedOperationId={localCaptureOperationIdRef.current}
      operation={operation}
      proposals={activeProposals}
      providersReady={providersReady}
      providersFailed={providersFailed}
      onCancel={() => void command("cancel")}
      onExternalProcessingAllowedChange={setExternalProcessingAllowed}
      onFinish={() => void command("finish")}
      onLanguageModeChange={setLanguageMode}
      onPause={() => void command("pause")}
      onResume={() => void command("resume")}
      onRetryProviders={() => void providersQuery.refetch()}
      onStart={() => void startRecording()}
      onWithdrawConsent={() => void command("withdraw_consent")}
      onVocabularyTextChange={setVocabularyText}
      vocabularyText={vocabularyText}
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
  const availableActions = new Set(operation.available_recovery_actions ?? []);
  const retryable = availableActions.has("retry");
  const providerRuns = operation.provider_runs ?? [];
  const providerRole = providerRuns[providerRuns.length - 1]?.role;
  const isReconcilerStage = providerRole === "reconciler";
  const stageName = isReconcilerStage ? "Task reconciliation" : "Accurate transcription";
  const retryLabel = isReconcilerStage ? "Retry task reconciliation" : "Retry accurate transcription";
  const retryFallback = isReconcilerStage
    ? "The task reconciler can be retried from the accurate transcript."
    : "The transcription provider can be retried from the sealed recording.";
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-base px-4 text-slate-900">
      <section role="alert" className="w-full max-w-md rounded-2xl border border-amber-200 bg-white p-6 shadow-floating">
        <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-amber-700">Voice brain dump</p>
        <h1 className="mt-2 text-xl font-semibold">{`${stageName} ${retryable ? "paused" : "failed"}`}</h1>
        <p className="mt-2 text-sm text-slate-600">
          {providerError ?? (retryable ? retryFallback : "The recording could not be processed accurately.")}
        </p>
        {error ? <p className="mt-3 text-sm text-rose-700">{error}</p> : null}
        <div className="mt-5 flex flex-col gap-2">
          {retryable ? <button type="button" className="h-11 rounded-xl bg-brand-primary px-4 text-sm font-semibold text-white" onClick={onRetry}>{retryLabel}</button> : null}
          {availableActions.has("review_provisional") ? <button type="button" className="h-11 rounded-xl border border-slate-200 px-4 text-sm font-medium text-slate-700" onClick={onReview}>Review provisional tasks</button> : null}
          <button type="button" className="h-11 rounded-xl border border-rose-200 px-4 text-sm font-medium text-rose-700" onClick={onDelete}>Delete recording</button>
        </div>
      </section>
    </div>
  );
}

function RecordingSurface({
  accurateSttProvider,
  reconcilerProvider,
  consentWithdrawnMidCapture,
  externalProcessingAllowed,
  error,
  isNewRecording,
  isStarting,
  languageMode,
  lastTranscript,
  locallyStartedOperationId,
  operation,
  proposals,
  providersReady,
  providersFailed,
  onCancel,
  onExternalProcessingAllowedChange,
  onFinish,
  onLanguageModeChange,
  onPause,
  onResume,
  onRetryProviders,
  onStart,
  onWithdrawConsent,
  onVocabularyTextChange,
  vocabularyText
}: {
  accurateSttProvider: string | null;
  reconcilerProvider: string | null;
  consentWithdrawnMidCapture: boolean;
  externalProcessingAllowed: boolean;
  error: string | null;
  isNewRecording: boolean;
  isStarting: boolean;
  languageMode: LanguageMode;
  lastTranscript: string;
  locallyStartedOperationId: string | null;
  operation: BrainDumpOperationResponse | null;
  proposals: BrainDumpProposal[];
  providersReady: boolean;
  providersFailed: boolean;
  onCancel: () => void;
  onExternalProcessingAllowedChange: (allowed: boolean) => void;
  onFinish: () => void;
  onLanguageModeChange: (mode: LanguageMode) => void;
  onPause: () => void;
  onResume: () => void;
  onRetryProviders: () => void;
  onStart: () => void;
  onWithdrawConsent: () => void;
  onVocabularyTextChange: (value: string) => void;
  vocabularyText: string;
}): JSX.Element {
  const count = proposals.length;
  // A stopped recorder must never keep showing Recording/Paused: consent
  // withdrawal already stopped local capture (see `stopMediaRecorder` in
  // `command()`), even though the server may leave `status` unchanged for a
  // mid-recording withdrawal (see ADR-0002 -- withdrawal is not cancel).
  const captureStoppedByConsent = Boolean(
    operation &&
      locallyStartedOperationId !== operation.id &&
      !operation.consent.external_processing_allowed &&
      (operation.status === "recording" || operation.status === "paused")
  );
  const captureStopped = consentWithdrawnMidCapture || captureStoppedByConsent;
  const isPaused = operation?.status === "paused" && !captureStopped;
  const isRecording = operation?.status === "recording" && !captureStopped;
  // Name the actual configured vendors so the user approves exactly the
  // providers their audio and transcript will reach (FR-012). The consent
  // surface is only rendered once discovery has resolved (`providersReady`),
  // so there is no generic no-vendor fallback here: every external role that is
  // configured is named, and audio never egresses to an unnamed provider.
  const cloudConsentProviderParts = [
    accurateSttProvider ? `speech-to-text by ${accurateSttProvider}` : null,
    reconcilerProvider ? `task extraction by ${reconcilerProvider}` : null
  ].filter((part): part is string => part !== null);
  const cloudConsentDescription = `Allow secure cloud processing: ${cloudConsentProviderParts.join(", ")}. Audio is not sent without this consent.`;
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
              {captureStopped ? "Cloud processing stopped" : isPaused ? "Paused" : isRecording ? "Recording" : "Ready"}
            </span>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 sm:px-6" aria-live="polite">
            {error ? <div role="alert" className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div> : null}
            {!operation && isNewRecording ? (
              <div className="mb-4 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
                <label className="grid gap-1 text-slate-700">
                  <span className="text-xs font-semibold">Speech languages</span>
                  <select aria-label="Speech languages" className="h-10 rounded-lg border border-slate-300 bg-white px-3" value={languageMode} onChange={(event) => onLanguageModeChange(event.target.value as LanguageMode)}>
                    <option value="ru-en">Russian + English</option>
                    <option value="ru">Russian</option>
                    <option value="en">English</option>
                  </select>
                </label>
                <label className="grid gap-1 text-slate-700">
                  <span className="text-xs font-semibold">Key terms</span>
                  <input aria-label="Voice key terms" className="h-10 rounded-lg border border-slate-300 bg-white px-3" value={vocabularyText} onChange={(event) => onVocabularyTextChange(event.target.value)} />
                </label>
                {providersReady ? (
                  <label className="flex items-start gap-2 text-xs text-slate-600">
                    <input aria-label="Allow secure cloud transcription" className="mt-0.5" type="checkbox" checked={externalProcessingAllowed} onChange={(event) => onExternalProcessingAllowedChange(event.target.checked)} />
                    <span>{cloudConsentDescription}</span>
                  </label>
                ) : providersFailed ? (
                  <div role="alert" className="grid gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    <span>Could not load the configured voice providers, so recording is unavailable. No audio leaves this device until the vendors are confirmed.</span>
                    <button type="button" className="justify-self-start rounded-md border border-amber-300 bg-white px-2.5 py-1 font-semibold text-amber-800" onClick={onRetryProviders}>
                      Retry
                    </button>
                  </div>
                ) : (
                  <p role="status" className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
                    Checking configured providers…
                  </p>
                )}
              </div>
            ) : null}
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-600">Provisional · {count}</div>
            <div className="flex flex-col gap-2">
              {proposals.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} />)}
              {proposals.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 p-4 text-sm text-slate-500">Press Record and speak. Provisional Inbox tasks will grow here while you talk.</p> : null}
            </div>
          </div>

          <footer className="shrink-0 border-t border-slate-100 bg-slate-50/80 px-4 py-3 sm:px-5">
            <div className="flex flex-wrap items-center gap-2 gap-y-2 sm:gap-3">
              <div className="relative h-10 w-10 shrink-0" aria-label="Voice level">
                <span className={`absolute inset-0 rounded-full bg-sky-200/70 ${isRecording ? "animate-[bbPulse_1.8s_cubic-bezier(.22,1,.36,1)_infinite]" : ""}`} />
                <div className="absolute inset-0 flex items-center justify-center rounded-full bg-brand-primary text-white">
                  <Mic className="h-4 w-4" aria-hidden />
                </div>
              </div>
              <details className="min-w-0 flex-1 basis-full text-[13px] leading-normal text-slate-500 sm:basis-auto">
                <summary className="cursor-pointer list-none overflow-hidden text-ellipsis whitespace-nowrap">{lastTranscript || "Transcript stays collapsed while tasks remain primary"}</summary>
                <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-700">Browser preview · provisional</span>
                <p className="mt-2 whitespace-pre-wrap rounded-lg bg-white p-2 text-xs text-slate-500">{lastTranscript || "No transcript yet."}</p>
              </details>
              {!operation ? (
                <button type="button" className="inline-flex h-10 items-center gap-2 rounded-lg bg-brand-primary px-4 text-sm font-semibold text-white shadow-soft disabled:cursor-not-allowed disabled:opacity-50" disabled={isStarting || (isNewRecording && !providersReady)} onClick={onStart}>
                  <Mic className="h-4 w-4" aria-hidden />
                  Record
                </button>
              ) : captureStopped ? (
                <span className="inline-flex h-10 items-center rounded-lg border border-amber-200 bg-amber-50 px-4 text-sm font-medium text-amber-800">
                  Cloud processing stopped
                </span>
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
              <button type="button" className="inline-flex h-10 items-center rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700" onClick={onCancel}>Discard</button>
              {operation?.consent.external_processing_allowed ? (
                <button type="button" className="inline-flex h-10 items-center rounded-lg border border-amber-200 bg-white px-4 text-sm font-medium text-amber-800" onClick={onWithdrawConsent}>
                  Stop cloud processing
                </button>
              ) : null}
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
  committable,
  error,
  hasUnresolvedConflicts,
  isSaving,
  rawAudioExpiresAt,
  rawAudioPresent,
  proposals,
  segmentsById,
  reconciliationQuality,
  onBack,
  onDelete,
  onDeleteRawAudio,
  onDiscard,
  onResolveConflict,
  onSave,
  onUpdateTitle
}: {
  committable: boolean;
  error: string | null;
  hasUnresolvedConflicts: boolean;
  isSaving: boolean;
  rawAudioExpiresAt?: string | null;
  rawAudioPresent: boolean;
  proposals: BrainDumpProposal[];
  segmentsById: Map<string, BrainDumpOperationResponse["segments"][number]>;
  reconciliationQuality: "none" | "provisional_only" | "accurate" | "conflicted";
  onBack: () => void;
  onDelete: (proposal: BrainDumpProposal) => void;
  onDeleteRawAudio: () => void;
  onDiscard: () => void;
  onResolveConflict: (proposal: BrainDumpProposal, resolution: "keep" | "accept") => void;
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
        {!committable ? (
          <div role="status" className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            These are {reconciliationQuality === "provisional_only" ? "provisional" : "not yet reconciled"} drafts. They can be edited or discarded, but cannot be saved to Inbox until the server confirms reconciliation.
          </div>
        ) : null}
        {rawAudioPresent ? (
          <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
            <span>Raw audio is retained until {rawAudioExpiresAt ? new Date(rawAudioExpiresAt).toLocaleString() : "its privacy expiry"}.</span>
            <button type="button" className="shrink-0 font-semibold text-rose-700" onClick={onDeleteRawAudio}>Delete audio now</button>
          </div>
        ) : null}
        <div className="flex flex-col gap-2.5">
          {proposals.map((proposal) => (
            <article key={proposal.id} className="rounded-[14px] border border-slate-200 bg-white px-3.5 py-3 shadow-soft">
              <div className="flex items-start gap-2.5">
                <span className="mt-1 text-xs font-semibold text-slate-500">#{proposal.ordinal}</span>
                <div className="min-w-0 flex-1">
                  <label className="sr-only" htmlFor={`proposal-title-${proposal.id}`}>Task title #{proposal.ordinal}</label>
                  <input key={`${proposal.id}-${proposal.revision}`} id={`proposal-title-${proposal.id}`} defaultValue={proposal.title} onBlur={(event) => void onUpdateTitle(proposal, event.currentTarget.value)} className="w-full border-0 border-b-[1.5px] border-sky-200 bg-transparent pb-1 text-[15px] font-medium text-slate-900 outline-none" />
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
                  <ProposalCitations segmentIds={proposal.source_segment_ids} segmentsById={segmentsById} />
                  {(proposal.conflicts ?? []).map((conflict) => (
                    <div key={`${conflict.field}-${conflict.suggested_value ?? ""}`} className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                      <div className="font-semibold">Conflict: {conflict.field}</div>
                      <div>Mine: {conflict.current_value ?? "—"}</div>
                      <div>Suggestion: {conflict.suggested_value ?? "—"}</div>
                      <div className="mt-2 flex gap-2">
                        <button type="button" className="rounded-md border border-amber-300 bg-white px-2 py-1 font-semibold" onClick={() => onResolveConflict(proposal, "keep")}>Keep mine</button>
                        <button type="button" className="rounded-md bg-amber-700 px-2 py-1 font-semibold text-white disabled:opacity-50" disabled={!conflict.suggested_value} onClick={() => onResolveConflict(proposal, "accept")}>Use suggestion</button>
                      </div>
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
        <button type="button" className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-brand-primary text-[15px] font-semibold text-white shadow-glow disabled:cursor-not-allowed disabled:opacity-50" disabled={!committable || hasUnresolvedConflicts || isSaving} onClick={onSave}>
          <Inbox className="h-4 w-4" aria-hidden />
          {isSaving ? "Confirming…" : `Confirm ${proposals.length} ${proposals.length === 1 ? "addition" : "additions"}`}
        </button>
      </footer>
    </div>
  );
}

// Resolves a proposal's cited source segment IDs to the exact utterance text on
// the review surface so each proposal visibly cites what it came from
// (US1 / FR-002). Single and multiple citations render one quoted utterance
// each; a missing or stale ID (e.g. superseded during reconciliation) degrades
// to a placeholder rather than crashing the review screen.
function ProposalCitations({
  segmentIds,
  segmentsById
}: {
  segmentIds: string[];
  segmentsById: Map<string, BrainDumpOperationResponse["segments"][number]>;
}): JSX.Element | null {
  const uniqueIds = Array.from(new Set(segmentIds));
  if (uniqueIds.length === 0) {
    return null;
  }
  return (
    <section aria-label="Cited utterances" className="mt-2 rounded-lg border border-slate-100 bg-slate-50 px-2.5 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-400">Cited from what you said</p>
      <ul className="mt-1 flex flex-col gap-1">
        {uniqueIds.map((id) => {
          const segment = segmentsById.get(id);
          return (
            <li key={id} className="text-xs leading-snug text-slate-600">
              {segment ? (
                <span>“{segment.text}”</span>
              ) : (
                <span className="italic text-slate-400">Source utterance no longer available</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
