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

  it("samples slow render streaks and resets the streak after a fast render", () => {
    const frames: (() => void)[] = [];
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: () => void) => {
      frames.push(callback);
      return frames.length;
    }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("performance", {
      now: vi
        .fn()
        .mockReturnValueOnce(10)
        .mockReturnValueOnce(25)
        .mockReturnValueOnce(30)
        .mockReturnValueOnce(45)
        .mockReturnValueOnce(50)
        .mockReturnValueOnce(65)
        .mockReturnValueOnce(70)
        .mockReturnValueOnce(75)
    });
    const onSample = vi.fn();
    const { rerender } = renderHook(
      ({ nodeCount }) => useGraphProfiler({ nodeCount, edgeCount: 4, onSample }),
      { initialProps: { nodeCount: 20 } }
    );

    act(() => frames[0]?.());
    rerender({ nodeCount: 21 });
    act(() => frames[1]?.());
    rerender({ nodeCount: 22 });
    act(() => frames[2]?.());
    rerender({ nodeCount: 23 });
    act(() => frames[3]?.());

    expect(onSample).toHaveBeenCalledTimes(4);
    expect(onSample.mock.calls[onSample.mock.calls.length - 1]?.[0].durationMs).toBe(5);
  });
});
