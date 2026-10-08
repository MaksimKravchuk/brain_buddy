/** M-18 Waiting for, older than 7 days: keep, follow up, return to Next, or cancel (FR-032). */
import { daysInNext, formatReviewDate } from "../formulation";
import { ItemDecisionStep } from "./ItemDecisionStep";
import type { ItemStepConfig } from "./ItemDecisionStep";

const CONFIG: ItemStepConfig = {
  step: "waiting",
  position: "Waiting for more than 7 days",
  empty: "Nothing to chase",
  describe: (task, now) => {
    const since = task.waiting_since as string;
    return `Waiting on: ${task.waiting_for} · since ${formatReviewDate(since)} (${daysInNext(since, now)} days)`;
  },
  actions: [
    { id: "keep_waiting", type: "keep_waiting", label: "Keep waiting", sub: "Checks in again in 7 days", undoName: "Kept waiting", toast: (title) => `“${title}” kept waiting · checks in again in 7 days` },
    {
      id: "follow_up",
      type: "follow_up",
      label: "Create a follow-up",
      form: { prompt: "What will you do to follow up?", save: "Save follow-up", prefill: false },
      undoName: "Follow-up for",
      toast: (_title, text) => `Follow-up added: “${text}”`
    },
    {
      id: "return_to_next",
      type: "return_to_next",
      label: "Return to Next",
      form: { prompt: "What's the next action now?", save: "Move to Next", prefill: true },
      undoName: "Moved to Next",
      toast: (title) => `“${title}” moved to Next actions`
    },
    { id: "cancel", type: "cancel", label: "Cancel task", undoName: "Cancelled", toast: (title) => `“${title}” cancelled` }
  ]
};

export function WaitingStep(): React.JSX.Element {
  return <ItemDecisionStep config={CONFIG} />;
}
