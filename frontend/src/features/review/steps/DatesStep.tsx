/** M-21 Dates in the next 14 days: a read-only look ahead, grouped by day (FR-028). */
import type { ReviewQueue } from "../../../api/review";
import { useReviewQueue } from "../../../api/reviewHooks";
import { formatReviewDate } from "../formulation";
import { LIST_NAMES } from "../reviewUndo";
import { QueueGate } from "./stepParts";
import { useReviewRun } from "./reviewRun";

export function DatesStep(): React.JSX.Element {
  const { session } = useReviewRun();
  const query = useReviewQueue("dates", session.id);
  return (
    <QueueGate queries={[query]}>
      {() => {
        const { items, meta } = query.data as ReviewQueue;
        const days = meta.days as NonNullable<ReviewQueue["meta"]["days"]>;
        if (days.length === 0) {
          return (
            <>
              <p className="m-0 text-base font-medium text-slate-900">A clear two weeks</p>
              <p className="m-0 text-sm text-slate-600">Nothing has a due date in the next 14 days.</p>
            </>
          );
        }
        const byId = new Map(items.map((task) => [task.id, task]));
        return (
          <>
            {days.map((entry) => {
              // The day is a calendar date in the stored zone: read it at noon UTC so no zone moves it.
              const label = formatReviewDate(`${entry.day}T12:00:00Z`, "UTC");
              return (
                <section key={entry.day} role="group" aria-label={label} className="flex flex-col gap-1">
                  <h2 className="m-0 text-xs font-semibold uppercase tracking-[0.06em] text-slate-500">{label}</h2>
                  <ul className="m-0 flex list-none flex-col divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white p-0 text-sm text-slate-800">
                    {entry.task_ids.map((id) => {
                      const task = byId.get(id) as NonNullable<ReturnType<typeof byId.get>>;
                      return (
                        <li key={id} className="flex items-baseline justify-between gap-3 px-3 py-2.5">
                          <span>{task.title}</span>
                          <span className="text-xs text-slate-500">{LIST_NAMES[task.state]}</span>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </>
        );
      }}
    </QueueGate>
  );
}
