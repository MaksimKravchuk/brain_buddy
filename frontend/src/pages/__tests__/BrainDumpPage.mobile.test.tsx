import { render, screen, waitFor } from "@testing-library/react";
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
      text: "Task one",
      created_at: "2026-07-12T12:00:00Z",
      updated_at: "2026-07-12T12:00:00Z",
      revision: 1,
    },
    {
      id: "draft-2",
      text: "Task two",
      created_at: "2026-07-12T12:00:00Z",
      updated_at: "2026-07-12T12:00:00Z",
      revision: 1,
    },
  ],
  revision: 2,
};

describe("BrainDumpPage mobile viewport (375px)", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: { id: "u1", email: "a@b.c" },
      status: "authed",
    });
    useBrainDumpStore.setState({
      sessionId: null,
      status: null,
      drafts: [],
      exportResults: [],
      loading: false,
      error: null,
    });

    // Simulate 375px mobile viewport
    Object.defineProperty(window, "innerWidth", {
      writable: true,
      configurable: true,
      value: 375,
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders and functions correctly at 375px width", async () => {
    vi.spyOn(apiClient, "createBrainDumpSession").mockResolvedValue(mockSession);
    vi.spyOn(apiClient, "uploadBrainDumpAudio").mockResolvedValue(
      mockUploadResponse
    );

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
      expect(screen.getByText("Task one")).toBeInTheDocument()
    );
    expect(screen.getByText("Task two")).toBeInTheDocument();

    // All action buttons should be present and clickable.
    expect(screen.getByTestId("save-session-btn")).toBeInTheDocument();
    expect(screen.getByTestId("record-more-btn")).toBeInTheDocument();

    // Draft action buttons should be present.
    expect(screen.getByTestId("edit-btn-draft-1")).toBeInTheDocument();
    expect(screen.getByTestId("delete-btn-draft-1")).toBeInTheDocument();
  });
});
