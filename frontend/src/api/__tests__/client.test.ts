import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../client";

describe("apiClient telemetry", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("records latency telemetry for successful requests", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        })
      )
    );

    await expect(apiClient.listTrees()).resolves.toEqual([]);

    expect(info).toHaveBeenCalledWith(
      "[telemetry]",
      expect.objectContaining({
        name: "api.request",
        ok: true,
        durationMs: expect.any(Number),
        details: expect.objectContaining({ method: "GET", path: "/trees", status: 200 })
      })
    );
  });

  it("records failure telemetry with correlation ids", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ message: "stale" }), {
          status: 409,
          statusText: "Conflict",
          headers: { "Content-Type": "application/json", "X-Correlation-ID": "corr-1" }
        })
      )
    );

    await expect(apiClient.getTree("tree-1")).rejects.toBeInstanceOf(ApiError);

    expect(warn).toHaveBeenCalledWith(
      "[telemetry]",
      expect.objectContaining({
        name: "api.request",
        ok: false,
        durationMs: expect.any(Number),
        details: expect.objectContaining({
          method: "GET",
          path: "/trees/tree-1",
          status: 409,
          correlationId: "corr-1"
        })
      })
    );
  });
});
