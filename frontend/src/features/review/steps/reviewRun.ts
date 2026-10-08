/**
 * What a review step may ask of the running review (design D-03). The shell
 * owns the session, its progress and the leave rules; a step owns its content.
 */
import { createContext, useContext } from "react";

import type { ClearStart, ProgressAttempt, ReviewSession, ReviewState } from "../../../api/review";

export interface ReviewRun {
  session: ReviewSession;
  state: ReviewState;
  /** Merge one progress change into the run; rejects with the request's error when it was not saved. */
  progress: (attempt: ProgressAttempt) => Promise<void>;
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
