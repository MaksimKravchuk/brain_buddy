/**
 * Undo of an applied review decision (FR-048), shared by the decision dialog
 * and the review steps. The server answers and its task wins (formulation-clock
 * §3 "decision undo"); the Ref of a refusal is quoted (FR-045).
 */
import type { QueryClient } from "@tanstack/react-query";

import { apiClient } from "../../api/client";
import { describeReviewError, isDecisionAlreadyUndone, newIdempotencyKey, reviewApi, withReference } from "../../api/review";
import type { DecisionResponse } from "../../api/review";
import { applyReviewTask, beginReviewContinuation, refreshAfterReviewWrite } from "../../api/reviewHooks";
import type { TaskResponse, TaskState } from "../../api/taskTypes";
import type { ShellNotify } from "../../components/shell/shellToast";

export const LIST_NAMES: Readonly<Record<TaskState, string>> = {
  inbox: "Inbox",
  next: "Next actions",
  waiting: "Waiting for",
  someday: "Someday / maybe",
  completed: "Completed",
  cancelled: "Cancelled"
};

/**
 * Undo after the card is gone. `onUndone` receives the restored task so a review
 * step can bring its card back as the current one.
 */
export async function runUndo(
  notify: ShellNotify,
  queryClient: QueryClient,
  response: DecisionResponse,
  title: string,
  onUndone?: (task: TaskResponse) => void
): Promise<void> {
  // The account that pressed Undo: an answer that arrives after it signed out
  // writes nothing and says nothing to whoever is signed in now.
  const run = beginReviewContinuation();
  try {
    const undone = await reviewApi.undoDecision(response.decision.id, { expected_task_revision: response.task.revision }, newIdempotencyKey());
    if (!run.stillCurrent()) {
      return;
    }
    applyReviewTask(queryClient, undone.task, run.scope);
    notify(`“${title}” is back as it was`);
    onUndone?.(undone.task);
  } catch (error) {
    if (!run.stillCurrent()) {
      return;
    }
    refreshAfterReviewWrite(queryClient, run.scope);
    const { kind, referenceId } = describeReviewError(error);
    if (isDecisionAlreadyUndone(error, response.decision.id)) {
      // Already undone (a retry whose first delivery applied, http §3). A 404
      // for the task or anything else falls through to the failure below.
      return;
    }
    if (kind === "undo_unavailable" || kind === "stale") {
      const current = await apiClient.getTask(response.task.id).catch(() => response.task);
      if (!run.stillCurrent()) {
        return;
      }
      notify(withReference(`Couldn't undo: “${title}” changed on another device. It's in ${LIST_NAMES[current.state]} now.`, referenceId));
      return;
    }
    notify(withReference("Couldn't undo. Nothing was changed.", referenceId));
  }
}
