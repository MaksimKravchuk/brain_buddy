import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { authApi } from "../../api/auth";
import { useAuthStore } from "../../stores/authStore";
import SignupPage from "../SignupPage";

function renderSignup() {
  return render(
    <MemoryRouter initialEntries={["/signup"]}>
      <Routes>
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/" element={<div>workspace</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe("SignupPage", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "anon" });
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows an error when the invite code is rejected", async () => {
    vi.spyOn(authApi, "signup").mockRejectedValue(
      new ApiError("Bad", 400, null)
    );
    renderSignup();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(screen.getByLabelText(/email/i), "a@b.c");
      await user.type(screen.getByLabelText(/password/i), "very-long-password");
      await user.type(screen.getByLabelText(/invite code/i), "bad-code");
      await user.click(screen.getByRole("button", { name: /create account/i }));
    });

    await waitFor(() =>
      expect(screen.getByText(/invite code is invalid/i)).toBeInTheDocument()
    );
  });

  it("redirects on successful signup", async () => {
    const spy = vi
      .spyOn(authApi, "signup")
      .mockResolvedValue({ id: "u1", email: "a@b.c" });
    renderSignup();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(screen.getByLabelText(/email/i), "a@b.c");
      await user.type(screen.getByLabelText(/password/i), "very-long-password");
      await user.type(screen.getByLabelText(/invite code/i), "good-code");
      await user.click(screen.getByRole("button", { name: /create account/i }));
    });

    await waitFor(() => expect(spy).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText(/workspace/i)).toBeInTheDocument()
    );
  });

  it("rejects a password shorter than the stated minimum without calling signup", async () => {
    const signup = vi.spyOn(authApi, "signup");
    renderSignup();

    const user = userEvent.setup();
    await act(async () => {
      await user.type(screen.getByLabelText(/email/i), "a@b.c");
      await user.type(screen.getByLabelText(/password/i), "too-short");
      await user.type(screen.getByLabelText(/invite code/i), "code");
      await user.click(screen.getByRole("button", { name: /create account/i }));
    });

    expect(screen.getByText(/password must be at least 12 characters/i)).toBeInTheDocument();
    expect(signup).not.toHaveBeenCalled();
  });

  it("explains conflicting and unexpected signup failures", async () => {
    vi.spyOn(authApi, "signup").mockRejectedValueOnce(new ApiError("Conflict", 409, null)).mockRejectedValueOnce(new Error("offline"));
    renderSignup();
    const user = userEvent.setup();

    await act(async () => {
      await user.type(screen.getByLabelText(/email/i), "a@b.c");
      await user.type(screen.getByLabelText(/password/i), "very-long-password");
      await user.type(screen.getByLabelText(/invite code/i), "existing");
      await user.click(screen.getByRole("button", { name: /create account/i }));
    });
    await waitFor(() => expect(screen.getByText(/account with that email already exists/i)).toBeInTheDocument());

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /create account/i }));
    });
    await waitFor(() => expect(screen.getByText(/signup failed. please try again/i)).toBeInTheDocument());
  });
});
