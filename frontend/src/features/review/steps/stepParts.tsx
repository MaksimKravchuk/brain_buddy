/**
 * Pieces every review step shares (design D-03): the failure banner with its
 * Ref and Retry, the load gate for a step's queries, and the confirmation
 * dialog of the Leave and unsaved-text rules.
 */
import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useId, useRef } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";

import { describeReviewError } from "../../../api/review";
import type { SessionCounts } from "../../../api/review";
import { trapTab } from "../focusTrap";
import { useReviewRun } from "./reviewRun";
import { SUMMARY_COUNTS } from "./summaryCounts";
import type { StepFailure } from "./useStepAction";

export const buttonClass = "min-h-11 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 hover:border-slate-300 disabled:opacity-60";
export const primaryButtonClass = "min-h-11 rounded-lg bg-sky-700 px-4 text-sm font-semibold text-white hover:bg-sky-800 disabled:opacity-60";
export const fieldClass = "min-h-11 w-full rounded-lg border border-slate-300 px-3 text-base text-slate-900 outline-hidden focus:border-brand-primary sm:text-sm";
const bannerClass = "flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900";

/** The Ref a person can quote (FR-045); nothing when there is none to quote. */
export function Ref({ id }: { id: string | undefined }): React.JSX.Element | null {
  return id ? <span className="text-xs">Ref {id}</span> : null;
}

/** "Couldn't save “Keep waiting”. Nothing was changed." + Ref + Retry (FR-045). */
export function FailureBanner({ failure, online }: { failure: StepFailure; online: boolean }): React.JSX.Element {
  return (
    <div role="alert" className={bannerClass}>
      <span>{failure.message ?? `Couldn't save “${failure.label}”. Nothing was changed.`}</span>
      <Ref id={failure.referenceId} />
      <button type="button" disabled={!online} className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100 disabled:opacity-60" onClick={failure.retry}>
        Retry
      </button>
    </div>
  );
}

/** The ten counts of a run, zero ones dimmed: two columns at 390 px, four from `md` up. */
export function CountsGrid({ counts, label }: { counts: SessionCounts; label: string }): React.JSX.Element {
  return (
    <ul aria-label={label} className="m-0 grid list-none grid-cols-2 overflow-hidden rounded-xl border border-slate-200 bg-white p-0 md:grid-cols-4">
      {SUMMARY_COUNTS.map(({ key, label: name }) => (
        <li key={key} className={`border-l border-t border-slate-200 px-3 py-2.5 text-xs ${counts[key] === 0 ? "text-slate-500" : "text-slate-600"}`}>
          {name}
          <b className={`block text-xl font-semibold ${counts[key] === 0 ? "text-slate-500" : "text-slate-900"}`}>{counts[key]}</b>
        </li>
      ))}
    </ul>
  );
}

/** A step's content once all its queries have answered; a placeholder or the load failure before. */
export function QueueGate({ queries, children }: { queries: Array<UseQueryResult<unknown>>; children: () => ReactNode }): React.JSX.Element {
  const run = useReviewRun();
  const failed = queries.find((query) => query.isError && !query.isFetching);
  if (failed) {
    return (
      <div role="alert" className={bannerClass}>
        <span>We couldn&apos;t load this step. Your progress is safe.</span>
        <Ref id={describeReviewError(failed.error).referenceId} />
        <button type="button" className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100" onClick={() => queries.filter((query) => query.isError).forEach((query) => void query.refetch())}>
          Retry
        </button>
        <button type="button" className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100" onClick={run.skipStep}>
          Skip step
        </button>
      </div>
    );
  }
  if (queries.some((query) => query.data === undefined)) {
    return (
      <div role="status" aria-label="Loading this step" aria-busy="true" className="flex flex-col gap-3">
        <div className="h-5 w-3/5 rounded-md bg-slate-200" />
        <div className="h-3 w-full rounded-md bg-slate-200" />
        <div className="h-3 w-4/5 rounded-md bg-slate-200" />
      </div>
    );
  }
  return <>{children()}</>;
}

/**
 * A two-way question that stops everything else (Leave, unsaved text): focus
 * starts on the safe choice, Escape means that choice, Tab stays inside, and
 * focus goes back to where it was when the dialog closes.
 */
export function ConfirmDialog({
  title,
  body,
  keepLabel,
  otherLabel,
  onKeep,
  onOther
}: {
  title: string;
  body: string;
  keepLabel: string;
  otherLabel: string;
  onKeep: () => void;
  onOther: () => void;
}): React.JSX.Element {
  const titleId = useId();
  const bodyId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement;
    keepRef.current?.focus();
    return () => opener.focus();
  }, []);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onKeep();
    } else if (event.key === "Tab") {
      trapTab(event, dialogRef.current as HTMLElement);
    }
  };

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-50/80 p-5 backdrop-blur-xs">
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        onKeyDown={onKeyDown}
        className="w-full max-w-[380px] rounded-[14px] border border-slate-200 bg-white p-4 shadow-floating"
      >
        <h2 id={titleId} className="m-0 text-sm font-semibold text-slate-900">{title}</h2>
        <p id={bodyId} className="m-0 mt-1 text-sm text-slate-600">{body}</p>
        <div className="mt-3 flex gap-2">
          <button ref={keepRef} type="button" className={`${primaryButtonClass} flex-1`} onClick={onKeep}>
            {keepLabel}
          </button>
          <button type="button" className={`${buttonClass} flex-1`} onClick={onOther}>
            {otherLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
