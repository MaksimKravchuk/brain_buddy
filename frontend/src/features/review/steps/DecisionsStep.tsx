/**
 * M-16 Tasks that ask for a decision, on the web (D-03): the D-02 card inline,
 * one task at a time, earliest-asking first. "Not now" passes a card and keeps
 * the task asking (FR-050); an Undo after each decision brings its card back
 * (FR-048).
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

const without = (ids: ReadonlySet<string>, id: string): ReadonlySet<string> => new Set([...ids].filter((entry) => entry !== id));

export function DecisionsStep(): React.JSX.Element {
  const run = useReviewRun();
  const queue = useReviewQueue("decisions", run.session.id);
  const projects = useProjects();
  const action = useStepAction();
  const [decided, setDecided] = useState<ReadonlySet<string>>(new Set());
  const [stillAsking, setStillAsking] = useState<ReadonlySet<string>>(new Set());
  const [passed, setPassed] = useState<ReadonlySet<string>>(new Set());
  const [latest, setLatest] = useState<Readonly<Record<string, TaskResponse>>>({});

  const onClose = (outcome: DecisionOutcome) => {
    // The inline card has no Close or Escape, so it only ever ends with a decision.
    const { task } = outcome as Extract<DecisionOutcome, { kind: "decided" }>;
    setDecided((ids) => new Set(ids).add(task.id));
    // A card saved anyway (FR-002) is decided, yet its task still asks.
    if (task.state === "next" && asksForDecision(classifyFromInstants(new Date(), formulationInstants(task.formulation)))) {
      setStillAsking((ids) => new Set(ids).add(task.id));
    }
  };

  const onUndone = (restored: TaskResponse) => {
    setLatest((tasks) => ({ ...tasks, [restored.id]: restored }));
    setDecided((ids) => without(ids, restored.id));
    setStillAsking((ids) => without(ids, restored.id));
  };

  const notNow = (task: TaskResponse) => {
    const attempt = newProgressAttempt(run.session.id, { set_aside_task_id: task.id });
    void action.run("not_now", "Not now", async () => {
      await run.progress(attempt);
      setPassed((ids) => new Set(ids).add(task.id));
    });
  };

  return (
    <QueueGate queries={[queue, projects]}>
      {() => {
        const items = (queue.data as ReviewQueue).items.map((item) => latest[item.id] ?? item);
        if (items.length === 0) {
          return <p className="m-0 text-sm text-slate-600">Nothing asks for a decision</p>;
        }
        const current = items.find((item) => !decided.has(item.id) && !passed.has(item.id));
        if (current === undefined) {
          const left = items.length - decided.size;
          return passed.size > 0 ? (
            <>
              <p className="m-0 text-base font-medium text-slate-900">{`${decided.size} of ${items.length} decided`}</p>
              <p className="m-0 text-sm text-slate-600">{`${left} still ask for a decision. They stay in Next whenever you're ready, and move to Someday on their usual date if nothing is decided.`}</p>
            </>
          ) : (
            <>
              <p className="m-0 text-base font-medium text-slate-900">{`All ${items.length} decided`}</p>
              <p className="m-0 text-sm text-slate-600">
                {stillAsking.size > 0
                  ? `${stillAsking.size} kept ${pick(stillAsking.size, "its", "their")} wording, so ${pick(stillAsking.size, "it still asks", "they still ask")} for a decision.`
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
              <button type="button" disabled={action.disabled} className={buttonClass} onClick={() => notNow(current)}>
                {action.pending === "not_now" ? "Saving…" : "Not now"}
              </button>
            </div>
          </>
        );
      }}
    </QueueGate>
  );
}
