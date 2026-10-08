/** M-20 Someday pass: at most seven tasks nobody has looked at lately (FR-032). */
import { formatReviewDate } from "../formulation";
import { ItemDecisionStep } from "./ItemDecisionStep";
import type { ItemStepConfig } from "./ItemDecisionStep";

const CONFIG: ItemStepConfig = {
  step: "someday",
  position: "Someday / maybe, not looked at lately",
  empty: "Nothing in Someday needs a look this week.",
  describe: (task) => (task.parked ? `Parked automatically on ${formatReviewDate(task.parked.at)}` : null),
  actions: [
    { id: "keep_someday", type: "keep_someday", label: "Keep in Someday", sub: "Looks again in 30 days", undoName: "Kept in Someday", toast: (title) => `“${title}” kept in Someday · looks again in 30 days` },
    {
      id: "return_to_next",
      type: "return_to_next",
      label: "Move to Next",
      form: { prompt: "What's the first concrete action?", save: "Move to Next", prefill: true },
      undoName: "Moved to Next",
      toast: (title) => `“${title}” moved to Next actions`
    },
    { id: "cancel", type: "cancel", label: "Cancel task", undoName: "Cancelled", toast: (title) => `“${title}” cancelled` }
  ]
};

export function SomedayStep(): React.JSX.Element {
  return <ItemDecisionStep config={CONFIG} />;
}
