import { describe, expect, it } from "vitest";

import {
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
  sameWording,
  type FormulationClass,
  type FormulationInstants
} from "../formulation";
import vectors from "./review_formulation_vectors.json";
import { askingTask, taskFixture } from "./reviewKit";

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

  it("020-FR-002 matches Python 3.11 casefold on every single scalar where it differs from toLowerCase", () => {
    // Generated from Python 3.11 (Unicode 14): every NFKC-stable scalar whose
    // `casefold()` is not this engine's per-scalar `toLowerCase()`, outside the
    // Cherokee and ypogegrammeni ranges checked below. "hex:hex hex" = in:out.
    const table =
      "df:73 73,1f0:6a 30c,345:3b9,390:3b9 308 301,3b0:3c5 308 301,3c2:3c3,1c80:432,1c81:434,1c82:43e," +
      "1c83:441,1c84:442,1c85:442,1c86:44a,1c87:463,1c88:a64b,1e96:68 331,1e97:74 308,1e98:77 30a," +
      "1e99:79 30a,1e9e:73 73,1f50:3c5 313,1f52:3c5 313 300,1f54:3c5 313 301,1f56:3c5 313 342," +
      "1fb2:1f70 3b9,1fb3:3b1 3b9,1fb4:3ac 3b9,1fb6:3b1 342,1fb7:3b1 342 3b9,1fbc:3b1 3b9,1fc2:1f74 3b9," +
      "1fc3:3b7 3b9,1fc4:3ae 3b9,1fc6:3b7 342,1fc7:3b7 342 3b9,1fcc:3b7 3b9,1fd2:3b9 308 300,1fd6:3b9 342," +
      "1fd7:3b9 308 342,1fe2:3c5 308 300,1fe4:3c1 313,1fe6:3c5 342,1fe7:3c5 308 342,1ff2:1f7c 3b9," +
      "1ff3:3c9 3b9,1ff4:3ce 3b9,1ff6:3c9 342,1ff7:3c9 342 3b9,1ffc:3c9 3b9";
    const scalars = (hex: string) => String.fromCodePoint(...hex.split(" ").map((part) => parseInt(part, 16)));
    const entries = table.split(",").map((entry) => entry.split(":"));
    expect(entries).toHaveLength(49);
    for (const [input, folded] of entries) {
      expect(formulationKey(scalars(input)), `U+${input}`).toBe(scalars(folded));
    }
  });

  it("020-FR-002 folds the Cherokee and ypogegrammeni ranges to their exact edges", () => {
    const key = (code: number) => formulationKey(String.fromCodePoint(code));
    const codes = (text: string) => Array.from(text, (char) => char.codePointAt(0));
    // Cherokee capitals U+13A0…U+13F5 fold to themselves, U+13F8…U+13FD to
    // U+13F0…U+13F5, and the small letters U+AB70…U+ABBF up to U+13A0….
    for (let code = 0x13a0; code <= 0x13f5; code += 1) {
      expect(codes(key(code)), `U+${code.toString(16)}`).toEqual([code]);
    }
    for (let code = 0x13f8; code <= 0x13fd; code += 1) {
      expect(codes(key(code)), `U+${code.toString(16)}`).toEqual([code - 8]);
    }
    for (let code = 0xab70; code <= 0xabbf; code += 1) {
      expect(codes(key(code)), `U+${code.toString(16)}`).toEqual([code - 0xab70 + 0x13a0]);
    }
    // Ypogegrammeni rows: U+1F80/U+1F88 → U+1F00, U+1F90/U+1F98 → U+1F20,
    // U+1FA0/U+1FA8 → U+1F60, each followed by iota.
    const rows: Array<[number, number]> = [
      [0x1f80, 0x1f00],
      [0x1f90, 0x1f20],
      [0x1fa0, 0x1f60]
    ];
    for (const [rowStart, base] of rows) {
      for (let offset = 0; offset < 16; offset += 1) {
        expect(codes(key(rowStart + offset)), `U+${(rowStart + offset).toString(16)}`).toEqual([
          base + (offset % 8),
          0x3b9
        ]);
      }
    }
    // Just outside every range the ordinary lowercase applies.
    expect(codes(key(0x139f))).toEqual([0x139f]);
    expect(codes(key(0x13fe))).toEqual([0x13fe]);
    expect(codes(key(0xab6f))).toEqual([0xab6f]);
    expect(codes(key(0xabc0))).toEqual([0xabc0]);
    expect(codes(key(0x1f7c))).toEqual([0x1f7c]);
    expect(codes(key(0x1fb0))).toEqual([0x1fb0]);
    expect(codes(key(0x1f6f))).toEqual([0x1f67]);
    expect(codes(key(0x1fb8))).toEqual([0x1fb0]);
  });

  it("020-FR-002 treats exactly Python's NFKC-stable whitespace as a separator", () => {
    // Python 3.11: every scalar where NFKC(c) == c and c.isspace().
    const spaces = [0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0x1680, 0x2028, 0x2029];
    for (const code of spaces) {
      expect(formulationKey(`a${String.fromCodePoint(code)}b`), `U+${code.toString(16)}`).toBe("a b");
    }
    for (const code of [0x08, 0x0e, 0x1b, 0x24, 0x84, 0x86, 0x167f, 0x1681, 0x200b, 0x202a]) {
      expect(formulationKey(`a${String.fromCodePoint(code)}b`), `U+${code.toString(16)}`).not.toBe("a b");
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
    const weekdays = [4, 5, 6, 7, 8, 9, 10].map((day) => formatReviewDate(`2027-01-${String(day).padStart(2, "0")}T12:00:00Z`, "UTC"));
    expect(weekdays).toEqual(["Mon 4 Jan", "Tue 5 Jan", "Wed 6 Jan", "Thu 7 Jan", "Fri 8 Jan", "Sat 9 Jan", "Sun 10 Jan"]);
    const months = Array.from({ length: 12 }, (_, index) =>
      formatReviewDate(`2027-${String(index + 1).padStart(2, "0")}-01T12:00:00Z`, "UTC").split(" ")[2]
    );
    expect(months).toEqual(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]);
    expect(formatReviewTime("2026-10-10T09:14:00Z", "UTC")).toBe("09:14");
    expect(formatReviewTime("2026-10-10T09:14:00Z", "Europe/Berlin")).toBe("11:14");
  });
});

describe("020-FR-052 whether a task kept the wording typed text was written for", () => {
  const next = askingTask("task_w", "Renovate the bathroom");

  it("020-FR-052 a revision that only moved keeps the wording, by formulation id in Next and by title key elsewhere", () => {
    expect(sameWording(next, { ...next, details: "notes", revision: 9 })).toBe(true);
    expect(sameWording(next, { ...next, title: "Renovate the Bathroom!" })).toBe(true);
    const waiting = taskFixture({ id: "task_x", title: "Pick up the drill", state: "waiting" });
    expect(sameWording(waiting, { ...waiting, details: "notes", revision: 9 })).toBe(true);
    expect(sameWording(waiting, { ...waiting, title: "Pick up the DRILL" })).toBe(true);
  });

  it("020-FR-052 another formulation, another list or another title key is not the same wording", () => {
    expect(sameWording(next, { ...next, formulation: { ...(next.formulation as NonNullable<typeof next.formulation>), id: "form_other" } })).toBe(false);
    expect(sameWording(next, { ...next, state: "someday", formulation: null })).toBe(false);
    const waiting = taskFixture({ id: "task_x", title: "Pick up the drill", state: "waiting" });
    expect(sameWording(waiting, { ...waiting, title: "Collect the saw" })).toBe(false);
    expect(sameWording(next, { ...next, formulation: null, title: "Something else entirely" })).toBe(false);
  });
});
