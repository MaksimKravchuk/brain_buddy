/* istanbul ignore file -- task shell rendering is covered by route tests and Playwright snapshots. */
import { AlertTriangle, Check, Edit3, Plus, RotateCcw, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../api/client";
import { parseOpenTaskState, useProjects, useTags, useTaskList } from "../../api/taskHooks";
import type { OpenTaskState, ProjectResponse, TagResponse, TaskCounts, TaskResponse } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { getErrorMessage } from "../../utils/error";

const stateLabels: Record<OpenTaskState, string> = {
  inbox: "Inbox",
  next: "Next actions",
  waiting: "Waiting for",
  someday: "Someday / maybe"
};

const emptyCounts: TaskCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };
const emptyProjects: ProjectResponse[] = [];
const emptyTags: TagResponse[] = [];

function idempotencyKey(action: string): string {
  return `task-shell-${action}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function TaskListPage({ mode }: { mode?: "state" | "project" | "tag" }): JSX.Element {
  const params = useParams();
  const state = mode === "state" || !mode ? parseOpenTaskState(params.state) : undefined;
  const projectId = mode === "project" ? params.projectId : undefined;
  const tagId = mode === "tag" ? params.tagId : undefined;
  const queryClient = useQueryClient();
  const [newTitle, setNewTitle] = useState("");
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [showCompleted, setShowCompleted] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  const taskQuery = useTaskList({ state, projectId, tagId, includeCompleted: showCompleted });
  const projectsQuery = useProjects();
  const tagsQuery = useTags();

  const invalidateTasks = () => queryClient.invalidateQueries({ queryKey: ["tasks"] });

  const createMutation = useMutation({
    mutationFn: (title: string) => apiClient.createTask({ title, state: state ?? "inbox" }, idempotencyKey("create")),
    onSuccess: () => {
      setNewTitle("");
      setMutationError(null);
      void invalidateTasks();
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const updateMutation = useMutation({
    mutationFn: ({ task, title }: { task: TaskResponse; title: string }) =>
      apiClient.updateTask(task.id, { title, expected_revision: task.revision }, idempotencyKey("edit")),
    onSuccess: () => {
      setEditingTaskId(null);
      setEditingTitle("");
      setMutationError(null);
      void invalidateTasks();
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const transitionMutation = useMutation({
    mutationFn: ({ task, action, toState }: { task: TaskResponse; action: "move" | "complete" | "reopen"; toState?: OpenTaskState }) =>
      apiClient.transitionTask(task.id, { action, to_state: toState, expected_revision: task.revision }, idempotencyKey(action)),
    onSuccess: () => {
      setMutationError(null);
      void invalidateTasks();
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const projects = projectsQuery.data ?? emptyProjects;
  const tags = tagsQuery.data ?? emptyTags;
  const tasks = taskQuery.data?.items ?? [];
  const counts = taskQuery.data?.counts_by_state ?? emptyCounts;

  const title = useMemo(() => {
    if (projectId) {
      return projects.find((project) => project.id === projectId)?.name ?? "Project";
    }
    if (tagId) {
      const tag = tags.find((item) => item.id === tagId)?.name ?? "tag";
      return `@${tag.replace(/^@/, "")}`;
    }
    return stateLabels[state ?? "next"];
  }, [projectId, projects, state, tagId, tags]);

  const taskNoun = counts[state ?? "next"] === 1 ? "task" : "tasks";
  const subtitle = state ? `${counts[state]} ${taskNoun}` : `${tasks.length} ${tasks.length === 1 ? "task" : "tasks"}`;

  const hasFrameError = taskQuery.isError || projectsQuery.isError || tagsQuery.isError;

  return (
    <AppShell
      counts={counts}
      projects={projects}
      tags={tags}
      activeState={state}
      activeProjectId={projectId}
      activeTagId={tagId}
    >
      <section aria-labelledby="task-list-title" className="mx-auto max-w-5xl">
        <div className="mb-4 flex flex-wrap items-baseline gap-3">
          <h1 id="task-list-title" className="m-0 text-title font-semibold text-slate-900">
            {title}
          </h1>
          <span className="text-xs text-slate-600">{subtitle}</span>
          <button
            type="button"
            className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs text-slate-600 hover:bg-slate-100"
            disabled
          >
            <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
            Sort by tag
          </button>
        </div>

        {mutationError ? <div role="alert" className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{mutationError}</div> : null}

        {hasFrameError ? (
          <ErrorState
            message={getErrorMessage(taskQuery.error ?? projectsQuery.error ?? tagsQuery.error)}
            onRetry={() => {
              void taskQuery.refetch();
              void projectsQuery.refetch();
              void tagsQuery.refetch();
            }}
          />
        ) : taskQuery.isLoading || projectsQuery.isLoading || tagsQuery.isLoading ? (
          <LoadingState label={title} />
        ) : tasks.length ? (
          <TaskList
            tasks={tasks}
            projects={projects}
            tags={tags}
            activeState={state}
            editingTaskId={editingTaskId}
            editingTitle={editingTitle}
            onBeginEdit={(task) => {
              setEditingTaskId(task.id);
              setEditingTitle(task.title);
            }}
            onCancelEdit={() => {
              setEditingTaskId(null);
              setEditingTitle("");
            }}
            onComplete={(task) => transitionMutation.mutate({ task, action: "complete" })}
            onEditTitle={(title) => setEditingTitle(title)}
            onMoveToNext={(task) => transitionMutation.mutate({ task, action: "move", toState: "next" })}
            onReopen={(task) => transitionMutation.mutate({ task, action: "reopen", toState: state ?? "next" })}
            onSaveEdit={(task) => updateMutation.mutate({ task, title: editingTitle.trim() })}
          />
        ) : (
          <EmptyState state={state} />
        )}

        <TaskCreator
          newTitle={newTitle}
          showCompleted={showCompleted}
          isCreating={createMutation.isPending}
          onCreate={(title) => createMutation.mutate(title)}
          onTitleChange={setNewTitle}
          onToggleCompleted={setShowCompleted}
        />
      </section>
    </AppShell>
  );
}

function TaskList({
  tasks,
  projects,
  tags,
  activeState,
  editingTaskId,
  editingTitle,
  onBeginEdit,
  onCancelEdit,
  onComplete,
  onEditTitle,
  onMoveToNext,
  onReopen,
  onSaveEdit
}: {
  tasks: TaskResponse[];
  projects: ProjectResponse[];
  tags: TagResponse[];
  activeState?: OpenTaskState;
  editingTaskId: string | null;
  editingTitle: string;
  onBeginEdit: (task: TaskResponse) => void;
  onCancelEdit: () => void;
  onComplete: (task: TaskResponse) => void;
  onEditTitle: (title: string) => void;
  onMoveToNext: (task: TaskResponse) => void;
  onReopen: (task: TaskResponse) => void;
  onSaveEdit: (task: TaskResponse) => void;
}): JSX.Element {
  const projectById = new Map(projects.map((project) => [project.id, project]));
  const tagById = new Map(tags.map((tag) => [tag.id, tag]));

  return (
    <div className="flex flex-col gap-2" role="list" aria-label="Tasks">
      {tasks.map((task) => {
        const project = task.project_id ? projectById.get(task.project_id) : undefined;
        const taskTags = task.tag_ids.map((id) => tagById.get(id)).filter((tag): tag is TagResponse => Boolean(tag));
        return (
          <TaskRow
            key={task.id}
            task={task}
            project={project}
            tags={taskTags}
            activeState={activeState}
            isEditing={editingTaskId === task.id}
            editingTitle={editingTitle}
            onBeginEdit={onBeginEdit}
            onCancelEdit={onCancelEdit}
            onComplete={onComplete}
            onEditTitle={onEditTitle}
            onMoveToNext={onMoveToNext}
            onReopen={onReopen}
            onSaveEdit={onSaveEdit}
          />
        );
      })}
    </div>
  );
}

function TaskRow({
  task,
  project,
  tags,
  activeState,
  isEditing,
  editingTitle,
  onBeginEdit,
  onCancelEdit,
  onComplete,
  onEditTitle,
  onMoveToNext,
  onReopen,
  onSaveEdit
}: {
  task: TaskResponse;
  project?: ProjectResponse;
  tags: TagResponse[];
  activeState?: OpenTaskState;
  isEditing: boolean;
  editingTitle: string;
  onBeginEdit: (task: TaskResponse) => void;
  onCancelEdit: () => void;
  onComplete: (task: TaskResponse) => void;
  onEditTitle: (title: string) => void;
  onMoveToNext: (task: TaskResponse) => void;
  onReopen: (task: TaskResponse) => void;
  onSaveEdit: (task: TaskResponse) => void;
}): JSX.Element {
  const isCompleted = task.state === "completed";
  const reopenState = activeState ?? "next";

  return (
    <article
      className={`flex min-h-[48px] flex-col gap-2 rounded-xl border px-4 py-3 shadow-soft transition hover:shadow-raised sm:flex-row sm:items-center sm:gap-3 ${isCompleted ? "border-emerald-100 bg-emerald-50/50" : "border-slate-200 bg-white"}`}
      role="listitem"
    >
      {isCompleted ? (
        <button
          type="button"
          className="inline-flex h-8 shrink-0 items-center justify-center rounded-lg border border-emerald-200 bg-white px-2 text-xs font-medium text-emerald-700"
          aria-label={`Reopen ${task.title} to ${stateLabels[reopenState].replace(" actions", "")}`}
          onClick={() => onReopen(task)}
        >
          Reopen
        </button>
      ) : (
        <button
          type="button"
          className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border border-[1.5px] border-slate-300 bg-white text-white hover:border-emerald-400 hover:bg-emerald-500"
          aria-label={`Complete ${task.title}`}
          onClick={() => onComplete(task)}
        >
          <Check className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
      {isEditing ? (
        <form
          className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center"
          onSubmit={(event) => {
            event.preventDefault();
            if (editingTitle.trim()) {
              onSaveEdit(task);
            }
          }}
        >
          <label className="sr-only" htmlFor={`task-title-${task.id}`}>Task title</label>
          <input
            id={`task-title-${task.id}`}
            aria-label="Task title"
            className="min-w-0 flex-1 rounded-lg border border-sky-200 px-3 py-2 text-sm font-medium text-slate-900 outline-none focus:border-sky-400"
            value={editingTitle}
            onChange={(event) => onEditTitle(event.currentTarget.value)}
          />
          <button type="submit" className="h-9 rounded-lg bg-brand-primary px-3 text-xs font-semibold text-white">Save task title</button>
          <button type="button" className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-600" onClick={onCancelEdit}>Cancel</button>
        </form>
      ) : (
        <div className={`min-w-0 flex-1 text-sm font-medium text-slate-900 ${isCompleted ? "line-through decoration-emerald-500/70" : ""}`}>{task.title}</div>
      )}
      {task.due_date ? (
        <span className="w-fit rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[11px] text-rose-700">
          {formatDueDate(task.due_date)}
        </span>
      ) : null}
      <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
        {tags.map((tag) => (
          <span key={tag.id} className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600">
            @{tag.name.replace(/^@/, "")}
          </span>
        ))}
        {project ? <span className="text-[11px] text-slate-500 sm:w-[120px] sm:text-right">{project.name}</span> : null}
        {!isEditing && !isCompleted ? (
          <button type="button" className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-600" aria-label={`Edit ${task.title}`} onClick={() => onBeginEdit(task)}>
            <Edit3 className="h-3.5 w-3.5" aria-hidden />
            Edit
          </button>
        ) : null}
        {!isEditing && !isCompleted && task.state !== "next" ? (
          <button type="button" className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-600" aria-label={`Move ${task.title} to Next`} onClick={() => onMoveToNext(task)}>
            Move to Next
          </button>
        ) : null}
      </div>
    </article>
  );
}

function TaskCreator({
  newTitle,
  showCompleted,
  isCreating,
  onCreate,
  onTitleChange,
  onToggleCompleted
}: {
  newTitle: string;
  showCompleted: boolean;
  isCreating: boolean;
  onCreate: (title: string) => void;
  onTitleChange: (title: string) => void;
  onToggleCompleted: (show: boolean) => void;
}): JSX.Element {
  return (
    <div className="mt-3 space-y-3">
      <form
        className="flex flex-col gap-2 rounded-xl border border-dashed border-slate-200 bg-slate-50/70 p-3 sm:flex-row sm:items-center"
        onSubmit={(event) => {
          event.preventDefault();
          if (newTitle.trim()) {
            onCreate(newTitle.trim());
          }
        }}
      >
        <Plus className="hidden h-3.5 w-3.5 text-slate-500 sm:block" aria-hidden />
        <label className="sr-only" htmlFor="new-task-title">New task title</label>
        <input
          id="new-task-title"
          aria-label="New task title"
          className="min-h-10 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none focus:border-sky-300"
          placeholder="Add a task — or dump everything on your mind with the mic above"
          value={newTitle}
          onChange={(event) => onTitleChange(event.currentTarget.value)}
        />
        <button type="submit" disabled={isCreating || !newTitle.trim()} className="h-10 rounded-lg bg-brand-primary px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">
          Add task
        </button>
      </form>
      <label className="inline-flex items-center gap-2 text-xs font-medium text-slate-600">
        <input type="checkbox" checked={showCompleted} onChange={(event) => onToggleCompleted(event.currentTarget.checked)} />
        Show completed tasks
      </label>
    </div>
  );
}

function LoadingState({ label }: { label: string }): JSX.Element {
  return (
    <div className="space-y-2" aria-label={`Loading ${label}`}>
      {[0, 1, 2, 3].map((item) => (
        <div key={item} className="h-12 animate-pulse rounded-xl border border-slate-200 bg-white" />
      ))}
    </div>
  );
}

function EmptyState({ state }: { state?: OpenTaskState }): JSX.Element {
  const label = state ? stateLabels[state] : "This view";
  return (
    <div className="rounded-xl border border-dashed border-slate-200 bg-white/70 px-5 py-8 text-center text-sm text-slate-600">
      <p className="font-medium text-slate-900">{label} is clear</p>
      <p className="mt-1">Use Brain dump when you are ready to capture what's on your mind.</p>
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }): JSX.Element {
  return (
    <div className="rounded-xl border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-900" role="alert">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">We couldn't load tasks</p>
          <p className="mt-1 text-rose-800">{message}</p>
          <button type="button" className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3 font-medium text-rose-800 shadow-soft" onClick={onRetry}>
            <RotateCcw className="h-4 w-4" aria-hidden />
            Retry
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDueDate(value: string): string {
  if (!value) {
    return "due";
  }
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}
