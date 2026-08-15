import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

const state = vi.hoisted(() => ({
  hydrate: vi.fn(),
  clearSession: vi.fn(),
  unauthorizedHandler: undefined as (() => void) | null | undefined
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: (selector: (store: typeof state) => unknown) => selector(state)
}));
vi.mock("../api/client", () => ({
  setUnauthorizedHandler: (handler: (() => void) | null) => {
    state.unauthorizedHandler = handler;
  }
}));
vi.mock("../app/AppRoutes", () => ({ AppRoutes: () => <div>App routes</div> }));

describe("App", () => {
  beforeEach(() => {
    state.hydrate.mockReset();
    state.clearSession.mockReset();
    state.unauthorizedHandler = undefined;
    window.history.pushState({}, "", "/login");
  });

  afterEach(() => vi.clearAllMocks());

  it("hydrates auth state and installs an unauthorized session handler", () => {
    const { unmount } = render(<App />);

    expect(screen.getByText("App routes")).toBeInTheDocument();
    expect(state.hydrate).toHaveBeenCalledOnce();
    expect(state.unauthorizedHandler).toBeTypeOf("function");

    state.unauthorizedHandler?.();
    expect(state.clearSession).toHaveBeenCalledOnce();

    unmount();
    expect(state.unauthorizedHandler).toBeNull();
  });

  it("delegates route selection to AppRoutes", () => {
    window.history.pushState({}, "", "/unknown");

    render(<App />);

    expect(screen.getByText("App routes")).toBeInTheDocument();
  });
  it("010-FR-009: opens no WebSocket and no EventSource anywhere in the app", () => {
    // The live-propagation requirement is deliberately bounded to a polled GET
    // of an endpoint that already exists: no new transport on either client.
    const socket = vi.fn();
    const events = vi.fn();
    vi.stubGlobal("WebSocket", socket);
    vi.stubGlobal("EventSource", events);

    try {
      render(<App />);
      expect(socket).not.toHaveBeenCalled();
      expect(events).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
