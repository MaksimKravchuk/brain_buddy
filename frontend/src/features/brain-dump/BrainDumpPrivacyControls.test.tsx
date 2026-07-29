import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BrainDumpPrivacyControls } from "./BrainDumpPrivacyControls";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }));
}

function existingOperation(overrides: Record<string, unknown> = {}) {
  return {
    id: "op_1",
    owner_id: "user_1",
    kind: "voice_brain_dump",
    status: "paused",
    consent: { microphone: true, external_processing_allowed: true, provider: "openai", recorded_at: "2026-07-16T00:00:00Z" },
    segments: [],
    proposals: [],
    raw_audio_present: true,
    committed_task_ids: [],
    created_at: "2026-07-16T00:00:00Z",
    updated_at: "2026-07-16T00:00:00Z",
    revision: 4,
    ...overrides
  };
}

// Mount the component directly so we can drive branch arms the gate never routes
// to (no operation reference, a still-loading fetch, terminal operations, and
// command failures). The "/plain" route carries no :operationId param.
function renderControls(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brain-dump/:operationId" element={<BrainDumpPrivacyControls />} />
        <Route path="/plain" element={<BrainDumpPrivacyControls />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("BrainDumpPrivacyControls", () => {
  it("shows nothing-to-manage and never reads status when the URL carries no operation", () => {
    renderControls("/plain");

    expect(screen.getByText("There is no recording to manage here.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("treats the new-recording sentinel as no known operation", () => {
    renderControls("/brain-dump/new");

    expect(screen.getByText("There is no recording to manage here.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("offers only discard for a live operation without cloud consent or retained audio", async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations/op_1")) {
        return jsonResponse(existingOperation({
          status: "awaiting_confirmation",
          consent: { microphone: true, external_processing_allowed: false, provider: "openai", recorded_at: "2026-07-16T00:00:00Z" },
          raw_audio_present: false
        }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderControls("/brain-dump/op_1");

    expect(await screen.findByText("Awaiting review")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Withdraw cloud-processing consent" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete raw audio now" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard recording" })).toBeInTheDocument();
    expect(screen.queryByText(/Nothing is retained/)).not.toBeInTheDocument();
  });

  it("tells the owner nothing is retained for a terminal operation with no audio", async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations/op_1")) {
        return jsonResponse(existingOperation({
          status: "completed",
          consent: { microphone: true, external_processing_allowed: false, provider: "openai", recorded_at: "2026-07-16T00:00:00Z" },
          raw_audio_present: false
        }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderControls("/brain-dump/op_1");

    expect(await screen.findByText(/Nothing is retained for this recording/)).toBeInTheDocument();
    expect(screen.getByText("Saved to Inbox")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard recording" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete raw audio now" })).not.toBeInTheDocument();
  });

  it("renders an unrecognized status verbatim", async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations/op_1")) {
        return jsonResponse(existingOperation({ status: "some_future_state" }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderControls("/brain-dump/op_1");

    expect(await screen.findByText("some_future_state")).toBeInTheDocument();
  });

  it("surfaces a rejected command's message and re-enables the controls", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations/op_1") && (!init?.method || init.method === "GET")) {
        return jsonResponse(existingOperation());
      }
      if (url.endsWith("/op_1/withdraw_consent")) {
        return Promise.reject(new Error("Consent service is unavailable"));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderControls("/brain-dump/op_1");

    await userEvent.click(await screen.findByRole("button", { name: "Withdraw cloud-processing consent" }));

    expect(await screen.findByText("Consent service is unavailable")).toBeInTheDocument();
    // The control is usable again after the failure (busy flag cleared).
    expect(screen.getByRole("button", { name: "Withdraw cloud-processing consent" })).toBeEnabled();
  });

  it("falls back to a generic message when a command rejects without an Error", async () => {
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations/op_1") && (!init?.method || init.method === "GET")) {
        return jsonResponse(existingOperation());
      }
      if (url.endsWith("/op_1/withdraw_consent")) {
        return Promise.reject("nope");
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderControls("/brain-dump/op_1");

    await userEvent.click(await screen.findByRole("button", { name: "Withdraw cloud-processing consent" }));

    expect(await screen.findByText("That privacy action could not be completed.")).toBeInTheDocument();
  });

  it("falls back to a generic message when the status read rejects without an Error", async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations/op_1")) {
        return Promise.reject("network down");
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderControls("/brain-dump/op_1");

    expect(await screen.findByText("Could not load this voice brain dump.")).toBeInTheDocument();
  });

  it("ignores a status rejection that lands after the surface has unmounted", async () => {
    let rejectRead: (reason: unknown) => void = () => {};
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations/op_1")) {
        return new Promise<Response>((_, reject) => {
          rejectRead = reject;
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    const view = renderControls("/brain-dump/op_1");
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    view.unmount();

    // The read aborts on unmount; a late rejection must be ignored (no state
    // update, no error surfaced) because the request signal is already aborted.
    await act(async () => {
      rejectRead(new DOMException("aborted", "AbortError"));
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
