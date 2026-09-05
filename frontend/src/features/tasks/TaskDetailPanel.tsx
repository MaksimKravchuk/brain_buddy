import { Bot, Check, ChevronRight, CircleAlert, Inbox, LoaderCircle, MoreHorizontal, Network, X } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { RefObject } from "react";

import { useAgentRuns } from "../../api/agentHooks";
import { hasFeatureFlag } from "../../api/auth";
import { apiClient } from "../../api/client";
import { AgentHandoffOverlay } from "../agents/AgentHandoffOverlay";
import { AgentRunSection } from "../agents/AgentRunSection";
import { useAuthStore } from "../../stores/authStore";
import type {
  OpenTaskState,
  ProjectResponse,
  TagResponse,
  TaskPriority,
  TaskResponse,
  TaskSubtaskResponse
} from "../../api/taskTypes";
import { Button } from "../../components/ui/Button";
import { useShellToast } from "../../components/shell/shellToast";
import { getErrorMessage } from "../../utils/error";
import type { AutosaveSnapshot, EditableField, TaskDetailAutosaveController } from "./taskDetailAutosave";

type TaskDetailSavePayload = Parameters<typeof apiClient.updateTask>[1];

const stateLabels: Record<OpenTaskState, string> = {
  inbox: "Inbox",
  next: "Next actions",
  waiting: "Waiting for",
  someday: "Someday / maybe"
};

const openStateOptions: OpenTaskState[] = ["inbox", "next", "waiting", "someday"];

// The panel is a docked 320px column from 1100px up (prototype `.bbs-detail`)
// and a fixed right slide-over below that breakpoint.
const activePanelClass =
  "fixed bottom-0 right-0 top-14 z-40 flex w-full max-w-none flex-col overflow-x-hidden overflow-y-auto border-l border-slate-200 bg-white shadow-floating motion-safe:animate-slide-in-right min-[1100px]:static min-[1100px]:z-auto min-[1100px]:w-[320px] min-[1100px]:max-w-none min-[1100px]:shrink-0 min-[1100px]:animate-none min-[1100px]:shadow-none";

const iconButtonClass =
  "inline-flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 shadow-soft transition-colors duration-200 ease-smooth hover:border-slate-300 hover:text-slate-800";

const propLabelClass = "text-slate-400";

const propFieldClass =
  "w-full min-w-0 appearance-none rounded-md border border-transparent bg-transparent px-1.5 py-1 text-[12.5px] text-slate-800 outline-none transition-colors duration-200 ease-smooth hover:border-slate-200 focus:border-brand-primary";

const dashedInputClass =
  "w-full rounded-lg border-[1.5px] border-dashed border-slate-300 bg-transparent px-2.5 py-1.5 text-[13px] text-slate-900 outline-none transition-colors duration-200 ease-smooth placeholder:text-slate-400 focus:border-solid focus:border-brand-primary";

export function TaskDetailEmptyPanel(): React.JSX.Element {
  return (
    <aside
      aria-label="Task detail"
      className="hidden w-[320px] shrink-0 flex-col items-center justify-center overflow-y-auto border-l border-slate-200 bg-surface-base min-[1100px]:flex"
    >
      <div className="flex flex-col items-center gap-1.5 px-8 text-center text-slate-300">
        <Inbox className="h-[26px] w-[26px]" aria-hidden />
        <div className="mt-1 text-sm font-semibold text-slate-900">Nothing selected</div>
        <p className="m-0 text-[12.5px] leading-relaxed text-slate-500">Pick a task to see its details.</p>
      </div>
    </aside>
  );
}

export function TaskDetailPanel({
  task,
  autosave,
  resetKey,
  projects,
  tags,
  isLoading,
  error,
  headingRef,
  onClose,
  onSave,
  onTransition,
  onCreateSubtask,
  onTransitionSubtask,
  onCreateComment
}: {
  task?: TaskResponse;
  autosave?: TaskDetailAutosaveController;
  resetKey?: number;
  projects: ProjectResponse[];
  tags: TagResponse[];
  isLoading: boolean;
  error: unknown;
  headingRef: RefObject<HTMLHeadingElement | null>;
  onClose: () => void;
  onSave: (task: TaskResponse, payload: TaskDetailSavePayload) => void;
  onTransition: (task: TaskResponse, action: "move" | "complete" | "reopen" | "cancel", toState?: OpenTaskState, waitingFor?: string) => void;
  onCreateSubtask: (task: TaskResponse, title: string) => void;
  onTransitionSubtask: (task: TaskResponse, subtask: TaskSubtaskResponse, action: "complete" | "reopen" | "cancel") => void;
  onCreateComment: (task: TaskResponse, body: string) => void;
}): React.JSX.Element {
  const notify = useShellToast();
  const [menuOpen, setMenuOpen] = useState(false);
  const isTerminal = Boolean(task && (task.state === "completed" || task.state === "cancelled"));
  const autosaveSnapshot = useSyncExternalStore(
    autosave?.subscribe ?? (() => () => undefined),
    autosave?.getSnapshot ?? (() => undefined),
    autosave?.getSnapshot ?? (() => undefined)
  );

  useEffect(() => {
    setMenuOpen(false);
  }, [task?.id]);

  return (
    <aside aria-labelledby="task-detail-title" className={activePanelClass}>
      <h2 id="task-detail-title" ref={headingRef} tabIndex={-1} className="sr-only">
        Task detail
      </h2>
      <div className="flex items-center px-3 pb-1.5 pt-2.5">
        <button type="button" aria-label="Close" className={iconButtonClass} onClick={onClose}>
          <ChevronRight className="h-[15px] w-[15px]" aria-hidden />
        </button>
        <span className="relative ml-auto flex min-w-0 items-center gap-1">
          <AutosaveStatus snapshot={autosaveSnapshot} />
          <button
            type="button"
            aria-label="Thinking canvas"
            className={iconButtonClass}
            onClick={() => notify("Thinking canvas isn't built yet — placeholder")}
          >
            <Network className="h-[15px] w-[15px]" aria-hidden />
          </button>
          {task && !isTerminal ? (
            <>
              <button
                type="button"
                aria-label="Task menu"
                aria-expanded={menuOpen}
                className={iconButtonClass}
                onClick={() => setMenuOpen((open) => !open)}
              >
                <MoreHorizontal className="h-[15px] w-[15px]" aria-hidden />
              </button>
              {menuOpen ? (
                <div className="absolute right-0 top-8 z-50 w-40 rounded-xl border border-slate-200 bg-white p-1.5 shadow-floating">
                  <button
                    type="button"
                    className="w-full rounded-lg px-2.5 py-1.5 text-left text-xs font-medium text-rose-600 transition-colors duration-200 ease-smooth hover:bg-rose-50"
                    onClick={() => {
                      setMenuOpen(false);
                      if (autosave) autosave.barrier("cancel");
                      else onTransition(task, "cancel");
                    }}
                  >
                    Cancel task
                  </button>
                </div>
              ) : null}
            </>
          ) : null}
        </span>
      </div>

      {isLoading ? <p className="px-4 pb-4 text-sm text-slate-600">Loading task detail…</p> : null}
      {error ? (
        <p role="alert" className="px-4 pb-4 text-sm text-rose-700">
          {getErrorMessage(error)}
        </p>
      ) : null}
      {task ? (
        <TaskDetailBody
          task={task}
          autosave={autosave}
          autosaveSnapshot={autosaveSnapshot}
          resetKey={resetKey}
          projects={projects}
          tags={tags}
          isTerminal={isTerminal}
          notify={notify}
          onSave={onSave}
          onTransition={onTransition}
          onCreateSubtask={onCreateSubtask}
          onTransitionSubtask={onTransitionSubtask}
          onCreateComment={onCreateComment}
        />
      ) : null}
    </aside>
  );
}

function AutosaveStatus({ snapshot }: { snapshot?: AutosaveSnapshot }): React.JSX.Element | null {
  if (!snapshot || snapshot.status === "clean") return null;
  const labels: Partial<Record<AutosaveSnapshot["status"], string>> = {
    saving: "Saving…",
    queued: snapshot.queuedCount === 1 ? "1 change queued" : `${snapshot.queuedCount} changes queued`,
    retrying: "Retrying…",
    saved: "Saved",
    conflicted: "Not saved",
    failed: snapshot.error?.kind === "protocol" ? "Save unverified" : "Not saved"
  };
  const announcements: Partial<Record<AutosaveSnapshot["status"], string>> = {
    saving: "Saving changes",
    queued: "Changes queued",
    retrying: "Retrying your edits",
    saved: "All changes saved",
    conflicted: "Task changed elsewhere",
    failed: snapshot.error?.kind === "protocol" ? "Could not verify whether changes were saved" : "Changes not saved"
  };
  const Icon = snapshot.status === "saving" || snapshot.status === "retrying"
    ? LoaderCircle
    : snapshot.status === "saved" ? Check : CircleAlert;
  return (
    <>
      <span className={`flex min-w-0 items-center gap-1 whitespace-nowrap text-xs ${snapshot.status === "saved" ? "text-[#065f46]" : "text-[#92400e]"}`}>
        <Icon className={`h-3.5 w-3.5 shrink-0 ${snapshot.status === "saving" || snapshot.status === "retrying" ? "motion-safe:animate-spin motion-reduce:animate-none" : ""}`} aria-hidden />
        <span>{labels[snapshot.status]}</span>
      </span>
      <span data-testid="autosave-announcement" className="sr-only" aria-live="polite" aria-atomic="true">{announcements[snapshot.status]}</span>
    </>
  );
}

function AutosaveRecovery({ snapshot, controller }: { snapshot?: AutosaveSnapshot; controller?: TaskDetailAutosaveController }): React.JSX.Element | null {
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  if (!snapshot || !controller || (snapshot.status !== "conflicted" && snapshot.status !== "failed" && snapshot.status !== "retrying")) return null;
  const conflict = snapshot.status === "conflicted";
  const offline = snapshot.error?.offline;
  const protocol = snapshot.error?.kind === "protocol";
  const checkSavedVersion = protocol && !snapshot.inFlight;
  const heading = conflict ? "Task changed elsewhere" : protocol ? "Couldn’t verify the saved version" : offline ? "You’re offline" : "Couldn’t save changes";
  const body = conflict
    ? snapshot.conflict?.refetchFailed ? "The latest task couldn’t be loaded. Your edits remain in this tab. Try again." : "Your edits remain in this tab. Retry to apply them to the latest task."
    : protocol ? snapshot.error?.refetchFailed ? "The saved version couldn’t be loaded or verified. Your edits remain in this tab. Try checking again."
      : checkSavedVersion ? "The server returned an unexpected task version. Your edits remain in this tab. Check the saved version before retrying."
        : "The server response couldn’t be verified. Your edits remain in this tab. Retry to confirm the save."
      : offline ? "Your edits remain in this tab. Retry when you’re back online."
        : snapshot.error?.kind === "unauthorized" ? "Your session has ended. Keep this tab open and sign in again before retrying."
          : snapshot.error?.kind === "unavailable" ? "This task is no longer available. Your edits remain in this tab so you can copy them."
            : snapshot.error?.kind === "validation" ? "The server didn’t accept this change. Review the error details before retrying."
              : "Your edits remain in this tab. Try again when the service is available.";
  const errorDetail = !conflict && snapshot.error?.message && snapshot.error.message !== "Couldn’t save changes"
    ? snapshot.error.message
    : null;
  const retryDisabled = snapshot.status === "retrying"
    || Boolean(!conflict && !protocol && snapshot.error && !snapshot.error.retryAllowed)
    || Boolean(conflict && !snapshot.conflict?.latestServerTask && !snapshot.conflict?.refetchFailed);
  return (
    <section role="alert" className="mx-4 mb-3 rounded-xl border border-[#fde68a] bg-[#fffbeb] p-3 text-[#92400e]">
      <h3 ref={headingRef} tabIndex={-1} className="m-0 text-sm font-semibold">{heading}</h3>
      {errorDetail ? <details className="mt-1 text-xs leading-relaxed"><summary className="cursor-pointer focus-visible:shadow-ring-focus">Error details</summary><p className="mb-0 mt-1">{errorDetail}</p></details> : null}
      <p className="mb-3 mt-1 text-xs leading-relaxed">{snapshot.status === "retrying" ? "Applying your edits to the latest task…" : body}</p>
      {confirmDiscard ? (
        <div>
          <p className="mb-2 text-sm font-semibold">Discard unsaved edits?</p>
          <div className="flex gap-2 max-[339px]:flex-col">
            <button type="button" className="min-h-11 flex-1 rounded-lg border border-[#fde68a] px-3 text-sm font-medium focus-visible:shadow-ring-focus" onClick={() => setConfirmDiscard(false)}>Keep editing</button>
            <button type="button" className="min-h-11 flex-1 rounded-lg bg-rose-700 px-3 text-sm font-semibold text-white focus-visible:shadow-ring-focus" onMouseDown={(event) => event.preventDefault()} onClick={() => { controller.discard(); setConfirmDiscard(false); queueMicrotask(() => headingRef.current?.focus()); }}>Discard</button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2 max-[339px]:flex-col">
          <button type="button" disabled={retryDisabled} aria-disabled={retryDisabled} className="min-h-11 flex-1 rounded-lg bg-[#92400e] px-3 text-sm font-semibold text-white focus-visible:shadow-ring-focus disabled:opacity-60" onClick={() => checkSavedVersion || snapshot.conflict?.refetchFailed ? void controller.retryRefetch() : controller.retry()}>{checkSavedVersion ? "Check saved version" : protocol ? "Retry verification" : conflict ? "Retry my edits" : "Retry"}</button>
          {conflict ? <button type="button" className="min-h-11 flex-1 rounded-lg border border-[#fde68a] px-3 text-sm font-medium focus-visible:shadow-ring-focus" onMouseDown={(event) => event.preventDefault()} onClick={() => setConfirmDiscard(true)}>Discard my edits</button> : null}
        </div>
      )}
    </section>
  );
}

function TaskDetailBody({
  task,
  autosave,
  autosaveSnapshot,
  resetKey,
  projects,
  tags,
  isTerminal,
  notify,
  onSave,
  onTransition,
  onCreateSubtask,
  onTransitionSubtask,
  onCreateComment
}: {
  task: TaskResponse;
  autosave?: TaskDetailAutosaveController;
  autosaveSnapshot?: AutosaveSnapshot;
  resetKey?: number;
  projects: ProjectResponse[];
  tags: TagResponse[];
  isTerminal: boolean;
  notify: (message: string) => void;
  onSave: (task: TaskResponse, payload: TaskDetailSavePayload) => void;
  onTransition: (task: TaskResponse, action: "move" | "complete" | "reopen" | "cancel", toState?: OpenTaskState, waitingFor?: string) => void;
  onCreateSubtask: (task: TaskResponse, title: string) => void;
  onTransitionSubtask: (task: TaskResponse, subtask: TaskSubtaskResponse, action: "complete" | "reopen" | "cancel") => void;
  onCreateComment: (task: TaskResponse, body: string) => void;
}): React.JSX.Element {
  // Live value shared between the "waiting" prop row and list moves into
  // Waiting for, which require a non-empty waiting_for on the transition.
  const [waitingFor, setWaitingFor] = useState(task.waiting_for ?? "");
  const [title, setTitle] = useState(task.title);
  const [details, setDetails] = useState(task.details ?? "");
  const [dueDate, setDueDate] = useState(task.due_date ?? "");
  const [draftState, setDraftState] = useState(task.state);
  const [projectId, setProjectId] = useState(task.project_id ?? "");
  const [priority, setPriority] = useState(task.priority);
  const [tagIds, setTagIds] = useState(task.tag_ids);
  const [waitingRequired, setWaitingRequired] = useState(false);
  const waitingRef = useRef<HTMLInputElement>(null);

  // Acknowledged revisions must not overwrite an active draft. Identity
  // changes and explicit conflict Discard are the only canonical resets.
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    setWaitingFor(task.waiting_for ?? "");
    setTitle(task.title);
    setDetails(task.details ?? "");
    setDueDate(task.due_date ?? "");
    setDraftState(task.state);
    setProjectId(task.project_id ?? "");
    setPriority(task.priority);
    setTagIds(task.tag_ids);
  }, [task.id, resetKey]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const save = (payload: Omit<TaskDetailSavePayload, "expected_revision">) =>
    onSave(task, { ...payload, expected_revision: task.revision });
  const draft = autosaveSnapshot?.draft;
  const fieldLabel = (label: string, field: EditableField) => {
    void field;
    return label;
  };
  const change = (field: EditableField, value: never, delay: number) => autosave?.change(field, value, delay);

  const project = projectId ? projects.find((item) => item.id === projectId) : undefined;
  const subtasks = task.subtasks ?? [];
  const doneSubtasks = subtasks.filter((subtask) => subtask.state !== "open").length;
  const comments = task.comments ?? [];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-start gap-2.5 px-4 pb-3">
        <button
          type="button"
          aria-label={isTerminal ? "Reopen task" : "Complete task"}
          className={`mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border-[1.5px] transition-colors duration-200 ease-smooth ${
            task.state === "completed"
              ? "border-brand-primary bg-brand-primary text-white"
              : task.state === "cancelled"
                ? "border-slate-300 bg-slate-200 text-slate-500"
                : "border-slate-300 bg-white text-transparent hover:border-brand-primary"
          }`}
          onClick={() => autosave ? autosave.barrier(isTerminal ? "reopen" : "complete", isTerminal ? "inbox" : undefined) : onTransition(task, isTerminal ? "reopen" : "complete", isTerminal ? "inbox" : undefined)}
        >
          {task.state === "cancelled" ? <X className="h-2.5 w-2.5" aria-hidden /> : <Check className="h-[11px] w-[11px]" aria-hidden />}
        </button>
        {/* A textarea so long titles wrap like the prototype's static title;
            Enter commits instead of inserting a newline. */}
        <textarea
          aria-label={fieldLabel("Title", "title")}
          value={draft?.title ?? title}
          rows={1}
          ref={autosizeTitle}
          className={`w-full min-w-0 resize-none overflow-hidden rounded-md border border-transparent bg-transparent px-1 py-0.5 text-[15px] font-semibold leading-[1.35] outline-none transition-colors duration-200 ease-smooth hover:border-slate-200 focus:border-brand-primary ${
            isTerminal ? "text-slate-500 line-through" : "text-slate-900"
          }`}
          onChange={(event) => { setTitle(event.currentTarget.value); change("title", event.currentTarget.value as never, 500); }}
          onInput={(event) => autosizeTitle(event.currentTarget)}
          onBlur={(event) => {
            const nextTitle = event.currentTarget.value.trim();
            if (autosave) autosave.flush("title");
            else if (nextTitle && nextTitle !== task.title) {
              save({ title: nextTitle });
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.blur();
            }
          }}
        />
      </div>

      <AutosaveRecovery snapshot={autosaveSnapshot} controller={autosave} />
      <span className="pointer-events-none absolute">
        {autosaveSnapshot?.dirtyFields.map((field) => (
          <i key={field} aria-label={`${field === "project_id" ? "Project" : field === "tag_ids" ? "Tags" : field === "due_date" ? "Due date" : field === "waiting_for" ? "Waiting for" : field[0]?.toUpperCase() + field.slice(1)}, unsaved`} className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
        ))}
      </span>

      <div className="grid grid-cols-[64px_1fr] items-center gap-x-2.5 gap-y-2 px-4 pb-3.5 text-[12.5px]">
        <span className={propLabelClass}>date</span>
        <input
          aria-label={fieldLabel("Due date", "due_date")}
          type="date"
          value={draft?.due_date ?? dueDate}
          className={`${propFieldClass} scroll-mb-[88px]`}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDueDate(value);
            if (autosave) change("due_date", (value || null) as never, 0); else save({ due_date: value || null });
          }}
        />

        <span className={propLabelClass}>list</span>
        <select
          aria-label={fieldLabel("List", "state")}
          value={isTerminal && !draft ? "" : draft?.state ?? draftState}
          className={propFieldClass}
          onChange={(event) => {
            const target = event.currentTarget.value as OpenTaskState | "";
            if (!target) {
              return;
            }
            setDraftState(target);
            if (autosave) {
              const result = autosave.transition(target);
              if (!result.accepted) {
                setWaitingRequired(true);
                queueMicrotask(() => waitingRef.current?.focus());
              } else setWaitingRequired(false);
            } else onTransition(task, isTerminal ? "reopen" : "move", target, target === "waiting" ? waitingFor : undefined);
          }}
        >
          {isTerminal ? <option value="">{task.state === "completed" ? "Completed" : "Cancelled"}</option> : null}
          {openStateOptions.map((option) => (
            <option key={option} value={option}>
              {isTerminal ? `Reopen to ${stateLabels[option]}` : stateLabels[option]}
            </option>
          ))}
        </select>

        <span className={propLabelClass}>project</span>
        <span className="flex min-w-0 items-center gap-1.5">
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: project?.color ?? "#cbd5e1" }}
            aria-hidden
          />
          <select
            aria-label={fieldLabel("Project", "project_id")}
            value={draft?.project_id ?? projectId}
            className={propFieldClass}
            onChange={(event) => {
              const value = event.currentTarget.value;
              setProjectId(value);
              if (autosave) change("project_id", (value || null) as never, 0); else save({ project_id: value || null });
            }}
          >
            <option value="">none</option>
            {projects.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </span>

        <span className={propLabelClass}>priority</span>
        <select
          aria-label={fieldLabel("Priority", "priority")}
          value={draft?.priority ?? priority}
          className={propFieldClass}
          onChange={(event) => {
            const value = event.currentTarget.value as TaskPriority;
            setPriority(value);
            if (autosave) change("priority", value as never, 0); else save({ priority: value });
          }}
        >
          <option value="none">none</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>

        <span className={`${propLabelClass} self-start pt-1`}>tags</span>
        <span className="flex min-w-0 flex-wrap gap-1.5">
          {tags.map((tag) => {
            const currentTagIds = draft?.tag_ids ?? tagIds;
            const checked = currentTagIds.includes(tag.id);
            return (
              <label key={tag.id} className="inline-flex cursor-pointer items-center">
                <input
                  type="checkbox"
                  className="peer sr-only"
                  checked={checked}
                  onChange={() => {
                    const nextTagIds = checked ? currentTagIds.filter((id) => id !== tag.id) : [...currentTagIds, tag.id];
                    setTagIds(nextTagIds);
                    if (autosave) change("tag_ids", nextTagIds as never, 0); else save({ tag_ids: nextTagIds });
                  }}
                />
                <span className="rounded-full border border-slate-200 bg-white px-2 py-[2px] text-[11px] font-medium text-slate-600 transition-colors duration-200 ease-smooth hover:border-slate-300 peer-checked:border-brand-primary peer-checked:bg-info-bg peer-checked:text-info-fg peer-focus-visible:shadow-ring-focus">
                  #{tag.name.replace(/^[#@]/, "")}
                </span>
              </label>
            );
          })}
        </span>

        <span className={propLabelClass}>waiting</span>
        <input
          ref={waitingRef}
          aria-label={fieldLabel("Waiting for", "waiting_for")}
          value={draft?.waiting_for ?? waitingFor}
          placeholder="never"
          className={`${propFieldClass} scroll-mb-[88px]`}
          onChange={(event) => { setWaitingFor(event.currentTarget.value); setWaitingRequired(false); change("waiting_for", event.currentTarget.value as never, task.state === "waiting" ? 500 : 60_000); }}
          onBlur={() => {
            if (autosave) autosave.flush("waiting_for");
            else if (task.state === "waiting" && waitingFor.trim() !== (task.waiting_for ?? "")) {
              save({ waiting_for: waitingFor.trim() });
            }
          }}
        />
        {waitingRequired ? <span className="col-start-2 text-xs text-[#92400e]">Add who or what you’re waiting for</span> : null}
      </div>

      <div className="flex flex-col gap-2 border-t border-slate-200 px-4 py-3">
        <div className="flex flex-col gap-1.5">
          <h3 className="m-0 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Details</h3>
          <textarea
            aria-label={fieldLabel("Details", "details")}
            value={draft?.details ?? details}
            rows={2}
            placeholder="Notes, links, whatever helps you pick this up again"
            className={`${dashedInputClass} resize-none`}
            onChange={(event) => { setDetails(event.currentTarget.value); change("details", event.currentTarget.value as never, 750); }}
            onBlur={() => {
              const nextDetails = details.trim();
              if (autosave) autosave.flush("details");
              else if (nextDetails !== (task.details ?? "")) {
                save({ details: nextDetails || null });
              }
            }}
          />
        </div>
      </div>

      <AgentTaskRelay task={task} isTerminal={isTerminal} />

      <div className="flex flex-col gap-2 border-t border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <h3 className="m-0 flex-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">
            {subtasks.length ? `Subtasks · ${doneSubtasks} / ${subtasks.length}` : "Subtasks"}
          </h3>
          {subtasks.length ? (
            <span className="text-[11px] text-slate-400">{Math.round((doneSubtasks / subtasks.length) * 100)}%</span>
          ) : null}
        </div>
        {subtasks.length ? (
          <div className="h-[3px] overflow-hidden rounded-full bg-surface-sunken">
            <i
              className="block h-full bg-brand-primary transition-[width] duration-200 ease-smooth"
              style={{ width: `${(doneSubtasks / subtasks.length) * 100}%` }}
            />
          </div>
        ) : null}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const title = String(form.get("subtask_title") ?? "").trim();
            if (title) {
              onCreateSubtask(task, title);
              event.currentTarget.reset();
            }
          }}
        >
          <input name="subtask_title" aria-label="New subtask title" placeholder="Add a subtask" className={dashedInputClass} />
        </form>
        {subtasks.map((subtask) => {
          const done = subtask.state !== "open";
          return (
            <div key={subtask.id} className="flex items-center gap-2 text-[13px] text-slate-700">
              <button
                type="button"
                className={`flex h-[14px] w-[14px] shrink-0 items-center justify-center rounded-full border-[1.5px] transition-colors duration-200 ease-smooth ${
                  done
                    ? "border-brand-primary bg-brand-primary text-white"
                    : "border-slate-300 bg-white text-transparent hover:border-brand-primary"
                }`}
                aria-label={done ? `Reopen ${subtask.title}` : `Complete ${subtask.title}`}
                onClick={() => onTransitionSubtask(task, subtask, done ? "reopen" : "complete")}
              >
                <Check className="h-[9px] w-[9px]" aria-hidden />
              </button>
              <span className={done ? "text-slate-500 line-through" : ""}>{subtask.title}</span>
            </div>
          );
        })}
      </div>

      <div className="flex flex-col gap-2 border-t border-slate-200 px-4 py-3">
        <h3 className="m-0 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Comments</h3>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const body = String(form.get("comment_body") ?? "").trim();
            if (body) {
              onCreateComment(task, body);
              event.currentTarget.reset();
            }
          }}
        >
          <input name="comment_body" aria-label="New comment" placeholder="Add a comment" className={dashedInputClass} />
        </form>
        {comments.map((comment) => (
          <div key={comment.id} className="text-[12.5px] leading-normal text-slate-700">
            {comment.body}
            <span className="mt-0.5 block text-[11px] text-slate-400">
              {comment.actor_id.slice(0, 2).toUpperCase()} · {formatCommentTime(comment.created_at)}
            </span>
          </div>
        ))}
      </div>

      <div className="sticky bottom-0 mt-auto flex items-center gap-1.5 border-t border-slate-200 bg-surface-base px-3 py-2.5">
        <Button
          variant="secondary"
          size="sm"
          leftIcon={<Network aria-hidden />}
          onClick={() => notify("Thinking canvas isn't built yet — placeholder")}
        >
          Think
        </Button>
        <span aria-hidden className="ml-auto font-mono text-[10.5px] text-slate-400">
          ⌘\
        </span>
      </div>
    </div>
  );
}

/**
 * Existing task runs remain observable and actionable after rollout is disabled.
 * The flag gates only creation of new hand-offs; it must not strand work that
 * already left BrainBuddy.
 */
function AgentTaskRelay({ task, isTerminal }: { task: TaskResponse; isTerminal: boolean }): React.JSX.Element | null {
  const user = useAuthStore((state) => state.user);
  const handoffEnabled = hasFeatureFlag(user, "external_agent_relay");
  const [reviewing, setReviewing] = useState(false);
  const runsQuery = useAgentRuns(task.id, Boolean(user));

  useEffect(() => {
    setReviewing(false);
  }, [task.id, handoffEnabled]);

  // Some older deployments/tests may answer a non-list projection while this
  // read is rolling out independently. Fail closed to an empty monitor rather
  // than crashing the entire task panel.
  const runs = Array.isArray(runsQuery.data) ? runsQuery.data : [];
  const canStartHandoff = handoffEnabled && !isTerminal;

  return (
    <>
      {runs.length || canStartHandoff ? (
        <div className="flex flex-col gap-2 border-t border-slate-200 px-4 py-3">
          <div className="flex items-center gap-2">
            <h3 className="m-0 flex-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">
              External agent
            </h3>
            {canStartHandoff ? (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                leftIcon={<Bot className="h-[13px] w-[13px]" aria-hidden />}
                onClick={() => setReviewing(true)}
              >
                Hand to agent
              </Button>
            ) : null}
          </div>
          {!runs.length && canStartHandoff ? (
            <p className="m-0 text-[12px] text-slate-500">
              Review exactly what would be sent before anything leaves BrainBuddy.
            </p>
          ) : null}
        </div>
      ) : null}

      <AgentRunSection taskId={task.id} runs={runs} isLoading={runsQuery.isLoading} error={runsQuery.error} />

      {reviewing && canStartHandoff ? (
        <AgentHandoffOverlay
          taskId={task.id}
          taskTitle={task.title}
          onClose={() => setReviewing(false)}
          onDispatched={() => setReviewing(false)}
        />
      ) : null}
    </>
  );
}

/** Grows the title textarea to its content so long titles wrap fully. */
function autosizeTitle(el: HTMLTextAreaElement | null): void {
  if (el) {
    const borders = el.offsetHeight - el.clientHeight;
    el.style.height = "0";
    el.style.height = `${el.scrollHeight + borders}px`;
  }
}

function formatCommentTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
