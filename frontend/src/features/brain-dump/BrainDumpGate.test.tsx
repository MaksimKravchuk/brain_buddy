import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { authApi, type AuthUser } from "../../api/auth";
import { useAuthStore } from "../../stores/authStore";
import { BrainDumpGate } from "./BrainDumpGate";

// The gate only needs to prove it renders (or withholds) the route; the real
// route is heavy and independently tested, so stand in a sentinel for it.
vi.mock("./BrainDumpRoute", () => ({
  BrainDumpRoute: () => <div data-testid="brain-dump-route">brain dump route</div>
}));

// Drive the auth store the way production does: through the GET /api/auth/me
// response. Mocking `authApi.me` and hydrating exercises the full
// me-response -> store -> gate path without any backend dependency, so the test
// stands whether or not the backend has shipped the flag yet.
async function hydrateFromMeResponse(user: AuthUser | null) {
  vi.spyOn(authApi, "me").mockResolvedValue(user);
  await act(async () => {
    await useAuthStore.getState().hydrate();
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  act(() => {
    useAuthStore.setState({ user: null, status: "loading" });
  });
});

describe("BrainDumpGate", () => {
  it("renders the brain dump route when /auth/me enables the voice_brain_dump flag", async () => {
    await hydrateFromMeResponse({
      id: "user_1",
      email: "founder@example.test",
      feature_flags: { voice_brain_dump: true }
    });

    render(<BrainDumpGate />);

    expect(screen.getByTestId("brain-dump-route")).toBeInTheDocument();
    expect(screen.queryByText("Voice brain dump is off")).not.toBeInTheDocument();
  });

  it("withholds the route behind a friendly note when the flag is explicitly false", async () => {
    await hydrateFromMeResponse({
      id: "user_1",
      email: "founder@example.test",
      feature_flags: { voice_brain_dump: false }
    });

    render(<BrainDumpGate />);

    expect(screen.queryByTestId("brain-dump-route")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Voice brain dump is off" })).toBeInTheDocument();
  });

  it("fails closed when /auth/me carries no feature_flags map at all", async () => {
    await hydrateFromMeResponse({ id: "user_1", email: "founder@example.test" });

    render(<BrainDumpGate />);

    expect(screen.queryByTestId("brain-dump-route")).not.toBeInTheDocument();
    expect(screen.getByText(/does not have voice brain dump enabled/i)).toBeInTheDocument();
  });
});
