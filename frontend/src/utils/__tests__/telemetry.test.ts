import { describe, expect, it, vi } from "vitest";

import { nowMs, recordTelemetry } from "../telemetry";

describe("telemetry edge cases", () => {
  it("omits durationMs from the payload when it is not a number", () => {
    const infoSpy = vi.spyOn(console, "info").mockImplementation(() => undefined);
    recordTelemetry({ name: "event-without-duration" });
    expect(infoSpy).toHaveBeenCalledWith("[telemetry]", { name: "event-without-duration" });
    infoSpy.mockRestore();
  });

  it("rounds durationMs to one decimal place when provided", () => {
    const infoSpy = vi.spyOn(console, "info").mockImplementation(() => undefined);
    recordTelemetry({ name: "timed", durationMs: 12.345 });
    expect(infoSpy).toHaveBeenCalledWith("[telemetry]", { name: "timed", durationMs: 12.3 });
    infoSpy.mockRestore();
  });

  it("logs warnings at warn level", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    recordTelemetry({ name: "problem" }, "warn");
    expect(warnSpy).toHaveBeenCalledOnce();
    warnSpy.mockRestore();
  });

  it("falls back to Date.now when performance is unavailable", () => {
    vi.stubGlobal("performance", undefined);
    const dateSpy = vi.spyOn(Date, "now").mockReturnValue(42);
    expect(nowMs()).toBe(42);
    expect(dateSpy).toHaveBeenCalled();
    vi.unstubAllGlobals();
    expect(typeof nowMs()).toBe("number");
  });

  it("prefers the high-resolution clock when the host provides one", () => {
    const now = vi.fn(() => 1234.5);
    vi.stubGlobal("performance", { now });

    // A wall-clock fallback would return a millisecond timestamp, not this.
    expect(nowMs()).toBe(1234.5);
    expect(now).toHaveBeenCalledTimes(1);

    vi.unstubAllGlobals();
  });

  it("falls back when performance exists but carries no now(), rather than throwing", () => {
    vi.stubGlobal("performance", {});
    const dateSpy = vi.spyOn(Date, "now").mockReturnValue(7);

    expect(nowMs()).toBe(7);

    vi.unstubAllGlobals();
    dateSpy.mockRestore();
  });
});
