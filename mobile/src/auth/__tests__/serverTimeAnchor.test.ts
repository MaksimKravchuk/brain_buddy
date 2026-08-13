import { advanceServerTimeAnchor } from "../SessionProvider";

describe("advanceServerTimeAnchor", () => {
  it("does not move authoritative time backward when an older response arrives late", () => {
    const newer = { serverTimeMs: 10_000, monotonicTimeMs: 1_000 };
    const delayedOlder = { serverTimeMs: 8_000, monotonicTimeMs: 1_500 };

    expect(advanceServerTimeAnchor(newer, delayedOlder)).toBe(newer);
  });

  it("advances to a response at or beyond the current projection", () => {
    const current = { serverTimeMs: 10_000, monotonicTimeMs: 1_000 };
    const incoming = { serverTimeMs: 11_000, monotonicTimeMs: 1_500 };

    expect(advanceServerTimeAnchor(current, incoming)).toBe(incoming);
    expect(advanceServerTimeAnchor(null, incoming)).toBe(incoming);
  });
});
