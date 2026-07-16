import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { BrainDumpRoute } from "./BrainDumpRoute";

interface FakeRecognitionInstance {
  start: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
  onresult: ((event: { results: Array<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
}

let recognition: FakeRecognitionInstance | null = null;
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

function renderBrainDump(initialEntry = "/brain-dump/new") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/brain-dump/:operationId" element={<BrainDumpRoute />} />
        <Route path="/brain-dump/:operationId/review" element={<BrainDumpRoute />} />
      </Routes>
    </MemoryRouter>
  );
}

function emitSpeech(text: string) {
  if (!recognition?.onresult) {
    throw new Error("recognition has not started");
  }
  recognition.onresult({ results: [{ 0: { transcript: text }, isFinal: true }] });
}

describe("BrainDumpRoute", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    recognition = null;
    function FakeRecognition() {
      recognition = {
        start: vi.fn(),
        stop: vi.fn(),
        onresult: null,
        onerror: null
      };
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
});
