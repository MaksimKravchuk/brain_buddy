import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import { authApi } from "../auth";

describe("authApi profile fallback and error branching", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("returns text payloads as ApiError on non-json failures", async () => {
    fetchMock.mockResolvedValue(
      new Response("Service down", { status: 503, statusText: "Service down", headers: { "Content-Type": "text/plain" } })
    );
    await expect(authApi.me()).rejects.toMatchObject({ status: 503, payload: "Service down" });
  });

  it("passes custom headers through authRequest", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: "u1", email: "a@b.c" }), { status: 200, headers: { "Content-Type": "application/json" } })
    );
    await authApi.login({ email: "a@b.c", password: "pass" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.credentials).toBe("include");
  });
});
