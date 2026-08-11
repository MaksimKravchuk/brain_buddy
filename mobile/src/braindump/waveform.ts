/**
 * Pure level maths for the brain-dump waveform.
 *
 * Kept out of the component so the mapping from raw mic metering to bar height
 * is testable (and mutable, per the mobile mutation scope) without rendering
 * React Native or driving a timer.
 */

/** Bar height for silence, as a fraction of the bar track. */
export const IDLE_LEVEL = 0.08;

/** How often the rolling buffer advances by one bar, in milliseconds. */
export const WAVEFORM_TICK_MS = 150;

/** Amplitude used when the recorder reports no metering at all. */
export const UNMETERED_LEVEL = 0.1;

/** Quietest metering value that still moves a bar, in dBFS. */
export const SILENCE_FLOOR_DB = -50;

/**
 * Map a metering reading in dBFS (roughly -160..0) onto a 0..1 amplitude.
 *
 * Anything at or below the silence floor flattens to zero, anything at or above
 * 0 dBFS saturates at one, and a missing reading falls back to a low constant
 * so an unmetered recorder still shows the bars moving.
 */
export function amplitudeFromMetering(db: number | undefined): number {
  if (typeof db !== "number" || Number.isNaN(db)) {
    return UNMETERED_LEVEL;
  }
  const scaled = (db - SILENCE_FLOOR_DB) / -SILENCE_FLOOR_DB;
  return Math.min(1, Math.max(0, scaled));
}

/** A flat buffer of `bars` silent levels. */
export function idleLevels(bars: number): number[] {
  return Array<number>(Math.max(0, bars)).fill(IDLE_LEVEL);
}

/**
 * Shift the buffer left by one and append `amplitude`, never below the idle
 * level so a silent bar is still visible.
 */
export function advanceLevels(levels: readonly number[], amplitude: number): number[] {
  return [...levels.slice(1), Math.max(IDLE_LEVEL, amplitude)];
}
