import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import { authApi, hasFeatureFlag } from "../auth";

describe("hasFeatureFlag", () => {
  it("is false for a null user (no session)", () => {
    expect(hasFeatureFlag(null, "voice_brain_dump")).toBe(false);
  });

  it("is false when the user carries no feature_flags map", () => {
    expect(hasFeatureFlag({ id: "u1", email: "a@b.c" }, "voice_brain_dump")).toBe(false);
  });

  it("reflects the flag value when present", () => {
    expect(hasFeatureFlag({ id: "u1", email: "a@b.c", feature_flags: { voice_brain_dump: true } }, "voice_brain_dump")).toBe(true);
    expect(hasFeatureFlag({ id: "u1", email: "a@b.c", feature_flags: { voice_brain_dump: false } }, "voice_brain_dump")).toBe(false);
  });
});

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

  it("falls back to a default message when the failed response has no status text", async () => {
    fetchMock.mockResolvedValue(
      new Response("{}", { status: 500, statusText: "", headers: { "Content-Type": "application/json" } })
    );
    await expect(authApi.login({ email: "a@b.c", password: "pass" })).rejects.toMatchObject({ message: "Request failed" });
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
