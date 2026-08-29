import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../../../api/client";
import { useAuthStore } from "../../../stores/authStore";
import { AdminUsersSection } from "../AdminUsersSection";

const member = { id: "user_1", email: "member@example.com", display_name: "Member", deletion_requested: false };
function renderUsers() {
  useAuthStore.setState({ user: { id: "operator-1", email: "operator@example.com" }, status: "authed", deletionCancelledNotice: false });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><AdminUsersSection /></QueryClientProvider>);
}

describe("AdminUsersSection CRUD safety", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders Users as a full-width semantic section without card chrome", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });

    renderUsers();

    const heading = await screen.findByRole("heading", { name: "Users" });
    const section = heading.closest("section");
    expect(section).toBeInTheDocument();
    expect(section).not.toHaveClass("rounded-2xl", "border", "p-5", "shadow-soft");
    expect(section).toHaveClass("w-full");
  });

  it("013-FR-010 013-FR-012 013-SC-006 loads accounts and requires target-bound revoke confirmation", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    const revoke = vi.spyOn(apiClient, "revokeAdminAccountSessions").mockResolvedValue({ revoked_count: 0 });
    renderUsers();
    await screen.findByText("member@example.com");
    const trigger = screen.getByRole("button", { name: "Revoke sessions for user_1 (member@example.com)" });
    await userEvent.setup().click(trigger);
    expect(screen.getByRole("dialog", { name: "Revoke sessions for user_1 (member@example.com)" })).toHaveTextContent("user_1 (member@example.com)");
    expect(revoke).not.toHaveBeenCalled();
    await userEvent.setup().click(within(screen.getByRole("dialog")).getByRole("button", { name: "Revoke sessions" }));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("user_1"));
  });

  it("013-FR-010 013-SC-007 names delete target and restores focus after Escape", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    renderUsers();
    await screen.findByText("member@example.com");
    const trigger = screen.getByRole("button", { name: "Delete user_1 (member@example.com)" });
    await userEvent.setup().click(trigger);
    expect(screen.getByRole("dialog", { name: "Delete account user_1 (member@example.com)" })).toHaveTextContent("user_1 (member@example.com)");
    await userEvent.setup().keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("013-FR-004 uses only the four-field account projection", async () => {
    const responseWithUnknownMetadata = {
      accounts: [member],
      configured_operator_ids: [member.id],
    } as unknown as Awaited<ReturnType<typeof apiClient.listAdminAccounts>>;
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue(responseWithUnknownMetadata);

    renderUsers();

    await screen.findByText(member.email);
    expect(screen.getByRole("button", { name: "Delete user_1 (member@example.com)" })).toBeInTheDocument();
  });

  it("013-FR-005 013-FR-006 013-SC-003 creates a member and clears the password field after success", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValueOnce({ accounts: [] }).mockResolvedValue({ accounts: [{ ...member, id: "user_2", email: "created@example.com", display_name: "Created" }] });
    const create = vi.spyOn(apiClient, "createAdminAccount").mockResolvedValue({
      id: "user_2",
      email: "created@example.com",
      display_name: "Created",
      deletion_requested: false,
    });
    renderUsers();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Create user" }));
    await user.type(screen.getByLabelText("Email"), "created@example.com");
    await user.type(screen.getByLabelText("Display name (optional)"), "Created");
    await user.type(screen.getByLabelText("Initial password"), "E2E-safe-password-123");
    await user.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({
      email: "created@example.com",
      display_name: "Created",
      password: "E2E-safe-password-123",
    }));
    expect(screen.queryByLabelText("Initial password")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Account created.");
    await waitFor(() => expect(screen.getByText("created@example.com").closest("tr")).toHaveFocus());
  });

  it("cancels create with cleared secrets and restores focus to its trigger", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    renderUsers();
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Create user" });
    await user.click(trigger);
    await user.type(screen.getByLabelText("Initial password"), "secret-value");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Initial password")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create user" })).toHaveFocus();
  });

  it("cancels create with Escape and restores focus to its trigger", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    renderUsers();
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Create user" });
    await user.click(trigger);
    await user.type(screen.getByLabelText("Initial password"), "secret-value");
    await user.keyboard("{Escape}");
    expect(screen.queryByLabelText("Initial password")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create user" })).toHaveFocus();
  });

  it("shows loading and generic create errors without a correlation reference", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockReturnValue(new Promise(() => {}));
    vi.spyOn(apiClient, "createAdminAccount").mockRejectedValue(new Error("create failed"));
    renderUsers();
    expect(screen.getByRole("status")).toHaveTextContent("Loading users");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Create user" }));
    await user.type(screen.getByLabelText("Email"), "generic-error@example.com");
    await user.type(screen.getByLabelText("Initial password"), "E2E-safe-password-123");
    await user.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(screen.getByText("Could not create the account. Check the account and try again.")).toBeInTheDocument());
    expect(screen.getByText("Could not create the account. Check the account and try again.")).not.toHaveTextContent("reference");
  });

  it("shows a correlation-aware create error without clearing entered fields", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    vi.spyOn(apiClient, "createAdminAccount").mockRejectedValue(new ApiError("bad", 409, null, "corr-create"));
    renderUsers();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Create user" }));
    await user.type(screen.getByLabelText("Email"), "duplicate@example.com");
    await user.type(screen.getByLabelText("Initial password"), "E2E-safe-password-123");
    await user.click(screen.getByRole("button", { name: "Create user" }));
    await expect(screen.findByText(/reference corr-create/)).resolves.toHaveTextContent("reference corr-create");
    expect(screen.getByLabelText("Email")).toHaveValue("duplicate@example.com");
  });

  it("013-FR-007 013-FR-008 013-FR-011 013-SC-004 edits a member and sends only the mutable projection", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    const update = vi.spyOn(apiClient, "updateAdminAccount").mockResolvedValue({ ...member, display_name: "Renamed" });
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit user_1 (member@example.com)" }));
    await user.clear(screen.getByLabelText("Display name"));
    await user.type(screen.getByLabelText("Display name"), "Renamed");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("user_1", { email: member.email, display_name: "Renamed" }));
  });

  it("cancels an edit without submitting", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    const update = vi.spyOn(apiClient, "updateAdminAccount");
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit user_1 (member@example.com)" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("form", { name: `Edit ${member.email}` })).not.toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
  });

  it("cancels an edit with Escape and restores focus to its trigger", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    const update = vi.spyOn(apiClient, "updateAdminAccount");
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Edit user_1 (member@example.com)" });
    await user.click(trigger);
    await user.click(screen.getByLabelText("Display name"));

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("form", { name: `Edit ${member.email}` })).not.toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
    expect(trigger).toHaveFocus();
  });

  it("reports an update failure without closing the edit form", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    vi.spyOn(apiClient, "updateAdminAccount").mockRejectedValue(new ApiError("bad", 500, null, "corr-update"));
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit user_1 (member@example.com)" }));

    await user.click(screen.getByRole("button", { name: "Save" }));

    await expect(screen.findByRole("status")).resolves.toHaveTextContent("reference corr-update");
    expect(screen.getByRole("form", { name: `Edit ${member.email}` })).toBeInTheDocument();
  });

  it("serializes a cleared display name as null", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    const update = vi.spyOn(apiClient, "updateAdminAccount").mockResolvedValue({ ...member, display_name: null });
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit user_1 (member@example.com)" }));
    await user.clear(screen.getByLabelText("Display name"));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("user_1", { email: member.email, display_name: null }));
  });

  it("opens a null display name as an empty editable field", async () => {
    const unnamed = { ...member, display_name: null };
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [unnamed] });
    renderUsers();
    await screen.findByText(member.email);

    await userEvent.click(screen.getByRole("button", { name: "Edit user_1 (member@example.com)" }));

    expect(screen.getByLabelText("Display name")).toHaveValue("");
  });

  it("reports revoke failure and restores focus to its row trigger", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    vi.spyOn(apiClient, "revokeAdminAccountSessions").mockRejectedValue(new ApiError("bad", 500, null, "corr-revoke"));
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Revoke sessions for user_1 (member@example.com)" });
    await user.click(trigger);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Revoke sessions" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("reference corr-revoke"));
    expect(trigger).toHaveFocus();
  });

  it("cancels revoke confirmation and restores focus without sending a request", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    const revoke = vi.spyOn(apiClient, "revokeAdminAccountSessions");
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: "Revoke sessions for user_1 (member@example.com)" });
    await user.click(trigger);

    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(revoke).not.toHaveBeenCalled();
    expect(trigger).toHaveFocus();
  });

  it("keeps the account when delete fails and reports the correlation", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    vi.spyOn(apiClient, "deleteAdminAccount").mockRejectedValue(new ApiError("bad", 500, null, "corr-delete"));
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete user_1 (member@example.com)" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("reference corr-delete"));
    expect(screen.getByText(member.email)).toBeInTheDocument();
  });

  it("renders the owner without a delete action and reports singular revoke feedback", async () => {
    const owner = { ...member, id: "operator-1", email: "operator@example.com", display_name: null, deletion_requested: true };
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [owner] });
    vi.spyOn(apiClient, "revokeAdminAccountSessions").mockResolvedValue({ revoked_count: 1 });
    renderUsers();
    await screen.findByText(owner.email);
    expect(screen.queryByRole("button", { name: "Delete user_1 (member@example.com)" })).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Revoke sessions for operator-1 (operator@example.com)" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Revoke sessions" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Revoked 1 session."));
  });

  it("013-FR-014 reports a failed account list instead of showing an empty table", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockRejectedValue(new Error("list failed"));
    renderUsers();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load users.");
  });

  it("013-FR-003 renders the exact empty state when the confirmed list has no accounts", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    renderUsers();
    expect(await screen.findByText("No accounts to manage yet.")).toBeInTheDocument();
  });

  it("013-FR-014 renders the exact correlation-aware list error and retries the real refetch", async () => {
    const list = vi
      .spyOn(apiClient, "listAdminAccounts")
      .mockRejectedValueOnce(new ApiError("bad", 503, null, "corr-list"))
      .mockResolvedValueOnce({ accounts: [member] });
    renderUsers();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load users. Ref: corr-list");
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(member.email)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("013-FR-014 preserves the last confirmed account list when a refetch fails", async () => {
    const list = vi
      .spyOn(apiClient, "listAdminAccounts")
      .mockResolvedValueOnce({ accounts: [member] })
      .mockRejectedValueOnce(new ApiError("bad", 503, null, "corr-stale"));
    renderUsers();
    await screen.findByText(member.email);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(screen.getByText(member.email)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load users. Ref: corr-stale");
  });

  it("removes the account only after a confirmed delete succeeds", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    const remove = vi.spyOn(apiClient, "deleteAdminAccount").mockResolvedValue({ account_id: member.id, deleted: true });
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete user_1 (member@example.com)" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(member.id));
    expect(screen.getByRole("status")).toHaveTextContent("Account permanently deleted.");
  });

  it("moves focus to the preceding row after deleting the final account", async () => {
    const preceding = { ...member, id: "user_0", email: "before@example.com" };
    vi.spyOn(apiClient, "listAdminAccounts")
      .mockResolvedValueOnce({ accounts: [preceding, member] })
      .mockResolvedValue({ accounts: [preceding] });
    vi.spyOn(apiClient, "deleteAdminAccount").mockResolvedValue({ account_id: member.id, deleted: true });
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete user_1 (member@example.com)" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete permanently" }));

    await waitFor(() => expect(screen.queryByText(member.email)).not.toBeInTheDocument());
    expect(screen.getByText(preceding.email).closest("tr")).toHaveFocus();
  });

  it("moves focus to the following row after deleting the first account", async () => {
    const following = { ...member, id: "user_2", email: "after@example.com" };
    vi.spyOn(apiClient, "listAdminAccounts")
      .mockResolvedValueOnce({ accounts: [member, following] })
      .mockResolvedValue({ accounts: [following] });
    vi.spyOn(apiClient, "deleteAdminAccount").mockResolvedValue({ account_id: member.id, deleted: true });
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Delete user_1 (member@example.com)" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete permanently" }));

    await waitFor(() => expect(screen.queryByText(member.email)).not.toBeInTheDocument());
    expect(screen.getByText(following.email).closest("tr")).toHaveFocus();
  });

  it("stays stable when a newly created account is absent from the refreshed list", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [] });
    vi.spyOn(apiClient, "createAdminAccount").mockResolvedValue({ ...member, id: "missing-after-refresh" });
    renderUsers();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Create user" }));
    await user.type(screen.getByLabelText("Email"), member.email);
    await user.type(screen.getByLabelText("Initial password"), "E2E-safe-password-123");
    await user.click(screen.getByRole("button", { name: "Create user" }));

    await expect(screen.findByText("Account created.")).resolves.toBeInTheDocument();
    expect(screen.getByText("No accounts to manage yet.")).toBeInTheDocument();
  });

  it("013-FR-010 013-SC-007 wraps dialog focus at both ends", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    renderUsers();
    await screen.findByText(member.email);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Revoke sessions for user_1 (member@example.com)" }));
    const dialog = screen.getByRole("dialog");
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const confirm = within(dialog).getByRole("button", { name: "Revoke sessions" });
    expect(cancel).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(confirm).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(cancel).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(confirm).toHaveFocus();
  });

  it("keeps an empty confirmation surface stable during a focus-trap transition", async () => {
    vi.spyOn(apiClient, "listAdminAccounts").mockResolvedValue({ accounts: [member] });
    renderUsers();
    await screen.findByText(member.email);
    await userEvent.setup().click(screen.getByRole("button", { name: "Revoke sessions for user_1 (member@example.com)" }));
    const dialog = screen.getByRole("dialog");
    dialog.querySelectorAll("button").forEach((button) => button.remove());

    fireEvent.keyDown(dialog, { key: "Tab" });

    expect(dialog).toBeInTheDocument();
  });
});
