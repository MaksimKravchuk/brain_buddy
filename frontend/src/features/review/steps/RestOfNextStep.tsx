/** M-17 The rest of Next with the capacity mirror: a count, the pace, no limit (FR-031). */
import type { ReviewQueue } from "../../../api/review";
import { useReviewQueue } from "../../../api/reviewHooks";
import { plural } from "../plural";
import { QueueGate } from "./stepParts";
import { useReviewRun } from "./reviewRun";

/** "4½ weeks", to the nearest half week and never less than half a week. */
function weeksOfWork(implied: number): string {
  const halves = Math.max(0.5, Math.round(implied * 2) / 2);
  const whole = Math.floor(halves);
  const label = `${whole === 0 ? "" : whole}${halves > whole ? "½" : ""}`;
  return `~${label} ${halves <= 1 ? "week" : "weeks"} of work at that pace`;
}

export function RestOfNextStep(): React.JSX.Element {
  const { session } = useReviewRun();
  const query = useReviewQueue("rest_of_next", session.id);
  return (
    <QueueGate queries={[query]}>
      {() => {
        const { items, meta } = query.data as ReviewQueue;
        const nextCount = meta.next_count as number;
        return (
          <>
            <div className="flex flex-col gap-1 rounded-xl border border-slate-200 bg-white p-4 text-base font-medium text-slate-900">
              <p className="m-0">{plural(nextCount, "next action")}</p>
              {meta.weekly_average_4w !== null && meta.weekly_average_4w !== undefined ? (
                <>
                  <p className="m-0">{`${meta.weekly_average_4w} done per week, last 4 weeks`}</p>
                  <p className="m-0">{weeksOfWork(meta.implied_weeks as number)}</p>
                </>
              ) : null}
            </div>
            {nextCount === 0 ? (
              <p className="m-0 text-sm text-slate-600">Next is empty.</p>
            ) : meta.weekly_average_4w === null ? (
              <p className="m-0 text-sm text-slate-600">After a few weeks of finished tasks, this will also show your weekly pace and how many weeks of work Next holds.</p>
            ) : (
              <p className="m-0 text-sm text-slate-600">No limit. Just a mirror of what you&apos;ve asked of yourself.</p>
            )}
            <ul className="m-0 flex list-none flex-col divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white p-0 text-sm text-slate-800">
              {items.map((task) => (
                <li key={task.id} className="px-3 py-2.5">{task.title}</li>
              ))}
            </ul>
          </>
        );
      }}
    </QueueGate>
  );
}
