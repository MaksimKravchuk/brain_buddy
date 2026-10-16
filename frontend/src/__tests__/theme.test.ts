import { afterEach, describe, expect, it, vi } from "vitest";

import { applySystemTheme } from "../theme";

type Listener = (event: MediaQueryListEvent) => void;

function stubMatchMedia(matches: boolean) {
  let listener: Listener | undefined;
  const removeEventListener = vi.fn();
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches,
    media: query,
    addEventListener: (_type: string, next: Listener) => {
      listener = next;
    },
    removeEventListener
  }));
  return { emit: (next: boolean) => listener?.({ matches: next } as MediaQueryListEvent), removeEventListener };
}

describe("applySystemTheme", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    delete document.documentElement.dataset.theme;
  });

  it("sets data-theme from the OS preference and follows changes", () => {
    const media = stubMatchMedia(true);
    const stop = applySystemTheme();
    expect(document.documentElement.dataset.theme).toBe("dark");

    media.emit(false);
    expect(document.documentElement.dataset.theme).toBe("light");

    stop();
    expect(media.removeEventListener).toHaveBeenCalledTimes(1);
  });

  it("uses light when the OS prefers light", () => {
    stubMatchMedia(false);
    applySystemTheme();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("does nothing where matchMedia is unavailable", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(applySystemTheme()()).toBeUndefined();
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });
});
