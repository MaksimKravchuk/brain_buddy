/**
 * The running review on the web (design D-03): a focused page with a top bar
 * (Skip step, Leave), a read-only step rail and one 600 px column. It owns the
 * session and its progress, the leave rules (Leave confirmation, unsaved text,
 * browser Back) and the notices for a run that ended or moved on elsewhere;
 * the steps own their content and reach the run through `useReviewRun`.
 */
import { useQueryClient } from "@tanstack/react-query";
import { Check, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { newProgressAttempt, reviewApi } from "../../api/review";
import type { ClearStart, ProgressAttempt, ReviewSession, ReviewState, SessionProgress, StepCode } from "../../api/review";
import { captureReviewScope, refreshAfterReviewWrite, settleForAccount, useOnlineStatus } from "../../api/reviewHooks";
import { decisionCount, lastReviewText } from "./lastReview";
import { forgetRelease } from "./releaseMemory";
import { useLeaveGuard } from "./useLeaveGuard";
import { useReviewDrafts } from "./useReviewDrafts";
import { DatesStep } from "./steps/DatesStep";
import { DecisionsStep } from "./steps/DecisionsStep";
import { InboxStep } from "./steps/InboxStep";
import { MindSweepStep } from "./steps/MindSweepStep";
import { ProjectsStep } from "./steps/ProjectsStep";
import { RestOfNextStep } from "./steps/RestOfNextStep";
import { ReviewRunContext } from "./steps/reviewRun";
import type { ReviewRun } from "./steps/reviewRun";
import { SomedayStep } from "./steps/SomedayStep";
import { SummaryStep } from "./steps/SummaryStep";
import { buttonClass, ConfirmDialog, FailureBanner } from "./steps/stepParts";
import { useStepAction } from "./steps/useStepAction";
import { WaitingStep } from "./steps/WaitingStep";
import { WinsStep } from "./steps/WinsStep";

const DAY_MS = 86_400_000;

const STEPS: Record<StepCode, { title: string; rail: string; view: () => React.JSX.Element }> = {
  wins: { title: "Wins of the week", rail: "Wins of the week", view: WinsStep },
  mind_sweep: { title: "Mind sweep", rail: "Mind sweep", view: MindSweepStep },
  inbox: { title: "Inbox", rail: "Inbox", view: InboxStep },
  decisions: { title: "Tasks that ask for a decision", rail: "Decisions", view: DecisionsStep },
  rest_of_next: { title: "The rest of Next", rail: "The rest of Next", view: RestOfNextStep },
  waiting: { title: "Waiting for, older than 7 days", rail: "Waiting for", view: WaitingStep },
  projects: { title: "Projects without a next action", rail: "Projects", view: ProjectsStep },
  someday: { title: "Someday / maybe", rail: "Someday / maybe", view: SomedayStep },
  dates: { title: "The next 14 days", rail: "Next 14 days", view: DatesStep },
  summary: { title: "Review done", rail: "Summary", view: SummaryStep }
};

const STEP_ORDER = Object.keys(STEPS) as StepCode[];

/** A focused review page: the bar, then whatever the page holds. */
export function ReviewFrame({
  title,
  recap,
  actions,
  children
}: {
  title: string;
  recap?: string | null;
  actions?: ReactNode;
  children: ReactNode;
}): React.JSX.Element {
  return (
    <div className="flex min-h-screen flex-col bg-surface-base text-slate-900">
      <header className="flex min-h-14 shrink-0 flex-wrap items-center gap-x-3 border-b border-slate-200 bg-white/95 px-5 py-1">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <RotateCcw className="h-4 w-4 text-sky-700" aria-hidden />
          {title}
        </span>
        {recap ? <span className="text-xs text-slate-500">{recap}</span> : null}
        <span className="flex-1" />
        {actions}
      </header>
      {children}
    </div>
  );
}

type Confirm = { kind: "discard"; then: () => void; rearm: boolean; keepStep: boolean } | { kind: "leave"; rearm: boolean };

export function ReviewShell({ initial, state, onExit }: { initial: ReviewSession; state: ReviewState; onExit: () => void }): React.JSX.Element {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const online = useOnlineStatus();
  const bar = useStepAction();
  const [session, setSession] = useState(initial);
  const sessionRef = useRef(initial);
  const [note, setNote] = useState<string | null>(null);
  const [unsaved, setUnsaved] = useState(false);
  const [stepKey, setStepKey] = useState(0);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  // Writes of the showing step still in flight (FR-048): the run stays on this step until they settle.
  const writesRef = useRef(0);
  const [writing, setWriting] = useState(false);
  const beginWrite = useCallback(() => {
    let open = true;
    writesRef.current += 1;
    setWriting(true);
    return () => {
      if (open) {
        open = false;
        writesRef.current -= 1;
        setWriting(writesRef.current > 0);
      }
    };
  }, []);

  const steps = STEP_ORDER.filter((code) => code in session.steps);
  const current = session.current_step ?? "summary";
  const position = steps.indexOf(current) + 1;
  const ended = session.status !== "open";
  const idleClosed = ended && Date.parse(session.ended_at as string) - Date.parse(session.last_activity_at) >= 7 * DAY_MS;
  const View = STEPS[current].view;
  const drafts = useReviewDrafts(initial.id, current);

  useEffect(() => {
    headingRef.current?.focus();
  }, [current, ended]);

  /** Merge a progress answer into the run; notice a run that moved on while this device looked away. */
  const progress = async (attempt: ProgressAttempt): Promise<void> => {
    const settled = await settleForAccount(() => reviewApi.progress(attempt));
    if (settled === null) {
      return;
    }
    if (!settled.ok) {
      throw settled.error;
    }
    const merged = settled.value;
    const before = sessionRef.current.current_step;
    sessionRef.current = merged;
    setSession(merged);
    if (merged.status === "open" && attempt.body.current_step === undefined && merged.current_step !== before) {
      const mergedSteps = STEP_ORDER.filter((code) => code in merged.steps);
      setNote(`You continued this review on another device, so it's at step ${mergedSteps.indexOf(merged.current_step as StepCode) + 1} now.`);
    }
  };

  const finish = async (clearStart: ClearStart | null, key: string): Promise<void> => {
    const settled = await settleForAccount(() => reviewApi.finish(session.id, clearStart ? { clear_start: clearStart } : {}, key));
    if (settled === null) {
      return;
    }
    if (!settled.ok) {
      throw settled.error;
    }
    refreshAfterReviewWrite(queryClient, settled.scope);
    onExit();
  };

  /** Anything that leaves the step asks first when a field holds unsaved text (FR-052). */
  const request = (action: () => void, rearm = false, keepStep = false) => {
    if (unsaved) {
      setConfirm({ kind: "discard", then: action, rearm, keepStep });
      return;
    }
    action();
  };

  // The bar's own Next/Skip progress write sits outside the run context, so it counts here beside the steps' writes.
  const inFlight = () => writesRef.current > 0 || bar.pending !== null;

  // Browser Back while a write is saving goes nowhere: the entry is put back and the page stays (FR-048);
  // a tab close or reload gets the browser's warning then too, as it does for unsaved text.
  const guard = useLeaveGuard({
    dirty: unsaved || writing || bar.pending !== null,
    onBack: () => {
      if (inFlight()) {
        guard.rearm();
        return;
      }
      request(() => setConfirm({ kind: "leave", rearm: true }), true);
    }
  });

  const advance = (status: "finished" | "skipped") => {
    if (inFlight()) {
      return;
    }
    const change: SessionProgress = {
      step: { code: current, status },
      current_step: steps[position],
      ...(steps[position] === "decisions" ? { snapshot_decision_queue: true as const } : {})
    };
    const attempt = newProgressAttempt(session.id, change);
    void bar.run(
      status,
      status === "skipped" ? "Skip step" : "Next",
      async () => {
        await progress(attempt);
        setNote(null);
        setUnsaved(false);
      },
      `Couldn't save that you ${status === "skipped" ? "skipped" : "finished"} this step. Try again.`
    );
  };

  const skip = () => request(() => advance("skipped"));
  // A form's own Back closes only that form, so the rest of the step keeps its state.
  const confirmDiscard = (close: () => void) => request(close, false, true);
  const run: ReviewRun = { session, state, progress, beginWrite, setUnsaved, confirmDiscard, skipStep: skip, finish };
  // Next and Skip also wait for the connection; Leave stays available offline, where a write fails and settles.
  const held = bar.disabled || writing;
  const saving = bar.pending !== null || writing;

  const keepGoing = (rearm: boolean) => {
    if (rearm) {
      guard.rearm();
    }
    setConfirm(null);
  };

  const leave = () => {
    if (inFlight()) {
      return;
    }
    forgetRelease(captureReviewScope().accountId as string);
    guard.release();
    navigate("/tasks/next", { replace: true });
  };

  return (
    <ReviewFrame
      title={`Weekly review · ${session.mode === "quick" ? "Quick" : "Full"}`}
      recap={lastReviewText(state)}
      actions={
        <>
          {ended || current === "summary" ? null : (
            <button type="button" disabled={held} className={`${buttonClass} border-transparent bg-transparent text-sky-700`} onClick={skip}>
              Skip step
            </button>
          )}
          <button type="button" disabled={saving} className={buttonClass} onClick={() => request(() => setConfirm({ kind: "leave", rearm: false }))}>
            Leave
          </button>
        </>
      }
    >
      <div className="grid min-h-0 flex-1 md:grid-cols-[240px_1fr]">
        <nav aria-label="Review steps" className="hidden w-[240px] flex-col gap-0.5 border-r border-slate-200 bg-white px-3 py-4 md:flex">
          <ol className="m-0 flex list-none flex-col gap-0.5 p-0">
            {steps.map((code) => {
              const status = session.steps[code];
              return (
                <li
                  key={code}
                  aria-current={code === current ? "step" : undefined}
                  className={`flex min-h-[34px] items-center gap-2.5 rounded-lg px-2.5 text-[13px] ${code === current ? "bg-sky-50 font-semibold text-sky-700" : status === "skipped" ? "text-slate-500" : "text-slate-600"}`}
                >
                  <span className={`grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border-[1.5px] ${status === "finished" ? "border-sky-500 bg-sky-500 text-white" : status === "skipped" ? "border-dashed border-slate-300" : "border-slate-300"}`} aria-hidden>
                    {status === "finished" ? <Check className="h-3 w-3" /> : null}
                  </span>
                  {STEPS[code].rail}
                  {status === "finished" ? <small className="ml-auto text-[11px] font-normal text-slate-500">done</small> : null}
                  {status === "skipped" ? <small className="ml-auto text-[11px] font-normal text-slate-500">skipped</small> : null}
                </li>
              );
            })}
          </ol>
        </nav>
        <main className="flex justify-center px-5 py-6 md:px-10">
          <div className="flex w-full max-w-[600px] flex-col gap-3.5">
            {online ? null : (
              <p role="status" aria-label="Offline" className="m-0 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700">
                <b>You&apos;re offline.</b> Decisions made so far are saved. Retry when you&apos;re back online, here or on another device.
              </p>
            )}
            {ended ? (
              <>
                <h1 ref={headingRef} tabIndex={-1} className="m-0 text-2xl font-semibold text-slate-900 outline-hidden">
                  {idleClosed ? "This review was closed" : "This review has ended"}
                </h1>
                <p className="m-0 text-sm text-slate-600">
                  {idleClosed
                    ? `This review was closed after a week without activity. Its ${decisionCount(session.counts)} decisions are kept.`
                    : `This review was finished or replaced on another device. Its ${decisionCount(session.counts)} decisions are kept.`}
                </p>
                <div>
                  <button type="button" className={buttonClass} onClick={onExit}>
                    Open the review
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="m-0 text-xs text-slate-500 md:hidden">{`Step ${position} of ${steps.length}`}</p>
                <h1 ref={headingRef} tabIndex={-1} className="m-0 text-2xl font-semibold text-slate-900 outline-hidden">
                  {STEPS[current].title}
                </h1>
                {note ? <p role="status" className="m-0 rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-800">{note}</p> : null}
                {bar.failure ? <FailureBanner failure={bar.failure} online={bar.online} /> : null}
                <ReviewRunContext.Provider value={run}>
                  <div key={`${current}-${stepKey}`} className="flex flex-col gap-3.5">
                    <View />
                  </div>
                </ReviewRunContext.Provider>
                {current === "summary" ? null : (
                  <div className="mt-2 flex justify-end">
                    <button
                      type="button"
                      disabled={held}
                      className="min-h-11 rounded-lg bg-sky-700 px-5 text-sm font-semibold text-white hover:bg-sky-800 disabled:opacity-60"
                      onClick={() => request(() => advance("finished"))}
                    >
                      {bar.pending === "finished" ? "Saving…" : "Next"}
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </main>
      </div>
      {confirm?.kind === "discard" ? (
        <ConfirmDialog
          title="Discard what you typed?"
          body="It hasn't been saved."
          keepLabel="Keep editing"
          otherLabel="Discard"
          onKeep={() => keepGoing(confirm.rearm)}
          onOther={() => {
            setUnsaved(false);
            if (!confirm.keepStep) {
              // The step starts over (or is left): what was typed in it goes with it, drafts included.
              drafts.clearAll();
              setStepKey((key) => key + 1);
            }
            setConfirm(null);
            confirm.then();
          }}
        />
      ) : null}
      {confirm?.kind === "leave" ? (
        <ConfirmDialog
          title="Take a break?"
          body={`Everything you've done is kept. Continue from step ${position} any time, on any device.`}
          keepLabel="Keep going"
          otherLabel="Leave for now"
          onKeep={() => keepGoing(confirm.rearm)}
          onOther={leave}
        />
      ) : null}
    </ReviewFrame>
  );
}
