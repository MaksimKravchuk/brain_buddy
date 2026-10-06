import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
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
  it("022-FR-006/021 blocks a different owner on direct account deletion and retains the fixed destination", () => {
    useAuthStore.setState({ user: { id: "B", email: "b@test.example" }, status: "authed" });
    function LoginProbe() {
      const state = useLocation().state as { from: { pathname: string; search: string } };
      return <div>{state.from.pathname}{state.from.search}</div>;
    }
    render(<MemoryRouter initialEntries={["/settings/account/delete?expected_owner=A&redirect=https://evil.test"]}><Routes><Route path="/settings/account/delete" element={<ProtectedRoute><div>Delete controls</div></ProtectedRoute>} /><Route path="/login" element={<LoginProbe />} /></Routes></MemoryRouter>);
    expect(screen.queryByText("Delete controls")).not.toBeInTheDocument();
    expect(screen.getByText("/settings/account/delete?expected_owner=A")).toBeInTheDocument();
  });
});
