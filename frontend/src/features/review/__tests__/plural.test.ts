import { describe, expect, it } from "vitest";

import { pick, plural } from "../plural";

describe("020-FR-033 counts with their words", () => {
  it("020-FR-033 picks the singular for one and the plural for everything else, zero included", () => {
    expect(pick(1, "it", "they")).toBe("it");
    expect(pick(0, "it", "they")).toBe("they");
    expect(pick(2, "it", "they")).toBe("they");
  });

  it("020-FR-033 puts the count before its noun, regular or given", () => {
    expect(plural(1, "item")).toBe("1 item");
    expect(plural(12, "item")).toBe("12 items");
    expect(plural(1, "task was", "tasks were")).toBe("1 task was");
    expect(plural(3, "task was", "tasks were")).toBe("3 tasks were");
  });
});
