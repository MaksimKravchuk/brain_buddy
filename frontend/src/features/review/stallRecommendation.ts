/**
 * FR-007: an optional stall reason visually recommends a fitting decision
 * without restricting the choice. One constant, checked against the same
 * `stall_recommendation` vectors as the server and iOS (plan US1 "Web").
 */

export type StallReason =
  | "unclear"
  | "too_big"
  | "missing_info"
  | "waiting_on_someone"
  | "no_energy"
  | "no_longer_matters";

export type RecommendedDecision = "reformulate" | "first_step" | "waiting" | "cancel";

/** The six reasons in the order design D-02 shows them, with their wire codes. */
export const STALL_REASONS: ReadonlyArray<{ code: StallReason; label: string }> = [
  { code: "unclear", label: "Unclear" },
  { code: "too_big", label: "Too big" },
  { code: "missing_info", label: "Missing information" },
  { code: "waiting_on_someone", label: "Waiting on someone" },
  { code: "no_energy", label: "Unpleasant / no energy" },
  { code: "no_longer_matters", label: "No longer matters" }
];

const RECOMMENDATIONS: Readonly<Record<StallReason, RecommendedDecision>> = {
  unclear: "reformulate",
  too_big: "first_step",
  missing_info: "first_step",
  waiting_on_someone: "waiting",
  no_energy: "first_step",
  no_longer_matters: "cancel"
};

/** No reason, or a value outside the fixed list, recommends nothing. */
export function recommendedDecision(reason: StallReason | null): RecommendedDecision | null {
  return Object.prototype.hasOwnProperty.call(RECOMMENDATIONS, String(reason))
    ? RECOMMENDATIONS[reason as StallReason]
    : null;
}
