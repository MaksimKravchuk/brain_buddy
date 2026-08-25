import { useCallback, useEffect, useRef, useState } from "react";

import { apiClient, ApiError } from "../../api/client";

interface Options {
  enabled: boolean;
  draft: string;
  projectId: string | null;
  smartAddActive: boolean;
}

interface Result {
  provider: string | null;
  consent: boolean;
  setConsent: (allowed: boolean) => void;
  candidates: string[];
  requestId: string | null;
  loading: boolean;
  error: string | null;
  dismiss: (nextDraft?: string) => void;
  recordAcceptance: (requestId: string, rank: number) => Promise<void>;
}

const eligible = (draft: string, projectId: string | null): boolean => {
  const trimmed = draft.trim();
  if (/[\r\n]/.test(draft) || trimmed.length > 500) return false;
  const words = trimmed.split(/\s+/u).filter(Boolean);
  return projectId ? words.length >= 1 : words.length >= 3;
};

const unavailableMessage = (caught: unknown): string => {
  const correlation = caught instanceof ApiError ? caught.correlationId : undefined;
  return correlation ? `Suggestions unavailable. Reference ${correlation}.` : "Suggestions unavailable.";
};

export function useTaskTitleAutocomplete({ enabled, draft, projectId, smartAddActive }: Options): Result {
  const [provider, setProvider] = useState<string | null>(null);
  const [consent, setConsentState] = useState(false);
  const [candidates, setCandidates] = useState<string[]>([]);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dismissedSnapshot, setDismissedSnapshot] = useState<string | null>(null);
  const sequence = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    sequence.current += 1;
    setCandidates([]);
    setRequestId(null);
    setError(null);
    if (!enabled) {
      setProvider(null);
      setConsentState(false);
      return () => controller.abort();
    }
    void apiClient.getTitleCompletionProvider(controller.signal).then(
      ({ provider: discovered }) => {
        if (!controller.signal.aborted) {
          setProvider(discovered);
          setConsentState(false);
          setError(discovered ? null : "Suggestions unavailable.");
        }
      },
      (caught: unknown) => {
        if (!controller.signal.aborted) {
          setProvider(null);
          setConsentState(false);
          setError(unavailableMessage(caught));
        }
      }
    );
    return () => controller.abort();
  }, [enabled]);

  useEffect(() => {
    const current = ++sequence.current;
    const snapshot = `${draft}\u0000${projectId ?? ""}`;
    if (dismissedSnapshot !== null && dismissedSnapshot !== snapshot) {
      setDismissedSnapshot(null);
    }
    setCandidates([]);
    setRequestId(null);
    setLoading(false);
    if (provider) setError(null);
    if (
      !enabled ||
      !provider ||
      !consent ||
      smartAddActive ||
      dismissedSnapshot === snapshot ||
      !eligible(draft, projectId)
    ) {
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      void apiClient
        .generateTitleCompletions(
          {
            draft,
            project_id: projectId,
            consent: { external_processing_allowed: true, provider }
          },
          controller.signal
        )
        .then((response) => {
          if (controller.signal.aborted || sequence.current !== current) return;
          setCandidates(response.candidates);
          setRequestId(response.request_id);
        })
        .catch((caught: unknown) => {
          if (controller.signal.aborted || sequence.current !== current) return;
          setError(unavailableMessage(caught));
        })
        .finally(() => {
          if (!controller.signal.aborted && sequence.current === current) setLoading(false);
        });
    }, 350);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [consent, dismissedSnapshot, draft, enabled, projectId, provider, smartAddActive]);

  const setConsent = useCallback((allowed: boolean) => {
    setConsentState(allowed);
    if (!allowed) {
      setCandidates([]);
      setRequestId(null);
    }
  }, []);

  const dismiss = useCallback((nextDraft?: string) => {
    setDismissedSnapshot(`${nextDraft ?? draft}\u0000${projectId ?? ""}`);
    setCandidates([]);
    setRequestId(null);
  }, [draft, projectId]);

  const recordAcceptance = useCallback(async (acceptedRequestId: string, rank: number) => {
    try {
      await apiClient.recordTitleCompletionAccepted(acceptedRequestId, rank);
    } catch {
      // Best effort only: telemetry must never affect capture.
    }
  }, []);

  return { provider, consent, setConsent, candidates, requestId, loading, error, dismiss, recordAcceptance };
}
