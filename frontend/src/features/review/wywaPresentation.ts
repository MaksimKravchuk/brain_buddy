/**
 * When the "While you were away" dialog appears (FR-015, design D-01).
 *
 * At web open it appears only while unseen parks exist, and at most once per
 * local calendar day: Esc and Close leave the parks unseen, and the dialog
 * comes back the next day. As the first screen of a review it always
 * appears. The rule is the shared `while_away` vectors; the last-shown day
 * lives under `bb.reviewWywaLastShown.v1.<origin>.<account>` (data-model E11),
 * holds no content, and is removed on sign-out with the other review keys
 * (`clearReviewLocalState`).
 */

export type WhileAwayContext = "app_open" | "review_start";

export interface WhileAwayScope {
  apiOrigin: string;
  accountId: string;
}

const PREFIX = "bb.reviewWywaLastShown.v1";

export function shouldShowWhileAway({
  context,
  hasUnseen,
  lastShownDay,
  today
}: {
  context: WhileAwayContext;
  hasUnseen: boolean;
  lastShownDay: string | null;
  today: string;
}): boolean {
  if (!hasUnseen) {
    return false;
  }
  return context === "review_start" || lastShownDay !== today;
}

export function whileAwayLastShownKey(scope: WhileAwayScope): string {
  return `${PREFIX}.${encodeURIComponent(scope.apiOrigin)}.${encodeURIComponent(scope.accountId)}`;
}

export function readWhileAwayLastShown(scope: WhileAwayScope, storage: Storage = window.localStorage): string | null {
  try {
    return storage.getItem(whileAwayLastShownKey(scope));
  } catch {
    return null;
  }
}

export function markWhileAwayShown(scope: WhileAwayScope, day: string, storage: Storage = window.localStorage): void {
  try {
    storage.setItem(whileAwayLastShownKey(scope), day);
  } catch {
    // Best effort: without storage the dialog may show again today.
  }
}

/** The browser's local calendar day, "YYYY-MM-DD". */
export function localDay(now = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}
