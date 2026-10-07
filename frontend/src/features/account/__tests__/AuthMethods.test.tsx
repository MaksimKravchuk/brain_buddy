import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { modernAuthApi, type AccountMethods } from "../../../api/modernAuth";
import { ApiError } from "../../../api/client";
import { useAuthStore } from "../../../stores/authStore";
import { AccountSecurity } from "../../auth/AccountSecurity";

vi.mock("../../../api/modernAuth", () => ({ modernAuthApi: { methods: vi.fn(), accountMethods: vi.fn(), confirmPassword: vi.fn(), unlink: vi.fn(), setPassword: vi.fn(), exportAccount: vi.fn(), deleteAccount: vi.fn(), requestEmail: vi.fn(), verifyEmail: vi.fn(), resendEmail: vi.fn() } }));
const methods: AccountMethods = { account_id: "A", email: "a@example.com", email_verified: false, email_delivery: "available", has_password: true, methods: [{ method: "password", state: "active", usable: true, connected_at: null }, { method: "google", state: "active", usable: true, connected_at: null }] };
describe("023-FR-006/007/013/018 same-owner connected methods and privacy actions", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: { id: "A", email: "a@example.com" }, status: "authed" });
    vi.mocked(modernAuthApi.methods).mockResolvedValue({ password: true, google: true, apple: true, email: true, web_account_origin: null });
    vi.mocked(modernAuthApi.accountMethods).mockResolvedValue(methods);
    vi.mocked(modernAuthApi.confirmPassword).mockResolvedValue({ status: "reauthenticated", recent_proof: "p", expires_at: new Date(Date.now() + 300000).toISOString() });
  });
  afterEach(() => vi.clearAllMocks());
  const show = () => render(<MemoryRouter><AccountSecurity /></MemoryRouter>);

  it("023-FR-003 a discovery failure offers retry without downgrading account actions", async () => {
    vi.mocked(modernAuthApi.methods).mockRejectedValue(new Error("offline"));
    show();
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download my data/i })).not.toBeInTheDocument();
    vi.mocked(modernAuthApi.methods).mockResolvedValue({ password: true, google: true, apple: false, email: false, web_account_origin: "https://brainbuddy.example.com" });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: "Remove Google" })).toBeEnabled();
    expect(modernAuthApi.methods).toHaveBeenCalledTimes(2);
  });

  it("023-FR-013 an unconfigured passwordless account never enters the password-only fallback", async () => {
    vi.mocked(modernAuthApi.methods).mockResolvedValue({ password: true, google: false, apple: false, email: false, web_account_origin: null });
    vi.mocked(modernAuthApi.accountMethods).mockResolvedValue({ ...methods, has_password: false });
    show();
    expect(await screen.findByRole("button", { name: "Add password" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download my data/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Current password")).not.toBeInTheDocument();
  });
  async function confirm() {
    const input = await screen.findByLabelText("Current password");
    await act(async () => { fireEvent.change(input, { target: { value: "password-123456" } }); fireEvent.click(screen.getByRole("button", { name: "Confirm" })); });
  }
  it("023-FR-007 offers reconnection after a provider is disabled", async () => {
    vi.mocked(modernAuthApi.accountMethods).mockResolvedValue({ ...methods, methods: [...methods.methods, { method: "apple", state: "disabled", usable: false, connected_at: null }] });
    show();
    expect(await screen.findByRole("button", { name: "Reconnect Apple" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Remove Apple" })).toBeNull();
  });
  it("requires consequence confirmation and preserves last-method rejection", async () => {
    vi.mocked(modernAuthApi.unlink).mockRejectedValue(new ApiError("Conflict", 409, { detail: { code: "last_method" } }));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Remove Google" }));
    expect(screen.getByText(/sessions started with it will end/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }));
    await confirm();
    await waitFor(() => expect(modernAuthApi.unlink).toHaveBeenCalledWith("google", { expected_account_id: "A", recent_proof: "p" }));
    expect(await screen.findByText(/Add another way to sign in/i)).toBeInTheDocument();
    expect(useAuthStore.getState().user?.id).toBe("A");
  });
  it("does not mutate if the acting auth-store owner changes while confirming", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof modernAuthApi.confirmPassword>>) => void;
    vi.mocked(modernAuthApi.confirmPassword).mockReturnValue(new Promise(done => { resolve = done; }));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Export" }));
    await confirm();
    await act(async () => { useAuthStore.setState({ user: { id: "B", email: "b@example.com" } }); resolve({ status: "reauthenticated", recent_proof: "p", expires_at: new Date(Date.now() + 300000).toISOString() }); });
    await waitFor(() => expect(modernAuthApi.exportAccount).not.toHaveBeenCalled());
  });
  it("refreshes metadata after a lost mutation response and requires a fresh proof", async () => {
    vi.mocked(modernAuthApi.setPassword).mockRejectedValue(new TypeError("Network error"));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Change password" }));
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "new-password-123" } });
    fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: "new-password-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and save" }));
    await confirm();
    expect(await screen.findByText(/couldn't confirm whether this finished/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check account" }));
    await waitFor(() => expect(modernAuthApi.accountMethods).toHaveBeenCalledTimes(2));
    expect(modernAuthApi.setPassword).toHaveBeenCalledTimes(1);
  });
  it("023-FR-013 lets a passwordless owner request direct deletion using action-bound email proof", async () => {
    vi.mocked(modernAuthApi.accountMethods).mockResolvedValue({ ...methods, has_password: false, email_verified: true, methods: [{ method: "email", usable: true, state: "active", connected_at: null }] });
    vi.mocked(modernAuthApi.requestEmail).mockResolvedValue({ challenge_id: "c", expires_at: new Date(Date.now() + 600000).toISOString(), resend_at: new Date(Date.now() + 60000).toISOString(), message: "neutral" });
    vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue({ status: "reauthenticated", recent_proof: "email-proof", expires_at: new Date(Date.now() + 300000).toISOString() });
    vi.mocked(modernAuthApi.deleteAccount).mockResolvedValue({ deletion_requested_at: "2026-10-06T12:00:00Z", purge_at: "2026-10-20T12:00:00Z" });
    const cleanup = useAuthStore.getState().clearSessionAfterCleanup;
    useAuthStore.setState({ clearSessionAfterCleanup: vi.fn(async () => { useAuthStore.setState({ user: null, status: "anon" }); return true; }) });
    function Login() { const state = useLocation().state as { deletionScheduled: string }; return <p>Deletion scheduled {state.deletionScheduled}</p>; }
    try {
      render(<MemoryRouter initialEntries={["/settings/account/delete"]}><Routes><Route path="/settings/account/delete" element={<AccountSecurity directDelete />} /><Route path="/login" element={<Login />} /></Routes></MemoryRouter>);
      fireEvent.click(await screen.findByRole("button", { name: "Confirm and delete" }));
      expect(screen.queryByLabelText("Current password")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Send an email code" }));
      await screen.findByLabelText("Email code");
      expect(modernAuthApi.requestEmail).toHaveBeenCalledWith(expect.objectContaining({ purpose: "reauth", action: "delete", expected_account_id: "A" }));
      await act(async () => { fireEvent.change(screen.getByLabelText("Email code"), { target: { value: "123456" } }); fireEvent.click(screen.getByRole("button", { name: "Verify and continue" })); });
      expect(await screen.findByText("Deletion scheduled 2026-10-20T12:00:00Z")).toBeInTheDocument();
      expect(modernAuthApi.deleteAccount).toHaveBeenCalledWith({ expected_account_id: "A", recent_proof: "email-proof" });
      expect(useAuthStore.getState().status).toBe("anon");
    } finally { useAuthStore.setState({ clearSessionAfterCleanup: cleanup }); }
  });
  it("shows the actual remaining method when unlinking signs this session out", async () => {
    vi.mocked(modernAuthApi.unlink).mockResolvedValue({ methods: { ...methods, methods: [methods.methods[0]] }, signed_out: true });
    function Login() { const state = useLocation().state as { authNotice: string }; return <p>{state.authNotice}</p>; }
    render(<MemoryRouter initialEntries={["/account"]}><Routes><Route path="/account" element={<AccountSecurity />} /><Route path="/login" element={<Login />} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Remove Google" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm removal" })); await confirm();
    expect(await screen.findByText(/Sign in again with your password/i)).toBeInTheDocument();
    expect(useAuthStore.getState().user).toBeNull();
  });
  it("keeps the old email until fresh ownership proof and the new mailbox code both finish", async () => {
    vi.mocked(modernAuthApi.requestEmail).mockResolvedValue({ challenge_id: "new-mailbox", expires_at: new Date(Date.now() + 600000).toISOString(), resend_at: new Date(Date.now() + 60000).toISOString(), message: "neutral" });
    vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue({ status: "changed_email", user: { id: "A", email: "new@example.com" } });
    show(); fireEvent.click(await screen.findByRole("button", { name: "Change email" }));
    fireEvent.change(screen.getByLabelText("New email"), { target: { value: "new@example.com" } }); fireEvent.click(screen.getByRole("button", { name: "Continue" })); await confirm();
    await screen.findByLabelText("Email code");
    expect(useAuthStore.getState().user?.email).toBe("a@example.com");
    expect(modernAuthApi.requestEmail).toHaveBeenCalledWith(expect.objectContaining({ email: "new@example.com", purpose: "change_email", action: "change_email", expected_account_id: "A", recent_proof: "p" }));
    await act(async () => { fireEvent.change(screen.getByLabelText("Email code"), { target: { value: "123456" } }); fireEvent.click(screen.getByRole("button", { name: "Verify and continue" })); });
    expect(useAuthStore.getState().user?.email).toBe("new@example.com");
    expect(modernAuthApi.verifyEmail).toHaveBeenCalledWith(expect.objectContaining({ challenge_id: "new-mailbox", code: "123456", recent_proof: "p" }));
  });
});
