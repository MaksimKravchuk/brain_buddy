import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../api/client";
import { reviewApi, type ReviewState } from "../../../api/review";
import { reviewKeys, useReviewState } from "../../../api/reviewHooks";
import { useAuthStore } from "../../../stores/authStore";
import { AutoParkExplainer } from "../AutoParkExplainer";
import { formatReviewDate } from "../formulation";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, acknowledgeExplainer: vi.fn(), updateSettings: vi.fn(), getState: vi.fn() } };
});
const acknowledge = vi.mocked(reviewApi.acknowledgeExplainer);
const updateSettings = vi.mocked(reviewApi.updateSettings);
const getState = vi.mocked(reviewApi.getState);

const DAY = 86_400_000;
const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();
const unseen: ReviewState = {
  settings: { threshold_days: 14, review_weekday: 5, review_time: "16:00", time_zone: "UTC", onboarded_at: null, activated_at: null, owner_park_floor_at: null, revision: 1 },
  explainer_seen: false,
  grace_until: null,
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
const seen: ReviewState = { ...unseen, explainer_seen: true, grace_until: iso(14 * DAY), settings: { ...unseen.settings, activated_at: iso(0), time_zone: "Europe/Berlin", revision: 2 } };

const onDone = vi.fn();

function renderExplainer(state: ReviewState = unseen, timeZone?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <AutoParkExplainer state={state} onDone={onDone} timeZone={timeZone} />
    </QueryClientProvider>
  );
  return { ...view, client };
}

const dialog = () => screen.getByRole("dialog", { name: "How Next stays fresh" });

beforeEach(() => {
  act(() => {
    useAuthStore.setState({ user: { id: "user-1", email: "max@example.test", feature_flags: { weekly_review: true } }, status: "authed" });
  });
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  acknowledge.mockReset();
  updateSettings.mockReset();
  getState.mockReset();
  onDone.mockReset();
});

describe("020-FR-051 D-05 auto-park explainer", () => {
  it("020-FR-051 020-FR-016 020-FR-018 states the rule, the one automatic move and the grace date, focus on the heading", () => {
    renderExplainer();

    expect(dialog()).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("heading", { name: "How Next stays fresh" })).toHaveFocus();
    expect(dialog()).toHaveTextContent("When a task stalls. If a next action keeps the same wording for 14 days, it asks for a decision.");
    expect(dialog()).toHaveTextContent("If it stays undecided. 7 days later it moves to Someday / maybe. Nothing is deleted, and you can bring it back in one click. It's the only thing the app moves on its own.");
    expect(dialog()).toHaveTextContent(`Your tasks get time. Tasks already in Next won't move before ${formatReviewDate(iso(14 * DAY))}.`);
    expect(within(dialog()).getByRole("button", { name: "Got it" })).toBeEnabled();
    expect(dialog()).toHaveClass("h-full", "sm:h-auto", "sm:w-[480px]");
  });

  it("020-FR-051 Got it records the explainer as seen with the browser's time zone, then closes", async () => {
    const user = userEvent.setup();
    acknowledge.mockResolvedValueOnce(seen);
    const { client } = renderExplainer(unseen, "Europe/Berlin");

    await user.click(screen.getByRole("button", { name: "Got it" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(acknowledge).toHaveBeenCalledWith({ time_zone: "Europe/Berlin" }, expect.any(String));
    expect(updateSettings).not.toHaveBeenCalled();
    expect(client.getQueryData(reviewKeys.state())).toEqual(seen);
  });

  it.each([
    ["Close", async (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole("button", { name: "Close" }))],
    ["Escape", async (user: ReturnType<typeof userEvent.setup>) => user.keyboard("{Escape}")]
  ])("020-FR-051 %s also records the explainer as seen", async (_label, act) => {
    const user = userEvent.setup();
    acknowledge.mockResolvedValueOnce(seen);
    renderExplainer();

    await act(user);

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(acknowledge).toHaveBeenCalledWith({ time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone }, expect.any(String));
  });

  it("020-FR-039 Change the number of days shows the threshold inline, the rule follows, and Got it saves both", async () => {
    const user = userEvent.setup();
    updateSettings.mockResolvedValueOnce({ ...unseen.settings, threshold_days: 7, owner_park_floor_at: iso(7 * DAY), revision: 2 });
    acknowledge.mockResolvedValueOnce(seen);
    renderExplainer();

    await user.click(screen.getByRole("button", { name: "Change the number of days" }));
    await user.click(screen.getByRole("radio", { name: "7 days" }));

    expect(dialog()).toHaveTextContent("If a next action keeps the same wording for 7 days, it asks for a decision.");
    expect(dialog()).toHaveTextContent(`Markers in Next update now. Because of this change, nothing moves to Someday before ${formatReviewDate(iso(7 * DAY))}.`);
    expect(screen.queryByRole("button", { name: "Change the number of days" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Got it" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(updateSettings).toHaveBeenCalledWith({ threshold_days: 7, expected_revision: 1 }, expect.any(String));
    expect(updateSettings.mock.invocationCallOrder[0]).toBeLessThan(acknowledge.mock.invocationCallOrder[0]);
  });

  it("020-FR-045 a failed acknowledgement keeps the dialog with the Ref, and Retry resends the same request", async () => {
    const user = userEvent.setup();
    acknowledge
      .mockRejectedValueOnce(new ApiError("Couldn't reach Brain Buddy", 0, null, "corr_3b9d07c2"))
      .mockResolvedValueOnce(seen);
    renderExplainer();

    await user.click(screen.getByRole("button", { name: "Got it" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save that you've seen this. Try again.");
    expect(alert).toHaveTextContent("Ref corr_3b9d07c2");
    expect(onDone).not.toHaveBeenCalled();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(acknowledge.mock.calls[1]).toEqual(acknowledge.mock.calls[0]);
  });

  it("020-FR-045 a failed threshold save is retried before the acknowledgement, and only once it is saved", async () => {
    const user = userEvent.setup();
    updateSettings
      .mockRejectedValueOnce(new ApiError("Server Error", 500, null, "corr_thr"))
      .mockResolvedValueOnce({ ...unseen.settings, threshold_days: 21, owner_park_floor_at: iso(7 * DAY), revision: 2 });
    acknowledge.mockRejectedValueOnce(new ApiError("Server Error", 500, null, "corr_ack")).mockResolvedValueOnce(seen);
    renderExplainer();

    await user.click(screen.getByRole("button", { name: "Change the number of days" }));
    await user.click(screen.getByRole("radio", { name: "21 days" }));
    await user.click(screen.getByRole("button", { name: "Got it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ref corr_thr");
    expect(acknowledge).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Ref corr_ack"));
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(updateSettings).toHaveBeenCalledTimes(2);
    expect(updateSettings.mock.calls[1]).toEqual(updateSettings.mock.calls[0]);
    expect(acknowledge).toHaveBeenCalledTimes(2);
  });

  /** The explainer as the shell mounts it: fed by the live review state query. */
  function LiveExplainer(): React.JSX.Element | null {
    const state = useReviewState().data;
    return state ? <AutoParkExplainer state={state} onDone={onDone} /> : null;
  }

  function renderLive() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <LiveExplainer />
      </QueryClientProvider>
    );
    return client;
  }

  it("020-FR-039 020-FR-045 a threshold changed after a saved one is sent under a new key against the saved revision, so Retry cannot loop on 409", async () => {
    const user = userEvent.setup();
    getState.mockResolvedValue(unseen);
    const usedKeys = new Map<string, string>();
    updateSettings.mockImplementation(async (body, key) => {
      const sent = JSON.stringify(body);
      if (usedKeys.has(key) && usedKeys.get(key) !== sent) {
        throw new ApiError("Idempotency key reused.", 409, { message: "x", detail: { reason: "idempotency_conflict" } }, "corr_reuse");
      }
      usedKeys.set(key, sent);
      return { ...unseen.settings, threshold_days: body.threshold_days as 7 | 14 | 21 | 28, owner_park_floor_at: iso(7 * DAY), revision: body.expected_revision + 1 };
    });
    acknowledge.mockRejectedValueOnce(new ApiError("Server Error", 500, null, "corr_ack")).mockResolvedValueOnce(seen);
    renderLive();

    await user.click(await screen.findByRole("button", { name: "Change the number of days" }));
    await user.click(screen.getByRole("radio", { name: "21 days" }));
    await user.click(screen.getByRole("button", { name: "Got it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ref corr_ack");

    await user.click(screen.getByRole("radio", { name: "28 days" }));
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(updateSettings).toHaveBeenCalledTimes(2);
    expect(updateSettings.mock.calls[0][0]).toEqual({ threshold_days: 21, expected_revision: 1 });
    expect(updateSettings.mock.calls[1][0]).toEqual({ threshold_days: 28, expected_revision: 2 });
    expect(updateSettings.mock.calls[1][1]).not.toBe(updateSettings.mock.calls[0][1]);
    expect(acknowledge).toHaveBeenCalledTimes(2);
  });

  it("020-FR-045 a threshold save refused as changed elsewhere refetches the state, and Retry saves against the fresh revision", async () => {
    const user = userEvent.setup();
    const changedElsewhere: ReviewState = { ...unseen, settings: { ...unseen.settings, review_time: "09:00", revision: 3 } };
    getState.mockResolvedValueOnce(unseen).mockResolvedValue(changedElsewhere);
    updateSettings
      .mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "x", detail: { resource: "review_settings", id: "user-1" } }, "corr_stale"))
      .mockResolvedValueOnce({ ...changedElsewhere.settings, threshold_days: 21, owner_park_floor_at: iso(7 * DAY), revision: 4 });
    acknowledge.mockResolvedValueOnce(seen);
    renderLive();

    await user.click(await screen.findByRole("button", { name: "Change the number of days" }));
    await user.click(screen.getByRole("radio", { name: "21 days" }));
    await user.click(screen.getByRole("button", { name: "Got it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ref corr_stale");
    await waitFor(() => expect(getState).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(updateSettings.mock.calls[1][0]).toEqual({ threshold_days: 21, expected_revision: 3 });
    expect(updateSettings.mock.calls[1][1]).not.toBe(updateSettings.mock.calls[0][1]);
    expect(acknowledge).toHaveBeenCalledTimes(1);
  });

  it("020-FR-051 020-FR-042 a threshold saved for one account never chains an acknowledgement after the session switched to another", async () => {
    const user = userEvent.setup();
    let release: () => void = () => undefined;
    updateSettings.mockImplementationOnce(() => new Promise((resolve) => {
      release = () => resolve({ ...unseen.settings, threshold_days: 21, owner_park_floor_at: iso(7 * DAY), revision: 2 });
    }));
    renderExplainer();

    await user.click(screen.getByRole("button", { name: "Change the number of days" }));
    await user.click(screen.getByRole("radio", { name: "21 days" }));
    await user.click(screen.getByRole("button", { name: "Got it" }));
    await waitFor(() => expect(updateSettings).toHaveBeenCalledTimes(1));

    act(() => {
      useAuthStore.setState({ user: { id: "user-2", email: "b@example.test", feature_flags: { weekly_review: true } }, status: "authed" });
    });
    await act(async () => release());
    await act(() => new Promise<void>((resolve) => setTimeout(resolve, 20)));

    expect(acknowledge).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("020-FR-045 a failure without a reference shows no empty Ref line", async () => {
    const user = userEvent.setup();
    acknowledge.mockRejectedValueOnce(new Error("socket hang up"));
    renderExplainer();

    await user.click(screen.getByRole("button", { name: "Got it" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't save that you've seen this. Try again.");
    expect(alert).not.toHaveTextContent(/Ref/);
  });

  it("020-FR-040 offline: Got it is disabled with the reason, and Close leaves it unseen for next time", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    renderExplainer();

    expect(screen.getByRole("button", { name: "Got it" })).toBeDisabled();
    expect(dialog()).toHaveTextContent("You're offline. Try again when you're back online.");
    await user.keyboard("{Escape}");
    expect(onDone).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onDone).toHaveBeenCalledTimes(2);
    expect(acknowledge).not.toHaveBeenCalled();
  });

  it("020-FR-051 keeps focus inside the dialog", async () => {
    const user = userEvent.setup();
    renderExplainer();
    const close = screen.getByRole("button", { name: "Close" });
    const gotIt = screen.getByRole("button", { name: "Got it" });

    screen.getByRole("button", { name: "Change the number of days" }).focus();
    await user.tab();
    expect(gotIt).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(gotIt).toHaveFocus();
    screen.getByRole("heading", { name: "How Next stays fresh" }).focus();
    await user.tab({ shift: true });
    expect(gotIt).toHaveFocus();
    await user.keyboard("a");
    expect(onDone).not.toHaveBeenCalled();
  });

  it("020-FR-051 ignores Escape and Close while the acknowledgement is on its way", async () => {
    const user = userEvent.setup();
    let resolve: (state: ReviewState) => void = () => undefined;
    acknowledge.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    renderExplainer();

    await user.click(screen.getByRole("button", { name: "Got it" }));
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    screen.getByRole("heading", { name: "How Next stays fresh" }).focus();
    await user.keyboard("{Escape}");
    expect(acknowledge).toHaveBeenCalledTimes(1);

    await act(async () => resolve(seen));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("020-FR-051 is never shown once the explainer was seen on any device", () => {
    renderExplainer(seen);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("020-FR-016 states the server's grace date once it is known", () => {
    renderExplainer({ ...unseen, grace_until: "2026-10-23T08:00:00Z" });
    expect(dialog()).toHaveTextContent(`Tasks already in Next won't move before ${formatReviewDate("2026-10-23T08:00:00Z")}.`);
  });
});
