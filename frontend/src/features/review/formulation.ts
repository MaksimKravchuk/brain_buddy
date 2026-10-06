/**
 * The web half of the shared formulation rule (contracts/formulation-clock.md).
 *
 * The web never derives the clock itself: the server sends the derived instants
 * (`ageing_at`, `ask_at`, `park_due_at`, `paused_until`, http §2) and this module
 * classifies them against the browser clock (§5). It also keys titles (§1) so
 * the reformulate form can say "only capitals or punctuation changed" before a
 * save. Both run against the shared vector file; nothing here reads the DOM.
 */

import type { TaskFormulationResponse } from "../../api/taskTypes";

export type FormulationClass = "none" | "fresh" | "ageing" | "asks" | "moves_tomorrow" | "park_due" | "paused";

/** The server's advisory projection of one formulation (http §2). */
export interface FormulationInstants {
  ageing_at: string;
  ask_at: string;
  park_due_at: string;
  paused_until: string | null;
}

export type ListMarker = "asks" | "moves_tomorrow";

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

/** formulation-clock §5: the "asks for a decision" aggregate. */
export const askDecisionClasses: ReadonlySet<FormulationClass> = new Set<FormulationClass>([
  "asks",
  "moves_tomorrow",
  "park_due"
]);

// ------------------------------------------------------------------ §1 key

/** Python `str.isspace()`: what `str.split()` collapses. */
function isPythonSpace(code: number): boolean {
  return (
    (code >= 0x09 && code <= 0x0d) ||
    (code >= 0x1c && code <= 0x20) ||
    code === 0x85 ||
    code === 0xa0 ||
    code === 0x1680 ||
    (code >= 0x2000 && code <= 0x200a) ||
    code === 0x2028 ||
    code === 0x2029 ||
    code === 0x202f ||
    code === 0x205f ||
    code === 0x3000
  );
}

/**
 * NFKC-stable scalars whose full case folding is not their full lowercase
 * mapping (Unicode 14, the server's Python 3.11), apart from the ranges
 * handled in `caseFoldScalar`. Ported from `NameNormalizer.swift` (research R3).
 */
const FOLDING_EXCEPTIONS: ReadonlyMap<number, readonly number[]> = new Map<number, readonly number[]>([
  [0x00df, [0x73, 0x73]], [0x1e9e, [0x73, 0x73]], [0x01f0, [0x6a, 0x30c]], [0x0345, [0x3b9]],
  [0x0390, [0x3b9, 0x308, 0x301]], [0x03b0, [0x3c5, 0x308, 0x301]], [0x03c2, [0x3c3]],
  [0x1c80, [0x432]], [0x1c81, [0x434]], [0x1c82, [0x43e]], [0x1c83, [0x441]], [0x1c84, [0x442]],
  [0x1c85, [0x442]], [0x1c86, [0x44a]], [0x1c87, [0x463]], [0x1c88, [0xa64b]],
  [0x1e96, [0x68, 0x331]], [0x1e97, [0x74, 0x308]], [0x1e98, [0x77, 0x30a]], [0x1e99, [0x79, 0x30a]],
  [0x1f50, [0x3c5, 0x313]], [0x1f52, [0x3c5, 0x313, 0x300]], [0x1f54, [0x3c5, 0x313, 0x301]],
  [0x1f56, [0x3c5, 0x313, 0x342]],
  [0x1fb2, [0x1f70, 0x3b9]], [0x1fb3, [0x3b1, 0x3b9]], [0x1fb4, [0x3ac, 0x3b9]], [0x1fb6, [0x3b1, 0x342]],
  [0x1fb7, [0x3b1, 0x342, 0x3b9]], [0x1fbc, [0x3b1, 0x3b9]],
  [0x1fc2, [0x1f74, 0x3b9]], [0x1fc3, [0x3b7, 0x3b9]], [0x1fc4, [0x3ae, 0x3b9]], [0x1fc6, [0x3b7, 0x342]],
  [0x1fc7, [0x3b7, 0x342, 0x3b9]], [0x1fcc, [0x3b7, 0x3b9]],
  [0x1fd2, [0x3b9, 0x308, 0x300]], [0x1fd6, [0x3b9, 0x342]], [0x1fd7, [0x3b9, 0x308, 0x342]],
  [0x1fe2, [0x3c5, 0x308, 0x300]], [0x1fe4, [0x3c1, 0x313]], [0x1fe6, [0x3c5, 0x342]],
  [0x1fe7, [0x3c5, 0x308, 0x342]],
  [0x1ff2, [0x1f7c, 0x3b9]], [0x1ff3, [0x3c9, 0x3b9]], [0x1ff4, [0x3ce, 0x3b9]], [0x1ff6, [0x3c9, 0x342]],
  [0x1ff7, [0x3c9, 0x342, 0x3b9]], [0x1ffc, [0x3c9, 0x3b9]]
]);

/** Base letters of the Greek ypogegrammeni blocks U+1F80…U+1FAF, per row of 16. */
const IOTA_SUBSCRIPT_BASES = [0x1f00, 0x1f20, 0x1f60] as const;

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
    // Greek with ypogegrammeni / prosgegrammeni: base letter + iota.
    const base = IOTA_SUBSCRIPT_BASES[Math.floor((code - 0x1f80) / 16)] + (code & 0x7);
    return String.fromCodePoint(base, 0x3b9);
  }
  const folded = FOLDING_EXCEPTIONS.get(code);
  if (folded) {
    return String.fromCodePoint(...folded);
  }
  // A lone scalar has no casing context, so this is its full lowercase mapping
  // (final sigma never applies), exactly the per-scalar rule Python uses.
  return String.fromCodePoint(code).toLowerCase();
}

const PUNCTUATION = /\p{P}/u;

/** formulation-clock §1: NFKC, punctuation to a space, Python whitespace, casefold. */
export function formulationKey(title: string): string {
  let result = "";
  let pendingSpace = false;
  for (const char of title.normalize("NFKC")) {
    const code = char.codePointAt(0) as number;
    if (PUNCTUATION.test(char) || isPythonSpace(code)) {
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

export function asksForDecision(formulationClass: FormulationClass): boolean {
  return askDecisionClasses.has(formulationClass);
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

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

/**
 * "Fri 16 Oct", the date form every review screen uses. Built from numeric
 * parts so no locale data can change it ("Sept" in newer en-GB data).
 */
export function formatReviewDate(iso: string, timeZone?: string): string {
  const parts = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "numeric", day: "numeric", timeZone })
    .formatToParts(new Date(iso));
  const part = (type: "year" | "month" | "day") => Number(parts.find((entry) => entry.type === type)?.value);
  const year = part("year");
  const month = part("month");
  const day = part("day");
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return `${WEEKDAYS[weekday]} ${day} ${MONTHS[month - 1]}`;
}

/** "09:14", the 24-hour time the review screens use. */
export function formatReviewTime(iso: string, timeZone?: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone });
}
