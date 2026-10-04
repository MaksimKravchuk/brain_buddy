import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi } from "../../../api/auth";
import { ApiError, notifyUnauthorized, setUnauthorizedHandler } from "../../../api/client";
import { ProtectedRoute } from "../../../components/auth/ProtectedRoute";
import { crtApi } from "../../../api/crt";
import { useAuthStore } from "../../../stores/authStore";
import { CrtGate } from "../CrtGate";

function renderGate(): void {
  render(
    <MemoryRouter initialEntries={["/crt"]}>
      <CrtGate />
    </MemoryRouter>
  );
}

function renderProtectedGate(): void {
  render(
    <MemoryRouter initialEntries={["/crt"]}>
      <Routes>
        <Route path="/login" element={<div>login page</div>} />
        <Route
          path="/crt"
          element={
            <ProtectedRoute>
              <CrtGate />
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

async function flushProbe(): Promise<void> {
  await act(async () => {
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  window.innerWidth = 1024;
  useAuthStore.setState({
    user: {
      id: "user-1",
      email: "internal-user@example.test",
      feature_flags: { crt_canvas: true }
    },
    status: "authed"
  });
});

afterEach(() => {
  cleanup();
  setUnauthorizedHandler(null);
  vi.restoreAllMocks();
  useAuthStore.setState({ user: null, status: "loading" });
});

describe("CrtGate exposure boundary", () => {
  it("019-FR-002 shows the unsupported-width boundary without probing or loading tree content", async () => {
    window.innerWidth = 390;
    const probe = vi.spyOn(crtApi, "probeCrtExposure").mockResolvedValue(undefined);
    const listTrees = vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);

    renderGate();

    const heading = await screen.findByRole("heading", { name: "Thinking Mode needs a wider window" });
    expect(heading).toBeInTheDocument();
    expect(document.activeElement).toBe(heading);
    expect(screen.getByText(/Use a window at least 1024 px wide to edit this tree\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to Tasks" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Current Reality Tree" })).not.toBeInTheDocument();
    expect(probe).not.toHaveBeenCalled();
    expect(listTrees).not.toHaveBeenCalled();
  });

  it("019-FR-002 hides an already-mounted editor at unsupported widths without discarding its session", async () => {
    const probe = vi.spyOn(crtApi, "probeCrtExposure").mockResolvedValue(undefined);
    const listTrees = vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);

    renderGate();
    const workspaceHeading = await screen.findByRole("heading", { name: "Start with your first undesired effect" });
    expect(probe).toHaveBeenCalledTimes(1);
    expect(listTrees).toHaveBeenCalledTimes(1);

    await act(async () => {
      window.innerWidth = 800;
      window.dispatchEvent(new Event("resize"));
    });

    expect(await screen.findByRole("heading", { name: "Thinking Mode needs a wider window" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Start with your first undesired effect", hidden: true })).toBe(workspaceHeading);
    expect(probe).toHaveBeenCalledTimes(1);
    expect(listTrees).toHaveBeenCalledTimes(1);

    await act(async () => {
      window.innerWidth = 1024;
      window.dispatchEvent(new Event("resize"));
    });

    expect(await screen.findByRole("heading", { name: "Start with your first undesired effect" })).toBe(workspaceHeading);
    expect(probe).toHaveBeenCalledTimes(1);
    expect(listTrees).toHaveBeenCalledTimes(1);
  });

  it("019-FR-002 keeps the editor exposed while resizing within the supported range", async () => {
    const probe = vi.spyOn(crtApi, "probeCrtExposure").mockResolvedValue(undefined);
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);

    renderGate();
    expect(await screen.findByRole("heading", { name: "Start with your first undesired effect" })).toBeInTheDocument();

    await act(async () => {
      window.innerWidth = 1200;
      window.dispatchEvent(new Event("resize"));
    });

    expect(await screen.findByRole("heading", { name: "Start with your first undesired effect" })).toBeInTheDocument();
    expect(probe).toHaveBeenCalledTimes(1);
  });

  it("019-FR-002 keeps the mounted workspace across an equivalent periodic session refresh", async () => {
    const probe = vi.spyOn(crtApi, "probeCrtExposure").mockResolvedValue(undefined);
    const listTrees = vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    vi.spyOn(authApi, "me").mockResolvedValue({
      id: "user-1",
      email: "internal-user@example.test",
      feature_flags: { crt_canvas: true }
    });

    renderGate();
    const workspaceHeading = await screen.findByRole("heading", { name: "Start with your first undesired effect" });

    await act(async () => {
      await useAuthStore.getState().refreshSession();
    });

    expect(screen.getByRole("heading", { name: "Start with your first undesired effect" })).toBe(workspaceHeading);
    expect(probe).toHaveBeenCalledTimes(1);
    expect(listTrees).toHaveBeenCalledTimes(1);
  });

  it("019-FR-001 clears an expired session so ProtectedRoute redirects to login", async () => {
    setUnauthorizedHandler(() => useAuthStore.getState().clearSession());
    vi.spyOn(crtApi, "probeCrtExposure").mockImplementation(() => {
      notifyUnauthorized();
      return Promise.reject(new ApiError("Unauthorized", 401, { detail: "expired" }, "expired-reference"));
    });

    renderProtectedGate();
    await flushProbe();

    expect(await screen.findByText("login page")).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe("anon");
    expect(screen.queryByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).not.toBeInTheDocument();
  });

  it("019-FR-001 clears an expired session exactly once through the shared handler", async () => {
    const originalClearSession = useAuthStore.getState().clearSession;
    const clearSession = vi.fn(() => {
      // Keep the gate mounted until the rejected probe callback runs so this
      // catches a second clear from the gate itself, not only the shared path.
      setTimeout(() => originalClearSession(), 0);
      return true;
    });
    useAuthStore.setState({ clearSession });
    setUnauthorizedHandler(() => useAuthStore.getState().clearSession());
    vi.spyOn(crtApi, "probeCrtExposure").mockImplementation(() => {
      notifyUnauthorized();
      return Promise.reject(new ApiError("Unauthorized", 401, { detail: "expired" }, "expired-reference"));
    });

    renderProtectedGate();
    await flushProbe();

    expect(await screen.findByText("login page")).toBeInTheDocument();
    expect(clearSession).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().status).toBe("anon");
  });

  it("019-FR-001 renders the normal disabled boundary from the content-free probe", async () => {
    vi.spyOn(crtApi, "probeCrtExposure").mockRejectedValue(
      new ApiError("Not Found", 404, { detail: { reason: "crt_canvas_disabled" } }, "disabled-reference")
    );

    renderGate();
    await flushProbe();

    const heading = await screen.findByRole("heading", { name: "Thinking Mode isn't available for this account" });
    expect(heading).toBeInTheDocument();
    expect(document.activeElement).toBe(heading);
    expect(screen.getByText(/existing BrainBuddy work is unchanged/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to Tasks" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Current Reality Tree" })).not.toBeInTheDocument();
    expect(screen.queryByText(/support reference/i)).not.toBeInTheDocument();
  });

  it("019-FR-001 keeps degraded flag access distinct and exposes the probe reference", async () => {
    vi.spyOn(crtApi, "probeCrtExposure").mockRejectedValue(
      new ApiError("Service Unavailable", 503, { detail: { reason: "feature_flag_unavailable" } }, "degraded-reference")
    );

    renderGate();
    await flushProbe();

    const heading = await screen.findByRole("heading", { name: "Thinking Mode is temporarily unavailable" });
    expect(heading).toBeInTheDocument();
    expect(document.activeElement).toBe(heading);
    expect(screen.getByText("We couldn't check access safely.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Support reference" })).toHaveValue("degraded-reference");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Back to Tasks" })).toHaveLength(1);
    expect(screen.queryByRole("heading", { name: /isn't available for this account/i })).not.toBeInTheDocument();
  });

  it("019-FR-001 re-probes when periodic auth refresh revokes CRT exposure", async () => {
    const probe = vi
      .spyOn(crtApi, "probeCrtExposure")
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new ApiError("Not Found", 404, { detail: { reason: "crt_canvas_disabled" } }, "revoked-reference"));

    const listTrees = vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    renderGate();
    await flushProbe();
    expect(await screen.findByRole("heading", { name: "Start with your first undesired effect" })).toBeInTheDocument();
    expect(listTrees).toHaveBeenCalledTimes(1);

    await act(async () => {
      useAuthStore.setState({
        user: {
          id: "user-1",
          email: "internal-user@example.test",
          feature_flags: { crt_canvas: false }
        },
        status: "authed"
      });
    });

    expect(await screen.findByRole("heading", { name: "Thinking Mode isn't available for this account" })).toBeInTheDocument();
    expect(probe).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("heading", { name: "Current Reality Tree" })).not.toBeInTheDocument();
  });

  it("019-FR-001 re-probes and unmounts a hidden workspace when access changes below 1024px", async () => {
    const probe = vi
      .spyOn(crtApi, "probeCrtExposure")
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new ApiError("Not Found", 404, { detail: { reason: "crt_canvas_disabled" } }, "revoked-narrow-reference"));
    vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);

    renderGate();
    await screen.findByRole("heading", { name: "Start with your first undesired effect" });
    await act(async () => {
      window.innerWidth = 800;
      window.dispatchEvent(new Event("resize"));
    });
    expect(screen.getByRole("heading", { name: "Start with your first undesired effect", hidden: true })).toBeInTheDocument();

    await act(async () => {
      useAuthStore.setState({
        user: {
          id: "user-1",
          email: "internal-user@example.test",
          feature_flags: { crt_canvas: false }
        },
        status: "authed"
      });
    });
    await flushProbe();

    expect(probe).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("heading", { name: "Start with your first undesired effect", hidden: true })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Thinking Mode needs a wider window" })).toBeInTheDocument();
  });

  it("supports direct disabled reasons and degraded errors without a correlation id", async () => {
    vi.spyOn(crtApi, "probeCrtExposure").mockRejectedValueOnce(
      new ApiError("Not Found", 404, { reason: "crt_canvas_disabled" })
    );
    renderGate();
    await flushProbe();
    expect(await screen.findByRole("heading", { name: "Thinking Mode isn't available for this account" })).toBeInTheDocument();
    cleanup();
    vi.restoreAllMocks();
    vi.spyOn(crtApi, "probeCrtExposure").mockRejectedValue(
      new ApiError("Unavailable", 503, { detail: "unavailable" })
    );
    renderGate();
    await flushProbe();
    expect(await screen.findByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Support reference" })).not.toBeInTheDocument();
  });

  it("returns to tasks from unsupported and disabled boundaries", async () => {
    window.innerWidth = 800;
    vi.spyOn(crtApi, "probeCrtExposure").mockResolvedValue(undefined);
    renderGate();
    await screen.findByRole("button", { name: "Back to Tasks" });
    await act(async () => { screen.getByRole("button", { name: "Back to Tasks" }).click(); });
    cleanup();
    window.innerWidth = 1024;
    vi.restoreAllMocks();
    vi.spyOn(crtApi, "probeCrtExposure").mockRejectedValue(
      new ApiError("Not Found", 404, { reason: "crt_canvas_disabled" })
    );
    renderGate();
    await flushProbe();
    await act(async () => { screen.getByRole("button", { name: "Back to Tasks" }).click(); });
  });

  it("retries degraded exposure without requesting tree content", async () => {
    const probe = vi
      .spyOn(crtApi, "probeCrtExposure")
      .mockRejectedValueOnce(new ApiError("Service Unavailable", 503, { detail: { reason: "feature_flag_unavailable" } }, "first-reference"))
      .mockResolvedValueOnce(undefined);
    const listTrees = vi.spyOn(crtApi, "listCrtTrees").mockResolvedValue([]);
    renderGate();
    await flushProbe();
    expect(await screen.findByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeInTheDocument();
    await act(async () => { screen.getByRole("button", { name: "Retry" }).click(); });
    expect(await screen.findByRole("heading", { name: "Start with your first undesired effect" })).toBeInTheDocument();
    expect(probe).toHaveBeenCalledTimes(2);
    expect(listTrees).toHaveBeenCalledTimes(1);
  });

  it("classifies malformed exposure payloads as degraded and retries a failed probe", async () => {
    const probe = vi.spyOn(crtApi, "probeCrtExposure")
      .mockRejectedValueOnce(new ApiError("Unavailable", 503, "not-an-object"))
      .mockRejectedValueOnce(new Error("still unavailable"));
    renderGate();
    await flushProbe();
    expect(await screen.findByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Support reference" })).not.toBeInTheDocument();
    await act(async () => { screen.getByRole("button", { name: "Retry" }).click(); });
    await flushProbe();
    expect(probe).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeInTheDocument();
  });

  it("selects a degraded support reference and ignores stale probe responses after resize", async () => {
    let resolveProbe!: () => void;
    vi.spyOn(crtApi, "probeCrtExposure").mockReturnValue(new Promise<void>((resolve) => { resolveProbe = resolve; }));
    renderGate();
    await act(async () => {
      window.innerWidth = 800;
      window.dispatchEvent(new Event("resize"));
    });
    resolveProbe();
    await flushProbe();
    expect(screen.getByRole("heading", { name: "Thinking Mode needs a wider window" })).toBeInTheDocument();
    cleanup();
    window.innerWidth = 1024;
    vi.restoreAllMocks();
    const probe = vi.spyOn(crtApi, "probeCrtExposure").mockRejectedValue(new ApiError("Unavailable", 503, {}, "select-reference"));
    renderGate();
    await flushProbe();
    const reference = await screen.findByRole("textbox", { name: "Support reference" });
    reference.focus();
    expect(reference).toHaveValue("select-reference");
    expect(probe).toHaveBeenCalledOnce();
  });

  it("classifies non-API failures and keeps degraded navigation available", async () => {
    const probe = vi.spyOn(crtApi, "probeCrtExposure").mockRejectedValue(new Error("network"));
    renderGate();
    await flushProbe();
    expect(await screen.findByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeInTheDocument();
    await act(async () => { screen.getByRole("button", { name: "Back to Tasks" }).click(); });
    expect(probe).toHaveBeenCalledOnce();
  });

  it("distinguishes an object detail without a reason from a disabled response", async () => {
    const probe = vi.spyOn(crtApi, "probeCrtExposure")
      .mockRejectedValueOnce(new ApiError("Unavailable", 503, { detail: {} }, "detail-without-reason"))
      .mockRejectedValueOnce(new ApiError("Unavailable", 503, { detail: { reason: 42 } }, "non-string-reason"));
    renderGate();
    await flushProbe();
    expect(await screen.findByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Support reference" })).toBeInTheDocument();
    await act(async () => { screen.getByRole("button", { name: "Retry" }).click(); });
    await flushProbe();
    expect(probe).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeInTheDocument();
  });

  it("classifies malformed 404 exposure payloads as degraded", async () => {
    const probe = vi.spyOn(crtApi, "probeCrtExposure")
      .mockRejectedValueOnce(new ApiError("Not Found", 404, "raw-payload"))
      .mockRejectedValueOnce(new ApiError("Not Found", 404, { detail: "text-detail" }))
      .mockRejectedValueOnce(new ApiError("Not Found", 404, { detail: { reason: 42 } }));
    renderGate();
    await flushProbe();
    expect(await screen.findByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeInTheDocument();
    await act(async () => { screen.getByRole("button", { name: "Retry" }).click(); });
    await flushProbe();
    await act(async () => { screen.getByRole("button", { name: "Retry" }).click(); });
    await flushProbe();
    expect(probe).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeInTheDocument();
  });

  it("treats a null API payload as a degraded exposure failure", async () => {
    vi.spyOn(crtApi, "probeCrtExposure").mockRejectedValue(
      new ApiError("Unavailable", 503, null, "null-payload")
    );
    renderGate();
    await flushProbe();
    expect(await screen.findByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Support reference" })).toBeInTheDocument();
  });
});
