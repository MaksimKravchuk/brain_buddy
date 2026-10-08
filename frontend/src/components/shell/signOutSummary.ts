import { getApiBaseUrl } from "../../api/client";
import { countCrtOwnerDrafts } from "../../features/crt/crtDraftCoordinator";
import { countUnsavedReviewDrafts } from "../../features/review/reviewFormDrafts";

/**
 * Whether this browser holds unsaved local work that signing out removes
 * (spec 020, FR-052): weekly-review form text in `localStorage`
 * (`clearReviewLocalState`) or Thinking Mode drafts not yet saved online
 * (`cleanupCrtOwnerScope` in `logout()`).
 *
 * Work that cannot be read (storage refused, listing failed) is not reported:
 * the dialog then shows only its base sentence, and `logout()` called with
 * `lossConfirmed: false` refuses to drop Thinking Mode drafts it finds anyway.
 */
export interface SignOutSummary {
  unsavedWork: boolean;
}

export const SIGN_OUT_BASE =
  "You'll be signed out of Brain Buddy on this browser. Your tasks stay in your account.";
export const SIGN_OUT_LOSS = "Unsaved changes in this browser will be lost: they have not been saved to your account.";

export async function loadSignOutSummary(accountId: string): Promise<SignOutSummary> {
  let reviewDrafts = 0;
  try {
    reviewDrafts = countUnsavedReviewDrafts({ apiOrigin: getApiBaseUrl(), accountId });
  } catch {
    // Storage can refuse access (private mode); there is then no draft to warn about.
  }
  let crtDrafts: number | null = null;
  try {
    crtDrafts = await countCrtOwnerDrafts(accountId);
  } catch {
    // Not listable: left unreported, as above.
  }
  return { unsavedWork: reviewDrafts > 0 || (crtDrafts ?? 0) > 0 };
}

/** The dialog body: the base sentence, then one general loss sentence only when unsaved work exists. */
export function signOutSentences(summary: SignOutSummary): string[] {
  return summary.unsavedWork ? [SIGN_OUT_BASE, SIGN_OUT_LOSS] : [SIGN_OUT_BASE];
}
