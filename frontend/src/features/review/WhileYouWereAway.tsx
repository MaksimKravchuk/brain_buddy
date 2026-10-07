/**
 * "While you were away" at web open (FR-015, design D-01 rows, M-09 content).
 *
 * Lists the auto-parked tasks the person has not seen, each with a one-click
 * "Return to Next" (the existing `move → next` transition, which starts a new
 * formulation) and "Return all". "Continue" marks the parks seen once every
 * task has loaded (a task that is gone counts; one that could not be read
 * stays unseen); Esc and
 * Close leave them unseen, so the dialog comes back the next day (the caller
 * applies `wywaPresentation`). Per-row returning, failure with Ref and Retry,
 * changed-elsewhere and archived-project partial failures, and offline.
 */
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import type { AuthUser } from "../../api/auth";
import { ApiError, apiClient } from "../../api/client";
import { describeReviewError, newIdempotencyKey, type UnseenPark } from "../../api/review";
import {
  applyReviewTask,
  beginReviewContinuation,
  refreshAfterReviewWrite,
  useAcknowledgeParks,
  useOnlineStatus,
  type ReviewContinuation
} from "../../api/reviewHooks";
import { getTaskCacheScope, taskKeys, useProjects } from "../../api/taskHooks";
import type { ProjectResponse, TaskResponse, TaskState } from "../../api/taskTypes";
import { useAuthStore } from "../../stores/authStore";
import { formatReviewDate } from "./formulation";

type RowStatus =
  | { kind: "returning" }
  | { kind: "returned" }
  | { kind: "failed"; referenceId: string | undefined }
  | { kind: "stale"; current: TaskResponse | null };

const LIST_NAMES: Readonly<Record<TaskState, string>> = {
  inbox: "Inbox",
  next: "Next actions",
  waiting: "Waiting for",
  someday: "Someday / maybe",
  completed: "Completed",
  cancelled: "Cancelled"
};

const focusableSelector = 'button:not([disabled]), [tabindex]:not([tabindex="-1"])';

function intro(count: number): string {
  return count === 1
    ? "This task stayed undecided, so it moved to Someday / maybe to keep Next honest. Nothing was deleted. Bring it back if it still matters."
    : `These ${count} tasks stayed undecided, so they moved to Someday / maybe to keep Next honest. Nothing was deleted. Bring back anything that still matters.`;
}

export function WhileYouWereAway({
  parks,
  onDone
}: {
  parks: UnseenPark[];
  /** Closed: `true` after "Continue" was saved, `false` after Esc or Close. */
  onDone: (acknowledged: boolean) => void;
}): React.JSX.Element {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();
  const accountId = useAuthStore((state) => (state.user as AuthUser).id);
  // Returning waits for the projects: until they are known, a task in an
  // archived project would look project-less and be offered back.
  const projectsQuery = useProjects();
  const projects = projectsQuery.data ?? [];
  const projectsKnown = projectsQuery.data !== undefined;
  const acknowledgeMutation = useAcknowledgeParks();
  const [rows, setRows] = useState<Record<string, RowStatus>>({});
  const [summary, setSummary] = useState<string | null>(null);
  // "Return all" is in flight, including the moments between two rows.
  const [returningAll, setReturningAll] = useState(false);
  const [continueFailure, setContinueFailure] = useState<{ referenceId: string | undefined } | null>(null);
  const acknowledgeAttempt = useRef<{ body: string; key: string } | null>(null);
  // A failed return keeps its key, so Retry is a safe replay.
  const returnKeys = useRef(new Map<string, string>());

  const results = useQueries({
    queries: parks.map((park) => ({
      queryKey: taskKeys.detail(park.task_id, getTaskCacheScope(accountId)),
      queryFn: ({ signal }: { signal: AbortSignal }) => apiClient.getTask(park.task_id, signal),
      retry: false
    }))
  });
  const loaded = parks.flatMap((park, index) => {
    const task = results[index].data;
    return task ? [{ park, task }] : [];
  });
  const tasks = loaded.map(({ task }) => task);
  // "Continue" waits until every park's task has answered. It then marks seen
  // the parks it showed and those whose task is gone (404); a park whose task
  // could not be read for another reason stays unseen and comes back next time.
  const resolving = results.some((result) => result.isPending);
  const confirmed = parks.filter((_park, index) => {
    const result = results[index];
    return result.data !== undefined || (result.error instanceof ApiError && result.error.status === 404);
  });

  useLayoutEffect(() => {
    headingRef.current?.focus();
  }, []);

  const projectOf = (task: TaskResponse): ProjectResponse | undefined => projects.find((project) => project.id === task.project_id);
  const archived = (task: TaskResponse) => projectOf(task)?.state === "archived";
  const setRow = (taskId: string, status: RowStatus) => setRows((current) => ({ ...current, [taskId]: status }));
  const parkOf = new Map(loaded.map(({ park, task }) => [task.id, park]));
  /**
   * The task is no longer this park's: it left Someday (another device, or
   * returned before) or was parked again later. It is shown where it is now
   * and never offered Return. A row returned or refused here keeps its status.
   */
  const movedElsewhere = (task: TaskResponse): boolean => {
    const status = rows[task.id]?.kind;
    if (status === "returned" || status === "stale") {
      return false;
    }
    return task.state !== "someday" || task.parked?.formulation_id !== parkOf.get(task.id)?.formulation_id;
  };

  // The account that pressed Return (begun before the first await): an answer
  // after the session switched account changes no row and writes no cache.
  const returnTask = async (task: TaskResponse, run: ReviewContinuation = beginReviewContinuation()): Promise<boolean> => {
    if (!projectsKnown) {
      return false;
    }
    const key = returnKeys.current.get(task.id) ?? newIdempotencyKey();
    returnKeys.current.set(task.id, key);
    setRow(task.id, { kind: "returning" });
    try {
      const returned = await apiClient.transitionTask(task.id, { action: "move", to_state: "next", expected_revision: task.revision }, key);
      if (!run.stillCurrent()) {
        return false;
      }
      returnKeys.current.delete(task.id);
      applyReviewTask(queryClient, returned, run.scope);
      setRow(task.id, { kind: "returned" });
      return true;
    } catch (error) {
      if (!run.stillCurrent()) {
        return false;
      }
      const { kind, referenceId } = describeReviewError(error);
      if (kind === "stale") {
        returnKeys.current.delete(task.id);
        const current = await apiClient.getTask(task.id).catch(() => null);
        if (!run.stillCurrent()) {
          return false;
        }
        // The caches must not keep the version that lost the race.
        if (current) {
          applyReviewTask(queryClient, current, run.scope);
        } else {
          refreshAfterReviewWrite(queryClient, run.scope);
        }
        setRow(task.id, { kind: "stale", current });
      } else {
        setRow(task.id, { kind: "failed", referenceId });
      }
      return false;
    }
  };

  const returnable = (task: TaskResponse) => {
    const status = rows[task.id]?.kind;
    return !movedElsewhere(task) && !archived(task) && (status === undefined || status === "failed");
  };
  // What "Return all" would cover once the projects are known; nothing goes back before.
  const candidates = tasks.filter(returnable);
  const eligible = projectsKnown ? candidates : [];
  const anyReturned = tasks.some((task) => rows[task.id]?.kind === "returned");
  // Continue waits for every return to settle, so it never acknowledges a park mid-return.
  const returning = returningAll || Object.values(rows).some((status) => status.kind === "returning");

  const returnAll = async () => {
    const run = beginReviewContinuation();
    const alreadyBack = tasks.filter((task) => rows[task.id]?.kind === "returned").length;
    // The tasks this dialog can still speak for: not those already elsewhere.
    const inPlay = tasks.filter((task) => !movedElsewhere(task));
    let returnedNow = 0;
    setReturningAll(true);
    for (const task of eligible) {
      if (await returnTask(task, run)) {
        returnedNow += 1;
      }
      if (!run.stillCurrent()) {
        return;
      }
    }
    setReturningAll(false);
    const held = inPlay.filter(archived);
    const backInNext = alreadyBack + returnedNow;
    if (held.length > 0) {
      const back = `${backInNext} ${backInNext === 1 ? "task is" : "tasks are"} back in Next.`;
      const reasons = held.map((task) => ` “${task.title}” stayed in Someday because its project “${(projectOf(task) as ProjectResponse).name}” is archived. Restore the project first to bring it back.`);
      setSummary(`${back}${reasons.join("")}`);
    } else if (backInNext === inPlay.length) {
      setSummary(`All ${inPlay.length} are back in Next with a fresh start.`);
    }
  };

  const confirmSeen = () => {
    setContinueFailure(null);
    if (confirmed.length === 0) {
      onDone(false);
      return;
    }
    const body = { items: confirmed.map((park) => ({ task_id: park.task_id, formulation_id: park.formulation_id })) };
    // Retry replays the same body under the same key; a different set of parks gets a new key.
    const sent = JSON.stringify(body);
    if (acknowledgeAttempt.current?.body !== sent) {
      acknowledgeAttempt.current = { body: sent, key: newIdempotencyKey() };
    }
    const run = beginReviewContinuation();
    acknowledgeMutation.mutate(
      { body, idempotencyKey: acknowledgeAttempt.current.key },
      {
        onSuccess: () => {
          if (run.stillCurrent()) onDone(true);
        },
        onError: (error) => {
          if (run.stillCurrent()) setContinueFailure({ referenceId: describeReviewError(error).referenceId });
        }
      }
    );
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onDone(false);
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    const focusable = Array.from((sectionRef.current as HTMLElement).querySelectorAll<HTMLElement>(focusableSelector));
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement as HTMLElement;
    if (event.shiftKey && (active === first || !focusable.includes(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const returnAllLabel = candidates.length === 2
    ? "Return both to Next"
    : anyReturned ? `Return the other ${candidates.length} to Next` : `Return all ${candidates.length} to Next`;

  return (
    <div className="fixed inset-0 z-[150] flex items-stretch justify-center bg-slate-50/80 backdrop-blur-xs sm:items-center sm:p-6">
      <section
        ref={sectionRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        onKeyDown={onKeyDown}
        className="relative flex h-full w-full flex-col overflow-y-auto bg-white shadow-floating sm:h-auto sm:max-h-[calc(100vh-48px)] sm:w-[560px] sm:rounded-[20px] sm:border sm:border-slate-200"
      >
        <header className="flex items-start gap-3 px-5 pb-2 pt-5">
          <h2 id={headingId} ref={headingRef} tabIndex={-1} className="m-0 flex-1 text-[20px] font-semibold leading-[1.3] text-slate-900 outline-hidden">
            While you were away
          </h2>
          <button
            type="button"
            aria-label="Close"
            className="-mr-1.5 -mt-1 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-surface-sunken hover:text-slate-900"
            onClick={() => onDone(false)}
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>
        <div className="flex flex-col gap-3 px-5 pb-5 text-sm text-slate-700">
          <p className="m-0 leading-relaxed">{intro(parks.length)}</p>
          {!online ? <p role="status" className="m-0 rounded-lg bg-slate-50 px-3 py-2">You&apos;re offline. Returning tasks needs a connection.</p> : null}
          {summary ? <p role="status" className="m-0 rounded-lg bg-slate-50 px-3 py-2">{summary}</p> : null}
          {!projectsKnown && projectsQuery.isError ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
              <span>We couldn&apos;t load your projects, so tasks can&apos;t be returned yet.</span>
              {describeReviewError(projectsQuery.error).referenceId ? (
                <span className="text-xs">Ref {describeReviewError(projectsQuery.error).referenceId}</span>
              ) : null}
              <button type="button" className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100" onClick={() => void projectsQuery.refetch()}>
                Retry
              </button>
            </div>
          ) : null}
          <ul className="m-0 flex list-none flex-col divide-y divide-slate-100 rounded-xl border border-slate-200 p-0">
            {loaded.map(({ park, task }) => {
              const status = rows[task.id];
              const project = projectOf(task);
              const titleId = `${headingId}-${task.id}`;
              const elsewhere = movedElsewhere(task);
              return (
                <li key={task.id} aria-labelledby={titleId} className="flex flex-col gap-1 px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <p id={titleId} className="m-0 break-words font-medium text-slate-900">{task.title}</p>
                      {status?.kind === "returned" ? (
                        <p className="m-0 text-xs text-slate-600">Back in Next with a fresh start</p>
                      ) : status?.kind === "stale" ? (
                        <p className="m-0 text-xs text-slate-600">{`Now in ${LIST_NAMES[status.current?.state ?? "someday"]}`}</p>
                      ) : elsewhere ? (
                        <p className="m-0 text-xs text-slate-600">{`Now in ${LIST_NAMES[task.state]}`}</p>
                      ) : (
                        <p className="m-0 text-xs text-slate-500">
                          {projectsKnown
                            ? `Parked ${formatReviewDate(park.parked_at)} · ${project ? (project.state === "archived" ? `${project.name} (archived)` : project.name) : "no project"}`
                            : `Parked ${formatReviewDate(park.parked_at)}`}
                        </p>
                      )}
                    </div>
                    {status?.kind === "returned" ? (
                      <span className="text-xs font-semibold text-slate-600">Returned</span>
                    ) : status?.kind === "stale" || elsewhere ? null : archived(task) ? (
                      <button
                        type="button"
                        aria-disabled="true"
                        aria-label={`Return unavailable: project ${(project as ProjectResponse).name} is archived`}
                        className="min-h-11 rounded-lg border border-slate-200 px-3 text-xs font-medium text-slate-500"
                      >
                        Project archived
                      </button>
                    ) : (
                      <button
                        type="button"
                        aria-label={`Return ${task.title} to Next`}
                        disabled={!online || !projectsKnown || status?.kind === "returning"}
                        className="min-h-11 rounded-lg border border-slate-200 bg-white px-3 text-[13px] font-medium text-slate-800 hover:border-slate-300 disabled:opacity-60"
                        onClick={() => void returnTask(task)}
                      >
                        {status?.kind === "returning" ? "Returning…" : "Return to Next"}
                      </button>
                    )}
                  </div>
                  {status?.kind === "stale" ? (
                    <p className="m-0 text-xs text-slate-600">{`“${task.title}” changed on another device, so it was left as it is there.`}</p>
                  ) : null}
                  {status?.kind === "failed" ? (
                    <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-900">
                      <span>{`Couldn't return “${task.title}” to Next. It's still in Someday / maybe.`}</span>
                      {status.referenceId ? <span>Ref {status.referenceId}</span> : null}
                      <button type="button" className="min-h-11 rounded-lg px-2 font-semibold hover:bg-amber-100" onClick={() => void returnTask(task)}>
                        Retry
                      </button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
          {continueFailure ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
              <span>Couldn&apos;t save that you&apos;ve seen these. Try again.</span>
              {continueFailure.referenceId ? <span className="text-xs">Ref {continueFailure.referenceId}</span> : null}
              <button type="button" className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100" onClick={confirmSeen}>
                Retry
              </button>
            </div>
          ) : null}
          <div className="mt-1 flex flex-wrap justify-end gap-2">
            {candidates.length >= 2 ? (
              <button
                type="button"
                disabled={!online || !projectsKnown || returningAll}
                className="min-h-11 rounded-lg border border-slate-200 px-4 font-medium text-slate-800 hover:border-slate-300 disabled:opacity-60"
                onClick={() => void returnAll()}
              >
                {returnAllLabel}
              </button>
            ) : null}
            <button
              type="button"
              disabled={resolving || returning || acknowledgeMutation.isPending}
              className="min-h-11 rounded-lg bg-sky-700 px-5 font-semibold text-white hover:bg-sky-800 disabled:opacity-60"
              onClick={confirmSeen}
            >
              Continue
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
