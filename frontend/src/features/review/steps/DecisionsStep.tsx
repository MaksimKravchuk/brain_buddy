/**
 * M-16 Tasks that ask for a decision, on the web (D-03): the D-02 card inline,
 * one task at a time, earliest-asking first. "Not now" passes a card and keeps
 * the task asking (FR-050); an Undo after each decision brings its card back
 * (FR-048).
 *
 * The queue is the run's stable snapshot, so after a reload, in another
 * browser or on another device it still lists every card of the run. Which of
 * them are handled comes from the server (http §6): the queue says which cards
 * have a decision in this run (a card saved anyway included, FR-002; an Undo
 * deletes the decision) and which were set aside (FR-050), and the server's own
 * task settles a card that left Next or no longer asks. Nothing is kept in this
 * browser. What this view did itself is held here at once, until the queue is
 * read again; a card the person undid here stays, even when its restored
 * wording no longer asks, until they move on.
 */
import { useState } from "react";

import { newProgressAttempt } from "../../../api/review";
import type { ReviewQueue } from "../../../api/review";
import { useReviewQueue } from "../../../api/reviewHooks";
import { useProjects } from "../../../api/taskHooks";
import type { TaskResponse } from "../../../api/taskTypes";
import { DecisionDialog } from "../DecisionDialog";
import type { DecisionOutcome } from "../DecisionDialog";
import { asksForDecision, classifyFromInstants, formulationInstants } from "../formulation";
import { pick } from "../plural";
import { buttonClass, FailureBanner, QueueGate } from "./stepParts";
import { useReviewRun } from "./reviewRun";
import { useStepAction } from "./useStepAction";

const plus = (ids: ReadonlySet<string>, id: string): ReadonlySet<string> => new Set(ids).add(id);
const without = (ids: ReadonlySet<string>, id: string): ReadonlySet<string> => new Set([...ids].filter((entry) => entry !== id));

const asks = (task: TaskResponse, now: Date): boolean => task.state === "next" && asksForDecision(classifyFromInstants(now, formulationInstants(task.formulation)));

export function DecisionsStep(): React.JSX.Element {
  const run = useReviewRun();
  const queue = useReviewQueue("decisions", run.session.id);
  const projects = useProjects();
  const action = useStepAction();
  const [decided, setDecided] = useState<ReadonlySet<string>>(new Set());
  const [undone, setUndone] = useState<ReadonlySet<string>>(new Set());
  const [passed, setPassed] = useState<ReadonlySet<string>>(new Set());
  const [latest, setLatest] = useState<Readonly<Record<string, TaskResponse>>>({});

  const onClose = (outcome: DecisionOutcome) => {
    // The inline card has no Close or Escape, so it only ever ends with a decision.
    const { task } = outcome as Extract<DecisionOutcome, { kind: "decided" }>;
    setDecided((ids) => plus(ids, task.id));
    setUndone((ids) => without(ids, task.id));
    // The task as the decision left it: a card saved anyway (FR-002) still asks, any other no longer does.
    setLatest((tasks) => ({ ...tasks, [task.id]: task }));
  };

  const onUndone = (restored: TaskResponse) => {
    setLatest((tasks) => ({ ...tasks, [restored.id]: restored }));
    setDecided((ids) => without(ids, restored.id));
    setUndone((ids) => plus(ids, restored.id));
  };

  const notNow = (task: TaskResponse) => {
    // The card's own decision may still be saving: passing it now would hide its answer (FR-048).
    if (run.writing) {
      return;
    }
    const attempt = newProgressAttempt(run.session.id, { set_aside_task_id: task.id });
    void action.run("not_now", "Not now", async () => {
      await run.progress(attempt);
      setPassed((ids) => plus(ids, task.id));
    });
  };

  return (
    <QueueGate queries={[queue, projects]}>
      {() => {
        const now = new Date();
        const { items: queued, meta } = queue.data as ReviewQueue;
        const items = queued.map((item) => latest[item.id] ?? item);
        if (items.length === 0) {
          return <p className="m-0 text-sm text-slate-600">Nothing asks for a decision</p>;
        }
        const serverDecided = new Set(meta.decided_task_ids ?? []);
        const serverAside = new Set(meta.set_aside_task_ids ?? []);
        // A decision recorded in this run, here or anywhere; an Undo here overrides a queue read before it.
        const hasDecision = (item: TaskResponse) => decided.has(item.id) || (serverDecided.has(item.id) && !undone.has(item.id));
        // A card that left Next or no longer asks is settled, unless the person just undid it here.
        const isDecided = (item: TaskResponse) => hasDecision(item) || (!undone.has(item.id) && !asks(item, now));
        const isPassed = (item: TaskResponse) => passed.has(item.id) || serverAside.has(item.id);
        const current = items.find((item) => !isDecided(item) && !isPassed(item));
        if (current === undefined) {
          const decidedCount = items.filter(isDecided).length;
          const left = items.length - decidedCount;
          const stillAsking = items.filter((item) => hasDecision(item) && asks(item, now)).length;
          return left > 0 ? (
            <>
              <p className="m-0 text-base font-medium text-slate-900">{`${decidedCount} of ${items.length} decided`}</p>
              <p className="m-0 text-sm text-slate-600">{`${left} still ask for a decision. They stay in Next whenever you're ready, and move to Someday on their usual date if nothing is decided.`}</p>
            </>
          ) : (
            <>
              <p className="m-0 text-base font-medium text-slate-900">{`All ${items.length} decided`}</p>
              <p className="m-0 text-sm text-slate-600">
                {stillAsking > 0
                  ? `${stillAsking} kept ${pick(stillAsking, "its", "their")} wording, so ${pick(stillAsking, "it still asks", "they still ask")} for a decision.`
                  : "Nothing in Next is waiting for a decision now."}
              </p>
            </>
          );
        }
        const project = projects.data?.find((entry) => entry.id === current.project_id);
        return (
          <>
            <p className="m-0 flex justify-between text-xs text-slate-500">
              <span>{`${items.findIndex((item) => item.id === current.id) + 1} of ${items.length} · earliest-asking first`}</span>
              <span>Asks for a decision</span>
            </p>
            <DecisionDialog
              key={current.id}
              inline
              task={current}
              projectName={project?.name ?? null}
              sessionId={run.session.id}
              onClose={onClose}
              onUndone={onUndone}
              onDirtyChange={run.setUnsaved}
            />
            {action.failure ? <FailureBanner failure={action.failure} online={action.online} /> : null}
            <div>
              <button type="button" disabled={action.disabled || run.writing} className={buttonClass} onClick={() => notNow(current)}>
                {action.pending === "not_now" ? "Saving…" : "Not now"}
              </button>
            </div>
          </>
        );
      }}
    </QueueGate>
  );
}
