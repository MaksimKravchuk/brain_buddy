import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useDelayedUnmount } from "../useDelayedUnmount";

describe("useDelayedUnmount", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("uses its default delay before hiding a closed element", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDelayedUnmount(false));

    expect(result.current).toEqual({ shouldRender: false, isAnimatingOut: false });
    act(() => vi.advanceTimersByTime(200));
    expect(result.current.shouldRender).toBe(false);
  });
});
