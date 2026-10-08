/**
 * The bulk release whose Undo is still offered (FR-017 restart, FR-030 Inbox),
 * kept in the browser so a tab reload reopens on the released state with Undo
 * (design D-03). `bb.reviewRelease.v1.<origin>.<account>` holds ids and a count,
 * no content; it goes with the person's other review keys on sign-out
 * (`clearReviewLocalState`) and when the person moves on.
 */
import { getApiBaseUrl } from "../../api/client";

export interface RememberedRelease {
  kind: "restart" | "inbox_remainder";
  bulkId: string;
  /** The review run an Inbox release belongs to. */
  sessionId: string | null;
  released: number;
}

const PREFIX = "bb.reviewRelease.v1";

function keyFor(accountId: string): string {
  return `${PREFIX}.${encodeURIComponent(getApiBaseUrl())}.${encodeURIComponent(accountId)}`;
}

export function readRelease(accountId: string, storage: Storage = window.localStorage): RememberedRelease | null {
  try {
    const value: unknown = JSON.parse(storage.getItem(keyFor(accountId)) as string);
    const release = value as RememberedRelease;
    return typeof release?.bulkId === "string" && typeof release.released === "number" && (release.kind === "restart" || release.kind === "inbox_remainder")
      ? release
      : null;
  } catch {
    return null;
  }
}

export function rememberRelease(accountId: string, release: RememberedRelease, storage: Storage = window.localStorage): void {
  try {
    storage.setItem(keyFor(accountId), JSON.stringify(release));
  } catch {
    // Best effort: without storage a reload simply drops the Undo offer.
  }
}

export function forgetRelease(accountId: string, storage: Storage = window.localStorage): void {
  try {
    storage.removeItem(keyFor(accountId));
  } catch {
    // Best effort, as above.
  }
}
