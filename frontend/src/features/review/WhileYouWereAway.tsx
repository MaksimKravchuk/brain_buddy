/**
 * "While you were away" at web open (FR-015, design D-01 rows, M-09 content).
 *
 * Lists the auto-parked tasks the person has not seen, each with a one-click
 * "Return to Next" (the existing `move → next` transition, which starts a new
 * formulation) and "Return all". "Continue" marks every park seen; Esc and
 * Close leave them unseen, so the dialog comes back the next day (the caller
 * applies `wywaPresentation`). Per-row returning, failure with Ref and Retry,
 * changed-elsewhere and archived-project partial failures, and offline.
 */
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import type { AuthUser } from "../../api/auth";
import { apiClient } from "../../api/client";
import { describeReviewError, newIdempotencyKey, type UnseenPark } from "../../api/review";
import { applyReviewTask, useAcknowledgeParks, useOnlineStatus } from "../../api/reviewHooks";
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
  const projects = useProjects().data ?? [];
  const acknowledgeMutation = useAcknowledgeParks();
  const [rows, setRows] = useState<Record<string, RowStatus>>({});
  const [summary, setSummary] = useState<string | null>(null);
  const [continueFailure, setContinueFailure] = useState<{ referenceId: string | undefined } | null>(null);
  const [acknowledgeKey] = useState(newIdempotencyKey);
  // A failed return keeps its key, so Retry is a safe replay.
  const returnKeys = useRef(new Map<string, string>());

  const results = useQueries({
    queries: parks.map((park) => ({
      queryKey: taskKeys.detail(park.task_id, getTaskCacheScope(accountId)),
      queryFn: ({ signal }: { signal: AbortSignal }) => apiClient.getTask(park.task_id, signal),
      retry: false
    }))
  });
  // Parks whose task cannot be read are not listed, but "Continue" still marks them seen.
  const loaded = parks.flatMap((park, index) => {
    const task = results[index].data;
    return task ? [{ park, task }] : [];
  });
  const tasks = loaded.map(({ task }) => task);

  useLayoutEffect(() => {
    headingRef.current?.focus();
  }, []);

  const projectOf = (task: TaskResponse): ProjectResponse | undefined => projects.find((project) => project.id === task.project_id);
  const archived = (task: TaskResponse) => projectOf(task)?.state === "archived";
  const setRow = (taskId: string, status: RowStatus) => setRows((current) => ({ ...current, [taskId]: status }));

  const returnTask = async (task: TaskResponse): Promise<boolean> => {
    const key = returnKeys.current.get(task.id) ?? newIdempotencyKey();
    returnKeys.current.set(task.id, key);
    setRow(task.id, { kind: "returning" });
    try {
      const returned = await apiClient.transitionTask(task.id, { action: "move", to_state: "next", expected_revision: task.revision }, key);
      returnKeys.current.delete(task.id);
      applyReviewTask(queryClient, returned);
      setRow(task.id, { kind: "returned" });
      return true;
    } catch (error) {
      const { kind, referenceId } = describeReviewError(error);
      if (kind === "stale") {
        returnKeys.current.delete(task.id);
        setRow(task.id, { kind: "stale", current: await apiClient.getTask(task.id).catch(() => null) });
      } else {
        setRow(task.id, { kind: "failed", referenceId });
      }
      return false;
    }
  };

  const returnable = (task: TaskResponse) => {
    const status = rows[task.id]?.kind;
    return !archived(task) && (status === undefined || status === "failed");
  };
  const eligible = tasks.filter(returnable);
  const anyReturned = tasks.some((task) => rows[task.id]?.kind === "returned");

  const returnAll = async () => {
    const alreadyBack = tasks.filter((task) => rows[task.id]?.kind === "returned").length;
    let returnedNow = 0;
    for (const task of eligible) {
      if (await returnTask(task)) {
        returnedNow += 1;
      }
    }
    const held = tasks.filter(archived);
    if (held.length > 0) {
      const back = `${returnedNow} ${returnedNow === 1 ? "task is" : "tasks are"} back in Next.`;
      const reasons = held.map((task) => ` “${task.title}” stayed in Someday because its project “${(projectOf(task) as ProjectResponse).name}” is archived. Restore the project first to bring it back.`);
      setSummary(`${back}${reasons.join("")}`);
    } else if (alreadyBack + returnedNow === tasks.length) {
      setSummary(`All ${tasks.length} are back in Next with a fresh start.`);
    }
  };

  const confirmSeen = () => {
    setContinueFailure(null);
    acknowledgeMutation.mutate(
      { body: { items: parks.map((park) => ({ task_id: park.task_id, formulation_id: park.formulation_id })) }, idempotencyKey: acknowledgeKey },
      {
        onSuccess: () => onDone(true),
        onError: (error) => setContinueFailure({ referenceId: describeReviewError(error).referenceId })
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

  const returnAllLabel = eligible.length === 2
    ? "Return both to Next"
    : anyReturned ? `Return the other ${eligible.length} to Next` : `Return all ${eligible.length} to Next`;

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
          <ul className="m-0 flex list-none flex-col divide-y divide-slate-100 rounded-xl border border-slate-200 p-0">
            {loaded.map(({ park, task }) => {
              const status = rows[task.id];
              const project = projectOf(task);
              const titleId = `${headingId}-${task.id}`;
              return (
                <li key={task.id} aria-labelledby={titleId} className="flex flex-col gap-1 px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <p id={titleId} className="m-0 break-words font-medium text-slate-900">{task.title}</p>
                      {status?.kind === "returned" ? (
                        <p className="m-0 text-xs text-slate-600">Back in Next with a fresh start</p>
                      ) : status?.kind === "stale" ? (
                        <p className="m-0 text-xs text-slate-600">{`Now in ${LIST_NAMES[status.current?.state ?? "someday"]}`}</p>
                      ) : (
                        <p className="m-0 text-xs text-slate-500">
                          {`Parked ${formatReviewDate(park.parked_at)} · ${project ? (project.state === "archived" ? `${project.name} (archived)` : project.name) : "no project"}`}
                        </p>
                      )}
                    </div>
                    {status?.kind === "returned" ? (
                      <span className="text-xs font-semibold text-slate-600">Returned</span>
                    ) : status?.kind === "stale" ? null : archived(task) ? (
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
                        disabled={!online || status?.kind === "returning"}
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
                      <span>Ref {status.referenceId}</span>
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
              <span className="text-xs">Ref {continueFailure.referenceId}</span>
              <button type="button" className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100" onClick={confirmSeen}>
                Retry
              </button>
            </div>
          ) : null}
          <div className="mt-1 flex flex-wrap justify-end gap-2">
            {eligible.length >= 2 ? (
              <button
                type="button"
                disabled={!online}
                className="min-h-11 rounded-lg border border-slate-200 px-4 font-medium text-slate-800 hover:border-slate-300 disabled:opacity-60"
                onClick={() => void returnAll()}
              >
                {returnAllLabel}
              </button>
            ) : null}
            <button
              type="button"
              disabled={acknowledgeMutation.isPending}
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
