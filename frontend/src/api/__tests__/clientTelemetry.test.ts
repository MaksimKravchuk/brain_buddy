import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../client";
import { nowMs, recordTelemetry } from "../../utils/telemetry";

// Every request records one telemetry event. It is the only trace a support
// conversation has of a failed call — the correlation id, the path, and how
// long the user waited — so the payload is a contract, not a debug aid.
vi.mock("../../utils/telemetry", () => ({
  nowMs: vi.fn(),
  recordTelemetry: vi.fn()
}));

const clock = vi.mocked(nowMs);
const record = vi.mocked(recordTelemetry);

function response(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Request failed" : "OK",
    headers: { "Content-Type": "application/json", ...headers }
  });
}

describe("apiClient telemetry", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    record.mockClear();
    // A start and a stop 120ms apart. An event that adds them instead of
    // subtracting would report 2120, which is why the two differ by more than
    // their difference.
    clock.mockReset();
    clock.mockReturnValueOnce(1000).mockReturnValueOnce(1120);
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("records a successful request with its method, path, status and duration", async () => {
    fetchMock.mockResolvedValue(response({ items: [] }));

    await apiClient.listTags();

    expect(record).toHaveBeenCalledTimes(1);
    expect(record).toHaveBeenCalledWith({
      name: "api.request",
      durationMs: 120,
      ok: true,
      details: { method: "GET", path: "/tags", status: 200 }
    });
    // No level argument means the default: a successful call is not a warning.
    expect(record.mock.calls[0][1]).toBeUndefined();
  });

  it("records an empty 204 response as a successful request in its own right", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await apiClient.deleteTag("tag-1", 2, "key-1");

    expect(record).toHaveBeenCalledWith({
      name: "api.request",
      durationMs: 120,
      ok: true,
      details: { method: "DELETE", path: "/tags/tag-1?expected_revision=2", status: 204 }
    });
  });

  it("warns with the correlation id when the server rejects the request", async () => {
    fetchMock.mockResolvedValue(response({ detail: "nope" }, 409, { "X-Correlation-ID": "corr-9" }));

    await expect(apiClient.listTags()).rejects.toThrow();

    expect(record).toHaveBeenCalledWith(
      {
        name: "api.request",
        durationMs: 120,
        ok: false,
        details: { method: "GET", path: "/tags", status: 409, correlationId: "corr-9" }
      },
      "warn"
    );
  });

  it("warns with the failure text when the request never reached the server", async () => {
    fetchMock.mockRejectedValue(new Error("Network down"));

    await expect(apiClient.getTask("task-1")).rejects.toThrow("Network down");

    expect(record).toHaveBeenCalledWith(
      {
        name: "api.request",
        durationMs: 120,
        ok: false,
        details: { method: "GET", path: "/tasks/task-1", error: "Network down" }
      },
      "warn"
    );
  });

  it("stringifies a non-Error transport failure rather than logging nothing", async () => {
    fetchMock.mockRejectedValue("socket hang up");

    await expect(apiClient.getTask("task-1")).rejects.toBe("socket hang up");

    expect(record.mock.calls[0][0].details).toEqual({
      method: "GET",
      path: "/tasks/task-1",
      error: "socket hang up"
    });
  });
});
