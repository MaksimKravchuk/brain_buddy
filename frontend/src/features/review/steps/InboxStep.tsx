/**
 * M-15 Inbox to zero on the web (D-03 "Inbox step"): one item at a time with
 * the web choices, an Undo after each (FR-048) that also takes the item off the
 * run's count, and for a long Inbox the three FR-030 choices, the last of which
 * releases the remainder to Someday with an Undo until the step is left. An item
 * can also be given a project with its choice, or be made into one.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { apiClient } from "../../../api/client";
import { describeReviewError, newIdempotencyKey, newProgressAttempt, withReference } from "../../../api/review";
import type { ReviewQueue } from "../../../api/review";
import { applyReviewTask, refreshAfterReviewWrite, settleForAccount, useReviewQueue } from "../../../api/reviewHooks";
import type { ReviewContinuation } from "../../../api/reviewHooks";
import { getTaskCacheScope, taskKeys, useProjects } from "../../../api/taskHooks";
import type { OpenTaskState, ProjectResponse, TaskResponse, TaskTransitionRequest, TaskUpdateRequest } from "../../../api/taskTypes";
import { useShellToast } from "../../../components/shell/shellToast";
import { sameWording } from "../formulation";
import { plural } from "../plural";
import { useReviewDrafts } from "../useReviewDrafts";
import { MakeProjectForm, NEW_PROJECT, ProjectPicker } from "./InboxProjectParts";
import type { ProjectDraft } from "./InboxProjectParts";
import { buttonClass, fieldClass, FailureBanner, primaryButtonClass, QueueGate } from "./stepParts";
import { useReviewRun, useTrackedWrite } from "./reviewRun";
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
type Form = { kind: "waiting"; choice: Choice; text: string } | { kind: "title"; text: string } | ({ kind: "project" } & ProjectDraft);

/** The project staged for one item with its next choice; `newName` is the open "New project…" field. */
type Staged = { taskId: string; projectId: string | null; newName: string | null };

/** What Undo also puts back after a choice that changed the item's project or title, or made a project. */
interface Restore {
  fields: Pick<TaskUpdateRequest, "title" | "project_id">;
  /** What could not be put back, for Undo's message. */
  failure: string;
  /** A project made for the item: archived again by Undo. */
  archive?: ProjectResponse;
}

/** The project form keeps each of its fields as a draft (FR-052), under its own name. */
const PROJECT = "project";
const PROJECT_DRAFTS = { name: "project_name", outcome: "project_outcome", action: "project_action" } as const;
/** The open "New project…" name is typed text too (FR-052). */
const NEW_PROJECT_DRAFT = "new_project";

function unsavedText(form: Form, task: TaskResponse): boolean {
  return form.kind === "project" ? form.name !== task.title || form.outcome.trim() !== "" || form.action.trim() !== "" : form.text.trim() !== "";
}

export function InboxStep(): React.JSX.Element {
  const run = useReviewRun();
  const notify = useShellToast();
  const queryClient = useQueryClient();
  const queue = useReviewQueue("inbox", run.session.id);
  const action = useStepAction();
  const countAction = useStepAction();
  const track = useTrackedWrite();
  const drafts = useReviewDrafts(run.session.id, "inbox");
  const bulk = useBulkRelease("inbox_remainder", run.session.id, run.session.steps.inbox === "pending");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [processed, setProcessed] = useState<readonly string[]>([]);
  const [stale, setStale] = useState<readonly string[]>([]);
  const [latest, setLatest] = useState<Readonly<Record<string, TaskResponse>>>({});
  const [form, setForm] = useState<Form | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [staged, setStaged] = useState<Staged | null>(null);
  const projects = useProjects();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const fieldRef = useRef<HTMLInputElement>(null);
  const focusHeading = useRef(false);

  const items = ((queue.data as ReviewQueue | undefined)?.items ?? []).map((item) => latest[item.id] ?? item);
  const handled = new Set([...processed, ...stale]);
  const limit = plan?.limit ?? items.length;
  const current = handled.size < limit ? items.find((item) => !handled.has(item.id)) : undefined;

  // A processed count that did not save holds the run on this step until its Retry lands (FR-048,
  // FR-033): leaving would unmount the only Retry and leave the run's Inbox count wrong for good.
  const { beginWrite } = run;
  const countFailed = countAction.failure !== null;
  useEffect(() => (countFailed ? beginWrite() : undefined), [countFailed, beginWrite]);
  // The next item waits for the last one's count too: one count write and one Retry at a time,
  // so a second failure can never take the place of the first one's Retry.
  const itemsDisabled = action.disabled || countAction.pending !== null || countFailed;

  useEffect(() => {
    if (focusHeading.current) {
      focusHeading.current = false;
      headingRef.current?.focus();
    }
  }, [current?.id]);

  // Once per form opened, not per keystroke: a project form has several fields.
  const formKind = form?.kind ?? null;
  useEffect(() => {
    if (formKind !== null) {
      fieldRef.current?.focus();
    }
  }, [formKind]);

  /** The project staged for an item (nothing staged: the one it has); it is the current item's alone. */
  const projectOf = (task: TaskResponse) => (staged?.taskId === task.id ? staged.projectId : task.project_id);

  // Text typed before a reload or a closed tab comes back in its form (FR-052), once per item shown:
  // a form the person closes must not reopen on its own.
  const [draftsCheckedFor, setDraftsCheckedFor] = useState<string | null>(null);
  if (current !== undefined && draftsCheckedFor !== current.id) {
    setDraftsCheckedFor(current.id);
    // A form already open for this item keeps what it has.
    if (form === null) {
      const title = drafts.load(current.id, "title");
      const waitingFor = drafts.load(current.id, "waiting");
      const project = { name: drafts.load(current.id, PROJECT_DRAFTS.name), outcome: drafts.load(current.id, PROJECT_DRAFTS.outcome), action: drafts.load(current.id, PROJECT_DRAFTS.action) };
      const newProject = drafts.load(current.id, NEW_PROJECT_DRAFT);
      if (title !== null) {
        setForm({ kind: "title", text: title });
      } else if (waitingFor !== null) {
        setForm({ kind: "waiting", choice: CHOICES.find((entry) => entry.needsWaitingFor) as Choice, text: waitingFor });
      } else if (Object.values(project).some((draft) => draft !== null)) {
        setForm({ kind: "project", name: project.name ?? current.title, outcome: project.outcome ?? "", action: project.action ?? "" });
      } else if (newProject !== null) {
        setStaged({ taskId: current.id, projectId: current.project_id, newName: newProject });
      }
    }
  }
  useEffect(() => {
    const typedNewProject = staged?.taskId === draftsCheckedFor && Boolean(staged?.newName?.trim());
    if ((form !== null && current !== undefined && unsavedText(form, current)) || (form === null && typedNewProject)) {
      run.setUnsaved(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a restored form is unsaved text before anything is typed; typing reports itself.
  }, [draftsCheckedFor]);

  /** The form is over, saved or discarded: so is its draft. */
  const closeForm = (taskId: string, field: string) => {
    setForm(null);
    for (const name of field === PROJECT ? Object.values(PROJECT_DRAFTS) : [field]) {
      drafts.clear(taskId, name);
    }
    run.setUnsaved(false);
  };

  /**
   * A choice the server refused as stale: read the item again. When its
   * wording is unchanged (a notes edit elsewhere, say) the item and whatever
   * was typed for it stay, against the new revision; only when it moved or was
   * reworded does the review leave it as it is there and drop its form (FR-011,
   * FR-052).
   */
  const reconcileStale = async (task: TaskResponse, field: string, continuation: ReviewContinuation, staleError: unknown) => {
    const fresh = await apiClient.getTask(task.id).catch(() => null);
    if (!continuation.stillCurrent()) {
      return;
    }
    if (fresh === null) {
      // Its current wording is unknown, so nothing typed is dropped and the item stays: the
      // conflict shows as a failure with its Ref, and Retry reads the task again (FR-052, FR-045).
      refreshAfterReviewWrite(queryClient, continuation.scope);
      throw staleError;
    }
    applyReviewTask(queryClient, fresh, continuation.scope);
    focusHeading.current = true;
    if (fresh.state === "inbox" && sameWording(task, fresh)) {
      setLatest((tasks) => ({ ...tasks, [task.id]: fresh }));
      setNotice(`“${task.title}” was changed on another device, so nothing was moved. It's still in Inbox; choose again.`);
      return;
    }
    setStale((ids) => [...ids, task.id]);
    closeForm(task.id, field);
    setNotice(`“${task.title}” was changed on another device, so it stayed in Inbox.`);
  };

  /**
   * The move and the count are two writes, handled separately (as in Undo): once
   * the item is out of the Inbox it is shown as processed whatever happens to
   * the count, and a count that did not go up is retried alone under the same
   * progress id, so the replay is counted once (FR-048, FR-011).
   */
  const choose = (choice: Choice, task: TaskResponse, waitingFor?: string) => {
    // Every key is made before the first send, so a Retry replays the same requests.
    const key = newIdempotencyKey();
    const projectKey = newIdempotencyKey();
    const count = newProgressAttempt(run.session.id, { inbox_processed_delta: 1 });
    // A project staged for the item goes in first; the move then follows the update's revision.
    const projectId = projectOf(task);
    const reassign = projectId !== task.project_id;
    setNotice(null);
    void action.run(choice.id, choice.label, async (continuation) => {
      let moved: TaskResponse;
      try {
        const ready = reassign ? await apiClient.updateTask(task.id, { project_id: projectId, expected_revision: task.revision }, projectKey) : task;
        moved = await apiClient.transitionTask(task.id, choice.request(ready, waitingFor), key);
      } catch (error) {
        if (describeReviewError(error).kind !== "stale") {
          throw error;
        }
        await reconcileStale(task, choice.id, continuation, error);
        return;
      }
      finishProcessed(task, moved, continuation, count, {
        field: choice.id,
        message: `“${task.title}” ${choice.toast}`,
        undoName: choice.undoName,
        restore: reassign ? { fields: { project_id: task.project_id }, failure: "its project wasn't put back" } : undefined
      });
    });
  };

  /** The item is out of the Inbox: shown as processed, counted, and Undo offered. */
  const finishProcessed = (
    task: TaskResponse,
    moved: TaskResponse,
    continuation: ReviewContinuation,
    count: ReturnType<typeof newProgressAttempt>,
    done: { field: string; message: string; undoName: string; restore?: Restore }
  ) => {
    // Only the person who pressed it may have the count sent for them.
    if (!continuation.stillCurrent()) {
      return;
    }
    const willFinish = handled.size + 1 >= limit;
    const remaining = items.filter((item) => !handled.has(item.id) && item.id !== task.id);
    applyReviewTask(queryClient, moved, continuation.scope);
    focusHeading.current = true;
    setProcessed((ids) => [...ids, task.id]);
    setStaged(null);
    drafts.clear(task.id, NEW_PROJECT_DRAFT);
    closeForm(task.id, done.field);
    // The item is processed now; the count has its own pending and failure states.
    void countAction.run(
      "count",
      "Update the Inbox count",
      async (counting) => {
        await run.progress(count);
        if (!counting.stillCurrent()) {
          return;
        }
        // Undo is offered once the count is in, so it takes off what was added.
        notify(done.message, {
          action: { label: "Undo", accessibleLabel: `Undo: ${done.undoName} ${task.title}`, onAction: () => void track(() => undoChoice(task, moved, done.restore)) }
        });
        // Its own pending and failure states; a Retry of this count reaches it too.
        if (willFinish && plan?.release && remaining.length > 0) {
          void bulk.release(
            remaining.map((item) => ({ task_id: item.id, expected_revision: item.revision })),
            "Couldn't release the rest of your Inbox. Nothing was moved."
          );
        }
      },
      `${done.message}, but the processed count didn't go up.`
    );
  };

  /**
   * Back to the Inbox, and one off the run's count (FR-048). The two writes are
   * separate: once the item is back in the Inbox it is shown again whatever
   * happens to the count, and a count that did not go down is retried alone
   * under the same progress id. A choice that also changed the item's project or
   * title has them put back once it is in the Inbox (and a project made for it
   * archived): what then fails is said, and the item is back in the Inbox anyway.
   */
  const undoChoice = async (task: TaskResponse, moved: TaskResponse, restore?: Restore) => {
    const settled = await settleForAccount(async () => {
      const back = await apiClient.transitionTask(
        task.id,
        { action: moved.state === "completed" || moved.state === "cancelled" ? "reopen" : "move", to_state: "inbox", expected_revision: moved.revision },
        newIdempotencyKey()
      );
      if (restore === undefined) {
        return { task: back, failure: null };
      }
      let restored: TaskResponse;
      try {
        restored = await apiClient.updateTask(task.id, { ...restore.fields, expected_revision: back.revision }, newIdempotencyKey());
      } catch {
        return { task: back, failure: restore.failure };
      }
      const archived = restore.archive ? await apiClient.archiveProject(restore.archive.id, restore.archive.revision, newIdempotencyKey()).then(() => true, () => false) : true;
      return { task: restored, failure: archived ? null : `the project “${restore.archive?.name}” wasn't archived` };
    });
    if (settled === null) {
      return;
    }
    if (!settled.ok) {
      notify(withReference("Couldn't undo. Nothing was changed.", describeReviewError(settled.error).referenceId));
      return;
    }
    const { task: back, failure } = settled.value;
    applyReviewTask(queryClient, back, settled.scope);
    focusHeading.current = true;
    setLatest((tasks) => ({ ...tasks, [task.id]: back }));
    setProcessed((ids) => ids.filter((id) => id !== task.id));
    if (restore?.archive) {
      refreshProjects(settled.scope);
    }
    notify(`“${task.title}” is back in your Inbox${failure ? `, but ${failure}.` : ""}`);
    const count = newProgressAttempt(run.session.id, { inbox_processed_delta: -1 });
    void countAction.run(
      "undo-count",
      "Update the Inbox count",
      () => run.progress(count),
      `“${task.title}” is back in your Inbox, but the processed count didn't go down.`
    );
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
      closeForm(task.id, "title");
    });
  };

  const refreshProjects = (scope: ReviewContinuation["scope"]) =>
    void queryClient.invalidateQueries({ queryKey: taskKeys.projects(getTaskCacheScope(scope.accountId)) });

  /** "New project…": made at once (a project alone changes no task); the item gets it with its choice. */
  const addProject = (event: FormEvent, task: TaskResponse, name: string) => {
    event.preventDefault();
    const key = newIdempotencyKey();
    void action.run("project-add", "Add project", async (continuation) => {
      const created = await apiClient.createProject({ name: name.trim() }, key);
      if (!continuation.stillCurrent()) {
        return;
      }
      queryClient.setQueryData<ProjectResponse[]>(taskKeys.projects(getTaskCacheScope(continuation.scope.accountId)), (list) => list && [...list, created]);
      refreshProjects(continuation.scope);
      setStaged({ taskId: task.id, projectId: created.id, newName: null });
      drafts.clear(task.id, NEW_PROJECT_DRAFT);
      run.setUnsaved(false);
    });
  };

  /**
   * "Make it a project": the project, the item as its first next action, and the move to Next
   * actions are three writes in order, each under its own key made before the first send, so a
   * Retry replays what already landed (never a second project). A choice the server refuses as
   * stale leaves the item in the Inbox and archives the project made for it.
   */
  const submitProject = (event: FormEvent, task: TaskResponse, draft: ProjectDraft) => {
    event.preventDefault();
    const name = draft.name.trim();
    const outcome = draft.outcome.trim();
    const title = draft.action.trim();
    const keys = { project: newIdempotencyKey(), update: newIdempotencyKey(), move: newIdempotencyKey(), archive: newIdempotencyKey() };
    const count = newProgressAttempt(run.session.id, { inbox_processed_delta: 1 });
    setNotice(null);
    void action.run(PROJECT, "Make it a project", async (continuation) => {
      const project = await apiClient.createProject({ name, ...(outcome ? { desired_outcome: outcome } : {}) }, keys.project);
      let moved: TaskResponse;
      try {
        const titled = await apiClient.updateTask(task.id, { ...(title === task.title ? {} : { title }), project_id: project.id, expected_revision: task.revision }, keys.update);
        moved = await apiClient.transitionTask(task.id, { action: "move", to_state: "next", expected_revision: titled.revision }, keys.move);
      } catch (error) {
        if (describeReviewError(error).kind !== "stale") {
          throw error;
        }
        await reconcileStale(task, PROJECT, continuation, error);
        if (continuation.stillCurrent()) {
          await apiClient.archiveProject(project.id, project.revision, keys.archive).catch(() => undefined);
          refreshProjects(continuation.scope);
        }
        return;
      }
      refreshProjects(continuation.scope);
      finishProcessed(task, moved, continuation, count, {
        field: PROJECT,
        message: `“${name}” is now a project`,
        undoName: "Made a project",
        restore: { fields: { ...(title === task.title ? {} : { title: task.title }), project_id: task.project_id }, failure: "its title and project weren't put back", archive: project }
      });
      // Part of it may have landed (the project, the new title): Retry replays the same keys and finishes it.
    }, `Couldn't finish making “${name}” a project. Retry picks up where it stopped.`);
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
              {countAction.failure ? <FailureBanner failure={countAction.failure} online={countAction.online} /> : null}
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
              {countAction.failure ? <FailureBanner failure={countAction.failure} online={countAction.online} /> : null}
              {form?.kind === "project" ? (
                <MakeProjectForm
                  draft={form}
                  actionRef={fieldRef}
                  busy={action.pending !== null}
                  disabled={itemsDisabled}
                  onChange={(next) => {
                    setForm({ kind: "project", ...next });
                    drafts.save(current.id, PROJECT_DRAFTS.name, next.name, current.title);
                    drafts.save(current.id, PROJECT_DRAFTS.outcome, next.outcome);
                    drafts.save(current.id, PROJECT_DRAFTS.action, next.action);
                    run.setUnsaved(unsavedText({ kind: "project", ...next }, current));
                  }}
                  onBack={() => run.confirmDiscard(() => closeForm(current.id, PROJECT))}
                  onSubmit={(event) => submitProject(event, current, form)}
                />
              ) : form ? (
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
                        drafts.save(current.id, form.kind, text, form.kind === "title" ? current.title : "");
                        run.setUnsaved(text.trim() !== "" && text !== (form.kind === "title" ? current.title : ""));
                      }}
                    />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={action.pending !== null} className={buttonClass} onClick={() => run.confirmDiscard(() => closeForm(current.id, form.kind))}>Back</button>
                    <button type="submit" disabled={form.text.trim() === "" || itemsDisabled} className={`${primaryButtonClass} ml-auto`}>
                      {action.pending !== null ? "Saving…" : form.kind === "title" ? "Save title" : "Move to Waiting for"}
                    </button>
                  </div>
                </form>
              ) : (
                <>
                  <ProjectPicker
                    projects={(projects.data ?? []).filter((project) => project.state === "active")}
                    value={staged?.taskId === current.id && staged.newName !== null ? NEW_PROJECT : (projectOf(current) ?? "")}
                    newName={staged?.taskId === current.id ? (staged.newName ?? "") : ""}
                    busy={action.pending === "project-add"}
                    disabled={itemsDisabled}
                    onSelect={(value) => {
                      setStaged({ taskId: current.id, projectId: value === NEW_PROJECT ? projectOf(current) : value || null, newName: value === NEW_PROJECT ? "" : null });
                      if (value !== NEW_PROJECT) {
                        // Choosing a project instead discards the typed name.
                        drafts.clear(current.id, NEW_PROJECT_DRAFT);
                        run.setUnsaved(false);
                      }
                    }}
                    onNewName={(newName) => {
                      setStaged({ taskId: current.id, projectId: projectOf(current), newName });
                      drafts.save(current.id, NEW_PROJECT_DRAFT, newName);
                      run.setUnsaved(newName.trim() !== "");
                    }}
                    onAdd={(event) => addProject(event, current, staged?.newName ?? "")}
                  />
                  <div role="group" aria-label="Choices" className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                    {CHOICES.map((choice) => (
                      <button
                        key={choice.id}
                        type="button"
                        disabled={itemsDisabled}
                        className={`${buttonClass} flex flex-col items-start text-left`}
                        onClick={() => (choice.needsWaitingFor ? setForm({ kind: "waiting", choice, text: "" }) : choose(choice, current))}
                      >
                        {action.pending === choice.id ? "Saving…" : choice.label}
                        {choice.sub ? <span className="text-xs font-normal text-slate-500">{choice.sub}</span> : null}
                      </button>
                    ))}
                    <button type="button" disabled={itemsDisabled} className={buttonClass} onClick={() => setForm({ kind: "project", name: current.title, outcome: "", action: "" })}>
                      Make it a project
                    </button>
                    <button type="button" disabled={itemsDisabled} className={buttonClass} onClick={() => setForm({ kind: "title", text: current.title })}>
                      Edit title
                    </button>
                  </div>
                </>
              )}
            </div>
          </>
        );
      }}
    </QueueGate>
  );
}
