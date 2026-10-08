/**
 * What a review step may ask of the running review (design D-03). The shell
 * owns the session, its progress and the leave rules; a step owns its content.
 */
import { createContext, useCallback, useContext } from "react";

import type { ClearStart, ProgressAttempt, ReviewSession, ReviewState } from "../../../api/review";

export interface ReviewRun {
  session: ReviewSession;
  state: ReviewState;
  /** Merge one progress change into the run; rejects with the request's error when it was not saved. */
  progress: (attempt: ProgressAttempt) => Promise<void>;
  /**
   * A write of this step is in flight (FR-048): Next, Skip step, Leave and the
   * browser Back stay put until it settles, so its answer lands in the step that
   * sent it and the summary counts it. Returns the call that ends the hold; ending
   * twice is harmless. Steps go through `useTrackedWrite` rather than calling this.
   */
  beginWrite: () => () => void;
  /** A field of the step holds text that has not been saved: leaving asks first (FR-052). */
  setUnsaved: (unsaved: boolean) => void;
  /** Run `close` for a form's Back or Cancel: at once when nothing unsaved is typed, else after the discard confirmation (FR-052). */
  confirmDiscard: (close: () => void) => void;
  /** Skip the step that is showing (the same as the bar's "Skip step"). */
  skipStep: () => void;
  /** Done on the summary: finish the run under `key` (a retry resends it); rejects when it was not saved. */
  finish: (clearStart: ClearStart | null, key: string) => Promise<void>;
}

export const ReviewRunContext = createContext<ReviewRun | null>(null);

export function useReviewRun(): ReviewRun {
  return useContext(ReviewRunContext) as ReviewRun;
}

/**
 * Run `write` while holding the review's navigation: the hold ends when it
 * settles, whether it saved or failed, so a failure never leaves the person
 * stuck. Outside a running review (the decision dialog on its own) it just runs.
 */
export function useTrackedWrite(): <T>(write: () => Promise<T>) => Promise<T> {
  const beginWrite = useContext(ReviewRunContext)?.beginWrite;
  return useCallback(
    async <T>(write: () => Promise<T>): Promise<T> => {
      const end = beginWrite?.();
      try {
        return await write();
      } finally {
        end?.();
      }
    },
    [beginWrite]
  );
}
