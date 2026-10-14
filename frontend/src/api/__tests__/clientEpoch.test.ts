import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi } from "../auth";
import { apiClient } from "../client";
import { CLIENT_EPOCH } from "../clientEpoch";
import { modernAuthApi } from "../modernAuth";

function ok(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function headerOf(init: RequestInit | undefined, name: string): string | null {
  return new Headers(init?.headers).get(name);
}

describe("027-FR-018 client release epoch headers", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockImplementation(() => Promise.resolve(ok({})));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("027-FR-018 sends the epoch and web surface on the generic client", async () => {
    await apiClient.listTasks().catch(() => undefined);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(headerOf(init, "X-Client-Epoch")).toBe(String(CLIENT_EPOCH));
    expect(headerOf(init, "X-Client")).toMatch(/^brainbuddy-web\/.+/);
  });

  it("027-FR-018 sends the epoch on legacy auth requests", async () => {
    await authApi.login({ email: "a@example.com", password: "secure-password" }).catch(() => undefined);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(headerOf(init, "X-Client-Epoch")).toBe("1");
    expect(headerOf(init, "X-Client")).toMatch(/^brainbuddy-web\//);
    expect(headerOf(init, "Content-Type")).toBe("application/json");
  });

  it("027-FR-018 sends the epoch on modern auth requests", async () => {
    await modernAuthApi.methods().catch(() => undefined);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(headerOf(init, "X-Client-Epoch")).toBe("1");
    expect(headerOf(init, "X-Client")).toMatch(/^brainbuddy-web\//);
    expect(headerOf(init, "Accept")).toBe("application/json");
  });
});
