import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminAccountResponse } from "../../../api/adminTypes";
import { ApiError, apiClient } from "../../../api/client";
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

function mockTaskShellQueries() {
  vi.spyOn(apiClient, "listTasks").mockResolvedValue({
    items: [],
    next_cursor: null,
    has_more: false,
    counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 }
  });
  vi.spyOn(apiClient, "listProjects").mockResolvedValue([]);
  vi.spyOn(apiClient, "listTags").mockResolvedValue([]);
}

describe("AdminPage capability gate (009-FR-005, 009-SC-002)", () => {
  beforeEach(() => {
    act(() => {
      useAuthStore.setState({
        user: { id: "operator-1", email: "operator@example.com" },
        status: "authed",
        deletionCancelledNotice: false
      });
    });
    mockTaskShellQueries();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("009-FR-005: shows a checking-access state and no lookup form while the capability check is pending", () => {
    vi.spyOn(apiClient, "getAdminStatus").mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(screen.getByRole("status")).toHaveTextContent(/checking access/i);
    expect(screen.queryByLabelText(/account id or email/i)).not.toBeInTheDocument();
  });

  it("009-SC-002: denies access and reveals no account data for a 403 non-operator", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockRejectedValue(new ApiError("Forbidden", 403, null));
    renderPage();

    expect(await screen.findByText("Access denied")).toBeInTheDocument();
    expect(screen.queryByLabelText(/account id or email/i)).not.toBeInTheDocument();
    expect(screen.queryByText(account.email)).not.toBeInTheDocument();
  });

  it("009-SC-002: denies access when the capability check itself errors", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockRejectedValue(new Error("network down"));
    renderPage();

    expect(await screen.findByText("Access denied")).toBeInTheDocument();
    expect(screen.queryByLabelText(/account id or email/i)).not.toBeInTheDocument();
  });
});

describe("AdminPage lookup and revoke (009-SC-001, 009-SC-003)", () => {
  beforeEach(() => {
    act(() => {
      useAuthStore.setState({
        user: { id: "operator-1", email: "operator@example.com" },
        status: "authed",
        deletionCancelledNotice: false
      });
    });
    vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    mockTaskShellQueries();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("009-FR-005, 009-SC-001: renders only the minimum four fields on a successful lookup by email", async () => {
    const spy = vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(await screen.findByLabelText(/account id or email/i), "member@example.com");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ email: "member@example.com" }));
    expect(await screen.findByText("user_1")).toBeInTheDocument();
    expect(screen.getByText("member@example.com")).toBeInTheDocument();
    expect(screen.getByText("Member One")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
  });

  it("does not submit a lookup for a whitespace-only query", async () => {
    const spy = vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    renderPage();

    const user = userEvent.setup();
    const input = await screen.findByLabelText(/account id or email/i);
    await act(async () => {
      await user.type(input, "   ");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });

    expect(spy).not.toHaveBeenCalled();
    expect(input).toHaveValue("   ");
    expect(screen.queryByText("No account found.")).not.toBeInTheDocument();
  });

  it("renders a missing display name and a pending deletion as an em dash and Yes", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue({
      ...account,
      display_name: null,
      deletion_requested: true
    });
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(await screen.findByLabelText(/account id or email/i), "member@example.com");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });

    expect(await screen.findByText("—")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });

  it("009-SC-001: looks up an account by its exact account ID rather than email", async () => {
    const spy = vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(await screen.findByLabelText(/account id or email/i), "user_1");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ account_id: "user_1" }));
    expect(await screen.findByText("user_1")).toBeInTheDocument();
  });

  it("shows no account found on an exact-match miss", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockRejectedValue(new ApiError("Not Found", 404, null));
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(await screen.findByLabelText(/account id or email/i), "missing@example.com");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });

    expect(await screen.findByText("No account found.")).toBeInTheDocument();
  });

  it("clears a prior account when the next lookup fails", async () => {
    const spy = vi
      .spyOn(apiClient, "lookupAdminAccount")
      .mockResolvedValueOnce(account)
      .mockRejectedValueOnce(new Error("Not Found"));
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(await screen.findByLabelText(/account id or email/i), "member@example.com");
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

  it("009-FR-006: does not revoke on the first click and requires a confirmation dialog", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    const revokeSpy = vi.spyOn(apiClient, "revokeAdminAccountSessions").mockResolvedValue({ revoked_count: 3 });
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(await screen.findByLabelText(/account id or email/i), "member@example.com");
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
      await user.click(within(dialog).getByRole("button", { name: /cancel/i }));
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(revokeSpy).not.toHaveBeenCalled();
  });

  it("009-FR-006, 009-SC-003: revokes only after explicit confirmation, reporting zero revoked as success", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    const revokeSpy = vi.spyOn(apiClient, "revokeAdminAccountSessions").mockResolvedValue({ revoked_count: 0 });
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(await screen.findByLabelText(/account id or email/i), "member@example.com");
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

  it("uses singular copy when exactly one session is revoked", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    const revokeSpy = vi.spyOn(apiClient, "revokeAdminAccountSessions").mockResolvedValue({ revoked_count: 1 });
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(await screen.findByLabelText(/account id or email/i), "member@example.com");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });
    expect(await screen.findByText("user_1")).toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /revoke sessions/i }));
    });
    await act(async () => {
      const dialog = screen.getByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: /revoke sessions/i }));
    });

    await waitFor(() => expect(revokeSpy).toHaveBeenCalledWith("user_1"));
    expect(await screen.findByText("Revoked 1 session.")).toBeInTheDocument();
  });

  it("surfaces a revoke error and keeps the account visible for a retry", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    const revokeSpy = vi.spyOn(apiClient, "revokeAdminAccountSessions").mockRejectedValue(new Error("revoke failed"));
    renderPage();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(await screen.findByLabelText(/account id or email/i), "member@example.com");
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });
    expect(await screen.findByText("user_1")).toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /revoke sessions/i }));
    });
    await act(async () => {
      const dialog = screen.getByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: /revoke sessions/i }));
    });

    await waitFor(() => expect(revokeSpy).toHaveBeenCalledWith("user_1"));
    expect(await screen.findByText("revoke failed")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("user_1")).toBeInTheDocument();
  });
});
