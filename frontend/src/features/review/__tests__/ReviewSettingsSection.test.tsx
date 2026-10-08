import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../api/client";
import { ProtectedRoute } from "../../../components/auth/ProtectedRoute";
import { reviewApi, type ReviewSettings, type ReviewState } from "../../../api/review";
import { useThresholdNotice } from "../../../api/reviewHooks";
import { useAuthStore } from "../../../stores/authStore";
import { formatReviewDate } from "../formulation";
import { ReviewSettingsSection, ThresholdControl } from "../ReviewSettingsSection";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, getState: vi.fn(), updateSettings: vi.fn() } };
});
const getState = vi.mocked(reviewApi.getState);
const updateSettings = vi.mocked(reviewApi.updateSettings);

const DAY = 86_400_000;
const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();
const settings: ReviewSettings = {
  threshold_days: 14,
  review_weekday: 5,
  review_time: "16:00",
  time_zone: "Europe/Berlin",
  onboarded_at: null,
  activated_at: iso(-30 * DAY),
  owner_park_floor_at: null,
  revision: 3
};
const state: ReviewState = {
  settings,
  explainer_seen: true,
  grace_until: iso(-16 * DAY),
  last_counted_review_at: null,
  last_counted_review: null,
  next_review_at: null,
  restart_mode: false,
  open_session: null,
  unseen_parks: [],
  counts: { asks_for_decision: 0, moves_tomorrow: 0 },
  receipts: [],
  server_now: iso(0)
};

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ReviewSettingsSection />
    </QueryClientProvider>
  );
  return client;
}

const option = (days: number) => screen.getByRole("radio", { name: `${days} days` });

beforeEach(() => {
  act(() => {
    useAuthStore.setState({ user: { id: "user-1", email: "max@example.test", feature_flags: { weekly_review: true } }, status: "authed" });
  });
  getState.mockResolvedValue(state);
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  vi.useRealTimers();
  getState.mockReset();
  updateSettings.mockReset();
  act(() => {
    useAuthStore.setState({ user: null, status: "loading" });
  });
});

describe("020-FR-039 D-04 review threshold setting", () => {
  it("020-FR-039 shows the four thresholds with the current one chosen, in one labelled group", async () => {
    renderSection();

    const group = await screen.findByRole("radiogroup", { name: "Ask for a decision after" });
    expect(within(group).getAllByRole("radio").map((radio) => radio.getAttribute("aria-label") ?? radio.closest("label")?.textContent)).toEqual([
      "7 days",
      "14 days",
      "21 days",
      "28 days"
    ]);
    expect(option(14)).toBeChecked();
    expect(screen.getByRole("heading", { name: "Weekly review" })).toBeInTheDocument();
    expect(screen.getByText("Tasks move to Someday 7 days after they start asking.")).toBeInTheDocument();
  });

  it("020-FR-039 saves on change and states the floor the change sets", async () => {
    const user = userEvent.setup();
    const saved = { ...settings, threshold_days: 7 as const, owner_park_floor_at: iso(7 * DAY), revision: 4 };
    updateSettings.mockResolvedValueOnce(saved);
    renderSection();

    const seven = await screen.findByRole("radio", { name: "7 days" });
    getState.mockResolvedValue({ ...state, settings: saved });
    await user.click(seven);

    expect(updateSettings).toHaveBeenCalledWith({ threshold_days: 7, expected_revision: 3 }, expect.any(String));
    expect(await screen.findByText(`Saved. Markers in Next update now. Because of this change, nothing moves to Someday before ${formatReviewDate(iso(7 * DAY))}.`)).toBeInTheDocument();
    expect(option(7)).toBeChecked();
    // Next actions shows the one-time "threshold just changed" note for this account (D-01).
    expect(useThresholdNotice.getState().notice).toEqual({ accountId: "user-1", threshold_days: 7, floor: saved.owner_park_floor_at });
  });

  it("020-FR-045 a failed save keeps the old value, shows the Ref and retries with the same key", async () => {
    const user = userEvent.setup();
    updateSettings
      .mockRejectedValueOnce(new ApiError("Couldn't reach Brain Buddy", 0, null, "corr_4e5d9a20"))
      .mockResolvedValueOnce({ ...settings, threshold_days: 21, owner_park_floor_at: iso(7 * DAY), revision: 4 });
    renderSection();

    await user.click(await screen.findByRole("radio", { name: "21 days" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your new threshold couldn't be saved. It's still 14 days.");
    expect(alert).toHaveTextContent("Ref corr_4e5d9a20");
    expect(option(14)).toBeChecked();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await screen.findByText(/^Saved\./);
    expect(updateSettings.mock.calls[1]).toEqual(updateSettings.mock.calls[0]);
  });

  it("020-FR-045 a save refused because the settings moved on retries against the current revision", async () => {
    const user = userEvent.setup();
    updateSettings
      .mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "stale", detail: { resource: "review_settings", id: "user-1" } }, "corr_409"))
      .mockResolvedValueOnce({ ...settings, threshold_days: 28, owner_park_floor_at: iso(7 * DAY), revision: 6 });
    renderSection();

    const twentyEight = await screen.findByRole("radio", { name: "28 days" });
    // Another device changed the settings meanwhile: the refetch sees revision 5.
    getState.mockResolvedValue({ ...state, settings: { ...settings, revision: 5 } });
    await user.click(twentyEight);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Ref corr_409");
    await waitFor(() => expect(getState).toHaveBeenCalledTimes(2));
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await screen.findByText(/^Saved\./);
    expect(updateSettings.mock.calls[1][0]).toEqual({ threshold_days: 28, expected_revision: 5 });
    expect(updateSettings.mock.calls[1][1]).not.toBe(updateSettings.mock.calls[0][1]);
  });

  it("020-FR-040 offline the control cannot save and says why", async () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    renderSection();

    expect(await screen.findByText("You're offline. Changes can't be saved. Retry when you're back online.")).toBeInTheDocument();
    for (const days of [7, 14, 21, 28]) {
      expect(option(days)).toBeDisabled();
    }
  });

  it("020-FR-045 shows static placeholders only once loading takes longer than 300 ms, and a failed load with its Ref", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    getState.mockReturnValue(new Promise<ReviewState>(() => undefined));
    renderSection();
    expect(screen.queryByTestId("review-settings-placeholder")).not.toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.getByTestId("review-settings-placeholder")).toBeInTheDocument();
    vi.useRealTimers();
    cleanup();

    const user = userEvent.setup();
    getState.mockReset();
    getState.mockRejectedValueOnce(new ApiError("Server Error", 500, null, "corr_load")).mockResolvedValueOnce(state);
    renderSection();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't load your review settings.");
    expect(alert).toHaveTextContent("Ref corr_load");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("radiogroup", { name: "Ask for a decision after" })).toBeInTheDocument();
  });

  it("020-FR-045 a failed save without a reference shows no empty Ref line", async () => {
    const user = userEvent.setup();
    updateSettings.mockRejectedValueOnce(new Error("socket hang up"));
    renderSection();

    await user.click(await screen.findByRole("radio", { name: "21 days" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your new threshold couldn't be saved. It's still 14 days.");
    expect(alert).not.toHaveTextContent(/Ref/);
  });

  it("020-FR-045 a failed load without a reference shows no empty Ref line", async () => {
    getState.mockReset();
    getState.mockRejectedValueOnce(new Error("socket hang up"));
    renderSection();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't load your review settings.");
    expect(alert).not.toHaveTextContent(/Ref/);
  });

  it("020-FR-045 020-FR-042 a failed save of one account never carries into the next: no failure, no Retry of the old threshold", async () => {
    const user = userEvent.setup();
    updateSettings.mockRejectedValueOnce(new ApiError("Server Error", 500, null, "corr_a"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/settings/account"]}>
          <Routes>
            <Route path="/settings/account" element={<ProtectedRoute><ReviewSettingsSection /></ProtectedRoute>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    await user.click(await screen.findByRole("radio", { name: "21 days" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ref corr_a");

    getState.mockResolvedValue({ ...state, settings: { ...settings, threshold_days: 28, revision: 9 } });
    act(() => {
      useAuthStore.setState({ user: { id: "user-2", email: "b@example.test", feature_flags: { weekly_review: true } }, status: "authed" });
    });

    await waitFor(() => expect(option(28)).toBeChecked());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(updateSettings).toHaveBeenCalledTimes(1);
  });

  it("020-FR-042 renders nothing while the weekly_review flag is off", () => {
    act(() => {
      useAuthStore.setState({ user: { id: "user-1", email: "max@example.test" } });
    });
    renderSection();
    expect(screen.queryByRole("heading", { name: "Weekly review" })).not.toBeInTheDocument();
    expect(getState).not.toHaveBeenCalled();
  });

  it("020-FR-040 stacks each row at 390 px", async () => {
    renderSection();
    const group = await screen.findByRole("radiogroup", { name: "Ask for a decision after" });
    expect(group.parentElement).toHaveClass("flex-col", "sm:flex-row");
  });
});

describe("020-FR-039 the shared threshold control", () => {
  it("020-FR-039 reports the chosen value and can be disabled", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<ThresholdControl value={14} onChange={onChange} disabled={false} />);

    await user.click(option(21));
    expect(onChange).toHaveBeenCalledWith(21);

    rerender(<ThresholdControl value={21} onChange={onChange} disabled />);
    expect(option(21)).toBeChecked();
    expect(option(7)).toBeDisabled();
  });
});
