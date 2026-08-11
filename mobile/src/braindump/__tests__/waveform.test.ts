import {
  advanceLevels,
  amplitudeFromMetering,
  idleLevels,
  IDLE_LEVEL,
  SILENCE_FLOOR_DB,
  UNMETERED_LEVEL,
  WAVEFORM_TICK_MS,
} from "../waveform";

describe("amplitudeFromMetering", () => {
  it("maps 0 dBFS to full amplitude and the silence floor to zero", () => {
    expect(amplitudeFromMetering(0)).toBe(1);
    expect(amplitudeFromMetering(SILENCE_FLOOR_DB)).toBe(0);
  });

  it("scales linearly between the silence floor and 0 dBFS", () => {
    expect(amplitudeFromMetering(-25)).toBeCloseTo(0.5, 10);
    expect(amplitudeFromMetering(-10)).toBeCloseTo(0.8, 10);
    expect(amplitudeFromMetering(-40)).toBeCloseTo(0.2, 10);
  });

  it("clamps readings outside the range instead of extrapolating", () => {
    expect(amplitudeFromMetering(-160)).toBe(0);
    expect(amplitudeFromMetering(-50.1)).toBe(0);
    expect(amplitudeFromMetering(12)).toBe(1);
  });

  it("falls back to a visible constant when the recorder reports no metering", () => {
    expect(amplitudeFromMetering(undefined)).toBe(UNMETERED_LEVEL);
    expect(amplitudeFromMetering(Number.NaN)).toBe(UNMETERED_LEVEL);
    expect(UNMETERED_LEVEL).toBeGreaterThan(0);
  });
});

describe("idleLevels", () => {
  it("fills the requested number of bars with the idle level", () => {
    expect(idleLevels(3)).toEqual([IDLE_LEVEL, IDLE_LEVEL, IDLE_LEVEL]);
    expect(idleLevels(24)).toHaveLength(24);
  });

  it("returns an empty buffer rather than throwing on a non-positive count", () => {
    expect(idleLevels(0)).toEqual([]);
    expect(idleLevels(-4)).toEqual([]);
  });

  it("returns a fresh array each call so callers cannot alias the baseline", () => {
    const first = idleLevels(2);
    first[0] = 0.9;
    expect(idleLevels(2)).toEqual([IDLE_LEVEL, IDLE_LEVEL]);
  });
});

describe("advanceLevels", () => {
  it("shifts one bar off the front and appends the new amplitude", () => {
    expect(advanceLevels([0.1, 0.2, 0.3], 0.4)).toEqual([0.2, 0.3, 0.4]);
  });

  it("keeps the buffer length stable across many ticks", () => {
    let levels = idleLevels(24);
    for (let tick = 0; tick < 100; tick += 1) {
      levels = advanceLevels(levels, 0.5);
    }
    expect(levels).toHaveLength(24);
    expect(levels.every((level) => level === 0.5)).toBe(true);
  });

  it("never appends below the idle level, so silence still draws a bar", () => {
    expect(advanceLevels([0.5, 0.5], 0)).toEqual([0.5, IDLE_LEVEL]);
    expect(advanceLevels([0.5, 0.5], IDLE_LEVEL / 2)).toEqual([0.5, IDLE_LEVEL]);
  });

  it("does not mutate the buffer it was given", () => {
    const previous = [0.1, 0.2];
    advanceLevels(previous, 0.9);
    expect(previous).toEqual([0.1, 0.2]);
  });
});

describe("WAVEFORM_TICK_MS", () => {
  it("advances several times a second so the bars read as live", () => {
    expect(WAVEFORM_TICK_MS).toBeGreaterThan(0);
    expect(WAVEFORM_TICK_MS).toBeLessThanOrEqual(250);
  });
});
