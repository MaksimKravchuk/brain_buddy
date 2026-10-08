import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { modernAuthApi } from "../../../api/modernAuth";
import { accountKeys } from "../../../api/accountHooks";
import type { AccountResponse } from "../../../api/accountTypes";
import { ApiError, apiClient } from "../../../api/client";
import { reviewApi, type ReviewSettings, type ReviewState } from "../../../api/review";
import { useAuthStore } from "../../../stores/authStore";
import { AccountSettingsPage } from "../AccountSettingsPage";

vi.mock("../../../api/modernAuth", () => ({ modernAuthApi: { methods: vi.fn(), accountMethods: vi.fn() } }));
vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, getState: vi.fn(), updateSettings: vi.fn() } };
});

const account: AccountResponse = {
  id: "user_1",
  email: "primary@example.com",
  display_name: null,
  completed_task_count: 2,
  created_at: "2026-08-01T00:00:00Z",
  deletion_requested_at: null,
  purge_at: null
};

function LoginProbe(): React.JSX.Element {
  const location = useLocation();
  const state = location.state as { deletionScheduled?: string } | null;
  return <div>login page {state?.deletionScheduled ?? ""}</div>;
}

function createQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage(client = createQueryClient()) {
  return {
    ...render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/settings/account"]}>
        <Routes>
          <Route path="/settings/account" element={<AccountSettingsPage />} />
          <Route path="/login" element={<LoginProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
    ),
    client
  };
}

describe("AccountSettingsPage", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: { id: "user_1", email: "primary@example.com" },
      status: "authed",
      deletionCancelledNotice: false
    });
    vi.spyOn(apiClient, "getAccount").mockResolvedValue(account);
    vi.spyOn(apiClient, "listTasks").mockResolvedValue({
      items: [],
      next_cursor: null,
      has_more: false,
      counts_by_state: { inbox: 1, next: 2, waiting: 0, someday: 0 }
    });
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([]);
    vi.spyOn(apiClient, "listTags").mockResolvedValue([]);
    vi.mocked(modernAuthApi.methods).mockResolvedValue({ password: true, google: false, apple: false, email: true, web_account_origin: null });
    vi.mocked(modernAuthApi.accountMethods).mockResolvedValue({ account_id: account.id, email: account.email, email_verified: false, email_delivery: "available", has_password: true, methods: [{ method: "password", state: "active", usable: true, connected_at: null }] });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("018-FR-010 shows a polite completed-count placeholder immediately", () => {
    vi.spyOn(apiClient, "getAccount").mockReturnValue(
      new Promise<AccountResponse>(() => undefined)
    );

    renderPage();

    expect(screen.getByText("Completed tasks: …")).toHaveAttribute("role", "status");
    expect(screen.getByLabelText(/display name/i)).toBeInTheDocument();
  });

  it("018-FR-001 shows exact zero and nonzero completed-task counts", async () => {
    const getAccount = vi.spyOn(apiClient, "getAccount");
    renderPage();

    const completedCount = await screen.findByText("Completed tasks: 2");
    expect(completedCount).toBeInTheDocument();
    expect(completedCount).toHaveAttribute("aria-live", "polite");
    expect(completedCount).toHaveAttribute("aria-atomic", "true");

    getAccount.mockResolvedValue({ ...account, completed_task_count: 0 });
    const zeroClient = createQueryClient();
    renderPage(zeroClient);

    expect(await screen.findByText("Completed tasks: 0")).toBeInTheDocument();
  });

  it("018-FR-010 shows unavailable copy for an authenticated initial failure", async () => {
    vi.spyOn(apiClient, "getAccount").mockRejectedValue(
      new ApiError("Server Error", 500, { message: "Internal storage error." })
    );

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Completed tasks unavailable. Refresh the page to try again."
    );
    expect(screen.queryByText(/Completed tasks: \d/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/display name/i)).toBeInTheDocument();
  });

  it("018-SC-004 hides stale count data after an authenticated failed refetch", async () => {
    const client = createQueryClient();
    client.setQueryData(accountKeys.detail(), {
      ...account,
      completed_task_count: 9
    });
    vi.spyOn(apiClient, "getAccount").mockRejectedValue(
      new ApiError("Server Error", 503, { message: "Storage unavailable." }, "corr-015")
    );

    renderPage(client);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Completed tasks unavailable. Refresh the page to try again. (ref: corr-015)"
    );
    expect(screen.queryByText("Completed tasks: 9")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/display name/i)).toBeInTheDocument();
  });

  it("shows the current account in the email section", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/you currently sign in as primary@example.com/i)).toBeInTheDocument()
    );
  });

  it("018-FR-009 keeps the returned count after a profile save", async () => {
    const updated = {
      ...account,
      display_name: "Maks",
      completed_task_count: 3
    };
    const spy = vi.spyOn(apiClient, "updateProfile").mockResolvedValue(updated);
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(screen.getByLabelText(/display name/i), "Maks");
      await user.click(screen.getByRole("button", { name: /save profile/i }));
    });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ display_name: "Maks" }));
    await waitFor(() => expect(screen.getByText(/profile saved/i)).toBeInTheDocument());
    expect(useAuthStore.getState().user?.display_name).toBe("Maks");
    expect(screen.getByText("Completed tasks: 3")).toBeInTheDocument();
  });

  it("surfaces profile-save failures as an alert", async () => {
    vi.spyOn(apiClient, "updateProfile").mockRejectedValue(
      new ApiError("Bad Request", 400, { message: "Display name is too long." }, "corr-9")
    );
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /save profile/i }));
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/display name is too long.*corr-9/i)
    );
  });

  it("023-FR-013 exposes direct deletion with the safe keep-account default", async () => {
    const client = createQueryClient();
    render(<QueryClientProvider client={client}><MemoryRouter><AccountSettingsPage directDelete /></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep account" })).toHaveFocus();
    expect(screen.queryByLabelText("Current password")).not.toBeInTheDocument();
  });

  describe("020-FR-039 D-04 Weekly review section", () => {
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

    beforeEach(() => {
      useAuthStore.setState({ user: { id: "user_1", email: "primary@example.com", feature_flags: { weekly_review: true } } });
      vi.mocked(reviewApi.getState).mockResolvedValue(state);
    });

    afterEach(() => {
      vi.mocked(reviewApi.getState).mockReset();
      vi.mocked(reviewApi.updateSettings).mockReset();
    });

    it("020-FR-039 sits on the account page with the threshold control and states the floor after a change", async () => {
      const user = userEvent.setup();
      const saved = { ...settings, threshold_days: 7 as const, owner_park_floor_at: iso(7 * DAY), revision: 4 };
      vi.mocked(reviewApi.updateSettings).mockResolvedValueOnce(saved);
      renderPage();

      const seven = await screen.findByRole("radio", { name: "7 days" });
      expect(screen.getByRole("heading", { name: "Weekly review" })).toBeInTheDocument();
      vi.mocked(reviewApi.getState).mockResolvedValue({ ...state, settings: saved });
      await user.click(seven);

      expect(await screen.findByText(/^Saved\. Markers in Next update now\. Because of this change, nothing moves to Someday before /)).toBeInTheDocument();
      expect(reviewApi.updateSettings).toHaveBeenCalledWith({ threshold_days: 7, expected_revision: 3 }, expect.any(String));
    });

    it("020-FR-045 a failed save keeps the old threshold and shows the Ref", async () => {
      const user = userEvent.setup();
      vi.mocked(reviewApi.updateSettings).mockRejectedValueOnce(new ApiError("Server Error", 500, null, "corr_settings"));
      renderPage();

      await user.click(await screen.findByRole("radio", { name: "21 days" }));

      const alert = await screen.findByText("Your new threshold couldn't be saved. It's still 14 days.");
      expect(alert.parentElement).toHaveTextContent("Ref corr_settings");
      expect(screen.getByRole("radio", { name: "14 days" })).toBeChecked();
    });

    it("020-FR-042 keeps the page without the section while the flag is off", async () => {
      useAuthStore.setState({ user: { id: "user_1", email: "primary@example.com" } });
      renderPage();
      expect(await screen.findByText("Completed tasks: 2")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Weekly review" })).not.toBeInTheDocument();
      expect(reviewApi.getState).not.toHaveBeenCalled();
    });
  });
});
