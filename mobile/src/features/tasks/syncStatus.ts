/**
 * SC-004 / FR-007 — the last-synchronised footer.
 *
 * FR-007 removed every per-change marker, so this one line is the whole of
 * what tells a person how current the screen is. It is therefore words, never
 * a coloured dot: design.md's accessibility rule is that no state in this
 * feature is communicated by colour alone.
 *
 * `now` is an argument. `mobile/` has no fake-timer precedent and plan.md makes
 * the clock rule explicit for this feature: nothing here reads the clock, so
 * every boundary below is exact rather than flaky.
 */

export type Instant = string | number | Date;

export type LastSyncedBucket = "never" | "just-now" | "minutes" | "hours" | "days";

export interface LastSyncedDescription {
  /** The unit the label is expressed in. The footer is an accessibility live
   *  region that should announce only when this or the count changes, not on
   *  every tick — comparing the whole description is enough for that. */
  bucket: LastSyncedBucket;
  label: string;
}

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const NEVER_LABEL = "Not synced yet";

/** Epoch milliseconds, or `null` when the value carries no usable time. */
export function toEpochMs(value: Instant | null | undefined): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (value instanceof Date) {
    const time = value.getTime();
    return Number.isNaN(time) ? null : time;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function ago(count: number, unit: string): string {
  return `Last synced ${count} ${unit}${count === 1 ? "" : "s"} ago`;
}

/** The footer's text and the bucket it falls in. */
export function describeLastSynced(
  lastSyncedAt: Instant | null | undefined,
  now: Instant,
): LastSyncedDescription {
  const synced = toEpochMs(lastSyncedAt);
  const current = toEpochMs(now);
  if (synced === null || current === null) {
    // Never synced on this device, or a stored value that no longer parses.
    // Saying so is honest; inventing an age is not.
    return { bucket: "never", label: NEVER_LABEL };
  }

  // A device clock that jumped forward must not produce "synced in 3 hours".
  // Same clamp the queue applies to its own timestamps (data-model invariant 8).
  const elapsed = Math.max(0, current - synced);

  if (elapsed < MINUTE) {
    return { bucket: "just-now", label: "Last synced just now" };
  }
  if (elapsed < HOUR) {
    return { bucket: "minutes", label: ago(Math.floor(elapsed / MINUTE), "minute") };
  }
  if (elapsed < DAY) {
    return { bucket: "hours", label: ago(Math.floor(elapsed / HOUR), "hour") };
  }
  return { bucket: "days", label: ago(Math.floor(elapsed / DAY), "day") };
}

/** The footer's text on its own. */
export function formatLastSynced(lastSyncedAt: Instant | null | undefined, now: Instant): string {
  return describeLastSynced(lastSyncedAt, now).label;
}
