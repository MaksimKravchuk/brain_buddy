import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../api/client";
import { reviewApi, type ReviewSettings } from "../../../api/review";
import { getReviewCacheScope, reviewKeys } from "../../../api/reviewHooks";
import { formatReviewDate } from "../formulation";
import { OnboardingDialog } from "../OnboardingDialog";
import { useAuthStore } from "../../../stores/authStore";
import { DAY, iso, signIn, stateFixture } from "./reviewKit";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, updateSettings: vi.fn() } };
});

const updateSettings = vi.mocked(reviewApi.updateSettings);
const onClose = vi.fn();

const grace = iso(10 * DAY);
const state = stateFixture({ grace_until: grace, settings: { ...stateFixture().settings, onboarded_at: null, activated_at: iso(-4 * DAY), revision: 2 } });
const saved: ReviewSettings = { ...state.settings, onboarded_at: iso(0), revision: 3 };

function renderDialog(overrides: Partial<typeof state> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(reviewKeys.state(getReviewCacheScope("user-1")), { ...state, ...overrides });
  render(
    <QueryClientProvider client={client}>
      <OnboardingDialog state={{ ...state, ...overrides }} timeZone="Europe/Berlin" onClose={onClose} />
    </QueryClientProvider>
  );
  return client;
}

beforeEach(() => {
  signIn();
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  updateSettings.mockReset();
  onClose.mockReset();
});

describe("020-FR-016 onboarding dialog", () => {
  it("020-FR-016 opens as a modal with focus on A weekly reset and the three points, with the grace date", () => {
    renderDialog();

    const dialog = screen.getByRole("dialog", { name: "A weekly reset" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("heading", { name: "A weekly reset" })).toHaveFocus();
    expect(within(dialog).getByText(/Once a week: see what you got done, empty your head, and choose what's next\./)).toBeInTheDocument();
    expect(within(dialog).getByText("If a next action keeps the same wording for 14 days, it asks for a decision. A stall is feedback on the wording, not on you.")).toBeInTheDocument();
    expect(within(dialog).getByText(/7 days later it moves to Someday \/ maybe/)).toBeInTheDocument();
    expect(within(dialog).getByText(`It's the only thing the app moves on its own. Tasks you had when you first saw this rule won't move before ${formatReviewDate(grace)}.`)).toBeInTheDocument();
  });

  it("020-FR-016 without a grace date it leaves that sentence out", () => {
    renderDialog({ grace_until: null });

    expect(screen.getByText("It's the only thing the app moves on its own.")).toBeInTheDocument();
    expect(screen.queryByText(/won't move before/)).not.toBeInTheDocument();
  });

  it("020-FR-035 defaults to Friday, 16:00 and 14 days, and says the web sends no reminders", () => {
    renderDialog();

    expect(screen.getByRole("combobox", { name: "Day" })).toHaveValue("5");
    expect(screen.getByRole("combobox", { name: "Time" })).toHaveValue("16:00");
    expect(screen.getByRole("radio", { name: "14 days" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(/The web doesn't send reminders; the sidebar shows when your last review was\./)).toBeInTheDocument();
    expect(screen.getByText(/Times are in your local time zone\./)).toBeInTheDocument();
  });

  it("020-FR-036 a stored time that is not on the hour is still offered", () => {
    renderDialog({ settings: { ...state.settings, review_time: "16:30" } });

    expect(screen.getByRole("combobox", { name: "Time" })).toHaveValue("16:30");
  });

  it("020-FR-035 the rule text follows the chosen threshold", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("radio", { name: "7 days" }));

    expect(screen.getByRole("radio", { name: "7 days" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "14 days" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("If a next action keeps the same wording for 7 days, it asks for a decision. A stall is feedback on the wording, not on you.")).toBeInTheDocument();
  });

  it("020-FR-035 Continue saves the day, time, threshold and the browser's zone with onboarded and the state's revision", async () => {
    const user = userEvent.setup();
    updateSettings.mockResolvedValueOnce(saved);
    const client = renderDialog();

    await user.selectOptions(screen.getByRole("combobox", { name: "Day" }), "1");
    await user.selectOptions(screen.getByRole("combobox", { name: "Time" }), "09:00");
    await user.click(screen.getByRole("radio", { name: "21 days" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(updateSettings).toHaveBeenCalledWith(
      { onboarded: true, threshold_days: 21, review_weekday: 1, review_time: "09:00", time_zone: "Europe/Berlin", expected_revision: 2 },
      expect.any(String)
    );
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledWith(true));
    expect(client.getQueryData<typeof state>(reviewKeys.state(getReviewCacheScope("user-1")))?.settings).toEqual(saved);
  });

  it("020-FR-016 Escape and Close save nothing and leave onboarding for next time", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenLastCalledWith(false);
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(updateSettings).not.toHaveBeenCalled();
  });

  it("020-FR-045 a failed save keeps the dialog with the Ref, and Retry resends the same request under the same key", async () => {
    const user = userEvent.setup();
    updateSettings.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_onboard"));
    updateSettings.mockResolvedValueOnce(saved);
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Continue" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your review settings couldn't be saved.");
    expect(alert).toHaveTextContent("Ref corr_onboard");
    expect(onClose).not.toHaveBeenCalled();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    await vi.waitFor(() => expect(onClose).toHaveBeenCalledWith(true));
    expect(updateSettings.mock.calls[1][1]).toBe(updateSettings.mock.calls[0][1]);
  });

  it("020-FR-045 a failure that carries no Ref shows none", async () => {
    const user = userEvent.setup();
    updateSettings.mockRejectedValueOnce(new Error("socket hang up"));
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Continue" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your review settings couldn't be saved.");
    expect(alert).not.toHaveTextContent("Ref");
  });

  it("020-FR-042 a save answered after another account signed in neither closes the dialog nor writes that account's state", async () => {
    const user = userEvent.setup();
    let resolve: (value: ReviewSettings) => void = () => undefined;
    updateSettings.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    const client = renderDialog();
    const before = client.getQueryData(reviewKeys.state(getReviewCacheScope("user-1")));

    await user.click(screen.getByRole("button", { name: "Continue" }));
    act(() => signIn("user-2"));
    await act(async () => resolve(saved));

    expect(onClose).not.toHaveBeenCalled();
    expect(client.getQueryData(reviewKeys.state(getReviewCacheScope("user-1")))).toEqual(before);
    act(() => useAuthStore.setState({ user: null, status: "loading" }));
  });

  it("020-FR-045 a changed choice after a failure is a new request under a new key", async () => {
    const user = userEvent.setup();
    updateSettings.mockRejectedValueOnce(new ApiError("down", 503, null, "corr_onboard"));
    updateSettings.mockResolvedValueOnce(saved);
    renderDialog();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("alert");

    await user.click(screen.getByRole("radio", { name: "28 days" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await vi.waitFor(() => expect(onClose).toHaveBeenCalledWith(true));
    expect(updateSettings.mock.calls[1][0]).toMatchObject({ threshold_days: 28 });
    expect(updateSettings.mock.calls[1][1]).not.toBe(updateSettings.mock.calls[0][1]);
  });

  it("020-FR-040 Continue is disabled while offline, with the reason", () => {
    renderDialog();
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    act(() => { window.dispatchEvent(new Event("offline")); });

    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(screen.getByText("You're offline. Try again when you're back online.")).toBeInTheDocument();
  });

  it("020-FR-016 keeps Tab inside the dialog", async () => {
    const user = userEvent.setup();
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: "A weekly reset" });
    const buttons = within(dialog).getAllByRole("button");
    const last = buttons[buttons.length - 1];

    last.focus();
    await user.tab();
    expect(within(dialog).getByRole("button", { name: "Close" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(last).toHaveFocus();
  });
});
