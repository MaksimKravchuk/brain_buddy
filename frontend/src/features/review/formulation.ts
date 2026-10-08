/**
 * The web half of the shared formulation rule (contracts/formulation-clock.md).
 *
 * The web never derives the clock itself: the server sends the derived instants
 * (`ageing_at`, `ask_at`, `park_due_at`, `paused_until`, http §2) and this module
 * classifies them against the browser clock (§5). It also keys titles (§1) so
 * the reformulate form can say "only capitals or punctuation changed" before a
 * save. Both run against the shared vector file; nothing here reads the DOM.
 */

import type { TaskFormulationResponse, TaskResponse } from "../../api/taskTypes";

export type FormulationClass = "none" | "fresh" | "ageing" | "asks" | "moves_tomorrow" | "park_due" | "paused";

/** The server's advisory projection of one formulation (http §2). */
export interface FormulationInstants {
  ageing_at: string;
  ask_at: string;
  park_due_at: string;
  paused_until: string | null;
}

export type ListMarker = "asks" | "moves_tomorrow";

// Tables live inside the functions that read them, not at module level, so
// each table entry is checked by the tests that exercise it (research R20:
// module-level code would make every entry a static mutant).
const DAY_MS = 86_400_000;

// ------------------------------------------------------------------ §1 key

/**
 * Python `str.isspace()` for NFKC text: what `str.split()` collapses. Every
 * other Python whitespace scalar (U+00A0, U+2000…U+200A, U+202F, U+205F,
 * U+3000) is already U+0020 after NFKC, so it never reaches this check.
 */
function isPythonSpace(code: number): boolean {
  return (
    (code >= 0x09 && code <= 0x0d) ||
    (code >= 0x1c && code <= 0x20) ||
    code === 0x85 ||
    code === 0x1680 ||
    code === 0x2028 ||
    code === 0x2029
  );
}

/**
 * Python `str.casefold()` of one NFKC-stable scalar outside the ranges handled
 * in `caseFoldScalar`. The cases are the scalars whose full case folding is not
 * their full lowercase mapping (Unicode 14, the server's Python 3.11), ported
 * from `NameNormalizer.swift` (research R3).
 */
function foldSingleScalar(code: number): string {
  switch (code) {
    case 0x00df:
    case 0x1e9e: return "ss";
    case 0x01f0: return "ǰ";
    case 0x0345: return "ι";
    case 0x0390: return "ΐ";
    case 0x03b0: return "ΰ";
    case 0x03c2: return "σ";
    case 0x1c80: return "в";
    case 0x1c81: return "д";
    case 0x1c82: return "о";
    case 0x1c83: return "с";
    case 0x1c84:
    case 0x1c85: return "т";
    case 0x1c86: return "ъ";
    case 0x1c87: return "ѣ";
    case 0x1c88: return "ꙋ";
    case 0x1e96: return "ẖ";
    case 0x1e97: return "ẗ";
    case 0x1e98: return "ẘ";
    case 0x1e99: return "ẙ";
    case 0x1f50: return "ὐ";
    case 0x1f52: return "ὒ";
    case 0x1f54: return "ὔ";
    case 0x1f56: return "ὖ";
    case 0x1fb2: return "ὰι";
    case 0x1fb3:
    case 0x1fbc: return "αι";
    case 0x1fb4: return "άι";
    case 0x1fb6: return "ᾶ";
    case 0x1fb7: return "ᾶι";
    case 0x1fc2: return "ὴι";
    case 0x1fc3:
    case 0x1fcc: return "ηι";
    case 0x1fc4: return "ήι";
    case 0x1fc6: return "ῆ";
    case 0x1fc7: return "ῆι";
    case 0x1fd2: return "ῒ";
    case 0x1fd6: return "ῖ";
    case 0x1fd7: return "ῗ";
    case 0x1fe2: return "ῢ";
    case 0x1fe4: return "ῤ";
    case 0x1fe6: return "ῦ";
    case 0x1fe7: return "ῧ";
    case 0x1ff2: return "ὼι";
    case 0x1ff3:
    case 0x1ffc: return "ωι";
    case 0x1ff4: return "ώι";
    case 0x1ff6: return "ῶ";
    case 0x1ff7: return "ῶι";
    default:
      // A lone scalar has no casing context, so its lowercase is the full
      // mapping (final sigma never applies), exactly the per-scalar rule
      // Python uses.
      return String.fromCodePoint(code).toLowerCase();
  }
}

/** Python `str.casefold()` of one scalar of NFKC text. */
function caseFoldScalar(code: number): string {
  if (code >= 0x13a0 && code <= 0x13f5) {
    // Cherokee capitals fold to themselves (their lowercase is U+AB70…).
    return String.fromCodePoint(code);
  }
  if (code >= 0x13f8 && code <= 0x13fd) {
    return String.fromCodePoint(code - 8);
  }
  if (code >= 0xab70 && code <= 0xabbf) {
    return String.fromCodePoint(code - 0xab70 + 0x13a0);
  }
  if (code >= 0x1f80 && code <= 0x1faf) {
    // Greek with ypogegrammeni / prosgegrammeni: base letter + iota, where the
    // three rows of 16 start at U+1F00, U+1F20 and U+1F60.
    const rowBase = [0x1f00, 0x1f20, 0x1f60][Math.floor((code - 0x1f80) / 16)];
    return String.fromCodePoint(rowBase + (code & 0x7), 0x3b9);
  }
  return foldSingleScalar(code);
}

/** formulation-clock §1: NFKC, punctuation to a space, Python whitespace, casefold. */
export function formulationKey(title: string): string {
  let result = "";
  let pendingSpace = false;
  for (const char of title.normalize("NFKC")) {
    const code = char.codePointAt(0) as number;
    if (/\p{P}/u.test(char) || isPythonSpace(code)) {
      pendingSpace = result.length > 0;
      continue;
    }
    if (pendingSpace) {
      result += " ";
      pendingSpace = false;
    }
    result += caseFoldScalar(code);
  }
  return result;
}

/** A title change starts a new formulation iff the keys differ (FR-002). */
export function isSubstantiveChange(oldTitle: string, newTitle: string): boolean {
  return formulationKey(oldTitle) !== formulationKey(newTitle);
}

/**
 * Whether a task read again after a stale answer still has the wording (and
 * list) that text typed for it was written against. A revision that only moved
 * (notes, tags, a cosmetic title change) keeps it, and so keeps typed text
 * (FR-052); a new formulation, another list or a title with another key does not.
 */
export function sameWording(before: TaskResponse, after: TaskResponse): boolean {
  if (before.state !== after.state) {
    return false;
  }
  if (before.formulation && after.formulation) {
    return before.formulation.id === after.formulation.id;
  }
  return !isSubstantiveChange(before.title, after.title);
}

// ------------------------------------------------------------ §5 classify

/** A task's instants (http §2), or `null` when it has no running, activated clock. */
export function formulationInstants(formulation: TaskFormulationResponse | null | undefined): FormulationInstants | null {
  if (!formulation?.ageing_at || !formulation.ask_at || !formulation.park_due_at) {
    return null;
  }
  return {
    ageing_at: formulation.ageing_at,
    ask_at: formulation.ask_at,
    park_due_at: formulation.park_due_at,
    paused_until: formulation.paused_until
  };
}

/**
 * formulation-clock §5 from the server's instants. `null` instants mean the
 * task has no running clock for an activated owner, which is class `none`.
 */
export function classifyFromInstants(now: Date, instants: FormulationInstants | null): FormulationClass {
  if (!instants) {
    return "none";
  }
  const at = now.getTime();
  if (instants.paused_until !== null && at < Date.parse(instants.paused_until)) {
    return "paused";
  }
  const parkDueAt = Date.parse(instants.park_due_at);
  if (at >= parkDueAt) {
    return "park_due";
  }
  if (at >= parkDueAt - DAY_MS) {
    return "moves_tomorrow";
  }
  if (at >= Date.parse(instants.ask_at)) {
    return "asks";
  }
  if (at >= Date.parse(instants.ageing_at)) {
    return "ageing";
  }
  return "fresh";
}

/** formulation-clock §5: the "asks for a decision" aggregate. */
export function asksForDecision(formulationClass: FormulationClass): boolean {
  return formulationClass === "asks" || formulationClass === "moves_tomorrow" || formulationClass === "park_due";
}

/** FR-005: the third consecutive formulation that reached the threshold. */
export function isThirdStall(formulationClass: FormulationClass, consecutiveStalled: number): boolean {
  return asksForDecision(formulationClass) && consecutiveStalled >= 2;
}

/** The list marker (owner decision 2: never "Ageing" in a list). */
export function listMarkerFor(formulationClass: FormulationClass): ListMarker | null {
  if (formulationClass === "asks") {
    return "asks";
  }
  if (formulationClass === "moves_tomorrow" || formulationClass === "park_due") {
    return "moves_tomorrow";
  }
  return null;
}

// ---------------------------------------------------------------- display

/** Whole days since the formulation started ("15 days in Next"). */
export function daysInNext(startedAt: string, now: Date): number {
  return Math.max(0, Math.floor((now.getTime() - Date.parse(startedAt)) / DAY_MS));
}

/**
 * "Fri 16 Oct", the date form every review screen uses. Built from numeric
 * parts so no locale data can change it ("Sept" in newer en-GB data).
 */
export function formatReviewDate(iso: string, timeZone?: string): string {
  const { year, month, day } = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", { year: "numeric", month: "numeric", day: "numeric", timeZone })
      .formatToParts(new Date(iso))
      .map((entry) => [entry.type, Number(entry.value)])
  ) as Record<"year" | "month" | "day", number>;
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  const weekdays = "Sun Mon Tue Wed Thu Fri Sat".split(" ");
  const months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
  return `${weekdays[weekday]} ${day} ${months[month - 1]}`;
}

/** "09:14", the 24-hour time the review screens use. */
export function formatReviewTime(iso: string, timeZone?: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone });
}
