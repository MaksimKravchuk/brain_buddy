/** M-22 Summary: the ten counts, the next review, an optional question, Done (FR-033). */
import { useState } from "react";

import { newIdempotencyKey } from "../../../api/review";
import type { ClearStart } from "../../../api/review";
import { formatReviewDate, formatReviewTime } from "../formulation";
import { CountsGrid, FailureBanner, buttonClass, primaryButtonClass } from "./stepParts";
import { SUMMARY_COUNTS } from "./summaryCounts";
import { useReviewRun } from "./reviewRun";
import { useStepAction } from "./useStepAction";

export function SummaryStep(): React.JSX.Element {
  const { session, state, finish } = useReviewRun();
  const action = useStepAction();
  const [answer, setAnswer] = useState<ClearStart | null>(null);
  const counts = session.counts;
  const next = state.next_review_at as string;

  const done = () => {
    const key = newIdempotencyKey();
    void action.run("done", "Done", () => finish(answer, key));
  };

  return (
    <>
      {SUMMARY_COUNTS.some(({ key }) => counts[key] > 0) ? (
        <CountsGrid counts={counts} label="Decisions in this review" />
      ) : (
        <p className="m-0 text-co-meta text-ink-muted">Nothing needed changing this time.</p>
      )}
      <p className="m-0 rounded-card bg-quiet px-3 py-2 text-co-meta text-ink-muted">{`Next review: ${formatReviewDate(next)}, ${formatReviewTime(next)}`}</p>
      <div role="group" aria-labelledby="clear-start-question" className="flex flex-col gap-2 rounded-card bg-card p-4">
        <p id="clear-start-question" className="m-0 text-co-meta font-semibold text-ink">
          Clear how to start the week? <span className="font-normal text-ink-muted">optional</span>
        </p>
        <div className="flex gap-2">
          {(["yes", "not_really"] as const).map((value) => (
            <button key={value} type="button" aria-pressed={answer === value} className={`${buttonClass} min-w-[120px] ${answer === value ? "bg-ink text-ground" : ""}`} onClick={() => setAnswer(value)}>
              {value === "yes" ? "Yes" : "Not really"}
            </button>
          ))}
        </div>
        {answer ? <p role="status" className="m-0 text-co-meta text-ink-muted">Thanks. Noted for this review.</p> : null}
      </div>
      {action.failure ? <FailureBanner failure={action.failure} online={action.online} /> : null}
      <div className="flex justify-end">
        <button type="button" disabled={action.disabled} className={primaryButtonClass} onClick={done}>
          {action.pending === "done" ? "Saving…" : "Done"}
        </button>
      </div>
    </>
  );
}
