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

function renderBrainDump(initialEntry = "/brain-dump/new", queryClient = new QueryClient()) {
  return render(
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
        return jsonResponse(operation(), 201);
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
    expect(micTrackStop).toHaveBeenCalledTimes(1);
    expect(recognition?.start).toHaveBeenCalledTimes(1);

    act(() => emitSpeech("Renew car insurance. Reply to Anna about the offsite."));
    expect(await screen.findByText("2 tasks captured")).toBeInTheDocument();
    expect(screen.getByText("Headed to inbox · 2")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("Renew car insurance")).toBeInTheDocument();
    expect(screen.getByText("Wording still changing")).toBeInTheDocument();
    expect(screen.getByText("Nothing is saved until review"));

    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(await screen.findByRole("button", { name: "Resume" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(await screen.findByRole("button", { name: "Pause" })).toBeEnabled();
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

  it("does not create a backend operation when browser speech recognition is unavailable", async () => {
    vi.stubGlobal("SpeechRecognition", undefined);
    vi.stubGlobal("webkitSpeechRecognition", undefined);
    fetchMock.mockImplementation(() => jsonResponse(operation(), 201));

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Browser speech recognition is unavailable");
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not create a backend operation when microphone permission fails", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(new Error("permission prompt rejected"));
    fetchMock.mockImplementation(() => jsonResponse(operation(), 201));

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("permission prompt rejected");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the generic microphone denial when the browser throws a non-error", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce("denied");
    fetchMock.mockImplementation(() => jsonResponse(operation(), 201));

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone permission was denied.");
    expect(fetchMock).not.toHaveBeenCalled();
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
    expect(fetchMock).toHaveBeenCalledTimes(1);

    act(() => recognition?.onerror?.({ error: "not-allowed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone permission was denied.");

    act(() => recognition?.onerror?.({ error: "network" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone error: network");
  });

  it("does not resume a paused operation when browser speech recognition becomes unavailable", async () => {
    const paused = operation({ id: "brain_dump_existing", status: "paused", revision: 3 });
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
    const paused = operation({ id: "brain_dump_existing", status: "paused", revision: 3 });
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
    const paused = operation({
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
    await userEvent.click(screen.getByRole("button", { name: "Save 0 to inbox" }));

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

  it("keeps recognition alive when finishing fails", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/finish")) {
        return Promise.reject(new Error("finish failed"));
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        const body = JSON.parse(String(init?.body));
        expect(body.segments[0]).toMatchObject({ sequence: 1, text: "Still recording after failed finish", stability: "stable" });
        return jsonResponse(operation({ revision: 2, proposals: [proposal("proposal_1", 1, "Still recording after failed finish")] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    const activeRecognition = recognition;
    await userEvent.click(screen.getByRole("button", { name: "Stop & review" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("finish failed");
    expect(screen.getByText("Recording")).toBeInTheDocument();
    expect(activeRecognition?.stop).not.toHaveBeenCalled();
    act(() => emitSpeech("Still recording after failed finish"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/brain_dump_1/transcript"), expect.anything()));
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
    const captured = operation({
      revision: 2,
      status: "awaiting_confirmation",
      proposals: [proposal("proposal_1", 1, "Renew car insurance"), proposal("proposal_2", 2, "Reply to Anna")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        return jsonResponse(captured);
      }
      if (url.endsWith("/brain_dump_1/finish")) {
        return jsonResponse(operation({ ...captured, status: "awaiting_confirmation", revision: 3 }));
      }
      if (url.endsWith("/brain_dump_1/commit")) {
        return jsonResponse(operation({ ...captured, status: "completed", revision: 4, committed_task_ids: ["task_1", "task_2"] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    act(() => emitSpeech("Renew car insurance. Reply to Anna."));
    await userEvent.click(await screen.findByRole("button", { name: "Stop & review" }));
    await userEvent.click(await screen.findByRole("button", { name: "Save 2 to inbox" }));

    expect(await screen.findByText("Saved 2 tasks to Inbox")).toBeInTheDocument();
  });

  it("preserves user-edited wording, deletes proposals and saves to native Inbox only after confirmation", async () => {
    const captured = operation({
      revision: 2,
      proposals: [proposal("proposal_1", 1, "Renew car insurance"), proposal("proposal_2", 2, "Reply to Anna")]
    });
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations") && init?.method === "POST") {
        return jsonResponse(operation(), 201);
      }
      if (url.endsWith("/brain_dump_1/transcript")) {
        return jsonResponse(captured);
      }
      if (url.endsWith("/brain_dump_1/finish")) {
        return jsonResponse(operation({ ...captured, status: "awaiting_confirmation", revision: 3 }));
      }
      if (url.includes("/proposals/proposal_1")) {
        return jsonResponse(
          operation({
            ...captured,
            revision: 4,
            proposals: [proposal("proposal_1", 1, "Renew car insurance before Friday", { status: "user_edited", user_edited: true }), proposal("proposal_2", 2, "Reply to Anna")]
          })
        );
      }
      if (url.includes("/proposals/proposal_2")) {
        return jsonResponse(
          operation({
            ...captured,
            revision: 5,
            proposals: [proposal("proposal_1", 1, "Renew car insurance before Friday", { status: "user_edited", user_edited: true }), proposal("proposal_2", 2, "Reply to Anna", { deleted: true })]
          })
        );
      }
      if (url.endsWith("/brain_dump_1/commit")) {
        return jsonResponse(
          operation({
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

    await userEvent.click(screen.getByRole("button", { name: "Save 1 to inbox" }));
    expect(await screen.findByText("Saved 1 task to Inbox")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/brain_dump_1/commit"), expect.anything());
  });

  it("ignores discard clicks before a brain dump operation exists", async () => {
    fetchMock.mockImplementation(() => Promise.reject(new Error("no requests expected")));

    renderBrainDump();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));

    expect(fetchMock).not.toHaveBeenCalled();
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
      if (url.endsWith("/brain_dump_existing/commit")) {
        return jsonResponse(operation({ ...captured, status: "completed", revision: 5, committed_task_ids: ["task_1"] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    const queryClient = new QueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    renderBrainDump("/brain-dump/brain_dump_existing/review", queryClient);
    await userEvent.click(await screen.findByRole("button", { name: "Save 1 to inbox" }));

    expect(await screen.findByText("Saved 1 task to Inbox")).toBeInTheDocument();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["tasks"] });
  });

  it("navigates to the inbox from the saved confirmation", async () => {
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
      if (url.endsWith("/brain_dump_existing/commit")) {
        return jsonResponse(operation({ ...captured, status: "completed", revision: 5, committed_task_ids: ["task_1"] }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderBrainDump("/brain-dump/brain_dump_existing/review");
    await userEvent.click(await screen.findByRole("button", { name: "Save 1 to inbox" }));
    await userEvent.click(await screen.findByRole("button", { name: "View inbox" }));

    expect(await screen.findByText("Task list route: inbox")).toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: "Save 1 to inbox" })).toBeDisabled();
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
    const paused = operation({ id: "brain_dump_existing", status: "paused", revision: 3 });
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
});
