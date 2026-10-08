import { describe, expect, it } from "vitest";

import { recommendedDecision, STALL_REASONS, type StallReason } from "../stallRecommendation";
import flowVectors from "./review_flow_vectors.json";

describe("020-FR-007 stall reason recommendation against the shared vectors", () => {
  it.each(flowVectors.stall_recommendation.map((vector) => [vector.id, vector] as const))(
    "020-FR-007 %s recommends the decision iOS and the server recommend",
    (_id, vector) => {
      expect(recommendedDecision(vector.stall_reason as StallReason | null)).toBe(vector.expect);
    }
  );

  it("020-FR-007 offers the six reasons in the design's order with their wire codes", () => {
    expect(STALL_REASONS.map((reason) => [reason.code, reason.label])).toEqual([
      ["unclear", "Unclear"],
      ["too_big", "Too big"],
      ["missing_info", "Missing information"],
      ["waiting_on_someone", "Waiting on someone"],
      ["no_energy", "Unpleasant / no energy"],
      ["no_longer_matters", "No longer matters"]
    ]);
  });

  it("020-FR-007 recommends nothing for a value outside the fixed list", () => {
    expect(recommendedDecision("lazy" as StallReason)).toBeNull();
  });
});
