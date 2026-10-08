import type { ReviewState, SessionCounts } from "../../api/review";

const DAY_MS = 86_400_000;

/**
 * The neutral recap of the last counted review (FR-038): "Last review: 9 days
 * ago", "Set up in a minute" when there has been none, nothing while the
 * state is not known. Never a score, never a count of missed weeks.
 */
export function lastReviewText(state: ReviewState | undefined, now = new Date()): string | null {
  if (state === undefined) {
    return null;
  }
  if (state.last_counted_review_at === null) {
    return "Set up in a minute";
  }
  const days = Math.max(0, Math.floor((now.getTime() - Date.parse(state.last_counted_review_at)) / DAY_MS));
  return `Last review: ${days === 0 ? "today" : days === 1 ? "1 day ago" : `${days} days ago`}`;
}

/** The decisions a run holds: every count but the Inbox one. */
export function decisionCount(counts: SessionCounts): number {
  return Object.entries(counts).reduce((sum, [name, count]) => (name === "inbox_processed" ? sum : sum + count), 0);
}
