import { getApiBaseUrl } from "../../api/client";
import { countCrtOwnerDrafts } from "../../features/crt/crtDraftCoordinator";
import { plural } from "../../features/review/plural";
import { countUnsavedReviewDrafts } from "../../features/review/reviewFormDrafts";

/**
 * The unsaved work in this browser that signing out removes, as far as the code
 * can count it without asking the server (spec 020, FR-052).
 *
 * - `reviewDrafts`: weekly-review form text kept in `localStorage`, removed by
 *   `clearReviewLocalState` when the account departs.
 * - `crtDrafts`: Thinking Mode drafts not yet saved online, removed by
 *   `cleanupCrtOwnerScope` in `logout()`.
 *
 * A count that cannot be read (storage refused, listing failed) is 0: the
 * dialog then names nothing rather than a number it does not know, and
 * `logout()` still asks before dropping Thinking Mode drafts it finds.
 */
export interface SignOutSummary {
  reviewDrafts: number;
  crtDrafts: number;
}

export async function loadSignOutSummary(accountId: string): Promise<SignOutSummary> {
  let reviewDrafts = 0;
  try {
    reviewDrafts = countUnsavedReviewDrafts({ apiOrigin: getApiBaseUrl(), accountId });
  } catch {
    // Storage can refuse access (private mode); there is then no draft to name.
  }
  let crtDrafts: number | null = null;
  try {
    crtDrafts = await countCrtOwnerDrafts(accountId);
  } catch {
    // Not listable: left unnamed, as above.
  }
  return { reviewDrafts, crtDrafts: crtDrafts ?? 0 };
}

/** The dialog body, in the native apps' order: the base sentence, then one sentence per kind of unsaved work. */
export function signOutSentences(summary: SignOutSummary): string[] {
  const sentences = ["You'll be signed out of Brain Buddy on this browser. Your tasks stay in your account."];
  if (summary.reviewDrafts > 0) {
    sentences.push(`${plural(summary.reviewDrafts, "unsaved weekly-review draft")} will also be removed from this browser.`);
  }
  if (summary.crtDrafts > 0) {
    sentences.push(`${plural(summary.crtDrafts, "unsaved Thinking Mode draft")} will also be removed from this browser.`);
  }
  return sentences;
}
