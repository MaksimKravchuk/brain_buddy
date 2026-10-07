import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { modernAuthApi } from "../../../api/modernAuth";

import { downloadAccountExport } from "../../../api/account";
import type { AccountResponse } from "../../../api/accountTypes";
import { ApiError, apiClient } from "../../../api/client";
import { useAuthStore } from "../../../stores/authStore";
import { AccountSettingsPage } from "../AccountSettingsPage";

vi.mock("../../../api/modernAuth", () => ({ modernAuthApi: { methods: vi.fn(), accountMethods: vi.fn() } }));

vi.mock("../../../api/account", () => ({
  downloadAccountExport: vi.fn()
}));

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

describe("023-FR-002/013 password-account rights before optional configuration", () => {
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
    vi.mocked(downloadAccountExport).mockReset();
    vi.mocked(modernAuthApi.methods).mockResolvedValue({ password: true, google: false, apple: false, email: false, web_account_origin: null });
    vi.mocked(modernAuthApi.accountMethods).mockResolvedValue({ account_id: account.id, email: account.email, email_verified: false, email_delivery: "unconfigured", has_password: true, methods: [{ method: "password", state: "active", usable: true, connected_at: null }] });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("023-FR-013 keeps a password account signed in after a rejected password change", async () => {
    vi.spyOn(apiClient, "changePassword").mockRejectedValue(new ApiError("Forbidden", 403, { detail: "Invalid password" }));
    renderPage();
    await screen.findByRole("heading", { name: "Password" });
    const user = userEvent.setup();
    await act(async () => {
      await user.type(screen.getByLabelText(/^current password$/i), "wrong-password-123");
      await user.type(screen.getByLabelText(/^new password$/i), "new-password-123");
      await user.type(screen.getByLabelText(/confirm new password/i), "new-password-123");
      await user.click(screen.getByRole("button", { name: "Change password" }));
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid password");
    expect(useAuthStore.getState().user?.id).toBe("user_1");
    expect(screen.queryByText(/Other devices have been signed out/)).not.toBeInTheDocument();
  });

  it("023-FR-022 overlapping password submissions perform one account change", async () => {
    let finish!: () => void;
    const spy = vi.spyOn(apiClient, "changePassword").mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
    renderPage();
    const current = await screen.findByLabelText(/^current password$/i);
    fireEvent.change(current, { target: { value: "old-password-123" } });
    fireEvent.change(screen.getByLabelText(/^new password$/i), { target: { value: "new-password-123" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "new-password-123" } });
    const form = current.closest("form");
    if (!form) throw new Error("Account action form is missing");
    const button = screen.getByRole("button", { name: "Change password" });
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(button).toBeDisabled();
    await act(async () => { finish(); });
    expect(await screen.findByText(/Other devices have been signed out/)).toBeInTheDocument();
  });

  it("023-FR-022 overlapping deletion submissions create one request", async () => {
    let finish!: (value: { deletion_requested_at: string; purge_at: string }) => void;
    const spy = vi.spyOn(apiClient, "requestAccountDeletion").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    renderPage();
    await screen.findByRole("heading", { name: "Password" });
    fireEvent.click(await screen.findByRole("button", { name: /delete account/i }));
    const current = await screen.findByLabelText(/confirm with your password/i);
    fireEvent.change(current, { target: { value: "current-password-123" } });
    const form = current.closest("form");
    if (!form) throw new Error("Account action form is missing");
    const button = screen.getByRole("button", { name: /delete my account/i });
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(button).toBeDisabled();
    await act(async () => { finish({ deletion_requested_at: "2026-10-06", purge_at: "2026-10-20" }); });
    expect(await screen.findByText(/login page 2026-10-20/)).toBeInTheDocument();
  });

  it("023-FR-007 retains connected-method metadata when optional methods become unavailable", async () => {
    vi.mocked(modernAuthApi.accountMethods).mockResolvedValue({ account_id: account.id, email: account.email, email_verified: true, email_delivery: "unconfigured", has_password: true, methods: [{ method: "password", state: "active", usable: true, connected_at: null }, { method: "google", state: "active", usable: false, connected_at: "2026-10-06" }] });
    renderPage();
    expect(await screen.findByText("Google: Currently unavailable")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download my data/i })).toBeEnabled();
  });

  it("023-FR-002/013 unconfigured auth: rejects mismatched new passwords before calling the API", async () => {
    const spy = vi.spyOn(apiClient, "changePassword").mockResolvedValue(undefined);
    renderPage();
    await screen.findByRole("heading", { name: "Password" });

    const user = userEvent.setup();
    await act(async () => {
      const passwordCurrent = screen.getByLabelText(/^current password$/i);
      await user.type(passwordCurrent, "old-password-123");
      await user.type(screen.getByLabelText(/^new password$/i), "new-password-123");
      await user.type(screen.getByLabelText(/confirm new password/i), "different-123");
      await user.click(screen.getByRole("button", { name: /change password/i }));
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(/don't match/i);
    expect(spy).not.toHaveBeenCalled();
  });

  it("023-FR-002/013 unconfigured auth: changes the password and clears the form", async () => {
    const spy = vi.spyOn(apiClient, "changePassword").mockResolvedValue(undefined);
    renderPage();
    await screen.findByRole("heading", { name: "Password" });

    const user = userEvent.setup();
    await act(async () => {
      const passwordCurrent = screen.getByLabelText(/^current password$/i);
      await user.type(passwordCurrent, "old-password-123");
      await user.type(screen.getByLabelText(/^new password$/i), "new-password-123");
      await user.type(screen.getByLabelText(/confirm new password/i), "new-password-123");
      await user.click(screen.getByRole("button", { name: /change password/i }));
    });

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        current_password: "old-password-123",
        new_password: "new-password-123"
      }, "user_1")
    );
    await waitFor(() =>
      expect(screen.getByText(/other devices have been signed out/i)).toBeInTheDocument()
    );
    expect(screen.getByLabelText(/^new password$/i)).toHaveValue("");
  });

  it("023-FR-002/013 unconfigured auth: downloads the export and names the file", async () => {
    vi.mocked(downloadAccountExport).mockResolvedValue("my-export.zip");
    renderPage();
    await screen.findByRole("heading", { name: "Password" });

    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /download my data/i }));
    });

    await waitFor(() =>
      expect(screen.getByText(/download started: my-export\.zip/i)).toBeInTheDocument()
    );
  });

  it("023-FR-002/013 unconfigured auth: surfaces export failures", async () => {
    vi.mocked(downloadAccountExport).mockRejectedValue(
      new ApiError("Server Error", 500, { message: "Internal storage error." }, "corr-2")
    );
    renderPage();
    await screen.findByRole("heading", { name: "Password" });

    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /download my data/i }));
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/internal storage error.*corr-2/i)
    );
  });

  it("023-FR-002/013 unconfigured auth: walks through the delete dialog and lands on the login notice", async () => {
    const spy = vi.spyOn(apiClient, "requestAccountDeletion").mockResolvedValue({
      deletion_requested_at: "2026-08-06T12:00:00Z",
      purge_at: "2026-08-20T12:00:00Z"
    });
    renderPage();
    await screen.findByRole("heading", { name: "Password" });

    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /delete account/i }));
    });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await act(async () => {
      await user.type(screen.getByLabelText(/confirm with your password/i), "hunter2hunter2");
      await user.click(screen.getByRole("button", { name: /delete my account/i }));
    });

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ current_password: "hunter2hunter2" }, "user_1")
    );
    await waitFor(() =>
      expect(screen.getByText(/login page 2026-08-20T12:00:00Z/)).toBeInTheDocument()
    );
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("023-FR-002/013 unconfigured auth: lets the user back out of the delete dialog", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Password" });

    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /delete account/i }));
    });
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /^cancel$/i }));
    });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("023-FR-002/013 unconfigured auth: shows the re-auth failure inside the delete dialog", async () => {
    vi.spyOn(apiClient, "requestAccountDeletion").mockRejectedValue(
      new ApiError("Forbidden", 403, { message: "Current password is incorrect." })
    );
    renderPage();
    await screen.findByRole("heading", { name: "Password" });

    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /delete account/i }));
    });
    await act(async () => {
      await user.type(screen.getByLabelText(/confirm with your password/i), "nope");
      await user.click(screen.getByRole("button", { name: /delete my account/i }));
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/current password is incorrect/i)
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("023-FR-002/013 unconfigured auth: keeps the account signed in when the browser-local CRT cleanup fails after scheduling", async () => {
    const spy = vi.spyOn(apiClient, "requestAccountDeletion").mockResolvedValue({
      deletion_requested_at: "2026-08-06T12:00:00Z",
      purge_at: "2026-08-20T12:00:00Z"
    });
    const clearSessionAfterCleanup = useAuthStore.getState().clearSessionAfterCleanup;
    useAuthStore.setState({ clearSessionAfterCleanup: vi.fn(async () => false) });
    renderPage();
    await screen.findByRole("heading", { name: "Password" });

    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: /delete account/i }));
    });
    await act(async () => {
      await user.type(screen.getByLabelText(/confirm with your password/i), "hunter2hunter2");
      await user.click(screen.getByRole("button", { name: /delete my account/i }));
    });

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ current_password: "hunter2hunter2" }, "user_1")
    );
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/couldn't clear this browser's local CRT data/i)
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByText(/login page/)).not.toBeInTheDocument();
    expect(useAuthStore.getState().user).not.toBeNull();
    useAuthStore.setState({ clearSessionAfterCleanup });
  });
});
