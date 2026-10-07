import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { authApi } from "../../api/auth";
import { modernAuthApi } from "../../api/modernAuth";
import { useAuthStore } from "../../stores/authStore";
import * as crtBoundary from "../../features/crt/crtDraftCoordinator";
import LoginPage from "../LoginPage";

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>workspace</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function renderLinkedLogin(pathname = "/settings/account/delete") {
  return render(<MemoryRouter initialEntries={[{ pathname: "/login", state: { from: { pathname, search: "?expected_owner=A" } } }]}>
    <Routes><Route path="/login" element={<LoginPage />} /><Route path={pathname} element={<div>linked account destination</div>} /></Routes>
  </MemoryRouter>);
}

describe("LoginPage", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "anon", deletionScheduledFor: null });
    vi.spyOn(modernAuthApi, "methods").mockResolvedValue({ password: true, email: true, google: false, apple: false, web_account_origin: null });
  });
  afterEach(() => vi.restoreAllMocks());

  it("submits credentials and redirects to /", async () => {
    const loginSpy = vi
      .spyOn(authApi, "login")
      .mockResolvedValue({ id: "u1", email: "a@b.c" });
    renderLogin();

    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Use your password" }));
      await user.type(screen.getByLabelText(/email/i), "a@b.c");
      await user.type(screen.getByLabelText(/password/i), "very-long-password");
      await user.click(screen.getByRole("button", { name: /sign in/i }));
    });

    await waitFor(() => expect(loginSpy).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText(/workspace/i)).toBeInTheDocument()
    );
  });

  it("shows a generic error on 401", async () => {
    vi.spyOn(authApi, "login").mockRejectedValue(
      new ApiError("Unauthorized", 401, null)
    );
    renderLogin();

    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Use your password" }));
      await user.type(screen.getByLabelText(/email/i), "a@b.c");
      await user.type(screen.getByLabelText(/password/i), "wrong-password");
      await user.click(screen.getByRole("button", { name: /sign in/i }));
    });

    await waitFor(() =>
      expect(screen.getByText(/invalid email or password/i)).toBeInTheDocument()
    );
  });

  it("shows a rate-limit message on 429", async () => {
    vi.spyOn(authApi, "login").mockRejectedValue(
      new ApiError("Too Many", 429, null)
    );
    renderLogin();

    const user = userEvent.setup();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Use your password" }));
      await user.type(screen.getByLabelText(/email/i), "a@b.c");
      await user.type(screen.getByLabelText(/password/i), "password-here");
      await user.click(screen.getByRole("button", { name: /sign in/i }));
    });

    await waitFor(() =>
      expect(screen.getByText(/too many attempts/i)).toBeInTheDocument()
    );
  });

  it("shows the grace notice from the auth store when router state was lost", () => {
    useAuthStore.setState({ deletionScheduledFor: "2026-08-20T12:00:00Z" });
    renderLogin();
    expect(screen.getByRole("status")).toHaveTextContent(/permanently deleted on/i);
  });

  it("explains the grace period after an account deletion request", () => {
    render(
      <MemoryRouter
        initialEntries={[
          { pathname: "/login", state: { deletionScheduled: "2026-08-20T12:00:00Z" } }
        ]}
      >
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByRole("status")).toHaveTextContent(/permanently deleted on/i);
    expect(screen.getByRole("status")).toHaveTextContent(/sign back in before then/i);
  });

  it("links to the privacy policy", () => {
    renderLogin();
    expect(screen.getByRole("link", { name: /privacy policy/i })).toHaveAttribute(
      "href",
      "/privacy"
    );
  });

  it("sends an already-signed-in visitor straight to the workspace", () => {
    useAuthStore.setState({ user: { id: "u1", email: "a@b.c" }, status: "authed" });
    renderLogin();

    expect(screen.getByText("workspace")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument();
  });

  it.each(["/settings/account", "/settings/account/delete"])("requires an explicit confirmed account switch before email sign-in to %s", async pathname => {
    useAuthStore.setState({ user: { id: "B", email: "b@example.com" }, status: "authed" });
    const cleanup = vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 2 });
    const logout = vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    let confirm!: (value: null) => void;
    const me = vi.spyOn(authApi, "me").mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockReturnValueOnce(new Promise(resolve => { confirm = resolve; })).mockResolvedValue(null);
    const request = vi.spyOn(modernAuthApi, "requestEmail").mockResolvedValue({ challenge_id: "c", expires_at: new Date(Date.now() + 600000).toISOString(), resend_at: new Date(Date.now() + 60000).toISOString(), message: "Check your email" });
    vi.spyOn(modernAuthApi, "verifyEmail").mockImplementation(async () => {
      me.mockResolvedValue({ id: "A", email: "a@example.com" });
      return { status: "signed_in", user: { id: "A", email: "a@example.com" }, deletion_cancelled: false };
    });
    renderLinkedLogin(pathname);
    expect(screen.queryByRole("button", { name: "Continue with email" })).not.toBeInTheDocument();
    expect(logout).not.toHaveBeenCalled();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Sign out and use linked account" }));
    await waitFor(() => expect(me).toHaveBeenCalledTimes(3));
    expect(cleanup).toHaveBeenCalledWith("B", window.location.origin);
    expect(logout).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Sign out and use linked account" })).toBeDisabled();
    expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
    await act(async () => { confirm(null); });
    await user.type(await screen.findByLabelText("Email address"), "a@example.com");
    await user.click(screen.getByRole("button", { name: "Continue with email" }));
    expect(request).toHaveBeenCalledOnce();
    await user.type(await screen.findByLabelText("Email code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify and continue" }));
    expect(await screen.findByText("linked account destination")).toBeInTheDocument();
    expect(useAuthStore.getState().user?.id).toBe("A");
  });

  it.each(["logout offline", "confirmation offline", "cookie retained", "cleanup refused"])("keeps sign-in blocked after %s and allows explicit retry", async failure => {
    useAuthStore.setState({ user: { id: "B", email: "b@example.com" }, status: "authed" });
    const cleanup = vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 0 });
    const logout = vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    const me = vi.spyOn(authApi, "me").mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockResolvedValue(null);
    if (failure === "logout offline") logout.mockRejectedValueOnce(new Error("offline"));
    if (failure === "confirmation offline") me.mockRejectedValueOnce(new Error("offline"));
    if (failure === "cookie retained") me.mockResolvedValueOnce({ id: "B", email: "b@example.com" });
    if (failure === "cleanup refused") cleanup.mockResolvedValueOnce({ ok: false, reason: "cleanup-failed" });
    renderLinkedLogin();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Sign out and use linked account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't confirm sign-out/i);
    expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
    expect(useAuthStore.getState().user?.id).toBe("B");
    if (failure === "cleanup refused") { expect(logout).not.toHaveBeenCalled(); expect(me).toHaveBeenCalledTimes(1); }
    me.mockReset().mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockResolvedValue(null);
    await user.click(screen.getByRole("button", { name: "Sign out and use linked account" }));
    expect(await screen.findByLabelText("Email address")).toBeInTheDocument();
  });

  it("waits for expected-owner hydration without exposing authentication methods", () => {
    useAuthStore.setState({ status: "loading" });
    renderLinkedLogin();
    expect(screen.getByText("Checking your current account…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use your password" })).not.toBeInTheDocument();
    expect(modernAuthApi.methods).not.toHaveBeenCalled();
  });

  it("continues directly when the linked owner is already authenticated", () => {
    useAuthStore.setState({ user: { id: "A", email: "a@example.com" }, status: "authed" });
    renderLinkedLogin();
    expect(screen.getByText("linked account destination")).toBeInTheDocument();
  });

  it("does not trust local anonymous state or reuse confirmation after another session transition", async () => {
    const logout = vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 0 });
    const me = vi.spyOn(authApi, "me").mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockResolvedValue(null);
    renderLinkedLogin();
    const user = userEvent.setup();
    expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign out and use linked account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't confirm sign-out/i);
    expect(screen.queryByRole("button", { name: "Continue with email" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign out and use linked account" }));
    expect(await screen.findByLabelText("Email address")).toBeInTheDocument();
    expect(logout).toHaveBeenCalledTimes(2);
    expect(me).toHaveBeenCalledTimes(6);
    await act(async () => { useAuthStore.getState().clearSession(); });
    expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out and use linked account" })).toBeEnabled();
  });

  it("blocks a newer owner hydrated between confirmed logout and form admission", async () => {
    useAuthStore.setState({ user: { id: "B", email: "b@example.com" }, status: "authed" });
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 0 });
    vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    vi.spyOn(authApi, "me").mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockResolvedValueOnce({ id: "B", email: "b@example.com" }).mockResolvedValueOnce(null).mockResolvedValue({ id: "C", email: "c@example.com" });
    let started = false;
    const unsubscribe = useAuthStore.subscribe(state => {
      if (state.status === "anon" && !started) {
        started = true;
        void useAuthStore.getState().hydrate();
      }
    });
    try {
      renderLinkedLogin();
      await act(async () => { await userEvent.setup().click(screen.getByRole("button", { name: "Sign out and use linked account" })); });
      await waitFor(() => expect(useAuthStore.getState().user?.id).toBe("C"));
      expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
      expect(modernAuthApi.methods).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Sign out and use linked account" })).toBeEnabled();
    } finally { unsubscribe(); }
  });

  it.each(["email", "password", "google"])("rechecks the shared cookie before linked-owner %s sign-in", async method => {
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 0 });
    vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    const me = vi.spyOn(authApi, "me").mockResolvedValue(null);
    vi.mocked(modernAuthApi.methods).mockResolvedValue({ password: true, email: true, google: true, apple: false, web_account_origin: null });
    const request = vi.spyOn(modernAuthApi, "requestEmail").mockRejectedValue(new Error("must not request"));
    const login = vi.spyOn(authApi, "login").mockRejectedValue(new Error("must not log in"));
    const provider = vi.spyOn(modernAuthApi, "startProvider").mockRejectedValue(new Error("must not start"));
    renderLinkedLogin();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Sign out and use linked account" }));
    await screen.findByLabelText("Email address");
    const confirmed = useAuthStore.getState();
    me.mockResolvedValue({ id: "C", email: "c@example.com" });
    if (method === "google") await user.click(screen.getByRole("button", { name: "Sign in with Google" }));
    else {
      if (method === "password") await user.click(screen.getByRole("button", { name: "Use your password" }));
      await user.type(screen.getByLabelText("Email address"), "a@example.com");
      if (method === "password") await user.type(screen.getByLabelText("Password"), "long-password");
      await user.click(screen.getByRole("button", { name: method === "email" ? "Continue with email" : "Sign in" }));
    }
    expect(await screen.findByRole("button", { name: "Sign out and use linked account" })).toBeEnabled();
    expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
    expect(request).not.toHaveBeenCalled(); expect(login).not.toHaveBeenCalled(); expect(provider).not.toHaveBeenCalled();
    expect(useAuthStore.getState()).toBe(confirmed);
  });

  it.each(["before verification", "during verification", "before resend"])("returns to explicit account switching when the cookie changes %s", async boundary => {
    vi.spyOn(crtBoundary, "cleanupCrtOwnerScope").mockResolvedValue({ ok: true, removed: 0 });
    vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    const me = vi.spyOn(authApi, "me").mockResolvedValue(null);
    vi.spyOn(modernAuthApi, "requestEmail").mockResolvedValue({ challenge_id: "c", expires_at: new Date(Date.now() + 600000).toISOString(), resend_at: new Date(Date.now() - 1000).toISOString(), message: "Check your email" });
    const verify = vi.spyOn(modernAuthApi, "verifyEmail").mockImplementation(async () => {
      me.mockResolvedValue({ id: "C", email: "c@example.com" });
      throw new ApiError("Not found", 404, { detail: { code: "owner_mismatch" } });
    });
    const resend = vi.spyOn(modernAuthApi, "resendEmail").mockRejectedValue(new Error("must not resend"));
    renderLinkedLogin(); const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Sign out and use linked account" }));
    await user.type(await screen.findByLabelText("Email address"), "a@example.com");
    await user.click(screen.getByRole("button", { name: "Continue with email" }));
    await screen.findByLabelText("Email code");
    if (boundary !== "during verification") me.mockResolvedValue({ id: "C", email: "c@example.com" });
    if (boundary === "before resend") await user.click(screen.getByRole("button", { name: "Send another code" }));
    else { await user.type(screen.getByLabelText("Email code"), "123456"); await user.click(screen.getByRole("button", { name: "Verify and continue" })); }
    expect(await screen.findByRole("button", { name: "Sign out and use linked account" })).toBeEnabled();
    expect(verify).toHaveBeenCalledTimes(boundary === "during verification" ? 1 : 0); expect(resend).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Email code")).not.toBeInTheDocument();
  });

  it.each(["offline", "new local transition"])("fails closed when the linked-owner preflight encounters %s", async failure => {
    vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    const me = vi.spyOn(authApi, "me").mockResolvedValue(null);
    const request = vi.spyOn(modernAuthApi, "requestEmail").mockRejectedValue(new Error("must not request"));
    renderLinkedLogin(); const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Sign out and use linked account" }));
    await user.type(await screen.findByLabelText("Email address"), "a@example.com");
    me.mockImplementationOnce(async () => {
      if (failure === "offline") throw new Error("offline");
      useAuthStore.getState().clearSession(); return null;
    });
    await user.click(screen.getByRole("button", { name: "Continue with email" }));
    expect(await screen.findByRole("button", { name: "Sign out and use linked account" })).toBeEnabled();
    expect(request).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
  });

  it.each(["proof creation", "after session read"])("does not dispatch a sign-in after confirmation changes during %s", async boundary => {
    vi.spyOn(authApi, "logout").mockResolvedValue(undefined);
    const me = vi.spyOn(authApi, "me").mockResolvedValue(null);
    const request = vi.spyOn(modernAuthApi, "requestEmail").mockRejectedValue(new Error("must not request"));
    renderLinkedLogin(); const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Sign out and use linked account" }));
    await user.type(await screen.findByLabelText("Email address"), "a@example.com");
    let finish!: () => void;
    if (boundary === "proof creation") vi.spyOn(crypto.subtle, "digest").mockReturnValueOnce(new Promise(resolve => { finish = () => resolve(new ArrayBuffer(32)); }));
    else me.mockImplementationOnce(async () => {
      queueMicrotask(() => queueMicrotask(() => useAuthStore.getState().clearSession()));
      return null;
    });
    await user.click(screen.getByRole("button", { name: "Continue with email" }));
    if (boundary === "proof creation") await act(async () => { useAuthStore.getState().clearSession(); finish(); });
    expect(await screen.findByRole("alert")).toHaveTextContent(/session changed or couldn't be checked/i);
    expect(screen.getByRole("button", { name: "Sign out and use linked account" })).toBeEnabled();
    expect(request).not.toHaveBeenCalled();
    expect(me).toHaveBeenCalledTimes(boundary === "proof creation" ? 3 : 4);
  });
});
