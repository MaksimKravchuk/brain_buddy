import { describe, expect, it } from "vitest";

import {
  askDecisionClasses,
  asksForDecision,
  classifyFromInstants,
  daysInNext,
  formatReviewDate,
  formatReviewTime,
  formulationInstants,
  formulationKey,
  isSubstantiveChange,
  isThirdStall,
  listMarkerFor,
  type FormulationClass,
  type FormulationInstants
} from "../formulation";
import vectors from "./review_formulation_vectors.json";

type ClassificationVector = (typeof vectors.classification)[number];

const DAY_MS = 86_400_000;

function instantsOf(vector: ClassificationVector): FormulationInstants | null {
  const { ageing_at, ask_at, park_due_at, paused_until } = vector.expect;
  if (ageing_at === null || ask_at === null || park_due_at === null) {
    return null;
  }
  return { ageing_at, ask_at, park_due_at, paused_until };
}

describe("020-FR-002 formulation key against the shared normalisation vectors", () => {
  it.each(vectors.normalisation.map((vector) => [vector.id, vector] as const))(
    "020-FR-002 %s keys both titles exactly as the server does",
    (_id, vector) => {
      expect(formulationKey(vector.old)).toBe(vector.old_key);
      expect(formulationKey(vector.new)).toBe(vector.new_key);
      expect(isSubstantiveChange(vector.old, vector.new)).toBe(vector.substantive);
    }
  );

  it("020-FR-002 folds every scalar the Python casefold table treats differently from toLowerCase", () => {
    // Each pair is (input, Python 3.11 `formulation_key(input)`), written as
    // escapes so no editor can recompose the expected decomposed sequences.
    const cases: Array<[string, string]> = [
      ["ẞ", "ss"],
      ["ς", "σ"],
      ["ǰ", "ǰ"],
      ["ͅ", "ι"],
      ["ΐ", "ΐ"],
      ["ΰ", "ΰ"],
      ["ᲀ", "в"],
      ["ᲈ", "ꙋ"],
      ["ẖ", "ẖ"],
      ["ὐ", "ὐ"],
      ["ᾳ", "αι"],
      ["ᾼ", "αι"],
      ["ᾷ", "ᾶι"],
      ["ῤ", "ῤ"],
      ["ῼ", "ωι"],
      ["ᾀ", "ἀι"],
      ["ᾏ", "ἇι"],
      ["ᾘ", "ἠι"],
      ["ᾯ", "ὧι"],
      ["Ꭰ", "Ꭰ"],
      ["ꭰ", "Ꭰ"],
      ["ᏸ", "Ᏸ"],
      ["ᏽ", "Ᏽ"],
      ["Ꮿ", "Ꮿ"],
      ["İ", "i̇"],
      ["Σ", "σ"],
      ["ΑΣ", "ασ"]
    ];
    for (const [input, folded] of cases) {
      expect(formulationKey(input)).toBe(folded);
    }
  });

  it("020-FR-002 collapses Python whitespace, including the separators split() treats as spaces", () => {
    expect(formulationKey("\u001cCall\u001d\u001e\u001fBob\u0085")).toBe("call bob");
    expect(formulationKey("\tCall\u000b\u000cBob\r\n")).toBe("call bob");
    expect(formulationKey("Call Bob Ann Eve  　Kim")).toBe("call bob ann eve kim");
    expect(formulationKey("Call​Bob")).toBe("call​bob");
    expect(formulationKey("")).toBe("");
    expect(formulationKey(" ... ")).toBe("");
  });
});

describe("020-FR-004 classification from the server's derived instants", () => {
  it.each(vectors.classification.map((vector) => [vector.id, vector] as const))(
    "020-FR-004 %s classifies like the server",
    (_id, vector) => {
      const instants = instantsOf(vector);
      const formulationClass = classifyFromInstants(new Date(vector.now), instants);
      expect(formulationClass).toBe(vector.expect.class);
      expect(asksForDecision(formulationClass)).toBe(vector.expect.asks_for_decision);
      expect(isThirdStall(formulationClass, vector.task.consecutive_stalled_formulations)).toBe(
        vector.expect.third_stall
      );
    }
  );

  it("020-FR-004 counts asks, moves tomorrow and a not-yet-applied park as asking, and nothing else", () => {
    const all: FormulationClass[] = ["none", "fresh", "ageing", "asks", "moves_tomorrow", "park_due", "paused"];
    expect(all.filter(asksForDecision)).toEqual(["asks", "moves_tomorrow", "park_due"]);
    expect([...askDecisionClasses]).toEqual(["asks", "moves_tomorrow", "park_due"]);
  });

  it("020-FR-004 shows only the two list markers and never Ageing in a list", () => {
    expect(listMarkerFor("asks")).toBe("asks");
    expect(listMarkerFor("moves_tomorrow")).toBe("moves_tomorrow");
    expect(listMarkerFor("park_due")).toBe("moves_tomorrow");
    for (const quiet of ["none", "fresh", "ageing", "paused"] as const) {
      expect(listMarkerFor(quiet)).toBeNull();
    }
  });

  it("020-FR-051 reads a task's instants, and none while the owner is not activated or the task is outside Next", () => {
    const formulation = {
      id: "form_a",
      started_at: "2026-09-24T09:14:00Z",
      extended_at: null,
      extension_reason: null,
      park_floor_at: null,
      consecutive_stalled: 0,
      ageing_at: "2026-10-01T09:14:00Z",
      ask_at: "2026-10-08T09:14:00Z",
      park_due_at: "2026-10-15T09:14:00Z",
      paused_until: null
    };
    expect(formulationInstants(formulation)).toEqual({
      ageing_at: "2026-10-01T09:14:00Z",
      ask_at: "2026-10-08T09:14:00Z",
      park_due_at: "2026-10-15T09:14:00Z",
      paused_until: null
    });
    expect(formulationInstants({ ...formulation, ageing_at: null })).toBeNull();
    expect(formulationInstants({ ...formulation, ask_at: null })).toBeNull();
    expect(formulationInstants({ ...formulation, park_due_at: null })).toBeNull();
    expect(formulationInstants(null)).toBeNull();
    expect(formulationInstants(undefined)).toBeNull();
  });

  it("020-FR-046 pauses until the due date, and only while now is before it", () => {
    const instants: FormulationInstants = {
      ageing_at: "2026-10-01T09:14:00Z",
      ask_at: "2026-10-08T09:14:00Z",
      park_due_at: "2026-10-15T09:14:00Z",
      paused_until: "2026-10-12T22:00:00Z"
    };
    expect(classifyFromInstants(new Date("2026-10-12T21:59:59Z"), instants)).toBe("paused");
    expect(classifyFromInstants(new Date("2026-10-12T22:00:00Z"), instants)).toBe("asks");
  });

  it("020-FR-004 needs two stalled wordings before the third-stall offer, and only while asking", () => {
    expect(isThirdStall("asks", 1)).toBe(false);
    expect(isThirdStall("asks", 2)).toBe(true);
    expect(isThirdStall("park_due", 5)).toBe(true);
    expect(isThirdStall("ageing", 5)).toBe(false);
  });
});

describe("020-FR-004 display helpers for the wording facts", () => {
  it("020-FR-004 counts whole days in Next and never goes below zero", () => {
    const start = "2026-09-24T09:14:00Z";
    expect(daysInNext(start, new Date(Date.parse(start) + 15 * DAY_MS))).toBe(15);
    expect(daysInNext(start, new Date(Date.parse(start) + 15 * DAY_MS - 1))).toBe(14);
    expect(daysInNext(start, new Date(Date.parse(start) - DAY_MS))).toBe(0);
  });

  it("020-FR-004 formats dates as the design does, in the given zone", () => {
    expect(formatReviewDate("2026-10-16T12:00:00Z", "UTC")).toBe("Fri 16 Oct");
    expect(formatReviewDate("2026-10-16T23:30:00Z", "Europe/Berlin")).toBe("Sat 17 Oct");
    expect(formatReviewDate("2026-09-30T15:40:00Z", "UTC")).toBe("Wed 30 Sep");
    expect(formatReviewDate("2027-01-03T12:00:00Z", "America/New_York")).toBe("Sun 3 Jan");
    expect(formatReviewTime("2026-10-10T09:14:00Z", "UTC")).toBe("09:14");
    expect(formatReviewTime("2026-10-10T09:14:00Z", "Europe/Berlin")).toBe("11:14");
  });
});
