/**
 * M-15 Inbox to zero on the web (D-03 "Inbox step"): one item at a time with
 * the web choices, an Undo after each (FR-048) that also takes the item off the
 * run's count, and for a long Inbox the three FR-030 choices, the last of which
 * releases the remainder to Someday with an Undo until the step is left.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { apiClient } from "../../../api/client";
import { describeReviewError, newIdempotencyKey, newProgressAttempt, withReference } from "../../../api/review";
import type { ReviewQueue } from "../../../api/review";
import { applyReviewTask, refreshAfterReviewWrite, settleForAccount, useReviewQueue } from "../../../api/reviewHooks";
import type { OpenTaskState, TaskResponse, TaskTransitionRequest } from "../../../api/taskTypes";
import { useShellToast } from "../../../components/shell/shellToast";
import { plural } from "../plural";
import { buttonClass, fieldClass, FailureBanner, primaryButtonClass, QueueGate } from "./stepParts";
import { useReviewRun } from "./reviewRun";
import { useBulkRelease } from "./useBulkRelease";
import { useStepAction } from "./useStepAction";

const LONG_INBOX = 15;
const BATCH = 10;

interface Choice {
  id: string;
  label: string;
  sub?: string;
  /** Moves the item; `needsWaitingFor` asks who or what first. */
  request: (task: TaskResponse, waitingFor?: string) => TaskTransitionRequest;
  needsWaitingFor?: boolean;
  toast: string;
  undoName: string;
}

const move = (to: OpenTaskState) => (task: TaskResponse, waitingFor?: string): TaskTransitionRequest => ({
  action: "move",
  to_state: to,
  ...(waitingFor ? { waiting_for: waitingFor } : {}),
  expected_revision: task.revision
});

const CHOICES: Choice[] = [
  { id: "next", label: "Next actions", request: move("next"), toast: "moved to Next actions", undoName: "Moved to Next actions" },
  { id: "waiting", label: "Waiting for…", request: move("waiting"), needsWaitingFor: true, toast: "moved to Waiting for", undoName: "Moved to Waiting for" },
  { id: "someday", label: "Someday / maybe", request: move("someday"), toast: "moved to Someday / maybe", undoName: "Moved to Someday / maybe" },
  { id: "done", label: "Done", sub: "Under 2 minutes? Do it now.", request: (task) => ({ action: "complete", expected_revision: task.revision }), toast: "done", undoName: "Marked done" },
  { id: "cancel", label: "Cancel", request: (task) => ({ action: "cancel", expected_revision: task.revision }), toast: "cancelled", undoName: "Cancelled" }
];

type Plan = { limit: number; release: boolean };
type Form = { kind: "waiting"; choice: Choice; text: string } | { kind: "title"; text: string };

export function InboxStep(): React.JSX.Element {
  const run = useReviewRun();
  const notify = useShellToast();
  const queryClient = useQueryClient();
  const queue = useReviewQueue("inbox", run.session.id);
  const action = useStepAction();
  const bulk = useBulkRelease("inbox_remainder", run.session.id, run.session.steps.inbox === "pending");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [processed, setProcessed] = useState<readonly string[]>([]);
  const [stale, setStale] = useState<readonly string[]>([]);
  const [latest, setLatest] = useState<Readonly<Record<string, TaskResponse>>>({});
  const [form, setForm] = useState<Form | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const fieldRef = useRef<HTMLInputElement>(null);
  const focusHeading = useRef(false);

  const items = ((queue.data as ReviewQueue | undefined)?.items ?? []).map((item) => latest[item.id] ?? item);
  const handled = new Set([...processed, ...stale]);
  const limit = plan?.limit ?? items.length;
  const current = handled.size < limit ? items.find((item) => !handled.has(item.id)) : undefined;

  useEffect(() => {
    if (focusHeading.current) {
      focusHeading.current = false;
      headingRef.current?.focus();
    }
  }, [current?.id]);

  useEffect(() => {
    if (form) {
      fieldRef.current?.focus();
    }
  }, [form]);

  const closeForm = () => {
    setForm(null);
    run.setUnsaved(false);
  };

  const choose = (choice: Choice, task: TaskResponse, waitingFor?: string) => {
    const key = newIdempotencyKey();
    const count = newProgressAttempt(run.session.id, { inbox_processed_delta: 1 });
    const willFinish = handled.size + 1 >= limit;
    const remaining = items.filter((item) => !handled.has(item.id) && item.id !== task.id);
    setNotice(null);
    void action.run(choice.id, choice.label, async (continuation) => {
      let moved: TaskResponse;
      try {
        moved = await apiClient.transitionTask(task.id, choice.request(task, waitingFor), key);
      } catch (error) {
        if (describeReviewError(error).kind !== "stale") {
          throw error;
        }
        refreshAfterReviewWrite(queryClient, continuation.scope);
        focusHeading.current = true;
        setStale((ids) => [...ids, task.id]);
        closeForm();
        setNotice(`“${task.title}” was changed on another device, so it stayed in Inbox.`);
        return;
      }
      // Only the person who pressed it may have the count sent for them.
      if (!continuation.stillCurrent()) {
        return;
      }
      await run.progress(count);
      applyReviewTask(queryClient, moved, continuation.scope);
      focusHeading.current = true;
      setProcessed((ids) => [...ids, task.id]);
      closeForm();
      notify(`“${task.title}” ${choice.toast}`, {
        action: { label: "Undo", accessibleLabel: `Undo: ${choice.undoName} ${task.title}`, onAction: () => void undoChoice(task, moved) }
      });
      // Its own pending and failure states; a Retry of this choice reaches it too.
      if (willFinish && plan?.release && remaining.length > 0) {
        void bulk.release(
          remaining.map((item) => ({ task_id: item.id, expected_revision: item.revision })),
          "Couldn't release the rest of your Inbox. Nothing was moved."
        );
      }
    });
  };

  /** Back to the Inbox, and one off the run's count (FR-048). */
  const undoChoice = async (task: TaskResponse, moved: TaskResponse) => {
    const settled = await settleForAccount(async () => {
      const back = await apiClient.transitionTask(
        task.id,
        { action: moved.state === "completed" || moved.state === "cancelled" ? "reopen" : "move", to_state: "inbox", expected_revision: moved.revision },
        newIdempotencyKey()
      );
      await run.progress(newProgressAttempt(run.session.id, { inbox_processed_delta: -1 }));
      return back;
    });
    if (settled === null) {
      return;
    }
    if (!settled.ok) {
      notify(withReference("Couldn't undo. Nothing was changed.", describeReviewError(settled.error).referenceId));
      return;
    }
    applyReviewTask(queryClient, settled.value, settled.scope);
    focusHeading.current = true;
    setLatest((tasks) => ({ ...tasks, [task.id]: settled.value }));
    setProcessed((ids) => ids.filter((id) => id !== task.id));
    notify(`“${task.title}” is back in your Inbox`);
  };

  const saveTitle = (event: FormEvent, task: TaskResponse, text: string) => {
    // A disabled submit button blocks implicit submission, so a submit always carries a savable text.
    event.preventDefault();
    const title = text.trim();
    const key = newIdempotencyKey();
    void action.run("title", "Save title", async (continuation) => {
      const updated = await apiClient.updateTask(task.id, { title, expected_revision: task.revision }, key);
      if (!continuation.stillCurrent()) {
        return;
      }
      applyReviewTask(queryClient, updated, continuation.scope);
      setLatest((tasks) => ({ ...tasks, [task.id]: updated }));
      closeForm();
    });
  };

  const submitWaiting = (event: FormEvent, task: TaskResponse, choice: Choice, text: string) => {
    event.preventDefault();
    choose(choice, task, text.trim());
  };

  const undoRelease = () => bulk.undo((count) => `Couldn't undo the release. The ${plural(count, "item is", "items are")} still in Someday / maybe.`);

  return (
    <QueueGate queries={[queue]}>
      {() => {
        const released = bulk.released;
        if (bulk.undone) {
          const { restored, skipped } = bulk.undone;
          return (
            <p role="status" className="m-0 text-sm text-slate-700">
              {skipped.length === 0
                ? `Undone. All ${restored.length} are back in your Inbox.`
                : `${restored.length} are back in your Inbox. ${skipped.length} changed on another device and stayed in Someday / maybe.`}
            </p>
          );
        }
        if (released) {
          return (
            <>
              <p role="status" className="m-0 text-sm text-slate-700">
                {released.resumed
                  ? `${plural(released.released, "item was", "items were")} released to Someday / maybe.`
                  : `${plural(processed.length, "item")} processed · ${released.released} released to Someday / maybe`}
              </p>
              {released.skipped > 0 ? <p className="m-0 text-sm text-slate-600">{`${released.skipped} changed on another device and stayed in Inbox.`}</p> : null}
              {bulk.undoAction.failure ? <FailureBanner failure={bulk.undoAction.failure} online={bulk.undoAction.online} /> : null}
              <div>
                <button type="button" disabled={bulk.undoAction.disabled} className={buttonClass} onClick={undoRelease}>
                  {bulk.undoAction.pending === "undo" ? "Undoing…" : "Undo the release"}
                </button>
              </div>
            </>
          );
        }
        if (items.length === 0) {
          return (
            <>
              <p className="m-0 text-base font-medium text-slate-900">Inbox is empty</p>
              <p className="m-0 text-sm text-slate-600">Nothing to process.</p>
            </>
          );
        }
        if (items.length > LONG_INBOX && plan === null) {
          return (
            <div role="group" aria-label="Your Inbox is long" className="flex flex-col gap-2">
              <button type="button" className={buttonClass} onClick={() => setPlan({ limit: BATCH, release: false })}>{`Process ${BATCH} now`}</button>
              <button type="button" className={buttonClass} onClick={() => setPlan({ limit: items.length, release: false })}>{`Process all ${items.length}`}</button>
              <button type="button" className={buttonClass} onClick={() => setPlan({ limit: BATCH, release: true })}>{`Process ${BATCH}, release the rest to Someday`}</button>
            </div>
          );
        }
        if (current === undefined) {
          return (
            <>
              {notice ? <p role="status" aria-label="Changed elsewhere" className="m-0 text-sm text-slate-700">{notice}</p> : null}
              <p className="m-0 text-base font-medium text-slate-900">{`${plural(processed.length, "item")} processed`}</p>
              {bulk.releaseAction.pending ? <p role="status" className="m-0 text-sm text-slate-600">Releasing…</p> : null}
              {bulk.releaseAction.failure ? <FailureBanner failure={bulk.releaseAction.failure} online={bulk.releaseAction.online} /> : null}
            </>
          );
        }
        return (
          <>
            {notice ? <p role="status" aria-label="Changed elsewhere" className="m-0 text-sm text-slate-700">{notice}</p> : null}
            <p className="m-0 text-xs text-slate-500">{`Item ${handled.size + 1} of ${limit}`}</p>
            <div className="flex flex-col gap-3 rounded-[14px] border border-slate-200 bg-white p-4 shadow-soft">
              <h2 ref={headingRef} tabIndex={-1} className="m-0 break-words text-lg font-semibold text-slate-900 outline-hidden">{current.title}</h2>
              <p className="m-0 -mt-2 text-xs text-slate-500">Is it actionable? Choose where it belongs.</p>
              {action.failure ? <FailureBanner failure={action.failure} online={action.online} /> : null}
              {form ? (
                <form className="flex flex-col gap-2" onSubmit={(event) => (form.kind === "title" ? saveTitle(event, current, form.text) : submitWaiting(event, current, form.choice, form.text))}>
                  <label className="flex flex-col gap-1 text-sm font-medium text-slate-800">
                    {form.kind === "title" ? "Title" : "Who or what are you waiting for?"}
                    <input
                      ref={fieldRef}
                      value={form.text}
                      maxLength={500}
                      readOnly={action.pending !== null}
                      className={fieldClass}
                      onChange={(event) => {
                        const text = event.currentTarget.value;
                        setForm({ ...form, text });
                        run.setUnsaved(text.trim() !== "" && text !== (form.kind === "title" ? current.title : ""));
                      }}
                    />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={action.pending !== null} className={buttonClass} onClick={closeForm}>Back</button>
                    <button type="submit" disabled={form.text.trim() === "" || action.disabled} className={`${primaryButtonClass} ml-auto`}>
                      {action.pending !== null ? "Saving…" : form.kind === "title" ? "Save title" : "Move to Waiting for"}
                    </button>
                  </div>
                </form>
              ) : (
                <div role="group" aria-label="Choices" className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                  {CHOICES.map((choice) => (
                    <button
                      key={choice.id}
                      type="button"
                      disabled={action.disabled}
                      className={`${buttonClass} flex flex-col items-start text-left`}
                      onClick={() => (choice.needsWaitingFor ? setForm({ kind: "waiting", choice, text: "" }) : choose(choice, current))}
                    >
                      {action.pending === choice.id ? "Saving…" : choice.label}
                      {choice.sub ? <span className="text-xs font-normal text-slate-500">{choice.sub}</span> : null}
                    </button>
                  ))}
                  <button type="button" disabled={action.disabled} className={buttonClass} onClick={() => setForm({ kind: "title", text: current.title })}>
                    Edit title
                  </button>
                </div>
              )}
            </div>
          </>
        );
      }}
    </QueueGate>
  );
}
