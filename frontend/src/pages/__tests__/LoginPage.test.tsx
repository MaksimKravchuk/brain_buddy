import { render, screen, waitFor } from "@testing-library/react";
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

    await userEvent.type(screen.getByLabelText(/email/i), "a@b.c");
    await userEvent.type(screen.getByLabelText(/password/i), "very-long-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

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

    await userEvent.type(screen.getByLabelText(/email/i), "a@b.c");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      expect(screen.getByText(/invalid email or password/i)).toBeInTheDocument()
    );
  });

  it("shows a rate-limit message on 429", async () => {
    vi.spyOn(authApi, "login").mockRejectedValue(
      new ApiError("Too Many", 429, null)
    );
    renderLogin();

    await userEvent.type(screen.getByLabelText(/email/i), "a@b.c");
    await userEvent.type(screen.getByLabelText(/password/i), "password-here");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      expect(screen.getByText(/too many login attempts/i)).toBeInTheDocument()
    );
  });
});
