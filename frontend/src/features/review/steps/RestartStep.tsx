/**
 * M-10 Restart mode on the web (FR-017, D-03): after 21 days without a counted
 * review, a neutral welcome and one reversible release of the Next actions
 * older than four weeks. The Undo lasts until the person moves on, also across
 * a tab reload. Someone set up but never reviewed gets the same offer with no
 * wording that implies they were away.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { apiClient } from "../../../api/client";
import { describeReviewError } from "../../../api/review";
import type { ReviewState } from "../../../api/review";
import { getReviewCacheScope } from "../../../api/reviewHooks";
import type { TaskResponse } from "../../../api/taskTypes";
import type { AuthUser } from "../../../api/auth";
import { useAuthStore } from "../../../stores/authStore";
import { classifyFromInstants, daysInNext, formulationInstants } from "../formulation";
import { pick, plural } from "../plural";
import { buttonClass, primaryButtonClass, FailureBanner, Ref } from "./stepParts";
import { useBulkRelease } from "./useBulkRelease";

const FOUR_WEEKS_MS = 28 * 86_400_000;

async function listAllNext(signal: AbortSignal): Promise<TaskResponse[]> {
  const all: TaskResponse[] = [];
  let cursor: string | null = null;
  do {
    const page: Awaited<ReturnType<typeof apiClient.listTasks>> = await apiClient.listTasks(cursor ? { state: "next", cursor } : { state: "next" }, signal);
    all.push(...page.items);
    cursor = page.has_more ? page.next_cursor : null;
  } while (cursor);
  return all;
}

/** formulation-clock §5: not paused by a due date, and started at least 28 days ago. */
function restartEligible(task: TaskResponse, now: Date): boolean {
  const formulation = task.formulation;
  return Boolean(formulation) && classifyFromInstants(now, formulationInstants(formulation)) !== "paused" && now.getTime() - Date.parse((formulation as NonNullable<typeof formulation>).started_at) >= FOUR_WEEKS_MS;
}

export function RestartStep({ state, onContinue }: { state: ReviewState; onContinue: () => void }): React.JSX.Element {
  const accountId = useAuthStore((store) => (store.user as AuthUser).id);
  const bulk = useBulkRelease("restart", null);
  const next = useQuery({
    queryKey: ["review-restart", getReviewCacheScope(accountId)],
    queryFn: ({ signal }) => listAllNext(signal),
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false
  });
  const [expanded, setExpanded] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const now = new Date();
  const neverReviewed = state.last_counted_review_at === null;

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const start = () => {
    bulk.forget();
    onContinue();
  };

  // A release or its Undo still on its way holds every way on, so its answer, failure and Undo stay on screen.
  const settling = bulk.releaseAction.pending !== null || bulk.undoAction.pending !== null;
  const startButton = (
    <button type="button" disabled={settling} className={primaryButtonClass} onClick={start}>
      Start the review
    </button>
  );
  const eligible = (next.data ?? []).filter((task) => restartEligible(task, now));
  const released = bulk.released;

  return (
    <>
      <h1 ref={headingRef} tabIndex={-1} className="m-0 text-2xl font-semibold text-slate-900 outline-hidden">
        {neverReviewed ? "Your first review" : "Welcome back"}
      </h1>
      <p className="m-0 text-sm text-slate-600">
        {neverReviewed
          ? "Let's make Next fit the week ahead."
          : `Your last review was ${daysInNext(state.last_counted_review_at as string, now)} days ago. Gaps happen. Let's make Next fit the week ahead.`}
      </p>
      {bulk.undone ? (
        <>
          <p role="status" className="m-0 text-sm text-slate-700">
            {bulk.undone.skipped.length === 0
              ? `Undone. All ${bulk.undone.restored.length} are back in Next as they were.`
              : `${bulk.undone.restored.length} are back in Next. ${bulk.undone.skipped.length} changed on another device and stayed in Someday / maybe.`}
          </p>
          <div>{startButton}</div>
        </>
      ) : released ? (
        <>
          <p role="status" className="m-0 text-sm text-slate-700">
            {released.resumed
              ? `${plural(released.released, "task was", "tasks were")} released to Someday / maybe.`
              : `${plural(released.released, "task")} released to Someday / maybe. Next now holds ${(next.data ?? []).length - released.released} tasks.`}
          </p>
          {released.skipped > 0 ? (
            <p className="m-0 text-sm text-slate-600">{`${plural(released.skipped, "task changed", "tasks changed")} on another device in the meantime, so ${pick(released.skipped, "it", "they")} stayed in Next.`}</p>
          ) : null}
          {bulk.undoAction.failure ? <FailureBanner failure={bulk.undoAction.failure} online={bulk.undoAction.online} /> : null}
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={bulk.undoAction.disabled} className={buttonClass} onClick={() => bulk.undo((count) => `Couldn't undo the release. The ${plural(count, "task is", "tasks are")} still in Someday / maybe.`)}>
              {bulk.undoAction.pending === "undo" ? "Undoing…" : `Undo the ${released.released}`}
            </button>
            {startButton}
          </div>
        </>
      ) : next.isError && !next.isFetching ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <span>We couldn&apos;t check your Next actions.</span>
          <Ref id={describeReviewError(next.error).referenceId} />
          <button type="button" className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100" onClick={() => void next.refetch()}>
            Retry
          </button>
          <button type="button" className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100" onClick={start}>
            Start the review
          </button>
        </div>
      ) : next.data === undefined ? (
        <p role="status" aria-busy="true" className="m-0 text-sm text-slate-500">Checking your Next actions…</p>
      ) : eligible.length === 0 ? (
        <>
          <p className="m-0 text-sm text-slate-600">Nothing in Next is older than 4 weeks, so let&apos;s go straight in.</p>
          <div>{startButton}</div>
        </>
      ) : (
        <div className="flex flex-col gap-3 rounded-[14px] border border-slate-200 bg-white p-4 shadow-soft">
          <p className="m-0 text-base font-semibold text-slate-900">{`${plural(eligible.length, "next action is", "next actions are")} older than 4 weeks`}</p>
          <p className="m-0 text-sm text-slate-600">Release them to Someday / maybe in one go? They keep their project, Tags and notes, and you can undo this right away.</p>
          {bulk.releaseAction.failure ? <FailureBanner failure={bulk.releaseAction.failure} online={bulk.releaseAction.online} /> : null}
          {expanded ? (
            <ul aria-label="Next actions older than 4 weeks" className="m-0 flex list-none flex-col divide-y divide-slate-100 p-0 text-sm text-slate-800">
              {eligible.map((task) => (
                <li key={task.id} className="flex justify-between gap-3 py-2">
                  <span>{task.title}</span>
                  <span className="text-xs text-slate-500">{`${daysInNext((task.formulation as NonNullable<TaskResponse["formulation"]>).started_at, now)} days`}</span>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={bulk.releaseAction.disabled}
              className={primaryButtonClass}
              onClick={() =>
                void bulk.release(
                  eligible.map((task) => ({ task_id: task.id, expected_revision: task.revision })),
                  "Couldn't release these tasks. Nothing was moved."
                )
              }
            >
              {bulk.releaseAction.pending === "release" ? "Releasing…" : `Release ${eligible.length} to Someday`}
            </button>
            <button type="button" disabled={settling} className={buttonClass} onClick={onContinue}>Keep them</button>
            <button type="button" className={buttonClass} onClick={() => setExpanded(!expanded)}>{expanded ? "Hide the list" : "See which ones"}</button>
          </div>
        </div>
      )}
    </>
  );
}
