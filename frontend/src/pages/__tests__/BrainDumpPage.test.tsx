import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";
import { useBrainDumpStore } from "../../stores/brainDumpStore";
import BrainDumpPage from "../BrainDumpPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <BrainDumpPage />
    </MemoryRouter>
  );
}

const mockSession = {
  id: "session-1",
  status: "recording" as const,
  drafts: [],
  revision: 1,
};

const mockUploadResponse = {
  id: "session-1",
  status: "reviewing" as const,
  drafts: [
    {
      id: "draft-1",
      text: "Buy groceries",
      created_at: "2026-07-12T12:00:00Z",
      updated_at: "2026-07-12T12:00:00Z",
      revision: 1,
    },
    {
      id: "draft-2",
      text: "Call mom",
      created_at: "2026-07-12T12:00:00Z",
      updated_at: "2026-07-12T12:00:00Z",
      revision: 1,
    },
  ],
  revision: 2,
};

describe("BrainDumpPage", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    useBrainDumpStore.setState({
      sessionId: null,
      status: null,
      drafts: [],
      exportResults: [],
      loading: false,
      error: null,
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("creates or resumes a session on mount", async () => {
    const spy = vi
      .spyOn(apiClient, "createBrainDumpSession")
      .mockResolvedValue(mockSession);

    renderPage();

    await waitFor(() => expect(spy).toHaveBeenCalled());
  });

  it("uploads audio and shows drafts", async () => {
    vi.spyOn(apiClient, "createBrainDumpSession").mockResolvedValue(mockSession);
    const uploadSpy = vi
      .spyOn(apiClient, "uploadBrainDumpAudio")
      .mockResolvedValue(mockUploadResponse);

    renderPage();

    await waitFor(() =>
      expect(useBrainDumpStore.getState().sessionId).toBe("session-1")
    );

    const input = screen.getByTestId("audio-file-input") as HTMLInputElement;
    const file = new File(["audio"], "audio.webm", { type: "audio/webm" });
    await userEvent.upload(input, file);

    await waitFor(() => expect(uploadSpy).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText("Buy groceries")).toBeInTheDocument()
    );
    expect(screen.getByText("Call mom")).toBeInTheDocument();
  });

  it("edits a draft text", async () => {
    vi.spyOn(apiClient, "createBrainDumpSession").mockResolvedValue(mockSession);
    vi.spyOn(apiClient, "uploadBrainDumpAudio").mockResolvedValue(
      mockUploadResponse
    );
    const editSpy = vi
      .spyOn(apiClient, "editBrainDumpDraft")
      .mockResolvedValue({
        id: "session-1",
        status: "reviewing",
        drafts: [
          {
            id: "draft-1",
            text: "Edited text",
            created_at: "2026-07-12T12:00:00Z",
            updated_at: "2026-07-12T12:00:00Z",
            revision: 2,
          },
          {
            id: "draft-2",
            text: "Call mom",
            created_at: "2026-07-12T12:00:00Z",
            updated_at: "2026-07-12T12:00:00Z",
            revision: 1,
          },
        ],
        export_results: [],
        revision: 3,
      });

    renderPage();

    await waitFor(() =>
      expect(useBrainDumpStore.getState().sessionId).toBe("session-1")
    );

    const input = screen.getByTestId("audio-file-input") as HTMLInputElement;
    await userEvent.upload(
      input,
      new File(["audio"], "audio.webm", { type: "audio/webm" })
    );

    await waitFor(() =>
      expect(screen.getByText("Buy groceries")).toBeInTheDocument()
    );

    await userEvent.click(screen.getByTestId("edit-btn-draft-1"));
    const editInput = screen.getByTestId(
      "edit-input-draft-1"
    ) as HTMLInputElement;
    await userEvent.clear(editInput);
    await userEvent.type(editInput, "Edited text");
    await userEvent.click(screen.getByTestId("save-edit-draft-1"));

    await waitFor(() => expect(editSpy).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText("Edited text")).toBeInTheDocument()
    );
  });

  it("deletes a draft", async () => {
    vi.spyOn(apiClient, "createBrainDumpSession").mockResolvedValue(mockSession);
    vi.spyOn(apiClient, "uploadBrainDumpAudio").mockResolvedValue(
      mockUploadResponse
    );
    const deleteSpy = vi
      .spyOn(apiClient, "deleteBrainDumpDraft")
      .mockResolvedValue({
        id: "session-1",
        status: "reviewing",
        drafts: [
          {
            id: "draft-2",
            text: "Call mom",
            created_at: "2026-07-12T12:00:00Z",
            updated_at: "2026-07-12T12:00:00Z",
            revision: 1,
          },
        ],
        export_results: [],
        revision: 3,
      });

    renderPage();

    await waitFor(() =>
      expect(useBrainDumpStore.getState().sessionId).toBe("session-1")
    );

    const input = screen.getByTestId("audio-file-input") as HTMLInputElement;
    await userEvent.upload(
      input,
      new File(["audio"], "audio.webm", { type: "audio/webm" })
    );

    await waitFor(() =>
      expect(screen.getByText("Buy groceries")).toBeInTheDocument()
    );

    await userEvent.click(screen.getByTestId("delete-btn-draft-1"));

    await waitFor(() => expect(deleteSpy).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByText("Buy groceries")).not.toBeInTheDocument()
    );
  });

  it("saves session and shows completion", async () => {
    vi.spyOn(apiClient, "createBrainDumpSession").mockResolvedValue(mockSession);
    vi.spyOn(apiClient, "uploadBrainDumpAudio").mockResolvedValue(
      mockUploadResponse
    );
    const saveSpy = vi
      .spyOn(apiClient, "saveBrainDumpSession")
      .mockResolvedValue({
        id: "session-1",
        status: "completed",
        export_results: [
          {
            draft_id: "draft-1",
            external_ref: "rtm-001",
            success: true,
          },
          {
            draft_id: "draft-2",
            external_ref: "rtm-002",
            success: true,
          },
        ],
        revision: 3,
      });

    renderPage();

    await waitFor(() =>
      expect(useBrainDumpStore.getState().sessionId).toBe("session-1")
    );

    const input = screen.getByTestId("audio-file-input") as HTMLInputElement;
    await userEvent.upload(
      input,
      new File(["audio"], "audio.webm", { type: "audio/webm" })
    );

    await waitFor(() =>
      expect(screen.getByText("Buy groceries")).toBeInTheDocument()
    );

    await userEvent.click(screen.getByTestId("save-session-btn"));

    await waitFor(() => expect(saveSpy).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText(/Brain Dump Saved/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/2 task\(s\) exported/i)).toBeInTheDocument();
  });

  it("shows sign-in prompt when not authed", () => {
    useAuthStore.setState({ user: null, status: "anon" });

    renderPage();

    expect(screen.getByText(/please sign in/i)).toBeInTheDocument();
  });

  it("does not show a text-to-draft input", () => {
    useAuthStore.setState({ user: null, status: "anon" });
    renderPage();
    // No text input for creating drafts by typing.
    expect(screen.queryByPlaceholderText(/add.*text/i)).not.toBeInTheDocument();
  });
});
