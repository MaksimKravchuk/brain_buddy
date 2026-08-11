/**
 * 006-SC-004 — a person can tell how current the screen is from the
 * last-synchronised footer alone, without per-change bookkeeping.
 *
 * `now` is an argument (plan.md's clock rule for this feature): the module
 * never reads the clock, so the whole table below is exact rather than flaky.
 */

import { describeLastSynced, formatLastSynced, type LastSyncedBucket } from "../syncStatus";

const NOW = Date.parse("2026-08-11T12:00:00.000Z");
const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** An ISO timestamp `ago` milliseconds before NOW. */
const ago = (milliseconds: number): string => new Date(NOW - milliseconds).toISOString();

describe("006-SC-004 formatLastSynced over now - lastSyncedAt", () => {
  it.each<[string, number, string]>([
    ["at the very moment of the sync", 0, "Last synced just now"],
    ["a few seconds", 3 * SECOND, "Last synced just now"],
    ["one second before the first minute", 59 * SECOND, "Last synced just now"],
    ["exactly one minute", MINUTE, "Last synced 1 minute ago"],
    ["one minute and a bit, which floors", 90 * SECOND, "Last synced 1 minute ago"],
    ["the design's own example", 14 * MINUTE, "Last synced 14 minutes ago"],
    ["one second before the first hour", HOUR - SECOND, "Last synced 59 minutes ago"],
    ["exactly one hour", HOUR, "Last synced 1 hour ago"],
    ["an hour and a half, which floors", 90 * MINUTE, "Last synced 1 hour ago"],
    ["one minute before a day", DAY - MINUTE, "Last synced 23 hours ago"],
    ["exactly one day", DAY, "Last synced 1 day ago"],
    ["not quite two days, which floors", 2 * DAY - MINUTE, "Last synced 1 day ago"],
    ["two days", 2 * DAY, "Last synced 2 days ago"],
    ["the retention bound itself", 30 * DAY, "Last synced 30 days ago"],
  ])("%s reads as words: %s", (_why, elapsed, expected) => {
    expect(formatLastSynced(ago(elapsed), NOW)).toBe(expected);
  });

  it.each<[string, string | null | undefined]>([
    ["null, never synced on this device", null],
    ["undefined, nothing persisted yet", undefined],
    ["an empty string", ""],
    ["a value that does not parse", "not-a-timestamp"],
  ])("006-SC-004 %s says so rather than inventing an age", (_why, value) => {
    expect(formatLastSynced(value, NOW)).toBe("Not synced yet");
  });

  it("006-SC-004 a timestamp ahead of now reads as just now, not as the future", () => {
    // A device clock that jumped forward must not make the footer say
    // "in 3 hours"; the same clamp the queue applies at write time (invariant 8).
    expect(formatLastSynced(new Date(NOW + 3 * HOUR).toISOString(), NOW)).toBe(
      "Last synced just now",
    );
  });

  it("006-SC-004 accepts epoch milliseconds and Date as well as an ISO string", () => {
    expect(formatLastSynced(NOW - 14 * MINUTE, NOW)).toBe("Last synced 14 minutes ago");
    expect(formatLastSynced(new Date(NOW - 14 * MINUTE), new Date(NOW))).toBe(
      "Last synced 14 minutes ago",
    );
  });

  it("006-SC-004 says it in words, never by colour or a dot (design.md: no state by colour alone)", () => {
    const labels = [
      formatLastSynced(null, NOW),
      formatLastSynced(ago(3 * SECOND), NOW),
      formatLastSynced(ago(14 * MINUTE), NOW),
      formatLastSynced(ago(3 * HOUR), NOW),
      formatLastSynced(ago(9 * DAY), NOW),
    ];
    for (const label of labels) {
      expect(label).toMatch(/[a-z]/i);
      expect(label).not.toMatch(/[•●▲◆]|#[0-9a-f]{3,8}\b|\brgb\(|\bgreen\b|\bred\b|\bamber\b/i);
    }
  });
});

describe("006-SC-004 describeLastSynced buckets, so the footer announces only material change", () => {
  it.each<[string, number, LastSyncedBucket]>([
    ["seconds", 5 * SECOND, "just-now"],
    ["minutes", 14 * MINUTE, "minutes"],
    ["hours", 3 * HOUR, "hours"],
    ["days", 9 * DAY, "days"],
  ])("%s falls in the %s bucket", (_why, elapsed, bucket) => {
    expect(describeLastSynced(ago(elapsed), NOW).bucket).toBe(bucket);
  });

  it("never-synced is its own bucket", () => {
    expect(describeLastSynced(null, NOW)).toEqual({ bucket: "never", label: "Not synced yet" });
  });

  it("a tick inside the same minute does not change the announcement", () => {
    const first = describeLastSynced(ago(14 * MINUTE), NOW);
    const second = describeLastSynced(ago(14 * MINUTE + 20 * SECOND), NOW);
    expect(second).toEqual(first);
  });

  it("the label is the string formatLastSynced returns", () => {
    expect(describeLastSynced(ago(3 * HOUR), NOW).label).toBe(formatLastSynced(ago(3 * HOUR), NOW));
  });
});
