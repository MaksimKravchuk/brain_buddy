import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { modernAuthApi, type AccountMethods, type Challenge, type RecentProof } from "../../../api/modernAuth";
import { ApiError } from "../../../api/client";
import { useAuthStore } from "../../../stores/authStore";
import { AuthEntry } from "../AuthEntry";
import { AccountSecurity } from "../AccountSecurity";
import { CodeStep } from "../AuthControls";
import { ConfirmAccount } from "../ConfirmAccount";
import { ProviderCompletionPage } from "../ProviderCompletionPage";
import { acceptSignedIn, rememberConfirmation, saveProviderAttempt, startBrowserProvider, takeConfirmation, takeProviderCallback, safeAuthDestination } from "../authFlow";

vi.mock("../../../api/modernAuth", () => ({ modernAuthApi: { methods: vi.fn(), accountMethods: vi.fn(), requestEmail: vi.fn(), verifyEmail: vi.fn(), resendEmail: vi.fn(), resetPassword: vi.fn(), confirmPassword: vi.fn(), startProvider: vi.fn(), completeProvider: vi.fn(), unlink: vi.fn(), setPassword: vi.fn(), exportAccount: vi.fn(), deleteAccount: vi.fn() } }));
const account = { id: "A", email: "a@example.com" };
const availability = { password: true, google: true, apple: true, email: true, web_account_origin: null };
const methods: AccountMethods = { account_id: "A", email: account.email, email_verified: false, email_delivery: "available", has_password: true, methods: [{ method: "password", state: "active", usable: true, connected_at: null }, { method: "google", state: "active", usable: true, connected_at: null }, { method: "apple", state: "active", usable: true, connected_at: null }] };
const token = "a".repeat(43);
const proof = (name = "recent-proof", expires = Date.now() + 300000): RecentProof => ({ status: "reauthenticated", recent_proof: name, expires_at: new Date(expires).toISOString() });
const challenge = (): Challenge => ({ challenge_id: "mailbox", expires_at: new Date(Date.now() + 600000).toISOString(), resend_at: new Date(Date.now() - 1000).toISOString(), message: "neutral" });
const original = { hydrate: useAuthStore.getState().hydrate, login: useAuthStore.getState().login, cleanup: useAuthStore.getState().clearSessionAfterCleanup };

function Destination(): React.JSX.Element {
  const location = useLocation();
  return <p>Destination {location.pathname} {JSON.stringify(location.state)}</p>;
}
const showEntry = () => render(<MemoryRouter initialEntries={["/login"]}><Routes><Route path="/login" element={<AuthEntry destination="/settings/account" />} /><Route path="/settings/account" element={<Destination />} /></Routes></MemoryRouter>);
const showAccount = (directDelete = false) => render(<MemoryRouter initialEntries={["/account"]}><Routes><Route path="/account" element={<AccountSecurity directDelete={directDelete} onUpdated={vi.fn()} />} /><Route path="/login" element={<Destination />} /></Routes></MemoryRouter>);
function pending(purpose: "login" | "link" | "reauth" = "login") {
  saveProviderAttempt({ attemptId: token, state: token, verifier: "v".repeat(43), purpose, destination: "/settings/account", expiresAt: Date.now() + 60000, ...(purpose === "login" ? {} : { expectedOwner: "A", action: purpose === "link" ? "link:google" as const : "export" as const }) });
  history.replaceState(null, "", `/auth/complete#attempt=${token}&state=${token}&grant=${token}`);
}
const showCallback = () => render(<StrictMode><MemoryRouter initialEntries={["/auth/complete"]}><Routes><Route path="/auth/complete" element={<ProviderCompletionPage />} /><Route path="/settings/account" element={<Destination />} /></Routes></MemoryRouter></StrictMode>);
function submitCode() {
  const form = screen.getByLabelText("Email code").closest("form");
  if (!form) throw new Error("Expected code form");
  fireEvent.change(screen.getByLabelText("Email code"), { target: { value: "123456" } }); fireEvent.submit(form);
}
async function passwordConfirm() {
  const input = await screen.findByLabelText("Current password");
  await act(async () => { fireEvent.change(input, { target: { value: "private-password" } }); fireEvent.click(screen.getByRole("button", { name: "Confirm" })); });
}
async function resetForm(expires = Date.now() + 600000) {
  showEntry(); fireEvent.click(screen.getByRole("button", { name: "Use your password" })); fireEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: account.email } }); fireEvent.click(screen.getByRole("button", { name: "Send a recovery code" }));
  await screen.findByLabelText("Email code");
  vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue({ status: "reset_ready", reset_grant: "one-use-reset", expires_at: new Date(expires).toISOString() });
  await act(async () => submitCode());
  await screen.findByLabelText("New password");
}
function newPassword(repeat = "new-password-123") {
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: "new-password-123" } });
  fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: repeat } });
}

describe("022-FR-006/008/009/011/013/015/016/021 remaining auth failure and recovery journeys", () => {
  beforeEach(() => {
    vi.resetAllMocks(); sessionStorage.clear();
    useAuthStore.setState({ user: account, status: "authed", deletionCancelledNotice: false, deletionScheduledFor: null, hydrate: original.hydrate, login: original.login, clearSessionAfterCleanup: original.cleanup });
    vi.mocked(modernAuthApi.methods).mockResolvedValue(availability); vi.mocked(modernAuthApi.accountMethods).mockResolvedValue(methods);
    vi.mocked(modernAuthApi.requestEmail).mockResolvedValue(challenge()); vi.mocked(modernAuthApi.confirmPassword).mockResolvedValue(proof());
    takeConfirmation("A", "export");
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear(); history.replaceState(null, "", "/"); useAuthStore.setState({ hydrate: original.hydrate, login: original.login, clearSessionAfterCleanup: original.cleanup }); });

  it("retries discovery successfully and preserves an entered email after a failed neutral request", async () => {
    vi.mocked(modernAuthApi.methods).mockRejectedValueOnce(new Error("offline")); showEntry();
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: account.email } });
    vi.mocked(modernAuthApi.requestEmail).mockRejectedValueOnce(new ApiError("Unavailable", 503, null, "mail-ref"));
    fireEvent.click(screen.getByRole("button", { name: "Continue with email" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/mail-ref/); expect(screen.getByLabelText("Email address")).toHaveValue(account.email);
    fireEvent.click(screen.getByRole("button", { name: "Continue with email" })); await screen.findByLabelText("Email code");
    fireEvent.click(screen.getByRole("button", { name: "Use another email or method" })); expect(screen.getByLabelText("Email address")).toHaveFocus();
  });

  it("explicit resend keeps the verifier, clears old digits and observes the returned cooldown", async () => {
    vi.mocked(modernAuthApi.resendEmail).mockResolvedValue({ ...challenge(), resend_at: new Date(Date.now() + 60000).toISOString() });
    const cancel = vi.fn(); render(<CodeStep challenge={challenge()} verifier="private-verifier" email="" onComplete={vi.fn()} onCancel={cancel} />);
    fireEvent.change(screen.getByLabelText("Email code"), { target: { value: "12a34567" } });
    expect(screen.getByLabelText("Email code")).toHaveValue("123456");
    fireEvent.click(screen.getByRole("button", { name: "Send another code" }));
    await waitFor(() => expect(screen.getByLabelText("Email code")).toHaveValue(""));
    expect(modernAuthApi.resendEmail).toHaveBeenCalledWith({ challenge_id: "mailbox", client_verifier: "private-verifier" });
    expect(screen.getByRole("button", { name: /Send another code in/ })).toBeDisabled(); expect(screen.getByText(/your provider email/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use another email or method" })); expect(cancel).toHaveBeenCalledOnce();
  });

  it("a rejected code remains retryable while an expired challenge cannot be submitted", async () => {
    vi.mocked(modernAuthApi.verifyEmail).mockRejectedValueOnce(new ApiError("Invalid", 400, null));
    const { unmount } = render(<CodeStep challenge={challenge()} verifier="verifier" email={account.email} onComplete={vi.fn()} onCancel={vi.fn()} />);
    await act(async () => submitCode()); expect(screen.getByRole("alert")).toHaveTextContent(/code isn't valid/); expect(screen.getByRole("button", { name: "Verify and continue" })).toBeEnabled();
    unmount(); render(<CodeStep challenge={{ ...challenge(), expires_at: new Date(Date.now() - 1000).toISOString() }} verifier="verifier" email={account.email} onComplete={vi.fn()} onCancel={vi.fn()} />);
    await act(async () => submitCode()); expect(screen.getByRole("button", { name: "Verify and continue" })).toBeDisabled(); expect(modernAuthApi.verifyEmail).toHaveBeenCalledTimes(1);
  });

  it("the countdown reaches the server expiry without sending or resending anything automatically", async () => {
    vi.useFakeTimers(); const clock = Date.now();
    const { unmount } = render(<CodeStep challenge={{ ...challenge(), expires_at: new Date(clock + 2000).toISOString(), resend_at: new Date(clock + 1000).toISOString() }} verifier="verifier" email={account.email} onComplete={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Send another code in/ })).toBeDisabled(); await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(screen.getByRole("button", { name: "Send another code" })).toBeEnabled(); expect(screen.getByText(/Code expires in 0:01/)).toBeInTheDocument(); await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(screen.getByRole("button", { name: "Verify and continue" })).toBeDisabled(); expect(modernAuthApi.requestEmail).not.toHaveBeenCalled(); expect(modernAuthApi.resendEmail).not.toHaveBeenCalled(); unmount();
  });

  it("a selected Apple sign-in starts one login proof and leaves password access available after failure", async () => {
    vi.mocked(modernAuthApi.startProvider).mockRejectedValue(new ApiError("Unavailable", 503, null)); showEntry();
    fireEvent.click(await screen.findByRole("button", { name: "Sign in with Apple" })); expect(screen.getByRole("button", { name: "Use your password" })).toBeDisabled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Couldn't complete this request/); expect(modernAuthApi.startProvider).toHaveBeenCalledOnce(); expect(modernAuthApi.startProvider).toHaveBeenCalledWith("apple", { purpose: "login", client: "web", client_challenge: expect.stringMatching(/^[A-Za-z0-9_-]{43}$/) });
    expect(screen.getByRole("button", { name: "Use your password" })).toBeEnabled(); expect(sessionStorage.length).toBe(0);
  });

  it("does not duplicate a pending password confirmation and announces busy state immediately", async () => {
    let resolve!: (value: RecentProof) => void; vi.mocked(modernAuthApi.confirmPassword).mockReturnValue(new Promise(done => { resolve = done; }));
    const confirmed = vi.fn(async () => undefined); render(<ConfirmAccount owner="A" action="export" methods={methods} availability={availability} onConfirm={confirmed} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "password" } });
    const form = screen.getByLabelText("Current password").closest("form"); if (!form) throw new Error("Expected confirmation form");
    fireEvent.submit(form); fireEvent.submit(form); expect(screen.getByRole("button", { name: /Please wait/ })).toBeDisabled(); expect(modernAuthApi.confirmPassword).toHaveBeenCalledTimes(1);
    await act(async () => resolve(proof())); expect(confirmed).toHaveBeenCalledTimes(1);
  });

  it("discarded confirmation UI cannot later start its action and expired proof is rejected", async () => {
    let resolve!: (value: RecentProof) => void; vi.mocked(modernAuthApi.confirmPassword).mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const confirmed = vi.fn(async () => undefined); const { unmount } = render(<ConfirmAccount owner="A" action="export" methods={methods} availability={availability} onConfirm={confirmed} onCancel={vi.fn()} />);
    await passwordConfirm(); unmount(); await act(async () => resolve(proof())); expect(confirmed).not.toHaveBeenCalled();
    vi.mocked(modernAuthApi.confirmPassword).mockResolvedValue(proof("expired", Date.now() - 1000));
    render(<ConfirmAccount owner="A" action="export" methods={methods} availability={availability} onConfirm={confirmed} onCancel={vi.fn()} />); await passwordConfirm();
    expect(screen.getByRole("alert")).toHaveTextContent(/Couldn't confirm this account/); expect(confirmed).not.toHaveBeenCalled();
  });

  it("canceling an email confirmation returns to connected choices and rejects the wrong code purpose", async () => {
    const emailMethods = { ...methods, email_verified: true, methods: [...methods.methods, { method: "email" as const, state: "active" as const, usable: true, connected_at: null }] };
    const confirmed = vi.fn(async () => undefined); render(<ConfirmAccount owner="A" action="password" methods={emailMethods} availability={availability} onConfirm={confirmed} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Send an email code" })); await screen.findByLabelText("Email code");
    fireEvent.click(screen.getByRole("button", { name: "Use another email or method" })); expect(screen.getByRole("button", { name: "Confirm with Apple" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send an email code" })); await screen.findByLabelText("Email code");
    vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue({ status: "signed_in", user: account, deletion_cancelled: false }); await act(async () => submitCode());
    expect(screen.getByRole("alert")).toHaveTextContent(/couldn't confirm whether this finished/); expect(confirmed).not.toHaveBeenCalled();
  });

  it("mismatched reset passwords stay editable and a lost reset response never reuses its grant", async () => {
    await resetForm(); newPassword("different-password"); fireEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/don't match/); expect(modernAuthApi.resetPassword).not.toHaveBeenCalled();
    newPassword(); vi.mocked(modernAuthApi.resetPassword).mockRejectedValue(new TypeError("offline")); fireEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't confirm the reset/); expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(modernAuthApi.resetPassword).toHaveBeenCalledTimes(1); expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });

  it("an expired reset requires a fresh recovery code before a password can be saved", async () => {
    const expiry = Date.now() + 1000; await resetForm(expiry); newPassword(); vi.spyOn(Date, "now").mockReturnValue(expiry + 1000);
    fireEvent.click(screen.getByRole("button", { name: "Save password" })); expect(await screen.findByRole("heading", { name: "Reset your password" })).toBeInTheDocument(); expect(modernAuthApi.resetPassword).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Back to sign in" })); expect(screen.getByRole("button", { name: "Use your password" })).toBeInTheDocument();
  });

  it("staged provider mailbox verification signs in without requesting or replaying another handoff", async () => {
    useAuthStore.setState({ user: null, status: "anon", hydrate: vi.fn(async () => { useAuthStore.setState({ user: account, status: "authed" }); }) });
    vi.mocked(modernAuthApi.completeProvider).mockResolvedValue({ status: "verify_mailbox", ...challenge() }); pending(); showCallback();
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue({ status: "signed_in", user: account, deletion_cancelled: true }); await act(async () => submitCode());
    expect(await screen.findByText(/Destination \/settings\/account/)).toBeInTheDocument(); expect(modernAuthApi.completeProvider).toHaveBeenCalledTimes(1); expect(modernAuthApi.requestEmail).not.toHaveBeenCalled(); expect(useAuthStore.getState().deletionCancelledNotice).toBe(true);
  });

  it("provider collision stops automatic linking and directs the person to existing-account sign-in", async () => {
    vi.mocked(modernAuthApi.completeProvider).mockResolvedValue({ status: "existing_account_required", message: "collision" }); pending(); showCallback();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Matching emails don't merge/); expect(screen.getByRole("link", { name: "Back to sign in" })).toHaveAttribute("href", "/login"); expect(sessionStorage.length).toBe(0);
  });

  it("direct provider sign-in corroborates the cookie once and wrong-purpose session results stop", async () => {
    useAuthStore.setState({ hydrate: vi.fn(async () => undefined) }); vi.mocked(modernAuthApi.completeProvider).mockResolvedValue({ status: "signed_in", user: account, deletion_cancelled: false }); pending(); const first = showCallback();
    expect(await screen.findByText(/Destination \/settings\/account/)).toBeInTheDocument(); expect(useAuthStore.getState().deletionCancelledNotice).toBe(false); first.unmount();
    pending("link"); showCallback(); expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't confirm whether linking finished/); expect(takeConfirmation("A", "export")).toBeNull();
  });

  it("provider confirmation is held in memory for the exact action and consumed once", async () => {
    vi.mocked(modernAuthApi.completeProvider).mockResolvedValue(proof()); pending("reauth"); showCallback();
    await screen.findByText(/Destination \/settings\/account/); expect(takeConfirmation("A", "export")).toMatchObject({ recent_proof: "recent-proof" }); expect(takeConfirmation("A", "export")).toBeNull(); expect(sessionStorage.length).toBe(0);
    rememberConfirmation("A", "export", proof()); expect(takeConfirmation("A", "delete")).toBeNull();
    rememberConfirmation("A", "export", proof("old", Date.now() - 1000)); expect(takeConfirmation("A", "export")).toBeNull();
  });

  it("a hydration timeout consumes callback state and never submits the owner-bound handoff", async () => {
    vi.useFakeTimers(); useAuthStore.setState({ user: null, status: "loading", hydrate: vi.fn(() => new Promise<void>(() => undefined)) }); pending("link"); showCallback();
    expect(location.hash).toBe(""); await act(async () => vi.advanceTimersByTimeAsync(10000));
    expect(screen.getByRole("alert")).toHaveTextContent(/couldn't confirm whether linking finished/); expect(modernAuthApi.completeProvider).not.toHaveBeenCalled(); expect(sessionStorage.length).toBe(0);
  });

  it("a rejected hydration and wrong provider outcome fail closed without session authority", async () => {
    useAuthStore.setState({ user: null, status: "loading", hydrate: vi.fn(async () => { throw new Error("offline"); }) }); pending("reauth"); const first = showCallback();
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't confirm whether this finished/); expect(modernAuthApi.completeProvider).not.toHaveBeenCalled(); first.unmount();
    useAuthStore.setState({ user: account, status: "authed" }); vi.mocked(modernAuthApi.completeProvider).mockResolvedValue({ status: "linked", user: { id: "B", email: "b@example.com" } }); pending("link"); showCallback();
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't confirm whether linking finished/); expect(useAuthStore.getState().user?.id).toBe("A");
  });

  it("refuses a signed-in result that the current cookie cannot corroborate", async () => {
    useAuthStore.setState({ hydrate: vi.fn(async () => undefined) });
    await expect(acceptSignedIn({ status: "reset_ready", reset_grant: "g", expires_at: new Date().toISOString() })).rejects.toThrow();
    await expect(acceptSignedIn({ status: "signed_in", user: { id: "B", email: "b@example.com" }, deletion_cancelled: false })).rejects.toThrow(/confirm sign-in/);
    expect(useAuthStore.getState().user?.id).toBe("A");
    await acceptSignedIn({ status: "signed_in", user: { ...account, deletion_cancelled: true }, deletion_cancelled: false }); expect(useAuthStore.getState().deletionCancelledNotice).toBe(true);
  });

  it("retries account metadata and disables mutations until it belongs to the captured owner", async () => {
    vi.mocked(modernAuthApi.accountMethods).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ ...methods, account_id: "B" }).mockResolvedValueOnce(methods); vi.mocked(modernAuthApi.methods).mockRejectedValueOnce(new Error("configuration unavailable"));
    showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Retry" })); await waitFor(() => expect(modernAuthApi.accountMethods).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled(); fireEvent.click(screen.getByRole("button", { name: "Retry" })); expect(await screen.findByRole("button", { name: "Remove Google" })).toBeEnabled();
  });

  it("late metadata cannot expose action controls after the signed-in owner changes", async () => {
    let resolve!: (value: AccountMethods) => void; vi.mocked(modernAuthApi.accountMethods).mockReturnValue(new Promise(done => { resolve = done; })); showAccount();
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();
    await act(async () => { useAuthStore.setState({ user: { id: "B", email: "b@example.com" } }); resolve(methods); });
    expect(screen.getByRole("alert")).toHaveTextContent(/Use the account linked to this action/); expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
  });

  it("abandoned account and discovery requests do not repopulate a closed screen", async () => {
    let resolveMetadata!: (value: AccountMethods) => void; let resolveAvailability!: (value: typeof availability) => void;
    vi.mocked(modernAuthApi.accountMethods).mockReturnValue(new Promise(done => { resolveMetadata = done; })); vi.mocked(modernAuthApi.methods).mockReturnValue(new Promise(done => { resolveAvailability = done; }));
    const first = showAccount(); first.unmount(); await act(async () => { resolveMetadata(methods); resolveAvailability(availability); }); expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
    let rejectMetadata!: (error: Error) => void; let rejectAvailability!: (error: Error) => void;
    vi.mocked(modernAuthApi.accountMethods).mockReturnValue(new Promise((_done, reject) => { rejectMetadata = reject; })); vi.mocked(modernAuthApi.methods).mockReturnValue(new Promise((_done, reject) => { rejectAvailability = reject; }));
    const second = showAccount(); second.unmount(); await act(async () => { rejectMetadata(new Error("offline")); rejectAvailability(new Error("offline")); });
    const third = showEntry(); third.unmount(); await act(async () => rejectAvailability(new Error("offline"))); expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a callback-confirmed Google reconnect uses the saved action proof and cannot merge by email", async () => {
    vi.mocked(modernAuthApi.accountMethods).mockResolvedValue({ ...methods, methods: methods.methods.map(method => method.method === "google" ? { ...method, state: "disabled", usable: false } : method) }); vi.mocked(modernAuthApi.startProvider).mockRejectedValue(new Error("offline"));
    rememberConfirmation("A", "link:google", proof()); showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Reconnect Google" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Couldn't start linking/); expect(modernAuthApi.startProvider).toHaveBeenCalledWith("google", expect.objectContaining({ purpose: "link", action: "link:google", expected_account_id: "A", recent_proof: "recent-proof" })); expect(modernAuthApi.confirmPassword).not.toHaveBeenCalled();
    expect(takeConfirmation("A", "link:google")).toBeNull();
  });

  it("verification can renew recent proof without issuing a second mailbox challenge", async () => {
    vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue({ status: "verified_email", user: account }); showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Verify email" })); await passwordConfirm(); await screen.findByLabelText("Email code");
    fireEvent.click(screen.getByRole("button", { name: "Confirm again for this email change" })); vi.mocked(modernAuthApi.confirmPassword).mockResolvedValue(proof("renewed-proof")); await passwordConfirm(); await screen.findByLabelText("Email code"); await act(async () => submitCode());
    expect(await screen.findByRole("status")).toHaveTextContent(/Email verified/); expect(modernAuthApi.requestEmail).toHaveBeenCalledTimes(1); expect(modernAuthApi.verifyEmail).toHaveBeenCalledWith(expect.objectContaining({ recent_proof: "renewed-proof" }));
  });

  it("a foreign email completion does not update this account and cannot be replayed", async () => {
    vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue({ status: "changed_email", user: { id: "B", email: "foreign@example.com" } }); showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Verify email" })); await passwordConfirm(); await screen.findByLabelText("Email code"); await act(async () => submitCode());
    expect(screen.getByRole("alert")).toHaveTextContent(/couldn't confirm whether this finished/); expect(useAuthStore.getState().user?.email).toBe(account.email); expect(screen.getByRole("button", { name: "Verify and continue" })).toBeDisabled();
  });

  it("password addition validates the repeat then consumes saved provider proof for the intended action", async () => {
    vi.mocked(modernAuthApi.accountMethods).mockResolvedValue({ ...methods, has_password: false }); vi.mocked(modernAuthApi.setPassword).mockResolvedValue(undefined); showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Add password" })); newPassword("different-password"); fireEvent.click(screen.getByRole("button", { name: "Confirm and save" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/don't match/); expect(modernAuthApi.setPassword).not.toHaveBeenCalled();
    rememberConfirmation("A", "password", proof()); newPassword(); fireEvent.click(screen.getByRole("button", { name: "Confirm and save" }));
    expect(await screen.findByText(/Password saved/)).toHaveAttribute("role", "status"); expect(modernAuthApi.setPassword).toHaveBeenCalledWith({ expected_account_id: "A", recent_proof: "recent-proof", new_password: "new-password-123" }); expect(modernAuthApi.confirmPassword).not.toHaveBeenCalled();
  });

  it("a failed export asks for fresh confirmation and then closes after a successful download", async () => {
    vi.mocked(modernAuthApi.exportAccount).mockRejectedValueOnce(new ApiError("Conflict", 409, null)).mockResolvedValueOnce("export.zip"); showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Export" })); await passwordConfirm(); expect(screen.getByRole("alert")).toHaveTextContent(/Check your sign-in methods/);
    fireEvent.click(screen.getByRole("button", { name: "Confirm again" })); await passwordConfirm(); expect(await screen.findByRole("status")).toHaveTextContent(/Download started/); expect(modernAuthApi.confirmPassword).toHaveBeenCalledTimes(2);
  });

  it("an owner-restricted 404 is shown without retrying a consumed export proof", async () => {
    vi.mocked(modernAuthApi.exportAccount).mockRejectedValue(new ApiError("Not found", 404, null)); showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Export" })); await passwordConfirm();
    expect(screen.getByRole("alert")).toHaveTextContent(/Use the account linked to this action/); expect(modernAuthApi.exportAccount).toHaveBeenCalledTimes(1); expect(screen.getByRole("button", { name: "Confirm again" })).toBeInTheDocument();
  });

  it("successful Apple unlink retains other sessions and reports pending provider cleanup truthfully", async () => {
    vi.mocked(modernAuthApi.unlink).mockResolvedValue({ methods, signed_out: false }); showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Remove Apple" })); fireEvent.click(screen.getByRole("button", { name: "Keep method" })); expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Remove Apple" })); fireEvent.click(screen.getByRole("button", { name: "Confirm removal" })); await passwordConfirm(); expect(await screen.findByRole("status")).toHaveTextContent(/Apple cleanup may still be pending/); expect(useAuthStore.getState().user?.id).toBe("A");
  });

  it("Google unlink refreshes the same-owner methods while retaining an unaffected session", async () => {
    vi.mocked(modernAuthApi.unlink).mockResolvedValue({ methods, signed_out: false }); showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Remove Google" })); fireEvent.click(screen.getByRole("button", { name: "Confirm removal" })); await passwordConfirm();
    expect(await screen.findByRole("status")).toHaveTextContent(/Affected sessions have ended/); expect(useAuthStore.getState().user?.id).toBe("A"); expect(modernAuthApi.accountMethods).toHaveBeenCalledTimes(2);
  });

  it("untrusted unlink metadata requires checking the account instead of claiming success", async () => {
    vi.mocked(modernAuthApi.unlink).mockResolvedValue({ methods: { ...methods, account_id: "B" }, signed_out: false }); showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Remove Google" })); fireEvent.click(screen.getByRole("button", { name: "Confirm removal" })); await passwordConfirm(); expect(screen.getByRole("alert")).toHaveTextContent(/couldn't confirm whether this finished/); fireEvent.click(screen.getByRole("button", { name: "Check account" })); await waitFor(() => expect(modernAuthApi.accountMethods).toHaveBeenCalledTimes(2)); expect(modernAuthApi.unlink).toHaveBeenCalledTimes(1);
  });

  it("a post-deletion local cleanup failure still ends the revoked session and exposes the cleanup limitation", async () => {
    vi.mocked(modernAuthApi.deleteAccount).mockResolvedValue({ deletion_requested_at: new Date().toISOString(), purge_at: "2026-10-20T12:00:00Z" }); useAuthStore.setState({ clearSessionAfterCleanup: vi.fn(async () => false) }); showAccount(true);
    fireEvent.click(await screen.findByRole("button", { name: "Confirm and delete" })); await passwordConfirm(); expect(await screen.findByText(/Destination \/login/)).toHaveTextContent(/couldn't clear this browser/); expect(useAuthStore.getState().status).toBe("anon");
  });

  it("provider confirmation and reconnect failures preserve the existing account methods", async () => {
    vi.mocked(modernAuthApi.startProvider).mockRejectedValue(new Error("offline")); vi.mocked(modernAuthApi.accountMethods).mockResolvedValue({ ...methods, methods: methods.methods.map(method => method.method === "apple" ? { ...method, state: "disabled", usable: false } : method) }); showAccount(); fireEvent.click(await screen.findByRole("button", { name: "Reconnect Apple" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm with Google" })); expect(await screen.findByRole("alert")).toHaveTextContent(/Couldn't complete this request/);
    await passwordConfirm(); expect(await screen.findByText(/Couldn't start linking/)).toHaveAttribute("role", "alert"); expect(modernAuthApi.startProvider).toHaveBeenLastCalledWith("apple", expect.objectContaining({ purpose: "link", action: "link:apple", expected_account_id: "A", recent_proof: "recent-proof" }));
    fireEvent.click(await screen.findByRole("button", { name: "Close dialog" })); expect(screen.getByRole("button", { name: "Reconnect Apple" })).toBeInTheDocument();
  });

  it.each([null, "http://accounts.google.com/oauth", "https://evil.example/oauth", "https://name:secret@accounts.google.com/oauth"])("rejects an unsafe provider destination %s before storing verifier state", async url => {
    vi.mocked(modernAuthApi.startProvider).mockResolvedValue({ attempt_id: token, state: token, nonce: token, authorization_url: url }); await expect(startBrowserProvider("google", { purpose: "login" })).rejects.toThrow(); expect(sessionStorage.length).toBe(0);
  });

  it("valid provider navigation stores only a short-lived verifier and fixed owner-bound return metadata", async () => {
    const assign = vi.fn(); const browser = window;
    vi.mocked(modernAuthApi.startProvider).mockResolvedValue({ attempt_id: token, state: token, nonce: token, authorization_url: "https://appleid.apple.com/auth/authorize" });
    vi.stubGlobal("window", { location: { assign } });
    try { await startBrowserProvider("apple", { purpose: "reauth", action: "password", expected_account_id: "A" }, "/settings/account?expected_owner=A&redirect=https://evil.test"); }
    finally { vi.stubGlobal("window", browser); }
    expect(assign).toHaveBeenCalledWith("https://appleid.apple.com/auth/authorize");
    const pending = JSON.parse(sessionStorage.getItem("brainbuddy.auth.provider-attempt") ?? "{}");
    expect(pending).toMatchObject({ purpose: "reauth", action: "password", expectedOwner: "A", destination: "/settings/account?expected_owner=A", verifier: expect.stringMatching(/^[A-Za-z0-9_-]{43}$/) });
    expect(pending.expiresAt - Date.now()).toBeLessThanOrEqual(600000); expect(pending.expiresAt).toBeGreaterThan(Date.now());
    expect(pending).not.toHaveProperty("recent_proof"); expect(pending).not.toHaveProperty("handoff_code");
  });

  it("stale or mismatched callback state is erased and resource return destinations stay allowlisted", () => {
    for (const changes of [{ expiresAt: Date.now() - 1000 }, { state: "z".repeat(43) }, { verifier: "bad" }, { expiresAt: Date.now() + 700000 }]) {
      saveProviderAttempt({ attemptId: token, state: token, verifier: "v".repeat(43), purpose: "login", destination: "/", expiresAt: Date.now() + 60000, ...changes }); history.replaceState(null, "", `/auth/complete#attempt=${token}&state=${token}&grant=${token}`); expect(() => takeProviderCallback()).toThrow(); expect(location.hash).toBe(""); expect(sessionStorage.length).toBe(0);
    }
    expect(safeAuthDestination("/unknown" )).toBe("/"); expect(safeAuthDestination("/tasks/next/task-1?redirect=https://evil.test")).toBe("/tasks/next/task-1"); expect(safeAuthDestination(null)).toBe("/");
    pending(); history.replaceState(null, "", `/auth/complete#attempt=${token}&state=${token}&extra=${token}`); expect(() => takeProviderCallback()).toThrow(); expect(sessionStorage.length).toBe(0);
  });
});
