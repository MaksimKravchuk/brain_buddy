import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { useAuthStore } from "../../../stores/authStore";
import { AdminPage } from "../AdminPage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/admin"]}><AdminPage /></MemoryRouter></QueryClientProvider>);
}

function mockShell() {
  vi.spyOn(apiClient, "listTasks").mockResolvedValue({ items: [], next_cursor: null, has_more: false, counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 } });
  vi.spyOn(apiClient, "listProjects").mockResolvedValue([]);
  vi.spyOn(apiClient, "listTags").mockResolvedValue([]);
}

describe("AdminPage capability and exclusive tabs", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: { id: "operator-1", email: "operator@example.com" }, status: "authed", deletionCancelledNotice: false });
    mockShell();
  });

  afterEach(() => vi.restoreAllMocks());

  it("keeps users as the default tab after operator confirmation", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    renderPage();
    expect(await screen.findByRole("tab", { name: "Users" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Users" })).toBeInTheDocument();
    expect(screen.queryByRole("tabpanel", { name: "Feature flags" })).not.toBeInTheDocument();
  });

  it("uses the available workspace width for the admin portal", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });

    renderPage();

    expect(await screen.findByRole("heading", { name: "Admin" })).toBeInTheDocument();
    const workspace = screen.getByRole("heading", { name: "Admin" }).parentElement?.parentElement;
    expect(workspace).toHaveClass("w-full");
    expect(workspace).not.toHaveClass("max-w-[680px]");
  });

  it("shows only access denied for a confirmed non-operator response", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockRejectedValue(new ApiError("Forbidden", 403, null));
    renderPage();
    expect(await screen.findByText("Access denied")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("treats a missing admin route as a confirmed denial", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockRejectedValue(new ApiError("Not found", 404, null));
    renderPage();
    expect(await screen.findByText("Access denied")).toBeInTheDocument();
  });

  it("offers retry for an unverifiable capability response", async () => {
    const status = vi.spyOn(apiClient, "getAdminStatus")
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ is_operator: false });
    renderPage();
    expect(await screen.findByRole("heading", { name: /couldn't verify access/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(screen.getByText("Access denied")).toBeInTheDocument());
    expect(status).toHaveBeenCalledTimes(2);
  });

  it("moves between exclusive tabs with arrow keys and restores Users", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue({ degraded: false, flags: [] });
    renderPage();
    const user = userEvent.setup();
    const users = await screen.findByRole("tab", { name: "Users" });
    const flags = screen.getByRole("tab", { name: "Feature flags" });
    await user.click(users);
    await user.keyboard("{ArrowRight}");
    expect(flags).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tabpanel", { name: "Users" })).not.toBeInTheDocument();
    await user.keyboard("{ArrowLeft}");
    expect(users).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowDown}");
    expect(flags).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowUp}");
    expect(users).toHaveAttribute("aria-selected", "true");
  });

  it("keeps the selected tab unchanged for unrelated keys", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    renderPage();
    const users = await screen.findByRole("tab", { name: "Users" });

    users.focus();
    await userEvent.keyboard("{Enter}");

    expect(users).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Users" })).toBeInTheDocument();
  });

  it("keeps focus and selection on a boundary tab for an outward arrow", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue({ degraded: false, flags: [] });
    renderPage();
    const flags = await screen.findByRole("tab", { name: "Feature flags" });
    await userEvent.click(flags);

    await userEvent.keyboard("{ArrowRight}");

    expect(flags).toHaveFocus();
    expect(flags).toHaveAttribute("aria-selected", "true");
  });

  it("selects Feature flags when its tab is clicked", async () => {
    vi.spyOn(apiClient, "getAdminStatus").mockResolvedValue({ is_operator: true });
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue({ degraded: false, flags: [] });
    renderPage();

    await userEvent.click(await screen.findByRole("tab", { name: "Feature flags" }));

    expect(screen.getByRole("tab", { name: "Feature flags" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Feature flags" })).toBeInTheDocument();
    expect(screen.queryByRole("tabpanel", { name: "Users" })).not.toBeInTheDocument();
  });

  it("announces the pending capability check before rendering the portal", async () => {
    let resolveStatus!: (value: { is_operator: boolean }) => void;
    vi.spyOn(apiClient, "getAdminStatus").mockReturnValue(new Promise((resolve) => { resolveStatus = resolve; }));
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("Checking access");
    resolveStatus({ is_operator: true });
    await waitFor(() => expect(screen.getByRole("tab", { name: "Users" })).toBeInTheDocument());
  });
});
