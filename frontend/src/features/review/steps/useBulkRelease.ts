/**
 * A bulk release and its Undo (FR-017 restart, FR-030 Inbox remainder) with the
 * states of design D-03: releasing, release failed, released with Undo
 * (restored after a tab reload while `resumable`), undoing, undo failed, undone.
 * The Undo lasts until the person moves on; the caller says when that is.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { newIdempotencyKey, reviewApi } from "../../../api/review";
import type { BulkReleaseRequest, BulkReleaseUndoResponse } from "../../../api/review";
import { captureReviewScope, refreshAfterReviewWrite } from "../../../api/reviewHooks";
import { forgetRelease, readRelease, rememberRelease } from "../releaseMemory";
import { useStepAction } from "./useStepAction";

export interface ReleasedState {
  bulkId: string;
  /** Restored after a tab reload rather than released in this view. */
  resumed: boolean;
  released: number;
  /** Items the server left where they were (changed meanwhile, or not eligible). */
  skipped: number;
}

export function useBulkRelease(kind: BulkReleaseRequest["kind"], sessionId: string | null, resumable = true) {
  const accountId = captureReviewScope().accountId as string;
  const queryClient = useQueryClient();
  const releaseAction = useStepAction();
  const undoAction = useStepAction();
  const [released, setReleased] = useState<ReleasedState | null>(() => {
    const remembered = readRelease(accountId);
    return resumable && remembered?.kind === kind && remembered.sessionId === sessionId ? { bulkId: remembered.bulkId, resumed: true, released: remembered.released, skipped: 0 } : null;
  });
  const [undone, setUndone] = useState<BulkReleaseUndoResponse | null>(null);

  const release = (items: BulkReleaseRequest["items"], failure: string) => {
    const key = newIdempotencyKey();
    return releaseAction.run(
      "release",
      "Release",
      async (continuation) => {
        const response = await reviewApi.bulkRelease({ kind, ...(sessionId ? { session_id: sessionId } : {}), items }, key);
        rememberRelease(accountId, { kind, bulkId: response.id, sessionId, released: response.released.length });
        setUndone(null);
        setReleased({ bulkId: response.id, resumed: false, released: response.released.length, skipped: response.skipped.length });
        refreshAfterReviewWrite(queryClient, continuation.scope);
      },
      failure
    );
  };

  const undo = (failure: (count: number) => string) => {
    const key = newIdempotencyKey();
    const target = released as ReleasedState;
    void undoAction.run(
      "undo",
      "Undo",
      async (continuation) => {
        const response = await reviewApi.undoBulkRelease(target.bulkId, key);
        forgetRelease(accountId);
        setReleased(null);
        setUndone(response);
        refreshAfterReviewWrite(queryClient, continuation.scope);
      },
      failure(target.released)
    );
  };

  return { released, undone, release, undo, releaseAction, undoAction, forget: () => forgetRelease(accountId) };
}
