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

  it("009-FR-013: a flag-OFF 404 renders the same denied state, not a not-found or an error", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockRejectedValue(new ApiError("Not Found", 404, null));
    renderPage();

    expect(await screen.findByText("Access denied")).toBeInTheDocument();
    expect(screen.queryByLabelText(/account id or email/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("009-FR-005: a transient failure renders D-09 with a retry, never a permanent denial", async () => {
    const spy = vi.spyOn(apiClient, "getAdminStatus").mockRejectedValue(new Error("network down"));
    renderPage();

    expect(await screen.findByRole("heading", { name: /couldn't verify access/i })).toBeInTheDocument();
    expect(screen.queryByText("Access denied")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/account id or email/i)).not.toBeInTheDocument();

    spy.mockResolvedValue({ is_operator: true });
    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /try again/i }));
    });

    expect(await screen.findByLabelText(/account id or email/i)).toBeInTheDocument();
  });

  it("009-FR-005: a 5xx on the capability check is retryable, not a denial", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockRejectedValue(
      new ApiError("Server Error", 500, null)
    );
    renderPage();

    expect(await screen.findByRole("heading", { name: /couldn't verify access/i })).toBeInTheDocument();
    expect(screen.queryByText("Access denied")).not.toBeInTheDocument();
  });

  it("009-FR-005: fails closed on an unexpected empty capability body", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue(
      null as unknown as Awaited<ReturnType<typeof apiClient.getAdminStatus>>
    );
    renderPage();

    expect(await screen.findByText("Access denied")).toBeInTheDocument();
    expect(screen.queryByLabelText(/account id or email/i)).not.toBeInTheDocument();
  });

  it("009-FR-011: queries the capability once for the page and does not refetch on focus", async () => {
    const spy = vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    renderPage();

    expect(await screen.findByLabelText(/account id or email/i)).toBeInTheDocument();

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("visibilitychange"));
    });

    expect(spy).toHaveBeenCalledTimes(1);
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

describe("AdminPage input classification and partial failures (009-SC-001, 009-SC-003)", () => {
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

  async function submit(value: string) {
    const user = userEvent.setup();
    await act(async () => {
      await user.type(await screen.findByLabelText(/account id or email/i), value);
      await user.click(screen.getByRole("button", { name: /look up/i }));
    });
    return user;
  }

  it("009-SC-001: sends a server-valid address without a dotted domain as an email", async () => {
    const spy = vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    renderPage();

    await submit("admin@localhost");

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ email: "admin@localhost" }));
  });

  it("009-SC-001: sends malformed email-like input as an account ID, not an email", async () => {
    const spy = vi
      .spyOn(apiClient, "lookupAdminAccount")
      .mockRejectedValue(new ApiError("Not Found", 404, null));
    renderPage();

    await submit("a@");

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ account_id: "a@" }));
    expect(await screen.findByText("No account found.")).toBeInTheDocument();
  });

  it("009-SC-001: never sends an account ID as an email", async () => {
    const spy = vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    renderPage();

    await submit("user_1");

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ account_id: "user_1" }));
    expect(spy).not.toHaveBeenCalledWith(expect.objectContaining({ email: expect.anything() }));
  });

  it("009-SC-001: sends a whitespace variant as typed rather than trimming it into a match", async () => {
    const spy = vi
      .spyOn(apiClient, "lookupAdminAccount")
      .mockRejectedValue(new ApiError("Not Found", 404, null));
    renderPage();

    await submit(" member@example.com ");

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ account_id: " member@example.com " })
    );
    expect(spy).not.toHaveBeenCalledWith({ email: "member@example.com" });
    expect(await screen.findByText("No account found.")).toBeInTheDocument();
  });

  it("009-SC-003: a revoke that 404s renders the not-found copy, not a raw error", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    vi.spyOn(apiClient, "revokeAdminAccountSessions").mockRejectedValue(
      new ApiError("Not Found", 404, null)
    );
    renderPage();

    const user = await submit("member@example.com");
    expect(await screen.findByText("user_1")).toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /revoke sessions/i }));
    });
    await act(async () => {
      const dialog = screen.getByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: /revoke sessions/i }));
    });

    expect(await screen.findByText("No account found.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("009-FR-006: returns focus to the trigger on cancel, Escape and a completed revoke", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    vi.spyOn(apiClient, "revokeAdminAccountSessions").mockResolvedValue({ revoked_count: 1 });
    renderPage();

    const user = await submit("member@example.com");
    expect(await screen.findByText("user_1")).toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: /revoke sessions/i });

    await act(async () => {
      await user.click(trigger);
    });
    expect(screen.getByRole("dialog")).toHaveFocus();
    await act(async () => {
      await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: /cancel/i }));
    });
    expect(trigger).toHaveFocus();

    await act(async () => {
      await user.click(trigger);
    });
    await act(async () => {
      await user.keyboard("{Escape}");
    });
    expect(trigger).toHaveFocus();

    await act(async () => {
      await user.click(trigger);
    });
    await act(async () => {
      await user.click(
        within(screen.getByRole("dialog")).getByRole("button", { name: /revoke sessions/i })
      );
    });
    expect(await screen.findByText("Revoked 1 session.")).toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("009-FR-006: names the self-sign-out consequence only when the target is the operator", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue(account);
    renderPage();

    const user = await submit("member@example.com");
    expect(await screen.findByText("user_1")).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /revoke sessions/i }));
    });

    expect(
      within(screen.getByRole("dialog")).queryByText(/this is your own account/i)
    ).not.toBeInTheDocument();
  });

  it("009-FR-006: warns in the confirm dialog when the operator revokes their own account", async () => {
    vi.spyOn(apiClient, "lookupAdminAccount").mockResolvedValue({
      ...account,
      id: "operator-1",
      email: "operator@example.com"
    });
    renderPage();

    const user = await submit("operator@example.com");
    expect(await screen.findByText("operator-1")).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /revoke sessions/i }));
    });

    expect(
      within(screen.getByRole("dialog")).getByText(/this is your own account/i)
    ).toBeInTheDocument();
  });
});
