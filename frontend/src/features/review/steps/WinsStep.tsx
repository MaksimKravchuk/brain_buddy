/** M-13 Wins of the week: what was finished in the last 7 days, before any backlog (FR-028). */
import type { ReviewQueue } from "../../../api/review";
import { useReviewQueue } from "../../../api/reviewHooks";
import { plural } from "../plural";
import { QueueGate } from "./stepParts";
import { useReviewRun } from "./reviewRun";

export function WinsStep(): React.JSX.Element {
  const { session } = useReviewRun();
  const query = useReviewQueue("wins", session.id);
  return (
    <QueueGate queries={[query]}>
      {() => {
        const { items, meta } = query.data as ReviewQueue;
        const count = meta.count as number;
        return count === 0 ? (
          <p className="m-0 text-co-meta text-ink-muted">A quiet week… Taking a few minutes now is how next week gets easier.</p>
        ) : (
          <>
            <p className="m-0 text-co-body font-medium text-ink">{`This week you finished ${plural(count, "thing")}`}</p>
            <ul className="m-0 flex list-none flex-col gap-2 p-0 text-co-meta text-ink">
              {items.map((task) => (
                <li key={task.id} className="rounded-card bg-card px-3 py-2.5">{task.title}</li>
              ))}
            </ul>
          </>
        );
      }}
    </QueueGate>
  );
}
