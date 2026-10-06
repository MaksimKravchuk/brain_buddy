/**
 * D-06 — "This wording" in the web task's inline detail (M-02 content).
 *
 * The only web place for "Ageing" (owner decision 2) and for the paused,
 * moves-tomorrow, kept and parked facts; "Decide" opens D-02 from the task on
 * any day (FR-010). Everything is computed from the task already loaded — the
 * server's instants and the browser clock — so there is no loading or error
 * state of its own. Nothing shows before the explainer was seen (FR-051).
 */
import { Archive, CircleHelp, Hourglass, Pause, RotateCcw } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";

import { useOnlineStatus, useReviewClock, useWeeklyReviewEnabled } from "../../api/reviewHooks";
import type { ProjectResponse, TaskFormulationResponse, TaskResponse } from "../../api/taskTypes";
import { DecisionDialog, type DecisionOutcome } from "./DecisionDialog";
import { classifyFromInstants, daysInNext, formatReviewDate, formatReviewTime, formulationInstants } from "./formulation";

const OFFLINE_REASON = "You're offline. Decisions need a connection. Retry when you're back online.";

type Tone = "asks" | "tomorrow" | "neutral";

function Chip({ tone, icon, children }: { tone: Tone; icon: ReactNode; children: ReactNode }): React.JSX.Element {
  const toneClass = tone === "asks"
    ? "border-indigo-200 bg-indigo-50 text-indigo-700"
    : tone === "tomorrow"
      ? "border-amber-200 bg-amber-50 text-amber-800"
      : "border-slate-200 bg-slate-100 text-slate-600";
  return (
    <span className={`inline-flex h-[22px] items-center gap-1 rounded-full border px-2 text-[11px] font-medium ${toneClass}`}>
      {icon}
      {children}
    </span>
  );
}

const iconClass = "h-3 w-3";

export function FormulationBlock({
  task,
  projects,
  headingRef
}: {
  task: TaskResponse;
  projects: ProjectResponse[];
  /** The panel heading, which takes focus when a decision moved the task out of Next. */
  headingRef: RefObject<HTMLHeadingElement | null>;
}): React.JSX.Element | null {
  const enabled = useWeeklyReviewEnabled();
  const now = useReviewClock(enabled);
  const online = useOnlineStatus();
  const titleId = useId();
  const offlineId = useId();
  const decideRef = useRef<HTMLButtonElement>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const focusTarget = useRef<"decide" | "heading" | null>(null);
  const project = projects.find((candidate) => candidate.id === task.project_id);

  useEffect(() => {
    if (dialogOpen || focusTarget.current === null) {
      return;
    }
    const target = focusTarget.current === "decide" && decideRef.current ? decideRef.current : headingRef.current;
    focusTarget.current = null;
    target?.focus();
  }, [dialogOpen, headingRef]);

  if (!enabled) {
    return null;
  }

  const closeDialog = (outcome: DecisionOutcome) => {
    focusTarget.current = outcome.kind === "decided" && outcome.leftNext ? "heading" : "decide";
    setDialogOpen(false);
  };

  let chip: ReactNode;
  let lines: string[];
  let decide = false;

  if (task.parked && task.state === "someday") {
    const moved = `Moved here on ${formatReviewDate(task.parked.at)} at ${formatReviewTime(task.parked.at)}.`;
    chip = <Chip tone="neutral" icon={<Archive className={iconClass} aria-hidden />}>Parked automatically</Chip>;
    lines = [
      project?.state === "archived"
        ? `${moved} Its project “${project.name}” is archived, so restore the project before moving this back to Next actions.`
        : `${moved} Project, Tags, notes and due date were kept.`
    ];
  } else {
    const formulation = task.formulation as TaskFormulationResponse;
    const instants = formulationInstants(formulation);
    if (task.state !== "next" || instants === null) {
      return null;
    }
    const formulationClass = classifyFromInstants(now, instants);
    const days = `${daysInNext(formulation.started_at, now)} days in Next`;
    if (formulationClass === "paused") {
      chip = <Chip tone="neutral" icon={<Pause className={iconClass} aria-hidden />}>Paused until the due date</Chip>;
      lines = [`The clock starts on ${formatReviewDate(instants.paused_until as string)}. Until then this task won't ask for a decision or move to Someday.`];
    } else if (formulationClass === "asks") {
      chip = <><Chip tone="asks" icon={<CircleHelp className={iconClass} aria-hidden />}>Asks for a decision</Chip> {days}</>;
      lines = ["The wording hasn't moved for a while. That's feedback on the wording, not on you. Changing notes, Tags, project or priority doesn't restart the clock."];
      decide = true;
    } else if (formulationClass === "moves_tomorrow" || formulationClass === "park_due") {
      chip = <><Chip tone="tomorrow" icon={<Archive className={iconClass} aria-hidden />}>Moves to Someday tomorrow</Chip> {days}</>;
      lines = [`If nothing is decided, it moves to Someday / maybe on ${formatReviewDate(instants.park_due_at)} at ${formatReviewTime(instants.park_due_at)}. Nothing is lost, and you can bring it back in one click.`];
      decide = true;
    } else if (formulation.extended_at) {
      chip = <><Chip tone="neutral" icon={<RotateCcw className={iconClass} aria-hidden />}>Kept 7 more days</Chip> {days}</>;
      lines = [
        `“${formulation.extension_reason}”`,
        `Kept on ${formatReviewDate(formulation.extended_at)}. Asks again on ${formatReviewDate(instants.ask_at)}; moves to Someday on ${formatReviewDate(instants.park_due_at)} if still undecided. This wording can't be extended again.`
      ];
    } else if (formulationClass === "ageing") {
      chip = <><Chip tone="neutral" icon={<Hourglass className={iconClass} aria-hidden />}>Ageing</Chip> {days}</>;
      lines = [`Asks for a decision from ${formatReviewDate(instants.ask_at)} if the wording stays the same.`];
    } else {
      chip = days;
      lines = [];
    }
  }

  return (
    <section aria-labelledby={titleId} className="mx-4 mb-3 flex flex-col gap-1.5 rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-2.5 text-[12.5px] text-slate-700">
      <h3 id={titleId} className="m-0 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">This wording</h3>
      <p className="m-0 flex flex-wrap items-center gap-1.5 text-slate-600">{chip}</p>
      {lines.map((line) => <p key={line} className="m-0 leading-relaxed">{line}</p>)}
      {decide ? (
        <>
          <button
            ref={decideRef}
            type="button"
            aria-disabled={online ? undefined : "true"}
            aria-describedby={online ? undefined : offlineId}
            className="mt-1 inline-flex min-h-11 items-center justify-center self-start rounded-lg bg-sky-700 px-4 text-sm font-semibold text-white hover:bg-sky-800 aria-disabled:opacity-60 max-sm:w-full"
            onClick={() => setDialogOpen(true)}
          >
            Decide
          </button>
          {online ? null : <span id={offlineId} className="sr-only">{OFFLINE_REASON}</span>}
        </>
      ) : null}
      {dialogOpen ? <DecisionDialog task={task} projectName={project ? project.name : null} onClose={closeDialog} /> : null}
    </section>
  );
}
