import { Bot, Check, ChevronRight, Inbox, MoreHorizontal, Network, X } from "lucide-react";
import { useEffect, useState } from "react";
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
  "fixed bottom-0 right-0 top-14 z-40 flex w-[360px] max-w-[90vw] flex-col overflow-y-auto border-l border-slate-200 bg-white shadow-floating motion-safe:animate-slide-in-right min-[1100px]:static min-[1100px]:z-auto min-[1100px]:w-[320px] min-[1100px]:max-w-none min-[1100px]:shrink-0 min-[1100px]:animate-none min-[1100px]:shadow-none";

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
        <span className="relative ml-auto flex items-center gap-1">
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
                      onTransition(task, "cancel");
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
          key={`${task.id}-${task.revision}`}
          task={task}
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

function TaskDetailBody({
  task,
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

  const save = (payload: Omit<TaskDetailSavePayload, "expected_revision">) =>
    onSave(task, { ...payload, expected_revision: task.revision });

  const project = task.project_id ? projects.find((item) => item.id === task.project_id) : undefined;
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
          onClick={() => onTransition(task, isTerminal ? "reopen" : "complete", isTerminal ? "inbox" : undefined)}
        >
          {task.state === "cancelled" ? <X className="h-2.5 w-2.5" aria-hidden /> : <Check className="h-[11px] w-[11px]" aria-hidden />}
        </button>
        {/* A textarea so long titles wrap like the prototype's static title;
            Enter commits instead of inserting a newline. */}
        <textarea
          aria-label="Title"
          defaultValue={task.title}
          rows={1}
          ref={autosizeTitle}
          className={`w-full min-w-0 resize-none overflow-hidden rounded-md border border-transparent bg-transparent px-1 py-0.5 text-[15px] font-semibold leading-[1.35] outline-none transition-colors duration-200 ease-smooth hover:border-slate-200 focus:border-brand-primary ${
            isTerminal ? "text-slate-500 line-through" : "text-slate-900"
          }`}
          onInput={(event) => autosizeTitle(event.currentTarget)}
          onBlur={(event) => {
            const title = event.currentTarget.value.trim();
            if (title && title !== task.title) {
              save({ title });
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

      <div className="grid grid-cols-[64px_1fr] items-center gap-x-2.5 gap-y-2 px-4 pb-3.5 text-[12.5px]">
        <span className={propLabelClass}>date</span>
        <input
          aria-label="Due date"
          type="date"
          defaultValue={task.due_date ?? ""}
          className={propFieldClass}
          onChange={(event) => save({ due_date: event.currentTarget.value || null })}
        />

        <span className={propLabelClass}>list</span>
        <select
          aria-label="List"
          value={isTerminal ? "" : task.state}
          className={propFieldClass}
          onChange={(event) => {
            const target = event.currentTarget.value as OpenTaskState | "";
            if (!target) {
              return;
            }
            onTransition(task, isTerminal ? "reopen" : "move", target, target === "waiting" ? waitingFor : undefined);
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
            aria-label="Project"
            value={task.project_id ?? ""}
            className={propFieldClass}
            onChange={(event) => save({ project_id: event.currentTarget.value || null })}
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
          aria-label="Priority"
          value={task.priority}
          className={propFieldClass}
          onChange={(event) => save({ priority: event.currentTarget.value as TaskPriority })}
        >
          <option value="none">none</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>

        <span className={`${propLabelClass} self-start pt-1`}>tags</span>
        <span className="flex min-w-0 flex-wrap gap-1.5">
          {tags.map((tag) => {
            const checked = task.tag_ids.includes(tag.id);
            return (
              <label key={tag.id} className="inline-flex cursor-pointer items-center">
                <input
                  type="checkbox"
                  className="peer sr-only"
                  checked={checked}
                  onChange={() =>
                    save({
                      tag_ids: checked ? task.tag_ids.filter((id) => id !== tag.id) : [...task.tag_ids, tag.id]
                    })
                  }
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
          aria-label="Waiting for"
          value={waitingFor}
          placeholder="never"
          className={propFieldClass}
          onChange={(event) => setWaitingFor(event.currentTarget.value)}
          onBlur={() => {
            if (task.state === "waiting" && waitingFor.trim() !== (task.waiting_for ?? "")) {
              save({ waiting_for: waitingFor.trim() });
            }
          }}
        />
      </div>

      <div className="flex flex-col gap-2 border-t border-slate-200 px-4 py-3">
        <div className="flex flex-col gap-1.5">
          <h3 className="m-0 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Details</h3>
          <textarea
            aria-label="Details"
            defaultValue={task.details ?? ""}
            rows={2}
            placeholder="Notes, links, whatever helps you pick this up again"
            className={`${dashedInputClass} resize-none`}
            onBlur={(event) => {
              const details = event.currentTarget.value.trim();
              if (details !== (task.details ?? "")) {
                save({ details: details || null });
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
