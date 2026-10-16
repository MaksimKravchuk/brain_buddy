/**
 * Pieces every review step shares (design D-03): the failure banner with its
 * Ref and Retry, the load gate for a step's queries, and the confirmation
 * dialog of the Leave and unsaved-text rules.
 */
import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useId, useLayoutEffect, useRef } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";

import { describeReviewError } from "../../../api/review";
import type { SessionCounts } from "../../../api/review";
import { trapTab } from "../focusTrap";
import { useReviewRun } from "./reviewRun";
import { SUMMARY_COUNTS } from "./summaryCounts";
import type { StepFailure } from "./useStepAction";

export const buttonClass = "min-h-11 rounded-control bg-quiet hover:bg-quiet-pressed px-3 text-co-meta font-medium text-ink disabled:opacity-60";
export const primaryButtonClass = "min-h-11 rounded-control bg-ink px-4 text-co-meta font-semibold text-ground hover:bg-ink/85 disabled:opacity-60";
export const fieldClass = "min-h-11 w-full rounded-card bg-quiet px-3 text-co-body text-ink outline-hidden focus-visible:shadow-ring-focus";
const bannerClass = "flex flex-wrap items-center gap-2 rounded-card bg-quiet px-3 py-2 text-co-meta text-warning";

/** The Ref a person can quote (FR-045); nothing when there is none to quote. */
export function Ref({ id }: { id: string | undefined }): React.JSX.Element | null {
  return id ? <span className="text-co-meta">Ref {id}</span> : null;
}

/** "Couldn't save “Keep waiting”. Nothing was changed." + Ref + Retry (FR-045). */
export function FailureBanner({ failure, online }: { failure: StepFailure; online: boolean }): React.JSX.Element {
  return (
    <div role="alert" className={bannerClass}>
      <span>{failure.message ?? `Couldn't save “${failure.label}”. Nothing was changed.`}</span>
      <Ref id={failure.referenceId} />
      <button type="button" disabled={!online} className="min-h-11 rounded-control px-3 font-semibold hover:bg-quiet-pressed disabled:opacity-60" onClick={failure.retry}>
        Retry
      </button>
    </div>
  );
}

/** The ten counts of a run, zero ones dimmed: two columns at 390 px, four from `md` up. */
export function CountsGrid({ counts, label }: { counts: SessionCounts; label: string }): React.JSX.Element {
  return (
    <ul aria-label={label} className="m-0 grid list-none grid-cols-2 gap-2 p-0 md:grid-cols-4">
      {SUMMARY_COUNTS.map(({ key, label: name }) => (
        <li key={key} className={`rounded-card bg-card px-3 py-2.5 text-co-meta ${counts[key] === 0 ? "text-ink-done" : "text-ink-muted"}`}>
          {name}
          <b className={`block text-xl font-semibold ${counts[key] === 0 ? "text-ink-done" : "text-ink"}`}>{counts[key]}</b>
        </li>
      ))}
    </ul>
  );
}

/** A step's content once all its queries have answered; a placeholder or the load failure before. */
export function QueueGate({ queries, children }: { queries: Array<UseQueryResult<unknown>>; children: () => ReactNode }): React.JSX.Element {
  const run = useReviewRun();
  const { setQueueBlocked } = run;
  const failed = queries.find((query) => query.isError && !query.isFetching);
  // Whatever the gate does not show the content for holds the shell's Next (D-03).
  const blocked = failed !== undefined || queries.some((query) => query.data === undefined);
  useLayoutEffect(() => {
    setQueueBlocked(blocked);
    return () => setQueueBlocked(false);
  }, [blocked, setQueueBlocked]);
  if (failed) {
    return (
      <div role="alert" className={bannerClass}>
        <span>We couldn&apos;t load this step. Your progress is safe.</span>
        <Ref id={describeReviewError(failed.error).referenceId} />
        <button type="button" className="min-h-11 rounded-control px-3 font-semibold hover:bg-quiet-pressed" onClick={() => queries.filter((query) => query.isError).forEach((query) => void query.refetch())}>
          Retry
        </button>
        <button type="button" className="min-h-11 rounded-control px-3 font-semibold hover:bg-quiet-pressed" onClick={run.skipStep}>
          Skip step
        </button>
      </div>
    );
  }
  if (queries.some((query) => query.data === undefined)) {
    return (
      <div role="status" aria-label="Loading this step" aria-busy="true" className="flex flex-col gap-3">
        <div className="h-5 w-3/5 rounded-card bg-quiet-pressed" />
        <div className="h-3 w-full rounded-card bg-quiet-pressed" />
        <div className="h-3 w-4/5 rounded-card bg-quiet-pressed" />
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
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-ground/80 p-5 backdrop-blur-xs">
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        onKeyDown={onKeyDown}
        className="w-full max-w-[380px] rounded-card bg-card p-4 shadow-floating"
      >
        <h2 id={titleId} className="m-0 text-co-meta font-semibold text-ink">{title}</h2>
        <p id={bodyId} className="m-0 mt-1 text-co-meta text-ink-muted">{body}</p>
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
