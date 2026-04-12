import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { useAuthStore } from "../../../stores/authStore";
import { ProtectedRoute } from "../ProtectedRoute";

function renderWithRoute(initialEntry = "/secret") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<div>login page</div>} />
        <Route
          path="/secret"
          element={
            <ProtectedRoute>
              <div>secret content</div>
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "loading" });
  });

  it("shows a loading state while auth is hydrating", () => {
    renderWithRoute();
    expect(screen.getByText(/loading session/i)).toBeInTheDocument();
  });

  it("redirects anonymous users to /login", () => {
    useAuthStore.setState({ user: null, status: "anon" });
    renderWithRoute();
    expect(screen.getByText(/login page/i)).toBeInTheDocument();
  });

  it("renders children when authed", () => {
    useAuthStore.setState({
      user: { id: "u1", email: "a@b.c" },
      status: "authed"
    });
    renderWithRoute();
    expect(screen.getByText(/secret content/i)).toBeInTheDocument();
  });
});
