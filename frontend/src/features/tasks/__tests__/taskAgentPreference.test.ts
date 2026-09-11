import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentConnectionResponse } from "../../../api/agentTypes";
import {
  bindTaskAgentPreferenceSession,
  readTaskAgentPreference,
  rememberTaskAgentPreference,
  sweepTaskAgentPreferences,
  taskAgentPreferenceKey
} from "../taskAgentPreference";
import { useAuthStore } from "../../../stores/authStore";

const DAY = 24 * 60 * 60 * 1000;
const scope = { ownerId: "owner-a", apiOrigin: "https://brain.example.test/api" };

function connection(id: string): AgentConnectionResponse {
  return { id, ready_for_handoff: true } as AgentConnectionResponse;
}

describe("017-FR-013 last-used task agent preference", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-11T12:00:00Z"));
    useAuthStore.setState({ user: { id: "owner-a", email: "a@example.test" }, status: "authed" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    vi.useRealTimers();
    useAuthStore.setState({ user: null, status: "loading" });
  });

  it("stores only an opaque connection id and resolves it for the same owner and API origin", () => {
    rememberTaskAgentPreference(scope, "connection-2");

    expect(JSON.parse(window.localStorage.getItem(taskAgentPreferenceKey(scope)) ?? "null")).toEqual({
      connectionId: "connection-2",
      confirmedAt: Date.now()
    });
    expect(readTaskAgentPreference(scope, [connection("connection-1"), connection("connection-2")])?.id).toBe("connection-2");
    expect(
      readTaskAgentPreference(
        { ...scope, ownerId: "owner-b" },
        [connection("connection-1"), connection("connection-2")]
      )?.id
    ).toBe("connection-1");
  });

  it("falls back safely and removes malformed, expired, or no-longer-eligible records", () => {
    const eligible = [connection("connection-1"), connection("connection-2")];
    window.localStorage.setItem(taskAgentPreferenceKey(scope), "not json");
    expect(readTaskAgentPreference(scope, eligible)?.id).toBe("connection-1");
    expect(window.localStorage.getItem(taskAgentPreferenceKey(scope))).toBeNull();

    rememberTaskAgentPreference(scope, "connection-2", Date.now() - 31 * DAY);
    expect(readTaskAgentPreference(scope, eligible)?.id).toBe("connection-1");
    expect(window.localStorage.getItem(taskAgentPreferenceKey(scope))).toBeNull();

    rememberTaskAgentPreference(scope, "connection-gone");
    expect(readTaskAgentPreference(scope, eligible)?.id).toBe("connection-1");
    expect(window.localStorage.getItem(taskAgentPreferenceKey(scope))).toBeNull();
  });

  it("sweeps stale records and clears the departing owner synchronously on logout or account switch", () => {
    rememberTaskAgentPreference(scope, "connection-1");
    rememberTaskAgentPreference({ ownerId: "owner-b", apiOrigin: scope.apiOrigin }, "connection-2", Date.now() - 31 * DAY);
    sweepTaskAgentPreferences();
    expect(window.localStorage.getItem(taskAgentPreferenceKey({ ownerId: "owner-b", apiOrigin: scope.apiOrigin }))).toBeNull();

    const unbind = bindTaskAgentPreferenceSession(scope.apiOrigin);
    useAuthStore.setState({ user: { id: "owner-c", email: "c@example.test" }, status: "authed" });
    expect(window.localStorage.getItem(taskAgentPreferenceKey(scope))).toBeNull();
    unbind();
  });

  it("sweeps expired records on focus and treats unavailable browser storage as optional", () => {
    const unbind = bindTaskAgentPreferenceSession(scope.apiOrigin);
    rememberTaskAgentPreference(scope, "connection-1", Date.now() - 31 * DAY);
    window.dispatchEvent(new Event("focus"));
    expect(window.localStorage.getItem(taskAgentPreferenceKey(scope))).toBeNull();
    unbind();

    const getter = vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    expect(readTaskAgentPreference(scope, [connection("connection-1")])?.id).toBe("connection-1");
    expect(() => rememberTaskAgentPreference(scope, "connection-1")).not.toThrow();
    expect(() => sweepTaskAgentPreferences()).not.toThrow();
    getter.mockRestore();
  });

  it("treats a missing browser and an authenticated session without an owner as storage-free", () => {
    const browserWindow = window;
    vi.stubGlobal("window", undefined);
    expect(() => sweepTaskAgentPreferences()).not.toThrow();
    vi.stubGlobal("window", browserWindow);

    useAuthStore.setState({ user: null, status: "authed" });
    const unbind = bindTaskAgentPreferenceSession(scope.apiOrigin);
    unbind();
  });
});
