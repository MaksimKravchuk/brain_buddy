/**
 * One pending-or-failed action at a time inside a review step (design D-03
 * "step action saving / failed"): the chosen button shows "Saving…", the
 * others are disabled, a failure keeps its Ref and offers Retry, and an answer
 * for an account that has gone is dropped.
 */
import { useCallback, useState } from "react";

import { describeReviewError } from "../../../api/review";
import { settleForAccount, useOnlineStatus } from "../../../api/reviewHooks";
import type { ReviewContinuation } from "../../../api/reviewHooks";
import { useTrackedWrite } from "./reviewRun";

export interface StepFailure {
  label: string;
  /** Overrides "Couldn't save “<label>”. Nothing was changed." */
  message?: string;
  referenceId: string | undefined;
  retry: () => void;
}

export function useStepAction() {
  const online = useOnlineStatus();
  const [pending, setPending] = useState<string | null>(null);
  const [failure, setFailure] = useState<StepFailure | null>(null);
  // Inside a running review the shell holds Next, Skip and Leave while this settles.
  const track = useTrackedWrite();

  const run = useCallback(async function runAction(
    id: string,
    label: string,
    action: (run: ReviewContinuation) => Promise<void>,
    message?: string
  ): Promise<boolean> {
    setPending(id);
    setFailure(null);
    const settled = await track(() => settleForAccount(action));
    if (settled === null) {
      return false;
    }
    setPending(null);
    if (!settled.ok) {
      setFailure({ label, message, referenceId: describeReviewError(settled.error).referenceId, retry: () => void runAction(id, label, action, message) });
    }
    return settled.ok;
  }, [track]);

  return { pending, failure, run, online, disabled: !online || pending !== null };
}
