import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { authApi } from "../../api/auth";
import { useAuthStore } from "../../stores/authStore";
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

describe("LoginPage", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "anon" });
  });
  afterEach(() => vi.restoreAllMocks());

  it("submits credentials and redirects to /", async () => {
    const loginSpy = vi
      .spyOn(authApi, "login")
      .mockResolvedValue({ id: "u1", email: "a@b.c" });
    renderLogin();

    const user = userEvent.setup();
    await act(async () => {
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
      await user.type(screen.getByLabelText(/email/i), "a@b.c");
      await user.type(screen.getByLabelText(/password/i), "password-here");
      await user.click(screen.getByRole("button", { name: /sign in/i }));
    });

    await waitFor(() =>
      expect(screen.getByText(/too many login attempts/i)).toBeInTheDocument()
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
});
