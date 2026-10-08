import type { SessionCounts } from "../../../api/review";

/** The ten counts of FR-033 in their fixed order (owner decision PD-1). */
export const SUMMARY_COUNTS: ReadonlyArray<{ key: keyof SessionCounts; label: string }> = [
  { key: "done", label: "Done" },
  { key: "reformulated", label: "Reformulated" },
  { key: "first_step", label: "First step" },
  { key: "waiting", label: "Waiting for" },
  { key: "someday", label: "Someday / maybe" },
  { key: "cancelled", label: "Cancelled" },
  { key: "extended", label: "Kept 7 more days" },
  { key: "inbox_processed", label: "Inbox processed" },
  { key: "kept", label: "Kept as is" },
  { key: "moved_to_next", label: "Moved to Next" }
];
