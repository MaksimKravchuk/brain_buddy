import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";

import { BrainDumpRoute } from "./BrainDumpRoute";

interface FakeRecognitionInstance {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
  onresult: ((event: { results: Array<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
}

let recognition: FakeRecognitionInstance | null = null;
let recognitions: FakeRecognitionInstance[] = [];
let micTrackStop: ReturnType<typeof vi.fn>;
const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" }
    })
  );
}

function operation(overrides: Record<string, unknown> = {}) {
  return {
    id: "brain_dump_1",
    owner_id: "user_1",
    kind: "voice_brain_dump",
    status: "recording",
    consent: {
      microphone: true,
      external_processing_allowed: false,
      provider: null,
      recorded_at: "2026-07-16T00:00:00Z"
    },
    segments: [],
    proposals: [],
    committed_task_ids: [],
    created_at: "2026-07-16T00:00:00Z",
    updated_at: "2026-07-16T00:00:00Z",
    revision: 1,
    ...overrides
  };
}

function consentedOperation(overrides: Record<string, unknown> = {}) {
  return operation({
    consent: {
      microphone: true,
      external_processing_allowed: true,
      provider: "openai",
      recorded_at: "2026-07-16T00:00:00Z"
    },
    committable: true,
    reconciliation_quality: "accurate",
    ...overrides
  });
}

function proposal(id: string, ordinal: number, title: string, extras: Record<string, unknown> = {}) {
  return {
    id,
    ordinal,
    title,
    status: "provisional",
    source_segment_ids: ["segment_1"],
    deleted: false,
    user_edited: false,
    revision: 1,
    ...extras
  };
}

function conflict(field: string, currentValue: string, suggestedValue: string) {
  return {
    field,
    current_value: currentValue,
    suggested_value: suggestedValue,
    producer: "reconciler",
    source_segment_ids: ["segment_accurate"]
  };
}

function TaskListProbe(): JSX.Element {
  const routeParams = useParams();
  return <div>{`Task list route: ${routeParams.state ?? "unknown"}`}</div>;
}

// Provider discovery is now a fail-closed prerequisite for consent + Record, so
// by default we pre-seed the (staleTime: Infinity) providers cache to a resolved
// vendor set — no network round-trip, discovery "ready", consent surfaced. Tests
// exercising the loading/failed/retry states pass `seedProviders: null` to leave
// discovery unresolved.
function renderBrainDump(
  initialEntry = "/brain-dump/new",
  queryClient = new QueryClient(),
  allowExternalProcessing = true,
  seedProviders: { accurate_stt: string | null; reconciler: string | null } | null = {
    accurate_stt: "openai",
    reconciler: "openai"
  }
) {
  if (seedProviders && !queryClient.getQueryData(["brain-dump-providers"])) {
    queryClient.setQueryData(["brain-dump-providers"], seedProviders);
  }
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <LocationProbe />
        <Routes>
          <Route path="/brain-dump/:operationId" element={<BrainDumpRoute />} />
          <Route path="/brain-dump/:operationId/review" element={<BrainDumpRoute />} />
          <Route path="/tasks/:state" element={<TaskListProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  if (allowExternalProcessing) {
    const consent = screen.queryByRole("checkbox", {
      name: "Allow secure cloud transcription"
    });
    if (consent) {
      fireEvent.click(consent);
    }
  }
  return rendered;
}

function LocationProbe(): JSX.Element {
  const location = useLocation();
  return <output aria-label="current route">{location.pathname}</output>;
}

function emitSpeech(text: string, isFinal = true) {
  if (!recognition?.onresult) {
    throw new Error("recognition has not started");
  }
  recognition.onresult({ results: [{ 0: { transcript: text }, isFinal }] });
}

// The fresh-recording screen fetches the configured voice providers (static
// server config) to seed consent. That read is orthogonal to the operation
// lifecycle, so call-count assertions look only at operation-endpoint fetches.
function operationFetchCalls() {
  return fetchMock.mock.calls.filter(([input]) => !String(input).includes("/brain-dump-providers"));
}

describe("BrainDumpRoute", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    recognition = null;
    recognitions = [];
    Object.defineProperty(window.navigator, "language", { configurable: true, value: "en-US" });
    function FakeRecognition() {
      recognition = {
        continuous: false,
        interimResults: false,
        lang: "",
        start: vi.fn(),
        stop: vi.fn(),
        onresult: null,
        onerror: null
      };
      recognitions.push(recognition);
      return recognition;
    }
    vi.stubGlobal("SpeechRecognition", FakeRecognition);
    function FakeMediaRecorder() {
      return {
        state: "inactive",
        ondataavailable: null,
        onstop: null,
        start(this: { state: string }) {
          this.state = "recording";
        },
        pause(this: { state: string }) {
          this.state = "paused";
        },
        resume(this: { state: string }) {
          this.state = "recording";
        },
        stop(this: { state: string; onstop: ((event: Event) => void) | null }) {
          this.state = "inactive";
          this.onstop?.(new Event("stop"));
        }
      };
    }
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    micTrackStop = vi.fn();
    Object.defineProperty(window.navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: micTrackStop }] }) }
    });
  });

  it("records through browser microphone and continuously renders provisional numbered inbox tasks", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(consentedOperation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        return jsonResponse(
          operation({
            revision: 2,
            proposals: [
              proposal("proposal_1", 1, "Renew car insurance"),
              proposal("proposal_2", 2, "Reply to Anna about the offsite", { status: "wording_changing" })
            ]
          })
        );
      }
      if (url.endsWith("/brain_dump_1/pause")) {
        return jsonResponse(operation({ status: "paused", revision: 3 }));
      }
      if (url.endsWith("/brain_dump_1/resume")) {
        return jsonResponse(operation({ status: "recording", revision: 4 }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(micTrackStop).not.toHaveBeenCalled();
    expect(recognition?.start).toHaveBeenCalledTimes(1);

    act(() => emitSpeech("Renew car insurance. Reply to Anna about the offsite."));
    expect(await screen.findByText("2 tasks captured")).toBeInTheDocument();
    expect(screen.getByText("Provisional · 2")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("Renew car insurance")).toBeInTheDocument();
    expect(screen.getByText("Wording still changing")).toBeInTheDocument();
    expect(screen.getByText("Nothing is saved until review"));

    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(await screen.findByRole("button", { name: "Resume" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(await screen.findByRole("button", { name: "Pause" })).toBeEnabled();
  });

  it("declares RU plus EN hints and keeps browser recognition visibly provisional", async () => {
    let startBody: unknown;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        startBody = JSON.parse(String(init.body));
        return jsonResponse(
          operation({
            consent: {
              microphone: true,
              external_processing_allowed: true,
              provider: "openai",
              language_hints: ["ru", "en"],
              vocabulary: ["BrainBuddy", "production smoke"],
              recorded_at: "2026-07-16T00:00:00Z"
            }
          }),
          201
        );
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Speech languages" }), "ru-en");
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(startBody).toEqual({
      consent: {
        microphone: true,
        external_processing_allowed: true,
        // Provider discovery is a fail-closed prerequisite now, so the consent
        // payload carries the discovered vendor names (never a hardcoded label).
        provider: "openai",
        providers: ["openai"],
        language_hints: ["ru", "en"],
        vocabulary: ["BrainBuddy", "production smoke"]
      }
    });
    expect(recognition?.lang).toBe("ru-RU");
    expect(screen.getByText("Browser preview · provisional")).toBeInTheDocument();
  });

  it("names each configured provider in consent for a mixed-vendor pipeline", async () => {
    const queryClient = new QueryClient();
    // Seed the providers cache (the hook's staleTime is Infinity, so no fetch
    // fires) to deterministically exercise the mixed-vendor consent the
    // /brain-dump-providers endpoint drives: Deepgram STT + OpenAI reconciler.
    queryClient.setQueryData(["brain-dump-providers"], { accurate_stt: "deepgram", reconciler: "openai" });
    let startBody: { consent: { provider: string | null; providers: string[] } } | undefined;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-providers")) {
        return jsonResponse({ accurate_stt: "deepgram", reconciler: "openai" });
      }
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        startBody = JSON.parse(String(init.body));
        return jsonResponse(operation(), 201);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/new", queryClient);
    // FR-012: the recording screen displays the actual configured vendors so
    // the user approves exactly the providers their audio and transcript reach.
    expect(
      await screen.findByText(
        "Allow secure cloud processing: speech-to-text by deepgram, task extraction by openai. Audio is not sent without this consent."
      )
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(startBody?.consent.provider).toBe("deepgram");
    expect(startBody?.consent.providers).toEqual(["deepgram", "openai"]);
  });

  it("gates consent and Record while provider discovery is still loading, never touching the mic", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-providers")) {
        // Never resolves: discovery is pending, so consent must not be grantable
        // and no audio capture may begin (fail-closed privacy boundary).
        return new Promise<Response>(() => {});
      }
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/new", new QueryClient(), true, null);

    expect(screen.getByText("Checking configured providers…")).toBeInTheDocument();
    // No consent checkbox and no enabled Record while providers are unknown.
    expect(screen.queryByRole("checkbox", { name: "Allow secure cloud transcription" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record" })).toBeDisabled();
    // The generic no-vendor consent copy the degraded path used to show is gone.
    expect(
      screen.queryByText("Allow secure cloud transcription after Stop. Audio is not sent without this consent.")
    ).not.toBeInTheDocument();

    // Privacy boundary: nothing about capture may have started.
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(recognition).toBeNull();
    expect(operationFetchCalls()).toHaveLength(0);
  });

  it("fails closed with a retry affordance when provider discovery errors, blocking any upload", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-providers")) {
        return jsonResponse({ detail: "providers unavailable" }, 503);
      }
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/new", new QueryClient(), true, null);

    expect(
      await screen.findByText(/Could not load the configured voice providers/i)
    ).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Allow secure cloud transcription" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();

    // Even trying to record must not reach the microphone, recorder, or upload.
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(recognition).toBeNull();
    expect(operationFetchCalls()).toHaveLength(0);
  });

  it("recovers and enables named-vendor consent after a discovery retry succeeds", async () => {
    let providerAttempts = 0;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-providers")) {
        providerAttempts += 1;
        if (providerAttempts === 1) {
          return jsonResponse({ detail: "providers unavailable" }, 503);
        }
        return jsonResponse({ accurate_stt: "deepgram", reconciler: "openai" });
      }
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/new", new QueryClient(), false, null);

    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));

    // FR-012: after recovery the consent names the actual discovered vendors.
    expect(
      await screen.findByText(
        "Allow secure cloud processing: speech-to-text by deepgram, task extraction by openai. Audio is not sent without this consent."
      )
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Allow secure cloud transcription" })).toBeInTheDocument();
  });

  it("ignores stale transcript responses that arrive after a newer pause", async () => {
    let resolveTranscript: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        return new Promise<Response>((resolve) => {
          resolveTranscript = resolve;
        });
      }
      if (url.endsWith("/brain_dump_1/pause")) {
        return jsonResponse(operation({ status: "paused", revision: 3, proposals: [proposal("proposal_1", 1, "Renew car insurance")] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    act(() => emitSpeech("Renew car insurance"));
    await waitFor(() => expect(resolveTranscript).toBeDefined());

    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(await screen.findByRole("button", { name: "Resume" })).toBeEnabled();

    await act(async () => {
      resolveTranscript?.(await jsonResponse(operation({ revision: 2, proposals: [proposal("proposal_1", 1, "Renew car insurance")] })));
    });

    expect(screen.getByRole("button", { name: "Resume" })).toBeEnabled();
    expect(screen.queryByText("Recording")).not.toBeInTheDocument();
  });

  it("replaces an interim speech result with the cumulative final transcript sequence", async () => {
    const uploaded: Array<{ sequence: number; text: string; stability: string }> = [];
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        const body = JSON.parse(String(init?.body));
        uploaded.push(body.segments[0]);
        return jsonResponse(
          operation({
            revision: uploaded.length + 1,
            segments: [
              {
                id: "segment_1",
                sequence: 1,
                text: body.segments[0].text,
                stability: body.segments[0].stability,
                created_at: "2026-07-16T00:00:00Z"
              }
            ],
            proposals:
              body.segments[0].stability === "interim"
                ? [proposal("proposal_1", 1, "Buy oat milk", { status: "wording_changing" })]
                : [proposal("proposal_1", 1, "Buy oat milk"), proposal("proposal_2", 2, "Call dentist")]
          })
        );
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    act(() => emitSpeech("buy oat milk", false));
    expect(await screen.findByRole("article", { name: "Draft task 1: Buy oat milk" })).toBeInTheDocument();

    act(() => emitSpeech("buy oat milk. call dentist", true));

    await waitFor(() =>
      expect(uploaded.map((segment) => [segment.sequence, segment.stability, segment.text])).toEqual([
        [1, "interim", "buy oat milk"],
        [1, "stable", "buy oat milk. call dentist"]
      ])
    );
    expect(await screen.findByRole("article", { name: "Draft task 1: Buy oat milk" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Draft task 2: Call dentist" })).toBeInTheDocument();
    expect(screen.queryByText("Buy oat milk buy oat milk")).not.toBeInTheDocument();
  });

  it("replaces the new recording route with the created operation route", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    await waitFor(() => expect(screen.getByLabelText("current route")).toHaveTextContent("/brain-dump/brain_dump_1"));
  });

  it("records original audio when browser speech recognition is unavailable", async () => {
    vi.stubGlobal("SpeechRecognition", undefined);
    vi.stubGlobal("webkitSpeechRecognition", undefined);
    fetchMock.mockImplementation(() => jsonResponse(operation(), 201));

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    await waitFor(() => expect(screen.getByLabelText("current route")).toHaveTextContent("/brain-dump/brain_dump_1"));
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/brain-dump-operations"), expect.anything());
  });

  it("does not start an operation when original audio recording is unavailable", async () => {
    vi.stubGlobal("MediaRecorder", undefined);
    fetchMock.mockImplementation(() => jsonResponse(operation(), 201));

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Original audio recording is unavailable");
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(operationFetchCalls()).toHaveLength(0);
  });

  it("uploads MediaRecorder chunks and seals their manifest before opening review", async () => {
    let uploadedHash = "";
    let sealPayload: { expected_chunks: number; manifest_hash: string } | null = null;
    function ChunkingMediaRecorder() {
      return {
        state: "inactive",
        mimeType: "audio/webm",
        ondataavailable: null as ((event: { data: Blob }) => void) | null,
        onstop: null as ((event: Event) => void) | null,
        start(this: { state: string }) {
          this.state = "recording";
        },
        pause(this: { state: string }) {
          this.state = "paused";
        },
        resume(this: { state: string }) {
          this.state = "recording";
        },
        stop(this: { state: string; ondataavailable: ((event: { data: Blob }) => void) | null; onstop: ((event: Event) => void) | null }) {
          this.state = "inactive";
          this.ondataavailable?.({ data: { size: 0 } as Blob });
          this.ondataavailable?.({
            data: {
              size: 14,
              type: "audio/webm",
              arrayBuffer: async () => new ArrayBuffer(14)
            } as Blob
          });
          this.onstop?.(new Event("stop"));
        }
      };
    }
    vi.stubGlobal("MediaRecorder", ChunkingMediaRecorder);
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(consentedOperation(), 201);
      }
      if (url.endsWith("/brain_dump_1/audio/0")) {
        const headers = new Headers(init?.headers);
        uploadedHash = headers.get("X-Content-SHA256") ?? "";
        expect(headers.get("Content-Type")).toBe("audio/webm");
        return jsonResponse(consentedOperation({ revision: 2, audio_chunks: [{ chunk_number: 0, sha256: uploadedHash, size_bytes: 14 }] }));
      }
      if (url.endsWith("/brain_dump_1/seal")) {
        sealPayload = JSON.parse(String(init?.body));
        return jsonResponse(consentedOperation({ status: "awaiting_confirmation", revision: 3 }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    await userEvent.click(screen.getByRole("button", { name: "Stop & review" }));

    await waitFor(() => expect(uploadedHash).toMatch(/^[a-f0-9]{64}$/));
    await waitFor(() => expect(sealPayload).not.toBeNull());
    expect(sealPayload).toMatchObject({ expected_chunks: 1, manifest_hash: expect.stringMatching(/^[a-f0-9]{64}$/) });
    expect(await screen.findByRole("main", { name: "Review brain dump proposals" })).toBeInTheDocument();
  });

  it("does not start browser capture or any upload pipeline without external processing consent", async () => {
    const mediaRecorderConstructor = vi.fn(function ChunkingMediaRecorder() {
      return {
        state: "inactive",
        ondataavailable: null as ((event: { data: Blob }) => void) | null,
        onstop: null as ((event: Event) => void) | null,
        start(this: { state: string }) {
          this.state = "recording";
        },
        stop(this: { state: string; onstop: ((event: Event) => void) | null }) {
          this.state = "inactive";
          this.onstop?.(new Event("stop"));
        }
      };
    });
    vi.stubGlobal("MediaRecorder", mediaRecorderConstructor);
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        return jsonResponse(
          operation({ revision: 2, proposals: [proposal("proposal_1", 1, "Renew car insurance")] })
        );
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/new", new QueryClient(), false);
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Secure cloud transcription consent");
    expect(mediaRecorderConstructor).not.toHaveBeenCalled();
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(recognitions).toHaveLength(0);
    const calledUrls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(calledUrls.some((calledUrl) => calledUrl.includes("/audio/"))).toBe(false);
    expect(calledUrls.some((calledUrl) => calledUrl.includes("/seal"))).toBe(false);
  });

  it("records a no-consent finish before opening its provisional-only review", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations/brain_dump_legacy")) {
        return jsonResponse(
          operation({
            id: "brain_dump_legacy",
            consent: {
              microphone: true,
              external_processing_allowed: false,
              provider: null,
              language_hints: ["en"],
              vocabulary: []
            }
          })
        );
      }
      if (url.endsWith("/brain_dump_legacy/finish") && init?.method === "POST") {
        return jsonResponse(
          operation({
            id: "brain_dump_legacy",
            status: "awaiting_confirmation",
            revision: 2,
            consent: {
              microphone: true,
              external_processing_allowed: false,
              provider: null,
              language_hints: ["en"],
              vocabulary: []
            }
          })
        );
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_legacy", new QueryClient(), false);
    await userEvent.click(await screen.findByRole("button", { name: "Stop & review" }));

    expect(await screen.findByRole("main", { name: "Review brain dump proposals" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input)).some((url) => url.includes("/seal"))).toBe(false);
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain(
      "/api/brain-dump-operations/brain_dump_legacy/finish"
    );
  });

  it("does not create a backend operation when microphone permission fails", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(new Error("permission prompt rejected"));
    fetchMock.mockImplementation(() => jsonResponse(operation(), 201));

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("permission prompt rejected");
    expect(operationFetchCalls()).toHaveLength(0);
  });

  it("shows the generic microphone denial when the browser throws a non-error", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce("denied");
    fetchMock.mockImplementation(() => jsonResponse(operation(), 201));

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone permission was denied.");
    expect(operationFetchCalls()).toHaveLength(0);
  });

  it("uses webkit speech recognition, uploads interim transcripts and reports upload failures", async () => {
    const WebkitRecognition = window.SpeechRecognition;
    vi.stubGlobal("SpeechRecognition", undefined);
    vi.stubGlobal("webkitSpeechRecognition", WebkitRecognition);
    Object.defineProperty(window.navigator, "language", { configurable: true, value: "" });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        const body = JSON.parse(String(init?.body));
        expect(body.segments[0]).toMatchObject({ sequence: 1, text: "Still thinking", stability: "interim" });
        return Promise.reject(new Error("transcript upload failed"));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    expect(recognition?.lang).toBe("en-US");

    act(() => emitSpeech("Still thinking", false));

    expect(await screen.findByRole("alert")).toHaveTextContent("transcript upload failed");
  });

  it("stops active recognition when discarding a recording", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/cancel")) {
        return jsonResponse(operation({ status: "cancelled", revision: 2 }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    expect(recognition?.start).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Discard" }));

    await waitFor(() => expect(recognition?.stop).toHaveBeenCalledTimes(1));
  });

  it("keeps recognition alive when discarding fails", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/cancel")) {
        return Promise.reject(new Error("cancel failed"));
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        const body = JSON.parse(String(init?.body));
        expect(body.segments[0]).toMatchObject({ sequence: 1, text: "Still recording after failed discard", stability: "stable" });
        return jsonResponse(operation({ revision: 2, proposals: [proposal("proposal_1", 1, "Still recording after failed discard")] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    const activeRecognition = recognition;
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("cancel failed");
    expect(screen.getByText("Recording")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Stop & review" })).toBeEnabled();
    expect(activeRecognition?.stop).not.toHaveBeenCalled();
    act(() => emitSpeech("Still recording after failed discard"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/brain_dump_1/transcript"), expect.anything()));
  });

  it("stops active recognition when the recording route unmounts", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    const view = renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    expect(recognition?.start).toHaveBeenCalledTimes(1);

    view.unmount();

    expect(recognition?.stop).toHaveBeenCalledTimes(1);
  });

  it("ignores blank speech results and shows browser recognition permission errors", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    act(() => emitSpeech("   "));
    expect(operationFetchCalls()).toHaveLength(1);

    act(() => recognition?.onerror?.({ error: "not-allowed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone permission was denied.");

    act(() => recognition?.onerror?.({ error: "network" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone error: network");
  });

  it("does not resume a paused operation when browser speech recognition becomes unavailable", async () => {
    const paused = consentedOperation({ id: "brain_dump_existing", status: "paused", revision: 3 });
    vi.stubGlobal("SpeechRecognition", undefined);
    vi.stubGlobal("webkitSpeechRecognition", undefined);
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(paused);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing");
    await userEvent.click(await screen.findByRole("button", { name: "Resume" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Browser speech recognition is unavailable");
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/resume"), expect.anything());
  });

  it("does not resume the backend when microphone permission is rejected", async () => {
    const paused = consentedOperation({ id: "brain_dump_existing", status: "paused", revision: 3 });
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(new Error("denied by browser"));
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(paused);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing");
    await userEvent.click(await screen.findByRole("button", { name: "Resume" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("denied by browser");
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/resume"), expect.anything());
  });

  it("resumes a fetched paused operation with a new recognizer and the next transcript sequence", async () => {
    const paused = consentedOperation({
      id: "brain_dump_existing",
      status: "paused",
      revision: 7,
      segments: [{ id: "segment_2", sequence: 2, text: "Existing thought", stability: "stable", created_at: "2026-07-16T00:00:00Z" }]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(paused);
      }
      if (url.endsWith("/brain_dump_existing/resume")) {
        return jsonResponse(operation({ ...paused, status: "recording", revision: 8 }));
      }
      if (url.endsWith("/brain_dump_existing/transcript")) {
        const body = JSON.parse(String(init?.body));
        expect(body.segments[0]).toMatchObject({ sequence: 3, text: "Follow up", stability: "stable" });
        return jsonResponse(operation({ ...paused, status: "recording", revision: 9 }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing");
    await userEvent.click(await screen.findByRole("button", { name: "Resume" }));

    expect(recognitions).toHaveLength(1);
    expect(recognitions[0].start).toHaveBeenCalledTimes(1);
    act(() => emitSpeech("Follow up"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/brain_dump_existing/transcript"), expect.anything()));
  });

  it("shows the singular captured task count while recording", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        return jsonResponse(operation({ revision: 2, proposals: [proposal("proposal_1", 1, "Renew car insurance")] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    act(() => emitSpeech("Renew car insurance."));

    expect(await screen.findByText("1 task captured")).toBeInTheDocument();
  });

  it("returns from an empty review route to a new recording screen", async () => {
    fetchMock.mockImplementation(() => Promise.reject(new Error("should not load a new operation")));

    renderBrainDump("/brain-dump/new/review");
    await userEvent.click(screen.getByRole("button", { name: "Back to recording" }));

    expect(await screen.findByRole("button", { name: "Record" })).toBeEnabled();
  });

  it("keeps empty review commands as no-ops until an operation exists", async () => {
    fetchMock.mockImplementation(() => Promise.reject(new Error("should not command a new operation")));

    renderBrainDump("/brain-dump/new/review");
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm 0 additions" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Review 0 tasks" })).toBeInTheDocument();
  });

  it("reports command failures without losing the current recording", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/pause")) {
        return Promise.reject(new Error("pause failed"));
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        const body = JSON.parse(String(init?.body));
        expect(body.segments[0]).toMatchObject({ sequence: 1, text: "Still recording after failed pause", stability: "stable" });
        return jsonResponse(operation({ revision: 2, proposals: [proposal("proposal_1", 1, "Still recording after failed pause")] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    const activeRecognition = recognition;
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("pause failed");
    expect(screen.getByText("Recording")).toBeInTheDocument();
    expect(activeRecognition?.stop).not.toHaveBeenCalled();
    act(() => emitSpeech("Still recording after failed pause"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/brain_dump_1/transcript"), expect.anything()));
  });

  it("shows a generic command failure for non-error rejections", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/pause")) {
        return Promise.reject("pause failed");
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Brain dump command failed.");
  });

  it("surfaces a seal failure after stopping preview recognition", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(consentedOperation(), 201);
      }
      if (url.endsWith("/brain_dump_1/seal")) {
        return Promise.reject(new Error("finish failed"));
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        const body = JSON.parse(String(init?.body));
        expect(body.segments[0]).toMatchObject({ sequence: 1, text: "Still recording after failed finish", stability: "stable" });
        return jsonResponse(consentedOperation({ revision: 2, proposals: [proposal("proposal_1", 1, "Still recording after failed finish")] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    const activeRecognition = recognition;
    await userEvent.click(screen.getByRole("button", { name: "Stop & review" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("finish failed");
    expect(screen.getByText("Recording")).toBeInTheDocument();
    expect(activeRecognition?.stop).toHaveBeenCalledTimes(1);
  });

  it("keeps unchanged and blank review edits local", async () => {
    const captured = operation({
      id: "brain_dump_existing",
      status: "awaiting_confirmation",
      revision: 4,
      proposals: [proposal("proposal_1", 1, "Renew car insurance")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing/review");
    const titleInput = await screen.findByDisplayValue("Renew car insurance");

    titleInput.focus();
    await userEvent.tab();
    await userEvent.clear(titleInput);
    await userEvent.type(titleInput, "   ");
    await userEvent.tab();

    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/proposals/proposal_1"), expect.anything());
  });

  it("discards an awaiting review instead of saving proposals", async () => {
    const captured = operation({
      id: "brain_dump_existing",
      status: "awaiting_confirmation",
      revision: 4,
      proposals: [proposal("proposal_1", 1, "Renew car insurance")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      if (url.endsWith("/brain_dump_existing/cancel")) {
        return jsonResponse(operation({ ...captured, status: "cancelled", revision: 5 }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing/review");
    await userEvent.click(await screen.findByRole("button", { name: "Discard" }));

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/brain_dump_existing/cancel"), expect.anything());
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/commit"), expect.anything());
  });

  it("reports plural saved task counts after confirmation", async () => {
    const captured = consentedOperation({
      revision: 2,
      status: "awaiting_confirmation",
      proposals: [proposal("proposal_1", 1, "Renew car insurance"), proposal("proposal_2", 2, "Reply to Anna")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(consentedOperation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        return jsonResponse(captured);
      }
      if (url.endsWith("/brain_dump_1/seal")) {
        return jsonResponse(consentedOperation({ ...captured, status: "awaiting_confirmation", revision: 3 }));
      }
      if (url.endsWith("/brain_dump_1/commit")) {
        return jsonResponse(consentedOperation({ ...captured, status: "completed", revision: 4, committed_task_ids: ["task_1", "task_2"] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    act(() => emitSpeech("Renew car insurance. Reply to Anna."));
    await userEvent.click(await screen.findByRole("button", { name: "Stop & review" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirm 2 additions" }));

    expect(await screen.findByText("Saved 2 tasks to Inbox")).toBeInTheDocument();
  });

  it("preserves user-edited wording, deletes proposals and saves to native Inbox only after confirmation", async () => {
    const captured = consentedOperation({
      revision: 2,
      proposals: [proposal("proposal_1", 1, "Renew car insurance"), proposal("proposal_2", 2, "Reply to Anna")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(consentedOperation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        return jsonResponse(captured);
      }
      if (url.endsWith("/brain_dump_1/seal")) {
        return jsonResponse(consentedOperation({ ...captured, status: "awaiting_confirmation", revision: 3 }));
      }
      if (url.includes("/proposals/proposal_1")) {
        return jsonResponse(
          consentedOperation({
            ...captured,
            revision: 4,
            proposals: [proposal("proposal_1", 1, "Renew car insurance before Friday", { status: "user_edited", user_edited: true }), proposal("proposal_2", 2, "Reply to Anna")]
          })
        );
      }
      if (url.includes("/proposals/proposal_2")) {
        return jsonResponse(
          consentedOperation({
            ...captured,
            revision: 5,
            proposals: [proposal("proposal_1", 1, "Renew car insurance before Friday", { status: "user_edited", user_edited: true }), proposal("proposal_2", 2, "Reply to Anna", { deleted: true })]
          })
        );
      }
      if (url.endsWith("/brain_dump_1/commit")) {
        return jsonResponse(
          consentedOperation({
            status: "completed",
            revision: 6,
            committed_task_ids: ["task_1"],
            proposals: [proposal("proposal_1", 1, "Renew car insurance before Friday", { status: "user_edited", user_edited: true }), proposal("proposal_2", 2, "Reply to Anna", { deleted: true })]
          })
        );
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    act(() => emitSpeech("Renew car insurance. Reply to Anna."));
    await userEvent.click(await screen.findByRole("button", { name: "Stop & review" }));

    const review = await screen.findByRole("main", { name: "Review brain dump proposals" });
    const titleInput = within(review).getByDisplayValue("Renew car insurance");
    await userEvent.clear(titleInput);
    await userEvent.type(titleInput, "Renew car insurance before Friday");
    await userEvent.tab();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/proposals/proposal_1"), expect.anything()));

    await userEvent.click(within(review).getByRole("button", { name: "Delete Reply to Anna" }));
    expect(within(review).queryByText("Reply to Anna")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/tasks"), expect.anything());

    await userEvent.click(screen.getByRole("button", { name: "Confirm 1 addition" }));
    expect(await screen.findByText("Saved 1 task to Inbox")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/brain_dump_1/commit"), expect.anything());
  });

  it("ignores discard clicks before a brain dump operation exists", async () => {
    fetchMock.mockImplementation(() => Promise.reject(new Error("no requests expected")));

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));

    expect(operationFetchCalls()).toHaveLength(0);
  });

  it("reports load failures when an existing brain dump cannot be resumed", async () => {
    fetchMock.mockImplementationOnce(() => Promise.reject(new Error("load failed")));
    const first = renderBrainDump("/brain-dump/brain_dump_missing");
    expect(await screen.findByRole("alert")).toHaveTextContent("load failed");
    first.unmount();

    fetchMock.mockImplementationOnce(() => Promise.reject("load blew up"));
    renderBrainDump("/brain-dump/brain_dump_missing");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not resume brain dump.");
  });

  it("surfaces rename failures on the review screen instead of swallowing them", async () => {
    const captured = operation({
      id: "brain_dump_existing",
      status: "awaiting_confirmation",
      revision: 4,
      proposals: [proposal("proposal_1", 1, "Renew car insurance")]
    });
    let renameAttempts = 0;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      if (url.includes("/proposals/proposal_1")) {
        renameAttempts += 1;
        return renameAttempts === 1 ? Promise.reject(new Error("rename failed")) : Promise.reject("rename blew up");
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing/review");
    const titleInput = await screen.findByDisplayValue("Renew car insurance");
    await userEvent.clear(titleInput);
    await userEvent.type(titleInput, "Renew car insurance before Friday");
    await userEvent.tab();

    expect(await screen.findByRole("alert")).toHaveTextContent("rename failed");
    expect(screen.getByRole("main", { name: "Review brain dump proposals" })).toBeInTheDocument();

    titleInput.focus();
    await userEvent.tab();

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not update the task title."));
  });

  it("surfaces delete failures including stale-revision conflicts and keeps the proposal visible", async () => {
    const captured = operation({
      id: "brain_dump_existing",
      status: "awaiting_confirmation",
      revision: 4,
      proposals: [proposal("proposal_1", 1, "Renew car insurance")]
    });
    let deleteAttempts = 0;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      if (url.includes("/proposals/proposal_1")) {
        deleteAttempts += 1;
        return deleteAttempts === 1 ? jsonResponse({ detail: "revision conflict" }, 409) : Promise.reject("delete blew up");
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing/review");
    const deleteButton = await screen.findByRole("button", { name: "Delete Renew car insurance" });

    await userEvent.click(deleteButton);
    expect(await screen.findByRole("alert")).toHaveTextContent("Request failed");
    expect(screen.getByDisplayValue("Renew car insurance")).toBeInTheDocument();

    await userEvent.click(deleteButton);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not delete the task."));
    expect(screen.getByDisplayValue("Renew car insurance")).toBeInTheDocument();
  });

  it("sends the freshest revision when a rename and delete land back-to-back", async () => {
    const captured = operation({
      id: "brain_dump_existing",
      status: "awaiting_confirmation",
      revision: 4,
      proposals: [proposal("proposal_1", 1, "Renew car insurance"), proposal("proposal_2", 2, "Reply to Anna")]
    });
    const renamed = proposal("proposal_1", 1, "Renew car insurance before Friday", { status: "user_edited", user_edited: true });
    const sentRevisions: number[] = [];
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      if (url.includes("/proposals/proposal_1")) {
        sentRevisions.push(JSON.parse(String(init?.body)).expected_revision);
        return jsonResponse(operation({ ...captured, revision: 5, proposals: [renamed, proposal("proposal_2", 2, "Reply to Anna")] }));
      }
      if (url.includes("/proposals/proposal_2")) {
        sentRevisions.push(JSON.parse(String(init?.body)).expected_revision);
        return jsonResponse(operation({ ...captured, revision: 6, proposals: [renamed, proposal("proposal_2", 2, "Reply to Anna", { deleted: true })] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing/review");
    const titleInput = await screen.findByDisplayValue("Renew car insurance");
    const deleteButton = screen.getByRole("button", { name: "Delete Reply to Anna" });
    await userEvent.clear(titleInput);
    await userEvent.type(titleInput, "Renew car insurance before Friday");

    await act(async () => {
      fireEvent.blur(titleInput);
      fireEvent.click(deleteButton);
    });

    await waitFor(() => expect(sentRevisions).toEqual([4, 5]));
    expect(screen.queryByText("Reply to Anna")).not.toBeInTheDocument();
  });

  it("refreshes cached task queries after committing a brain dump", async () => {
    const captured = consentedOperation({
      id: "brain_dump_existing",
      status: "awaiting_confirmation",
      revision: 4,
      proposals: [proposal("proposal_1", 1, "Renew car insurance")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      if (url.endsWith("/brain_dump_existing/commit")) {
        return jsonResponse(operation({ ...captured, status: "completed", revision: 5, committed_task_ids: ["task_1"] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    const queryClient = new QueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderBrainDump("/brain-dump/brain_dump_existing/review", queryClient);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm 1 addition" }));

    expect(await screen.findByText("Saved 1 task to Inbox")).toBeInTheDocument();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["tasks"] });
  });

  it("navigates to the inbox from the saved confirmation", async () => {
    const captured = consentedOperation({
      id: "brain_dump_existing",
      status: "awaiting_confirmation",
      revision: 4,
      proposals: [proposal("proposal_1", 1, "Renew car insurance")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      if (url.endsWith("/brain_dump_existing/commit")) {
        return jsonResponse(operation({ ...captured, status: "completed", revision: 5, committed_task_ids: ["task_1"] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing/review");
    await userEvent.click(await screen.findByRole("button", { name: "Confirm 1 addition" }));
    await userEvent.click(await screen.findByRole("button", { name: "View inbox" }));

    expect(await screen.findByText("Task list route: inbox")).toBeInTheDocument();
  });

  it("labels provisional review truthfully and lets its owner delete retained raw audio", async () => {
    const captured = consentedOperation({
      id: "brain_dump_provisional_audio",
      status: "awaiting_confirmation",
      revision: 4,
      committable: false,
      reconciliation_quality: "provisional_only",
      raw_audio_present: true,
      raw_audio_expires_at: "2026-07-17T00:00:00Z",
      proposals: [proposal("proposal_1", 1, "Renew car insurance")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_provisional_audio") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      if (url.endsWith("/brain_dump_provisional_audio/delete_raw_audio")) {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({ expected_revision: 4 });
        return jsonResponse({
          ...captured,
          revision: 5,
          raw_audio_present: false,
          raw_audio_expires_at: "2026-07-16T00:00:00Z"
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_provisional_audio/review");

    expect(await screen.findByText(/These are provisional drafts/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm 1 addition" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Delete audio now" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Delete audio now" })).not.toBeInTheDocument());
  });

  it("enables Save for an explicitly reviewed provisional operation", async () => {
    const reviewed = consentedOperation({
      id: "brain_dump_reviewed_provisional",
      status: "awaiting_confirmation",
      revision: 5,
      committable: true,
      reconciliation_quality: "provisional_only",
      proposals: [proposal("proposal_reviewed", 1, "Call the dentist")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_reviewed_provisional") && (!init?.method || init.method === "GET")) {
        return jsonResponse(reviewed);
      }
      if (url.endsWith("/brain_dump_reviewed_provisional/commit")) {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({ expected_revision: 5 });
        return jsonResponse(operation({
          ...reviewed,
          status: "completed",
          revision: 6,
          committed_task_ids: ["task_reviewed"]
        }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_reviewed_provisional/review");

    const save = await screen.findByRole("button", { name: "Confirm 1 addition" });
    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(await screen.findByText("Saved 1 task to Inbox")).toBeInTheDocument();
  });

  it("shows schema-v2 processing stages before editable review", async () => {
    const improving = operation({
      id: "brain_dump_processing",
      status: "accurate_transcribing",
      revision: 5,
      status_history: ["sealing", "fast_processing", "accurate_transcribing"]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_processing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(improving);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_processing");

    expect(await screen.findByText("Improving transcript")).toBeInTheDocument();
    expect(screen.getByText("accurate_transcribing")).toBeInTheDocument();
    expect(screen.queryByRole("main", { name: "Review brain dump proposals" })).not.toBeInTheDocument();
  });

  it("shows title conflicts and blocks Save until the user resolves them", async () => {
    const conflicted = operation({
      id: "brain_dump_conflict",
      status: "awaiting_confirmation",
      revision: 6,
      proposals: [
        proposal("proposal_locked", 1, "Починить BrainBuddy MVP", {
          status: "conflicted",
          user_edited: true,
          locked_fields: ["title"],
          conflicts: [conflict("title", "Починить BrainBuddy MVP", "Починить BrainBuddy")]
        })
      ]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_conflict") && (!init?.method || init.method === "GET")) {
        return jsonResponse(conflicted);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_conflict/review");

    expect(await screen.findByText("Conflict: title")).toBeInTheDocument();
    expect(screen.getByText("Mine: Починить BrainBuddy MVP")).toBeInTheDocument();
    expect(screen.getByText("Suggestion: Починить BrainBuddy")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm 1 addition" })).toBeDisabled();
  });

  it("keeps a provider-driven removal visible and individually confirmable instead of hiding it", async () => {
    // A reconciler-proposed removal must never silently vanish from Review;
    // it stays visible (not filtered out with `deleted`) as an open conflict
    // requiring the same explicit Keep/Accept confirmation as any other
    // conflict (exact-head review item 1).
    const proposedRemoval = operation({
      id: "brain_dump_model_removal",
      status: "awaiting_confirmation",
      revision: 6,
      proposals: [
        proposal("proposal_stale", 1, "Reply to Anna", {
          status: "conflicted",
          deleted: false,
          conflicts: [conflict("removal", "active", "removed")]
        })
      ]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_model_removal") && (!init?.method || init.method === "GET")) {
        return jsonResponse(proposedRemoval);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_model_removal/review");

    expect(await screen.findByText("Conflict: removal")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Reply to Anna")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm 1 addition" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Keep mine" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use suggestion" })).toBeInTheDocument();
  });

  it("does not replace a named recording route when starting after load fails", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_ad_hoc") && (!init?.method || init.method === "GET")) {
        return Promise.reject(new Error("load failed"));
      }
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation({ id: "brain_dump_ad_hoc" }), 201);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_ad_hoc");
    expect(await screen.findByRole("alert")).toHaveTextContent("load failed");
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    await waitFor(() => expect(screen.getByLabelText("current route")).toHaveTextContent("/brain-dump/brain_dump_ad_hoc"));
  });

  it("does not surface load errors after the route aborts an in-flight resume", async () => {
    let rejectLoad: ((reason: unknown) => void) | undefined;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_abort") && (!init?.method || init.method === "GET")) {
        return new Promise<Response>((_resolve, reject) => {
          rejectLoad = reject;
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    const view = renderBrainDump("/brain-dump/brain_dump_abort");
    await waitFor(() => expect(rejectLoad).toBeDefined());
    view.unmount();

    await act(async () => {
      rejectLoad?.(new Error("aborted load failed"));
    });
  });

  it("uses a generic transcript upload message for non-error rejections", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        return Promise.reject("upload rejected");
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    act(() => emitSpeech("Needs follow-up"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Transcript upload failed.");
  });

  it("shows the generic microphone denial when resume permission rejects with a non-error", async () => {
    const paused = consentedOperation({ id: "brain_dump_existing", status: "paused", revision: 3 });
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce("denied");
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(paused);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing");
    await userEvent.click(await screen.findByRole("button", { name: "Resume" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone permission was denied.");
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/resume"), expect.anything());
  });

  it("keeps provisional proposals visible while schema-v2 processing continues", async () => {
    const improving = operation({
      id: "brain_dump_processing",
      status: "reconciling",
      revision: 5,
      proposals: [proposal("proposal_1", 1, "Renew car insurance")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_processing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(improving);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_processing");

    expect(await screen.findByText("Reconciling tasks")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Draft task 1: Renew car insurance" })).toBeInTheDocument();
    expect(screen.queryByText("We are keeping the task list first while the accurate transcript catches up.")).not.toBeInTheDocument();
  });

  it("renders conflict value fallbacks when the reconciler omits current or suggested text", async () => {
    const conflicted = operation({
      id: "brain_dump_conflict_fallbacks",
      status: "awaiting_confirmation",
      revision: 6,
      proposals: [
        proposal("proposal_locked", 1, "Resolve missing context", {
          status: "conflicted",
          conflicts: [
            {
              field: "title",
              current_value: null,
              suggested_value: null,
              producer: "reconciler",
              source_segment_ids: []
            }
          ]
        })
      ]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_conflict_fallbacks") && (!init?.method || init.method === "GET")) {
        return jsonResponse(conflicted);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_conflict_fallbacks/review");

    expect(await screen.findByText("Mine: —")).toBeInTheDocument();
    expect(screen.getByText("Suggestion: —")).toBeInTheDocument();
  });

  it("offers a retry action for a persisted retryable provider checkpoint", async () => {
    const retryable = operation({
      id: "brain_dump_retryable",
      status: "retryable_error",
      revision: 7,
      proposals: [proposal("proposal_1", 1, "Renew car insurance")],
      available_recovery_actions: ["retry", "cancel"],
      provider_runs: [
        {
          id: "provider_run_1",
          role: "accurate_stt",
          status: "retryable_error",
          checkpoint: "sealed",
          attempt: 1,
          recovery_count: 0,
          error: "provider temporarily unavailable"
        }
      ]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_retryable") && (!init?.method || init.method === "GET")) {
        return jsonResponse(retryable);
      }
      if (url.endsWith("/brain_dump_retryable/retry") && init?.method === "POST") {
        return jsonResponse(operation({ ...retryable, status: "awaiting_confirmation", revision: 8 }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_retryable/review");
    expect(await screen.findByText("Accurate transcription paused")).toBeInTheDocument();
    expect(screen.getByText("provider temporarily unavailable")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry accurate transcription" }));

    expect(await screen.findByText("Review 1 task")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/brain_dump_retryable/retry"),
      expect.objectContaining({ method: "POST" })
    );
  });

  it("labels a reconciler retry with the stage that will actually run", async () => {
    const retryable = operation({
      id: "brain_dump_reconciler_retryable",
      status: "retryable_error",
      revision: 7,
      proposals: [proposal("proposal_1", 1, "Renew car insurance")],
      available_recovery_actions: ["retry", "cancel"],
      provider_runs: [
        {
          id: "provider_run_reconciler_retryable",
          role: "reconciler",
          status: "retryable_error",
          checkpoint: "accurate_transcribed",
          attempt: 1,
          recovery_count: 0
        }
      ]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_reconciler_retryable") && (!init?.method || init.method === "GET")) {
        return jsonResponse(retryable);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_reconciler_retryable/review");

    expect(await screen.findByText("Task reconciliation paused")).toBeInTheDocument();
    expect(screen.getByText("The task reconciler can be retried from the accurate transcript.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry task reconciliation" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Retry accurate transcription" })).not.toBeInTheDocument();
  });

  it("shows terminal recovery choices instead of a recording surface", async () => {
    const terminal = operation({
      id: "brain_dump_terminal",
      status: "terminal_error",
      revision: 4,
      proposals: [
        proposal("proposal_child", 1, "Call the dentist", {
          predecessor_ids: ["proposal_old_1", "proposal_old_2"],
          successor_ids: ["proposal_next"]
        }),
        proposal("proposal_split", 2, "Buy oat milk", {
          predecessor_ids: ["proposal_old_3"]
        })
      ],
      provider_runs: [
        {
          id: "provider_run_terminal",
          role: "reconciler",
          status: "terminal_error",
          checkpoint: "sealed",
          attempt: 3,
          recovery_count: 2,
          error: "proposals could not be reconciled"
        }
      ],
      available_recovery_actions: ["review_provisional", "cancel"]
    });
    const provisionalReview = operation({
      ...terminal,
      status: "awaiting_confirmation",
      revision: 5,
      reconciliation_quality: "provisional_only"
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_terminal") && (!init?.method || init.method === "GET")) {
        return jsonResponse(terminal);
      }
      if (url.endsWith("/brain_dump_terminal/review_provisional") && init?.method === "POST") {
        return jsonResponse(provisionalReview);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_terminal/review");

    expect(await screen.findByText("Task reconciliation failed")).toBeInTheDocument();
    expect(screen.getByText("proposals could not be reconciled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete recording" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Review provisional tasks" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Review provisional tasks" }));
    expect(screen.getByText("Merged from 2 tasks")).toBeInTheDocument();
    expect(screen.getByText("Split from an earlier task")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/brain_dump_terminal/review_provisional"),
      expect.objectContaining({ method: "POST" })
    );
  });

  it("hides provisional review when the backend does not authorize it", async () => {
    const terminal = operation({
      id: "brain_dump_terminal_stt",
      status: "terminal_error",
      proposals: [proposal("proposal_preview", 1, "Call the dentist")],
      available_recovery_actions: ["cancel"],
      provider_runs: [
        {
          id: "provider_run_terminal_stt",
          role: "accurate_stt",
          status: "terminal_error",
          checkpoint: "sealed",
          attempt: 1,
          recovery_count: 0,
          error: "audio could not be transcribed"
        }
      ]
    });
    fetchMock.mockImplementation(() => jsonResponse(terminal));

    renderBrainDump("/brain-dump/brain_dump_terminal_stt/review");

    expect(await screen.findByText("Accurate transcription failed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review provisional tasks" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete recording" })).toBeEnabled();
  });

  it("shows fallback terminal copy and preserves the recovery surface when deletion fails", async () => {
    const terminal = operation({
      id: "brain_dump_terminal_fallback",
      status: "terminal_error",
      revision: 5,
      proposals: [],
      provider_runs: undefined
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_terminal_fallback") && (!init?.method || init.method === "GET")) {
        return jsonResponse(terminal);
      }
      if (url.endsWith("/brain_dump_terminal_fallback/cancel") && init?.method === "POST") {
        return Promise.reject(new Error("delete failed"));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_terminal_fallback/review");

    expect(await screen.findByText("The recording could not be processed accurately.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review provisional tasks" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete recording" }));
    expect(await screen.findByText("delete failed")).toBeInTheDocument();
  });

  it("fails closed without cloud-processing consent before browser speech or capture starts", async () => {
    renderBrainDump("/brain-dump/new", new QueryClient(), false);

    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Secure cloud transcription consent");
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(recognitions).toHaveLength(0);
    expect(operationFetchCalls()).toHaveLength(0);
  });

  it("renders the stopped-capture UI for a persisted paused operation whose cloud consent is already revoked", async () => {
    const withdrawnPaused = operation({ id: "brain_dump_existing", status: "paused", revision: 5 });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(withdrawnPaused);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing");

    expect((await screen.findAllByText("Cloud processing stopped")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/resume"), expect.anything());
  });

  it("renders the stopped-capture UI for a persisted recording operation whose cloud consent is already revoked", async () => {
    const withdrawnRecording = operation({ id: "brain_dump_existing", status: "recording", revision: 5 });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_existing") && (!init?.method || init.method === "GET")) {
        return jsonResponse(withdrawnRecording);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing");

    expect((await screen.findAllByText("Cloud processing stopped")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("stops local capture before awaiting a slow withdraw_consent server response", async () => {
    let resolveWithdraw: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(consentedOperation(), 201);
      }
      if (url.endsWith("/brain_dump_1/withdraw_consent")) {
        return new Promise<Response>((resolve) => {
          resolveWithdraw = resolve;
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    const activeRecognition = recognition;

    await userEvent.click(screen.getByRole("button", { name: "Stop cloud processing" }));

    expect((await screen.findAllByText("Cloud processing stopped")).length).toBeGreaterThan(0);
    expect(activeRecognition?.stop).toHaveBeenCalledTimes(1);
    expect(micTrackStop).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();

    await act(async () => {
      resolveWithdraw?.(await jsonResponse(operation({ status: "recording", revision: 2 })));
    });
  });

  it("keeps capture stopped and offers a retry affordance when withdraw_consent is rejected by the server", async () => {
    let withdrawAttempts = 0;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(consentedOperation(), 201);
      }
      if (url.endsWith("/brain_dump_1/withdraw_consent")) {
        withdrawAttempts += 1;
        return withdrawAttempts === 1
          ? Promise.reject(new Error("withdraw_consent failed"))
          : jsonResponse(operation({ status: "recording", revision: 2 }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    const activeRecognition = recognition;

    await userEvent.click(screen.getByRole("button", { name: "Stop cloud processing" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("withdraw_consent failed");
    expect(screen.getAllByText("Cloud processing stopped").length).toBeGreaterThan(0);
    expect(activeRecognition?.stop).toHaveBeenCalledTimes(1);

    const retryButton = screen.getByRole("button", { name: "Stop cloud processing" });
    await userEvent.click(retryButton);

    await waitFor(() => expect(withdrawAttempts).toBe(2));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop cloud processing" })).not.toBeInTheDocument();
  });

  it("stops every acquired microphone track when the operation cannot be created after permission is granted", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return Promise.reject(new Error("operation create failed"));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("operation create failed");
    expect(micTrackStop).toHaveBeenCalledTimes(1);
  });

  it("stops every acquired microphone track when MediaRecorder construction fails", async () => {
    vi.stubGlobal(
      "MediaRecorder",
      vi.fn(() => {
        throw new Error("unsupported mime type");
      })
    );
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(consentedOperation(), 201);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("unsupported mime type");
    expect(micTrackStop).toHaveBeenCalledTimes(1);
  });

  it("stops every acquired microphone track when browser recognition startup fails", async () => {
    vi.stubGlobal(
      "SpeechRecognition",
      vi.fn(() => {
        throw new Error("recognition unavailable");
      })
    );
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(consentedOperation(), 201);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("recognition unavailable");
    expect(micTrackStop).toHaveBeenCalled();
  });

  it("explains a retryable provider failure when the provider supplied no error detail", async () => {
    const retryable = operation({
      id: "brain_dump_retryable_fallback",
      status: "retryable_error",
      revision: 7,
      available_recovery_actions: ["retry", "cancel"],
      provider_runs: undefined
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_retryable_fallback") && (!init?.method || init.method === "GET")) {
        return jsonResponse(retryable);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_retryable_fallback/review");

    expect(await screen.findByText("The transcription provider can be retried from the sealed recording.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry accurate transcription" })).toBeEnabled();
  });

  it("surfaces a safe conflict-resolution fallback when the request rejects with a non-error", async () => {
    const conflicted = operation({
      id: "brain_dump_conflict_resolution",
      status: "awaiting_confirmation",
      revision: 6,
      proposals: [
        proposal("proposal_locked", 1, "Resolve a conflict", {
          status: "conflicted",
          conflicts: [conflict("title", "Resolve a conflict", "Resolve the conflict")]
        })
      ]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_conflict_resolution") && (!init?.method || init.method === "GET")) {
        return jsonResponse(conflicted);
      }
      if (url.includes("/proposals/proposal_locked")) {
        return Promise.reject("resolution rejected");
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_conflict_resolution/review");
    await userEvent.click(await screen.findByRole("button", { name: "Use suggestion" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not resolve the conflict.");
  });

  it("renders the Saving tasks processing surface and keeps polling a persisted committing operation", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let getCalls = 0;
      fetchMock.mockImplementation((input, init) => {
        const url = String(input);
        if (url.endsWith("/brain_dump_committing") && (!init?.method || init.method === "GET")) {
          getCalls += 1;
          return jsonResponse(
            operation({
              id: "brain_dump_committing",
              status: getCalls === 1 ? "committing" : "completed",
              revision: getCalls === 1 ? 9 : 10,
              committed_task_ids: getCalls === 1 ? [] : ["task_1"]
            })
          );
        }
        throw new Error(`unexpected fetch ${url}`);
      });

      renderBrainDump("/brain-dump/brain_dump_committing/review");

      expect(await screen.findByText("Saving tasks")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Confirm 1 addition" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Record" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });

      expect(await screen.findByText("Saved 1 task to Inbox")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps polling after a transient processing refresh failure", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let getCalls = 0;
      fetchMock.mockImplementation((input, init) => {
        const url = String(input);
        if (url.endsWith("/brain_dump_poll_retry") && (!init?.method || init.method === "GET")) {
          getCalls += 1;
          if (getCalls === 2) {
            return Promise.reject(new Error("temporary refresh failure"));
          }
          return jsonResponse(
            operation({
              id: "brain_dump_poll_retry",
              status: getCalls === 1 ? "sealing" : "completed",
              revision: getCalls,
              committed_task_ids: getCalls === 1 ? [] : ["task_1"]
            })
          );
        }
        throw new Error(`unexpected fetch ${url}`);
      });

      renderBrainDump("/brain-dump/brain_dump_poll_retry");
      expect(await screen.findByText("Sealing audio")).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });

      expect(await screen.findByText("Saved 1 task to Inbox")).toBeInTheDocument();
      expect(getCalls).toBe(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("cites the exact source utterance behind each reviewed proposal", async () => {
    const captured = consentedOperation({
      id: "brain_dump_citations",
      status: "awaiting_confirmation",
      revision: 4,
      segments: [
        { id: "seg_1", sequence: 1, text: "Renew the car insurance before Friday", stability: "stable", created_at: "2026-07-16T00:00:00Z" },
        { id: "seg_2", sequence: 2, text: "Reply to Anna about the offsite", stability: "stable", created_at: "2026-07-16T00:00:00Z" }
      ],
      proposals: [
        proposal("proposal_1", 1, "Renew car insurance", { source_segment_ids: ["seg_1"] }),
        proposal("proposal_2", 2, "Reply to Anna", { source_segment_ids: ["seg_2"] })
      ]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_citations") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_citations/review");

    const review = await screen.findByRole("main", { name: "Review brain dump proposals" });
    const firstCard = within(review).getByRole("textbox", { name: "Task title #1" }).closest("article") as HTMLElement;
    expect(within(firstCard).getByText(/Renew the car insurance before Friday/)).toBeInTheDocument();
    // Each proposal cites only its own utterance, never a sibling's.
    expect(within(firstCard).queryByText(/Reply to Anna about the offsite/)).not.toBeInTheDocument();

    const secondCard = within(review).getByRole("textbox", { name: "Task title #2" }).closest("article") as HTMLElement;
    expect(within(secondCard).getByText(/Reply to Anna about the offsite/)).toBeInTheDocument();
  });

  it("resolves and renders every cited utterance for a multi-segment merged proposal", async () => {
    const captured = consentedOperation({
      id: "brain_dump_citations_multi",
      status: "awaiting_confirmation",
      revision: 4,
      segments: [
        { id: "seg_a", sequence: 1, text: "Call the plumber about the leak", stability: "stable", created_at: "2026-07-16T00:00:00Z" },
        { id: "seg_b", sequence: 2, text: "and ask when he can come by", stability: "stable", created_at: "2026-07-16T00:00:00Z" }
      ],
      proposals: [proposal("proposal_1", 1, "Call the plumber about the leak", { source_segment_ids: ["seg_a", "seg_b"] })]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_citations_multi") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_citations_multi/review");

    const review = await screen.findByRole("main", { name: "Review brain dump proposals" });
    const card = within(review).getByRole("textbox", { name: "Task title #1" }).closest("article") as HTMLElement;
    expect(within(card).getByText(/Call the plumber about the leak/)).toBeInTheDocument();
    expect(within(card).getByText(/and ask when he can come by/)).toBeInTheDocument();
  });

  it("degrades to a placeholder when a proposal cites a missing or stale segment", async () => {
    const captured = consentedOperation({
      id: "brain_dump_citations_stale",
      status: "awaiting_confirmation",
      revision: 4,
      // The cited segment was superseded during reconciliation and is no longer
      // present; the review screen must not crash resolving it.
      segments: [{ id: "seg_present", sequence: 1, text: "Book the dentist", stability: "stable", created_at: "2026-07-16T00:00:00Z" }],
      proposals: [proposal("proposal_1", 1, "Buy oat milk", { source_segment_ids: ["seg_missing"] })]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain_dump_citations_stale") && (!init?.method || init.method === "GET")) {
        return jsonResponse(captured);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_citations_stale/review");

    const review = await screen.findByRole("main", { name: "Review brain dump proposals" });
    const card = within(review).getByRole("textbox", { name: "Task title #1" }).closest("article") as HTMLElement;
    expect(within(card).getByText("Source utterance no longer available")).toBeInTheDocument();
    // The proposal itself still renders — one bad citation never breaks review.
    expect(within(card).getByDisplayValue("Buy oat milk")).toBeInTheDocument();
  });
});
