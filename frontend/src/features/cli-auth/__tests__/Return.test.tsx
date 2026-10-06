import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { modernAuthApi } from "../../../api/modernAuth";
import { useAuthStore } from "../../../stores/authStore";
import { AuthEntry } from "../../auth/AuthEntry";
import { ProviderCompletionPage } from "../../auth/ProviderCompletionPage";
import * as authFlow from "../../auth/authFlow";
import { CliAuthorizePage } from "../CliAuthorizePage";
import { captureCode, retainedCode } from "../code";
import { cliAuthApi } from "../api";

vi.mock("../../../api/modernAuth", () => ({ modernAuthApi: { methods: vi.fn(), requestEmail: vi.fn(), verifyEmail: vi.fn(), completeProvider: vi.fn() } }));
vi.mock("../api", () => ({ cliAuthApi: { request: vi.fn(), decision: vi.fn() } }));
const original = { login: useAuthStore.getState().login, hydrate: useAuthStore.getState().hydrate };
const user = { id: "A", email: "a@example.com", feature_flags: { cli_auth: true } };
const signedIn = { status: "signed_in" as const, user, deletion_cancelled: false };
function show(callback = false) {
  return render(<MemoryRouter initialEntries={[callback ? "/auth/complete" : "/login"]}><Routes>
    <Route path="/login" element={<AuthEntry destination="/cli/authorize" />} />
    <Route path="/auth/complete" element={<ProviderCompletionPage />} />
    <Route path="/cli/authorize" element={<CliAuthorizePage />} />
  </Routes></MemoryRouter>);
}
async function assertApproval(): Promise<void> {
  expect(await screen.findByRole("button", { name: "Approve access" })).toBeEnabled();
  expect(screen.getByText(user.email)).toBeInTheDocument();
  expect(retainedCode()?.userCode).toBe("ABCD-EFGH");
  expect(cliAuthApi.decision).not.toHaveBeenCalled();
}

describe("024-FR-013 shared sign-in returns to explicit CLI approval", () => {
  beforeEach(() => {
    vi.clearAllMocks(); sessionStorage.clear(); captureCode("#user_code=ABCD-EFGH");
    useAuthStore.setState({ user: null, status: "anon", hydrate: vi.fn(async () => { useAuthStore.setState({ user, status: "authed" }); }) });
    vi.mocked(modernAuthApi.methods).mockResolvedValue({ google: true, apple: true, email: true, password: true, web_account_origin: null });
    vi.mocked(cliAuthApi.request).mockResolvedValue({ user_code: "ABCD-EFGH", client_name: "BrainBuddy CLI", created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 600000).toISOString(), state: "pending" });
  });
  afterEach(() => { useAuthStore.setState(original); sessionStorage.clear(); history.replaceState(null, "", "/"); vi.restoreAllMocks(); });
  it.each(["google", "apple"] as const)("preserves the short code and clean destination through %s sign-in", async provider => {
    const start = vi.spyOn(authFlow, "startBrowserProvider").mockResolvedValue();
    const entry = show();
    fireEvent.click(await screen.findByRole("button", { name: `Sign in with ${provider === "google" ? "Google" : "Apple"}` }));
    await waitFor(() => expect(start).toHaveBeenCalledWith(provider, { purpose: "login" }, "/cli/authorize", undefined));
    expect(retainedCode()?.userCode).toBe("ABCD-EFGH");
    entry.unmount();
    // Synthetic provider handoff exercises the real shared completion page.
    const token = "a".repeat(43);
    authFlow.saveProviderAttempt({ attemptId: token, state: token, verifier: "v".repeat(43), purpose: "login", destination: "/cli/authorize", expiresAt: Date.now() + 60000 });
    history.replaceState(null, "", `/auth/complete#attempt=${token}&state=${token}&grant=${token}`);
    vi.mocked(modernAuthApi.completeProvider).mockResolvedValue(signedIn);
    show(true); await assertApproval();
    expect(location.hash).toBe("");
    expect(modernAuthApi.completeProvider).toHaveBeenCalledTimes(1);
  });
  it("returns from email-code login with the code retained and no implicit decision", async () => {
    vi.mocked(modernAuthApi.requestEmail).mockResolvedValue({ challenge_id: "mail-challenge", expires_at: new Date(Date.now() + 600000).toISOString(), resend_at: new Date(Date.now() + 60000).toISOString(), message: "Check your email" });
    vi.mocked(modernAuthApi.verifyEmail).mockResolvedValue(signedIn);
    show();
    fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: user.email } });
    fireEvent.click(screen.getByRole("button", { name: "Continue with email" }));
    fireEvent.change(await screen.findByLabelText("Email code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    await assertApproval();
  });
  it("returns from password login to approval for the actual signed-in account", async () => {
    useAuthStore.setState({ login: vi.fn(async () => { useAuthStore.setState({ user, status: "authed" }); }) });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Use your password" }));
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "synthetic-password" } });
    fireEvent.click(screen.getByRole("button", { name: /^Sign in$/ }));
    await assertApproval();
  });
});
