import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

const state = vi.hoisted(() => ({
  hydrate: vi.fn(),
  clearSession: vi.fn(),
  unauthorizedHandler: undefined as (() => void) | null | undefined,
  causalityProvider: undefined as (() => { epoch: number; generation: number }) | null | undefined
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: (selector: (store: typeof state) => unknown) => selector(state),
  getAuthCausality: () => ({ epoch: 0, generation: 0 })
}));
vi.mock("../api/client", () => ({
  setUnauthorizedHandler: (handler: (() => void) | null) => {
    state.unauthorizedHandler = handler;
  },
  setAuthCausalityProvider: (provider: (() => { epoch: number; generation: number }) | null) => {
    state.causalityProvider = provider;
  }
}));
vi.mock("../app/AppRoutes", () => ({ AppRoutes: () => <div>App routes</div> }));

describe("App", () => {
  beforeEach(() => {
    state.hydrate.mockReset();
    state.clearSession.mockReset();
    state.unauthorizedHandler = undefined;
    state.causalityProvider = undefined;
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
    expect(state.causalityProvider).toBeTypeOf("function");

    unmount();
    expect(state.unauthorizedHandler).toBeNull();
    expect(state.causalityProvider).toBeNull();
  });

  it("delegates route selection to AppRoutes", () => {
    window.history.pushState({}, "", "/unknown");

    render(<App />);

    expect(screen.getByText("App routes")).toBeInTheDocument();
  });
});
