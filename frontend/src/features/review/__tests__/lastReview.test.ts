import { describe, expect, it } from "vitest";

import { decisionCount, lastReviewText } from "../lastReview";
import { DAY, iso, stateFixture, zeroCounts } from "./reviewKit";

describe("020-FR-038 the neutral recap of the last review", () => {
  it.each([
    [0, "Last review: today"],
    [1, "Last review: 1 day ago"],
    [9, "Last review: 9 days ago"]
  ])("020-FR-038 %s days after a counted review reads %s", (days, text) => {
    expect(lastReviewText(stateFixture({ last_counted_review_at: iso(-days * DAY - 1000) }))).toBe(text);
  });

  it("020-FR-035 020-FR-038 offers setup when there has been none, and nothing while the state is unknown", () => {
    expect(lastReviewText(stateFixture({ last_counted_review_at: null }))).toBe("Set up in a minute");
    expect(lastReviewText(undefined)).toBeNull();
  });

  it("020-FR-033 counts decisions without the Inbox count", () => {
    expect(decisionCount({ ...zeroCounts, done: 2, someday: 4, inbox_processed: 9 })).toBe(6);
  });
});
