/**
 * Orchestrates the capture side of a brain dump: providers → consent →
 * start operation → record (pause/resume mirrored to the server) → stop →
 * chunk upload → seal. The processing/review side lives with the
 * [operationId] screen.
 */

import { useQuery } from "@tanstack/react-query";
import { useAudioRecorder, useAudioRecorderState } from "expo-audio";
import { useCallback, useRef, useState } from "react";

import { ApiError } from "@/api/client";
import type { BrainDumpOperationResponse } from "@/api/types";
import { useApi, useSession } from "@/auth/SessionProvider";
import { applyOperation, buildConsent } from "@/braindump/machine";
import { openFileReader } from "@/braindump/fileReader";
import { manifestHash } from "@/braindump/manifest";
import {
  BRAIN_DUMP_RECORDING_OPTIONS,
  prepareAudioSession,
  recordingMimeType,
  releaseAudioSession,
} from "@/braindump/recorder";
import { uploadChunks } from "@/braindump/uploader";
import { newIdempotencyKey } from "@/utils/ids";

export type CapturePhase =
  | { kind: "idle" }
  | { kind: "unavailable"; reason: "flag-off" | "no-provider" | "mic-denied" }
  | { kind: "starting" }
  | { kind: "recording"; paused: boolean }
  | { kind: "uploading"; uploaded: number; total: number }
  | { kind: "sealing" }
  | { kind: "sealed"; operationId: string }
  | { kind: "error"; error: unknown; recoverable: boolean };

export function useBrainDumpCapture() {
  const api = useApi();
  const { voiceEnabled } = useSession();
  const recorder = useAudioRecorder(BRAIN_DUMP_RECORDING_OPTIONS);
  const recorderState = useAudioRecorderState(recorder, 100);

  const [phase, setPhase] = useState<CapturePhase>({ kind: "idle" });
  const operationRef = useRef<BrainDumpOperationResponse | null>(null);

  const providersQuery = useQuery({
    queryKey: ["brain-dump", "providers"],
    queryFn: ({ signal }) => api.getBrainDumpProviders(signal),
    enabled: voiceEnabled,
    staleTime: 60_000,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status < 500) {
        return false;
      }
      return failureCount < 1;
    },
  });

  const providers = providersQuery.data ?? null;
  const consent = providers ? buildConsent(providers, ["ru", "en"]) : null;

  const remember = (operation: BrainDumpOperationResponse) => {
    operationRef.current = applyOperation(operationRef.current, operation);
    return operationRef.current;
  };

  const start = useCallback(async () => {
    if (!voiceEnabled) {
      setPhase({ kind: "unavailable", reason: "flag-off" });
      return;
    }
    if (!consent) {
      setPhase({ kind: "unavailable", reason: "no-provider" });
      return;
    }
    setPhase({ kind: "starting" });
    try {
      const permitted = await prepareAudioSession();
      if (!permitted) {
        setPhase({ kind: "unavailable", reason: "mic-denied" });
        return;
      }
      const operation = await api.startBrainDump(consent, newIdempotencyKey());
      remember(operation);
      await recorder.prepareToRecordAsync();
      recorder.record();
      setPhase({ kind: "recording", paused: false });
    } catch (error) {
      setPhase({ kind: "error", error, recoverable: true });
    }
  }, [api, consent, recorder, voiceEnabled]);

  const pause = useCallback(async () => {
    const operation = operationRef.current;
    if (!operation) {
      return;
    }
    recorder.pause();
    setPhase({ kind: "recording", paused: true });
    try {
      remember(await api.commandBrainDump(operation.id, "pause", operation.revision, newIdempotencyKey()));
    } catch {
      // Server pause is advisory for the capture UX; upload still validates.
    }
  }, [api, recorder]);

  const resume = useCallback(async () => {
    const operation = operationRef.current;
    if (!operation) {
      return;
    }
    recorder.record();
    setPhase({ kind: "recording", paused: false });
    try {
      remember(await api.commandBrainDump(operation.id, "resume", operation.revision, newIdempotencyKey()));
    } catch {
      // Same as pause: best-effort mirror.
    }
  }, [api, recorder]);

  /** Stop recording, upload every chunk, seal — resolves the operation id. */
  const stopAndSeal = useCallback(async (): Promise<string | null> => {
    const operation = operationRef.current;
    if (!operation) {
      return null;
    }
    try {
      await recorder.stop();
      await releaseAudioSession();
      const uri = recorder.uri;
      if (!uri) {
        throw new Error("The recording did not produce a file.");
      }

      setPhase({ kind: "uploading", uploaded: 0, total: 0 });
      const { reader, dispose, deleteFile } = openFileReader(uri);
      let sealed: BrainDumpOperationResponse;
      try {
        const result = await uploadChunks({
          reader,
          mimeType: recordingMimeType(),
          put: async (chunkNumber, bytes, sha, mime) =>
            remember(await api.uploadBrainDumpAudio(operation.id, chunkNumber, bytes, sha, mime)),
          onProgress: (uploaded, total) => setPhase({ kind: "uploading", uploaded, total }),
        });

        setPhase({ kind: "sealing" });
        const latest = result.lastOperation;
        sealed = await api.sealBrainDump(
          operation.id,
          {
            expected_revision: latest.revision,
            expected_chunks: result.expectedChunks,
            manifest_hash: manifestHash(latest.audio_chunks ?? [], result.expectedChunks),
          },
          newIdempotencyKey(),
        );
        remember(sealed);
      } finally {
        dispose();
      }
      deleteFile();
      setPhase({ kind: "sealed", operationId: operation.id });
      return operation.id;
    } catch (error) {
      setPhase({ kind: "error", error, recoverable: true });
      return null;
    }
  }, [api, recorder]);

  /** Cancel is idempotent server-side and deletes uploaded audio. */
  const cancel = useCallback(async () => {
    const operation = operationRef.current;
    try {
      if (recorderState.isRecording) {
        await recorder.stop();
      }
    } catch {
      // The recorder may already be stopped.
    }
    await releaseAudioSession();
    if (operation) {
      try {
        await api.commandBrainDump(operation.id, "cancel", operation.revision, newIdempotencyKey());
      } catch {
        // Cancel must never trap the user in the flow.
      }
    }
    operationRef.current = null;
    setPhase({ kind: "idle" });
  }, [api, recorder, recorderState.isRecording]);

  /** Retry the upload+seal after a failure (identical re-PUTs are no-ops). */
  const retryUpload = useCallback(() => stopAndSeal(), [stopAndSeal]);

  return {
    phase,
    providersLoading: providersQuery.isLoading,
    providersError: providersQuery.isError ? providersQuery.error : null,
    providers,
    consentAvailable: consent !== null,
    durationMillis: recorderState.durationMillis,
    metering: recorderState.metering,
    start,
    pause,
    resume,
    stopAndSeal,
    retryUpload,
    cancel,
  };
}
