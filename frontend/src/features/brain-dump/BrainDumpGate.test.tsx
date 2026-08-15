import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi, type AuthUser } from "../../api/auth";
import { useAuthStore } from "../../stores/authStore";
import { BrainDumpGate } from "./BrainDumpGate";

// The gate only needs to prove it renders (or withholds) the capture route; the
// real route is heavy and independently tested, so stand in a sentinel for it.
vi.mock("./BrainDumpRoute", () => ({
  BrainDumpRoute: () => <div data-testid="brain-dump-route">brain dump route</div>
}));

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
    consent: {
      microphone: true,
      external_processing_allowed: true,
      provider: "openai",
      recorded_at: "2026-07-16T00:00:00Z"
    },
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

// Drive the auth store the way production does: through the GET /api/auth/me
// response. Mocking `authApi.me` and hydrating exercises the full
// me-response -> store -> gate path without any backend dependency, so the test
// stands whether or not the backend has shipped the flag yet.
async function hydrateFromMeResponse(user: AuthUser | null) {
  vi.spyOn(authApi, "me").mockResolvedValue(user);
  await act(async () => {
    await useAuthStore.getState().hydrate();
  });
}

// The gate reads the operation reference from the URL, so it must render inside a
// router — that URL param is the only existing-operation reference the client
// recovers across reloads.
function renderGate(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brain-dump/:operationId" element={<BrainDumpGate />} />
        <Route path="/brain-dump/:operationId/review" element={<BrainDumpGate />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  act(() => {
    useAuthStore.setState({ user: null, status: "loading" });
  });
});

describe("BrainDumpGate", () => {
  it("renders the brain dump route when /auth/me enables the voice_brain_dump flag", async () => {
    await hydrateFromMeResponse({ id: "user_1", email: "founder@example.test", feature_flags: { voice_brain_dump: true } });

    renderGate("/brain-dump/op_1");

    expect(screen.getByTestId("brain-dump-route")).toBeInTheDocument();
    expect(screen.queryByText("Voice brain dump is off")).not.toBeInTheDocument();
  });

  it("shows only the friendly note when the flag is off and no existing operation is referenced", async () => {
    await hydrateFromMeResponse({ id: "user_1", email: "founder@example.test", feature_flags: { voice_brain_dump: false } });

    renderGate("/brain-dump/new");

    expect(screen.queryByTestId("brain-dump-route")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Voice brain dump is off" })).toBeInTheDocument();
    expect(screen.queryByText("Voice brain dump · privacy controls")).not.toBeInTheDocument();
    // No status read is attempted when there is no operation to manage.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed to the friendly note when /auth/me carries no feature_flags and no operation is referenced", async () => {
    await hydrateFromMeResponse({ id: "user_1", email: "founder@example.test" });

    renderGate("/brain-dump/new");

    expect(screen.queryByTestId("brain-dump-route")).not.toBeInTheDocument();
    expect(screen.getByText(/does not have voice brain dump enabled/i)).toBeInTheDocument();
  });

  it("keeps privacy controls reachable for an existing operation while the flag is off, with no new-capture UI", async () => {
    await hydrateFromMeResponse({ id: "user_1", email: "founder@example.test", feature_flags: { voice_brain_dump: false } });

    const commandUrls: string[] = [];
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations/op_1") && (!init?.method || init.method === "GET")) {
        return jsonResponse(existingOperation());
      }
      if (url.endsWith("/op_1/withdraw_consent")) {
        commandUrls.push("withdraw_consent");
        return jsonResponse(existingOperation({
          consent: { microphone: true, external_processing_allowed: false, provider: "openai", recorded_at: "2026-07-16T00:00:00Z" },
          revision: 5
        }));
      }
      if (url.endsWith("/op_1/delete_raw_audio")) {
        commandUrls.push("delete_raw_audio");
        return jsonResponse(existingOperation({ raw_audio_present: false, revision: 6 }));
      }
      if (url.endsWith("/op_1/cancel")) {
        commandUrls.push("cancel");
        return jsonResponse(existingOperation({ status: "cancelled", revision: 7 }));
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderGate("/brain-dump/op_1");

    // The owner sees the operation status and privacy controls, never the note.
    expect(await screen.findByText("Paused")).toBeInTheDocument();
    expect(screen.getByText("Voice brain dump · privacy controls")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Voice brain dump is off" })).not.toBeInTheDocument();
    // No new-capture affordances are offered while the flag is off.
    expect(screen.queryByRole("button", { name: "Record" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Allow secure cloud transcription" })).not.toBeInTheDocument();

    // Each standing right fires its backend command with the freshest revision.
    await userEvent.click(screen.getByRole("button", { name: "Withdraw cloud-processing consent" }));
    await waitFor(() => expect(commandUrls).toContain("withdraw_consent"));
    // Consent withdrawn -> that control drops away, the others remain.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Withdraw cloud-processing consent" })).not.toBeInTheDocument()
    );

    await userEvent.click(screen.getByRole("button", { name: "Delete raw audio now" }));
    await waitFor(() => expect(commandUrls).toContain("delete_raw_audio"));

    await userEvent.click(screen.getByRole("button", { name: "Discard recording" }));
    await waitFor(() => expect(commandUrls).toContain("cancel"));
    // After discard the operation is terminal: status reflects it and no actions remain.
    expect(await screen.findByText("Discarded")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard recording" })).not.toBeInTheDocument();

    // withdraw_consent, delete_raw_audio, cancel each POST once with expected_revision.
    const revisions = fetchMock.mock.calls
      .filter(([input]) => /\/op_1\/(withdraw_consent|delete_raw_audio|cancel)$/.test(String(input)))
      .map(([, init]) => JSON.parse(String(init?.body)).expected_revision);
    expect(revisions).toEqual([4, 5, 6]);
  });

  it("surfaces a read error but never falls back to new capture when status cannot load", async () => {
    await hydrateFromMeResponse({ id: "user_1", email: "founder@example.test", feature_flags: { voice_brain_dump: false } });

    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/brain-dump-operations/op_1")) {
        return jsonResponse({ detail: "not found" }, 404);
      }
      throw new Error(`unexpected fetch ${url}`);
    });

    renderGate("/brain-dump/op_1");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTestId("brain-dump-route")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record" })).not.toBeInTheDocument();
  });
  it("010-FR-009: a later /auth/me payload turns the capability on with no logout or reload", async () => {
    // 010-SC-004's client half: the gate re-renders straight from the refreshed
    // session state, so a member whose flag an operator just turned on gets the
    // capability without signing out, signing back in or reloading.
    await hydrateFromMeResponse({
      id: "user_1",
      email: "founder@example.test",
      feature_flags: { voice_brain_dump: false }
    });

    renderGate("/brain-dump/new");
    expect(screen.queryByTestId("brain-dump-route")).not.toBeInTheDocument();

    vi.spyOn(authApi, "me").mockResolvedValue({
      id: "user_1",
      email: "founder@example.test",
      feature_flags: { voice_brain_dump: true }
    });
    await act(async () => {
      await useAuthStore.getState().refreshSession();
    });

    expect(await screen.findByTestId("brain-dump-route")).toBeInTheDocument();
    expect(screen.queryByText("Voice brain dump is off")).not.toBeInTheDocument();
  });
});
