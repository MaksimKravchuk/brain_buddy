import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useGraphProfiler } from "../useGraphProfiler";

describe("useGraphProfiler", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("does not schedule performance samples for small graphs", () => {
    const requestAnimationFrame = vi.fn();
    vi.stubGlobal("requestAnimationFrame", requestAnimationFrame);
    vi.stubGlobal("cancelAnimationFrame", vi.fn());

    renderHook(() => useGraphProfiler({ nodeCount: 12, edgeCount: 11 }));

    expect(requestAnimationFrame).not.toHaveBeenCalled();
  });

  it("reports a completed large-graph render to the supplied sampler", () => {
    let frame: (() => void) | undefined;
    const requestAnimationFrame = vi.fn((callback: () => void) => {
      frame = callback;
      return 7;
    });
    vi.stubGlobal("requestAnimationFrame", requestAnimationFrame);
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.spyOn(performance, "now").mockReturnValueOnce(100).mockReturnValueOnce(116);
    const onSample = vi.fn();

    renderHook(() => useGraphProfiler({ nodeCount: 20, edgeCount: 4, onSample }));

    act(() => frame?.());

    expect(onSample).toHaveBeenCalledWith(
      expect.objectContaining({ nodeCount: 20, edgeCount: 4, durationMs: expect.any(Number) })
    );
  });

  it("cancels a scheduled sample when the profiler unmounts", () => {
    const cancelAnimationFrame = vi.fn();
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 11));
    vi.stubGlobal("cancelAnimationFrame", cancelAnimationFrame);

    const { unmount } = renderHook(() => useGraphProfiler({ nodeCount: 20, edgeCount: 4 }));
    unmount();

    expect(cancelAnimationFrame).toHaveBeenCalledWith(11);
  });
});
