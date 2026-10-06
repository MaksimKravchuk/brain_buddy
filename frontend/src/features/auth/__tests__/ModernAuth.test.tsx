import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { modernAuthApi } from "../../../api/modernAuth";
import { useAuthStore } from "../../../stores/authStore";
import { AuthEntry } from "../AuthEntry";

vi.mock("../../../api/modernAuth", () => ({ modernAuthApi: { methods: vi.fn(), requestEmail: vi.fn(), verifyEmail: vi.fn(), resendEmail: vi.fn(), resetPassword: vi.fn(), startProvider: vi.fn() } }));

describe("022-FR-001/003/008/009/010/022 configured choice and neutral code flow", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "anon" });
    vi.mocked(modernAuthApi.methods).mockResolvedValue({ google: true, apple: false, email: true, password: true, web_account_origin: null });
    vi.mocked(modernAuthApi.requestEmail).mockResolvedValue({ challenge_id: "c", expires_at: new Date(Date.now() + 600000).toISOString(), resend_at: new Date(Date.now() + 60000).toISOString(), message: "If this address can be used, you will receive a code." });
  });
  afterEach(() => vi.clearAllMocks());
  const show = () => render(<MemoryRouter><AuthEntry destination="/" /></MemoryRouter>);
  it("advertises only configured providers and keeps a password alternative", async () => {
    show();
    expect(await screen.findByRole("button", { name: "Sign in with Google" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign in with Apple" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use your password" })).toBeInTheDocument();
  });
  it("requests one code with immediate busy state, actual expiry and no automatic resend", async () => {
    show();
    await screen.findByRole("button", { name: "Continue with email" });
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "unknown@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue with email" }));
    expect(screen.getByRole("button", { name: "Please wait…" })).toBeDisabled();
    expect(await screen.findByLabelText("Email code")).toHaveFocus();
    expect(modernAuthApi.requestEmail).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/if this address can be used/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send another code in/i })).toBeDisabled();
    expect(modernAuthApi.resendEmail).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Email code"), { target: { value: "123456" } });
    vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue({ status: "existing_account_required", message: "Use existing account" });
    fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    expect(await screen.findByText("Connect to your existing account")).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe("anon");
  });
  it("failed discovery exposes retry and password without guessed methods", async () => {
    vi.mocked(modernAuthApi.methods).mockRejectedValue(new Error("unavailable"));
    show();
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign in with Google" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use your password" }));
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
  });
  it("022-FR-011 returns to sign-in after reset without creating a session", async () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Use your password" }));
    fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "person@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send a recovery code" }));
    await screen.findByLabelText("Email code");
    vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue({ status: "reset_ready", reset_grant: "g", expires_at: new Date(Date.now() + 600000).toISOString() });
    fireEvent.change(screen.getByLabelText("Email code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    fireEvent.change(await screen.findByLabelText("New password"), { target: { value: "long-password-123" } });
    fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: "long-password-123" } });
    vi.mocked(modernAuthApi.resetPassword).mockResolvedValue(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Save password" }));
    await waitFor(() => expect(screen.getByText(/Password reset. Sign in/i)).toBeInTheDocument());
    expect(useAuthStore.getState().status).toBe("anon");
  });
  it("022-FR-008/011 rejects a session outcome in a recovery-only flow", async () => {
    const hydrate = vi.spyOn(useAuthStore.getState(), "hydrate");
    show(); fireEvent.click(screen.getByRole("button", { name: "Use your password" })); fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "person@example.com" } }); fireEvent.click(screen.getByRole("button", { name: "Send a recovery code" }));
    await screen.findByLabelText("Email code");
    vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue({ status: "signed_in", user: { id: "A", email: "person@example.com" }, deletion_cancelled: false });
    fireEvent.change(screen.getByLabelText("Email code"), { target: { value: "123456" } }); fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't confirm whether this finished/i);
    expect(hydrate).not.toHaveBeenCalled(); expect(useAuthStore.getState().status).toBe("anon");
    hydrate.mockRestore();
  });
});
