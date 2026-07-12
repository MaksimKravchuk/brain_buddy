import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import WeeklyReviewPage from "../WeeklyReviewPage";

// Mock the vnext hooks
let reviewStarted = false;
vi.mock("../../api/vnext-hooks", () => ({
  useStartWeeklyReview: () => ({
    mutate: vi.fn((_, opts) => {
      if (reviewStarted) return;
      reviewStarted = true;
      opts?.onSuccess?.({
        review: {
          id: "wr_1",
          status: "open",
          period_start: "2026-01-01T00:00:00Z",
          period_end: "2026-01-08T00:00:00Z",
          item_ids: ["cap_1", "cap_2"],
          outcome_count: 0,
          started_at: "2026-01-01T00:00:00Z"
        },
        items: [
          {
            id: "cap_1",
            source_capture_id: "cs_1",
            current_text: "Fix the bug",
            review_state: "proposed",
            kind: "task",
            source_text: "Fix the bug",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
            revision: 1
          },
          {
            id: "cap_2",
            source_capture_id: "cs_1",
            current_text: "Deploy to staging",
            review_state: "proposed",
            kind: "task",
            source_text: "Deploy to staging",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
            revision: 1
          }
        ],
        outcomes: []
      });
    }),
    isIdle: !reviewStarted,
    isPending: false
  }),
  useRecordReviewOutcome: () => ({
    mutate: vi.fn((params, opts) => opts?.onSuccess?.({
      id: "wo_1",
      weekly_review_id: params.reviewId,
      atomic_capture_id: params.captureId,
      action: params.payload.action,
      reason: null,
      avoidance_reason: null,
      decided_at: "2026-01-01T00:00:00Z"
    })),
    isPending: false
  }),
  useCompleteWeeklyReview: () => ({
    mutate: vi.fn((_, opts) => opts?.onSuccess?.({
      review_id: "wr_1",
      total_items: 2,
      kept: 1,
      edited: 0,
      deferred: 1,
      deleted: 0,
      routed: 0,
      promoted: 0,
      completed_at: "2026-01-01T00:00:00Z"
    })),
    isPending: false
  })
}));

// Mock uiStore
vi.mock("../../stores/uiStore", () => ({
  useUiStore: () => () => ({
    id: "",
    title: "",
    description: "",
    variant: "info",
    duration: 0,
    createdAt: 0,
    dismissing: false
  })
}));

function renderWithProviders(component: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{component}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("WeeklyReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reviewStarted = false;
  });

  it("loads and displays review items", async () => {
    renderWithProviders(<WeeklyReviewPage />);

    await waitFor(() => {
      expect(screen.getByText("Fix the bug")).toBeInTheDocument();
    });
    expect(screen.getByText("Deploy to staging")).toBeInTheDocument();
  });

  it("shows outcome buttons for undecided items", async () => {
    renderWithProviders(<WeeklyReviewPage />);

    await waitFor(() => {
      expect(screen.getByText("Fix the bug")).toBeInTheDocument();
    });
    // Outcome buttons should be present (2 items = 2 of each)
    expect(screen.getAllByText("Defer")).toHaveLength(2);
    expect(screen.getAllByText("Delete")).toHaveLength(2);
    expect(screen.getAllByText("Promote to CRT")).toHaveLength(2);
  });

  it("complete button is disabled until all items decided", async () => {
    renderWithProviders(<WeeklyReviewPage />);

    await waitFor(() => {
      expect(screen.getByText("Complete Review")).toBeInTheDocument();
    });
    const completeBtn = screen.getByText("Complete Review").closest("button");
    expect(completeBtn).toBeDisabled();

    // Click Defer on first item
    const deferButtons = screen.getAllByText("Defer");
    fireEvent.click(deferButtons[0]);

    await waitFor(() => {
      // Still disabled — only one of two items decided
      expect(completeBtn).toBeDisabled();
    });
  });
});
