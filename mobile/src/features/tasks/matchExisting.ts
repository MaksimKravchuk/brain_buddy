/**
 * FR-005 — offer an existing project or Tag instead of creating a duplicate.
 *
 * The rule mirrors the server's own uniqueness rule, `normalize_task_name` in
 * `backend/app/modules/tasks/repository.py`: NFKC → trim → (for Tags) drop one
 * leading `@` → collapse internal whitespace → case-fold. Mirroring matters
 * because the two rules meet: a client rule narrower than the server's does not
 * merely miss the offer, it sends the person into a create that answers 409.
 *
 * A substring is deliberately not a match. "Q3" is a reasonable name for a
 * project that does not exist yet, and FR-004 says the person may create it;
 * treating it as "Q3 Launch" would silently classify a task under a project
 * they did not choose.
 */

export interface NamedEntity {
  id: string;
  name: string;
}

export interface MatchOptions {
  /**
   * Tags only. The server strips one leading `@` from a Tag name
   * (`normalize_task_name(..., strip_tag_prefix=True)`), so "@home" and "home"
   * are one Tag to it. Projects keep theirs, so this defaults to off.
   */
  stripTagPrefix?: boolean;
}

/** NFKC, trimmed, internal runs of whitespace collapsed to one space. */
function collapse(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/gu, " ");
}

function normalizeName(value: string, stripTagPrefix: boolean): string {
  let normalized = collapse(value);
  if (stripTagPrefix && normalized.startsWith("@")) {
    normalized = collapse(normalized.slice(1));
  }
  // `toLowerCase`, not `toLocaleLowerCase` (which the web client uses): the
  // server case-folds locale-independently, and on a Turkish-locale device
  // `toLocaleLowerCase` maps "I" to "ı" and the two rules would disagree.
  //
  // Known narrowness: Python's `casefold` also folds "ß" to "ss" and JS has no
  // equivalent, so "Straße" and "STRASSE" match on the server and not here.
  // The cost is a visible 409 on create, never a duplicate or a wrong match.
  return normalized.toLowerCase();
}

/**
 * The candidate whose name the server would consider the same as `typedName`,
 * or `null` when there is none and creating is genuinely the right offer.
 */
export function matchExisting(
  typedName: string,
  candidates: readonly NamedEntity[],
  options: MatchOptions = {},
): NamedEntity | null {
  const stripTagPrefix = options.stripTagPrefix === true;
  const typed = normalizeName(typedName, stripTagPrefix);
  if (typed === "") {
    // Nothing was typed. An empty name is not a match for a blank candidate
    // either — the server rejects both (`min_length=1`).
    return null;
  }
  for (const candidate of candidates) {
    if (normalizeName(candidate.name, stripTagPrefix) === typed) {
      return candidate;
    }
  }
  return null;
}
