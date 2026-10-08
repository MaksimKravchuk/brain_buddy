/**
 * The shared body of the Waiting (M-18) and Someday (M-20) steps: one task at a
 * time, a few decisions, an Undo after each (FR-048), and the same save, stale
 * and refusal states (FR-011, FR-045). Each decision is the review decision of
 * http §3, counted in the run.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { describeReviewError, newIdempotencyKey, reviewApi } from "../../../api/review";
import type { DecisionRequest, DecisionResponse, DecisionType, ReviewQueue, StepCode } from "../../../api/review";
import { applyReviewTask, refreshAfterReviewWrite, useReviewQueue } from "../../../api/reviewHooks";
import type { ReviewContinuation } from "../../../api/reviewHooks";
import { apiClient } from "../../../api/client";
import type { TaskResponse } from "../../../api/taskTypes";
import { useShellToast } from "../../../components/shell/shellToast";
import { sameWording } from "../formulation";
import { runUndo } from "../reviewUndo";
import { useReviewDrafts } from "../useReviewDrafts";
import { buttonClass, fieldClass, FailureBanner, primaryButtonClass, QueueGate, Ref } from "./stepParts";
import { useReviewRun } from "./reviewRun";
import { useStepAction } from "./useStepAction";

export interface ItemAction {
  id: string;
  type: DecisionType;
  label: string;
  sub?: string;
  /** Decisions that ask for a title first. */
  form?: { prompt: string; save: string; prefill: boolean };
  /** What Undo reverts, for "Undo: <what> <title>". */
  undoName: string;
  toast: (title: string, text: string) => string;
}

export interface ItemStepConfig {
  step: StepCode;
  /** "Waiting for more than 7 days" after "1 of 3 · ". */
  position: string;
  empty: string;
  describe: (task: TaskResponse, now: Date) => string | null;
  actions: ItemAction[];
}

const REFUSALS: Readonly<Record<string, string>> = {
  project_archived: "Restore this archived project before creating a follow-up in it.",
  decision_not_allowed: "This decision isn't available for this task's current list. Nothing was changed."
};

type Notice = { kind: "stale" | "refused"; text: string; referenceId?: string };

export function ItemDecisionStep({ config }: { config: ItemStepConfig }): React.JSX.Element {
  const run = useReviewRun();
  const notify = useShellToast();
  const queryClient = useQueryClient();
  const queue = useReviewQueue(config.step, run.session.id);
  const action = useStepAction();
  const drafts = useReviewDrafts(run.session.id, config.step);
  const [handled, setHandled] = useState<ReadonlySet<string>>(new Set());
  const [latest, setLatest] = useState<Readonly<Record<string, TaskResponse>>>({});
  const [form, setForm] = useState<{ action: ItemAction; text: string; initial: string } | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const fieldRef = useRef<HTMLInputElement>(null);
  const focusHeading = useRef(false);
  const now = new Date();

  const items = (queue.data as ReviewQueue | undefined)?.items ?? [];
  const current = items.map((item) => latest[item.id] ?? item).find((item) => !handled.has(item.id));

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

  // Text typed before a reload or a closed tab comes back in its form (FR-052), once per item shown:
  // a form the person closes must not reopen on its own.
  const [draftsCheckedFor, setDraftsCheckedFor] = useState<string | null>(null);
  if (current !== undefined && draftsCheckedFor !== current.id) {
    setDraftsCheckedFor(current.id);
    for (const item of config.actions) {
      const text = form === null && item.form ? drafts.load(current.id, item.id) : null;
      if (item.form && text !== null) {
        setForm({ action: item, text, initial: item.form.prefill ? current.title : "" });
        break;
      }
    }
  }
  useEffect(() => {
    if (form !== null && form.text.trim() !== "") {
      run.setUnsaved(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a restored form is unsaved text before anything is typed; typing reports itself.
  }, [draftsCheckedFor]);

  /** The form is over, saved or discarded: so is its draft. */
  const closeForm = (taskId: string, field: string) => {
    setForm(null);
    drafts.clear(taskId, field);
    run.setUnsaved(false);
  };

  /**
   * A decision the server refused as stale: read the task again. When its
   * wording is unchanged (a notes edit elsewhere, say) the card, the open form
   * and its draft stay, and the next try carries the new revision under a new
   * key; only when the task moved or was reworded is it left as it is there and
   * its form dropped (FR-011, FR-052).
   */
  const reconcileStale = async (task: TaskResponse, item: ItemAction, continuation: ReviewContinuation) => {
    const fresh = await apiClient.getTask(task.id).catch(() => null);
    if (!continuation.stillCurrent()) {
      return;
    }
    if (fresh) {
      applyReviewTask(queryClient, fresh, continuation.scope);
    } else {
      refreshAfterReviewWrite(queryClient, continuation.scope);
    }
    focusHeading.current = true;
    if (fresh !== null && sameWording(task, fresh)) {
      setLatest((tasks) => ({ ...tasks, [task.id]: fresh }));
      setNotice({ kind: "stale", text: `“${task.title}” changed on another device, so nothing was applied. Here's the current version; decide again if it still needs it.` });
      return;
    }
    setHandled((ids) => new Set(ids).add(task.id));
    closeForm(task.id, item.id);
    setNotice({ kind: "stale", text: `“${task.title}” changed on another device, so it was left as it is there.` });
  };

  const decide = (item: ItemAction, task: TaskResponse, text: string) => {
    const key = newIdempotencyKey();
    const body: DecisionRequest = { type: item.type, expected_revision: task.revision, ...(item.form ? { title: text } : {}), session_id: run.session.id };
    setNotice(null);
    void action.run(item.id, item.label, async (continuation) => {
      let response: DecisionResponse;
      try {
        response = await reviewApi.decide(task.id, body, key);
      } catch (error) {
        const { kind, referenceId } = describeReviewError(error);
        if (kind === "stale") {
          await reconcileStale(task, item, continuation);
          return;
        }
        if (kind in REFUSALS) {
          setNotice({ kind: "refused", text: REFUSALS[kind], referenceId });
          return;
        }
        throw error;
      }
      applyReviewTask(queryClient, response.task, continuation.scope);
      focusHeading.current = true;
      setHandled((ids) => new Set(ids).add(task.id));
      closeForm(task.id, item.id);
      notify(item.toast(task.title, text), {
        action: {
          label: "Undo",
          accessibleLabel: `Undo: ${item.undoName} ${task.title}`,
          onAction: () =>
            void runUndo(notify, queryClient, response, task.title, (restored) => {
              focusHeading.current = true;
              setLatest((tasks) => ({ ...tasks, [restored.id]: restored }));
              setHandled((ids) => {
                const next = new Set(ids);
                next.delete(restored.id);
                return next;
              });
            })
        }
      });
    });
  };

  const submitForm = (event: FormEvent, task: TaskResponse, chosen: ItemAction, text: string) => {
    // A disabled submit button blocks implicit submission, so a submit always carries a title.
    event.preventDefault();
    decide(chosen, task, text.trim());
  };

  return (
    <QueueGate queries={[queue]}>
      {() => {
        if (items.length === 0) {
          return <p className="m-0 text-sm text-slate-600">{config.empty}</p>;
        }
        if (current === undefined) {
          return (
            <>
              {notice ? <p role="status" aria-label="Changed elsewhere" className="m-0 text-sm text-slate-700">{notice.text}</p> : null}
              <p className="m-0 text-sm text-slate-600">All caught up.</p>
            </>
          );
        }
        const meta = config.describe(current, now);
        return (
          <>
            {notice?.kind === "stale" ? <p role="status" aria-label="Changed elsewhere" className="m-0 text-sm text-slate-700">{notice.text}</p> : null}
            <p className="m-0 flex justify-between text-xs text-slate-500">
              {`${items.findIndex((item) => item.id === current.id) + 1} of ${items.length} · ${config.position}`}
            </p>
            <div className="flex flex-col gap-3 rounded-[14px] border border-slate-200 bg-white p-4 shadow-soft">
              <h2 ref={headingRef} tabIndex={-1} className="m-0 break-words text-lg font-semibold text-slate-900 outline-hidden">{current.title}</h2>
              {meta ? <p className="m-0 -mt-2 text-xs text-slate-500">{meta}</p> : null}
              {action.failure ? <FailureBanner failure={action.failure} online={action.online} /> : null}
              {notice?.kind === "refused" ? (
                <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <span>{notice.text}</span>
                  <Ref id={notice.referenceId} />
                </div>
              ) : null}
              {form ? (
                <form className="flex flex-col gap-2" onSubmit={(event) => submitForm(event, current, form.action, form.text)}>
                  <label className="flex flex-col gap-1 text-sm font-medium text-slate-800">
                    {form.action.form?.prompt}
                    <input
                      ref={fieldRef}
                      value={form.text}
                      maxLength={500}
                      readOnly={action.pending !== null}
                      className={fieldClass}
                      onChange={(event) => {
                        const text = event.currentTarget.value;
                        setForm({ ...form, text });
                        drafts.save(current.id, form.action.id, text, form.initial);
                        run.setUnsaved(text.trim() !== "" && text !== form.initial);
                      }}
                    />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={action.pending !== null} className={buttonClass} onClick={() => run.confirmDiscard(() => closeForm(current.id, form.action.id))}>Back</button>
                    <button type="submit" disabled={form.text.trim() === "" || action.disabled} className={`${primaryButtonClass} ml-auto`}>
                      {action.pending === form.action.id ? "Saving…" : form.action.form?.save}
                    </button>
                  </div>
                </form>
              ) : (
                <div role="group" aria-label="Decisions" className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                  {config.actions.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      disabled={action.disabled}
                      className={`${buttonClass} flex flex-col items-start text-left`}
                      onClick={() => {
                        const initial = item.form?.prefill ? current.title : "";
                        return item.form ? setForm({ action: item, text: initial, initial }) : decide(item, current, "");
                      }}
                    >
                      {action.pending === item.id ? "Saving…" : item.label}
                      {item.sub ? <span className="text-xs font-normal text-slate-500">{item.sub}</span> : null}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>
        );
      }}
    </QueueGate>
  );
}
