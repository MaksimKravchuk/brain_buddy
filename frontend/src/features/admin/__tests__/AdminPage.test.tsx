import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminAccountResponse } from "../../../api/adminTypes";
import { apiClient } from "../../../api/client";
import { useAuthStore } from "../../../stores/authStore";
import { AdminPage } from "../AdminPage";

const account: AdminAccountResponse = {
  id: "user_1",
  email: "member@example.com",
  display_name: "Member One",
  deletion_requested: false
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/admin"]}>
        <Routes>
          <Route path="/admin" element={<AdminPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("AdminPage", () => {
  beforeEach(() => {
    act(() => {
      useAuthStore.setState({
        user: { id: "operator-1", email: "operator@example.com", is_operator: true },
        status: "authed",
        deletionCancelledNotice: false
      });
    });
    vi.spyOn(apiClient, "listTasks").mockResolvedValue({
      items: [],
      next_cursor: null,
      has_more: false,
      counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 }
    });
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([]);
    vi.spyOn(apiClient, "listTags").mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the minimum account projection on a successful lookup", async () => {
    const spy = vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(screen.getByLabelText(/account id or email/i), "member@example.com");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ email: "member@example.com" }));
    expect(await screen.findByText("user_1")).toBeInTheDocument();
    expect(screen.getByText("member@example.com")).toBeInTheDocument();
    expect(screen.getByText("Member One")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
  });

  it("clears a prior account when the next lookup fails", async () => {
    const spy = vi
      .spyOn(apiClient, "lookupAdminAccount")
      .mockResolvedValueOnce(account)
      .mockRejectedValueOnce(new Error("Not Found"));
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(screen.getByLabelText(/account id or email/i), "member@example.com");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });
    expect(await screen.findByText("user_1")).toBeInTheDocument();

    await act(async () => {
      await user.clear(screen.getByLabelText(/account id or email/i));
      await user.type(screen.getByLabelText(/account id or email/i), "missing@example.com");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("user_1")).not.toBeInTheDocument();
  });

  it("revokes sessions after explicit confirmation and reports the count", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    const revokeSpy = vi.spyOn(apiClient, "revokeAdminAccountSessions").mockResolvedValue({ revoked_count: 0 });
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(screen.getByLabelText(/account id or email/i), "member@example.com");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });
    expect(await screen.findByText("user_1")).toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /revoke sessions/i }));
    });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(revokeSpy).not.toHaveBeenCalled();

    await act(async () => {
      const dialog = screen.getByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: /revoke sessions/i }));
    });

    await waitFor(() => expect(revokeSpy).toHaveBeenCalledWith("user_1"));
    expect(await screen.findByText("Revoked 0 sessions.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
