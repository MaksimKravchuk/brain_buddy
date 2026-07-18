/* istanbul ignore file -- task shell rendering is covered by route tests and Playwright snapshots. */
import { AlertTriangle, Check, Edit3, Plus, RotateCcw, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../api/client";
import { parseOpenTaskState, parseTaskDateView, useProjects, useTags, useTaskDetail, useTaskList } from "../../api/taskHooks";
import type { OpenTaskState, ProjectResponse, TagResponse, TaskCounts, TaskPriority, TaskResponse, TaskSort, TaskSubtaskResponse, TaskUpdateRequest } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { getErrorMessage } from "../../utils/error";
import { applySmartAddSuggestion, parseSmartAdd, smartAddChips, smartAddSuggestions } from "./smartAdd";
import type { SmartAddDraft, SmartAddSuggestion } from "./smartAdd";
import { SmartAddSuggestions } from "./SmartAddSuggestions";

const stateLabels: Record<OpenTaskState, string> = {
  inbox: "Inbox",
  next: "Next actions",
  waiting: "Waiting for",
  someday: "Someday / maybe"
};

const dateViewLabels = {
  overdue: "Overdue",
  today: "Today",
  upcoming: "Upcoming"
} as const;

const emptyCounts: TaskCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };
const emptyProjects: ProjectResponse[] = [];
const emptyTags: TagResponse[] = [];
const openStateOptions: OpenTaskState[] = ["inbox", "next", "waiting", "someday"];

function idempotencyKey(action: string): string {
  return `task-shell-${action}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function TaskListPage({ mode }: { mode?: "state" | "project" | "tag" }): JSX.Element {
  const params = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const dateView = mode === "state" || !mode ? parseTaskDateView(params.state) : undefined;
  const state = (mode === "state" || !mode) && !dateView ? parseOpenTaskState(params.state) : undefined;
  const projectId = mode === "project" ? params.projectId : undefined;
  const tagId = mode === "tag" ? params.tagId : undefined;
  const taskId = params.taskId;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [newTitle, setNewTitle] = useState("");
  const [newWaitingFor, setNewWaitingFor] = useState("");
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [showCompleted, setShowCompleted] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  const sort = parseTaskSort(searchParams.get("sort"));
  const searchQuery = searchParams.get("q") ?? "";
  const today = localDateIso();
  const isInboxProductView = state === "inbox" && !projectId && !tagId && !dateView;
  const taskQuery = useTaskList({
    state,
    projectId,
    tagId,
    unassignedProject: isInboxProductView,
    includeCompleted: showCompleted,
    includeCancelled: showCompleted,
    q: searchQuery,
    sort,
    dueBefore: dateView === "overdue" ? today : undefined,
    dueOn: dateView === "today" ? today : undefined,
    dueAfter: dateView === "upcoming" ? today : undefined
  });
  const inboxBadgeQuery = useTaskList({ state: "inbox", unassignedProject: true, limit: 1 });
  const detailQuery = useTaskDetail(taskId);
  const projectsQuery = useProjects();
  const tagsQuery = useTags();

  const projects = projectsQuery.data ?? emptyProjects;
  const tags = tagsQuery.data ?? emptyTags;
  const tasks = taskQuery.data?.items ?? [];
  const counts = taskQuery.data?.counts_by_state ?? emptyCounts;

  const invalidateTasks = () => queryClient.invalidateQueries({ queryKey: ["tasks"] });
  const listPath = projectId
    ? `/projects/${projectId}`
    : tagId
      ? `/tags/${tagId}`
      : `/tasks/${params.state ?? "next"}`;

  const createMutation = useMutation({
    mutationFn: (draft: SmartAddDraft) => {
      const payload = {
        title: draft.cleanTitle,
        state: state ?? "inbox",
        ...(state === "waiting" ? { waiting_for: newWaitingFor.trim() } : {})
      };
      if (draft.hasCompletedTokens) {
        return apiClient.smartAddTask(
          {
            ...payload,
            project: draft.project,
            tags: draft.tags
          },
          idempotencyKey("smart-add")
        ).then((response) => response.task);
      }
      return apiClient.createTask(
        {
          ...payload,
          ...(projectId ? { project_id: projectId } : {}),
          ...(tagId ? { tag_ids: [tagId] } : {})
        },
        idempotencyKey("create")
      );
    },
    onSuccess: () => {
      setNewTitle("");
      setNewWaitingFor("");
      setMutationError(null);
      void invalidateTasks();
      void queryClient.invalidateQueries({ queryKey: ["tasks", "projects"] });
      void queryClient.invalidateQueries({ queryKey: ["tasks", "tags"] });
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const updateMutation = useMutation({
    mutationFn: ({ task, payload }: { task: TaskResponse; payload: Omit<TaskUpdateRequest, "expected_revision"> }) =>
      apiClient.updateTask(task.id, { ...payload, expected_revision: task.revision }, idempotencyKey("edit")),
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

  const detailUpdateMutation = useMutation({
    mutationFn: ({ task, payload }: { task: TaskResponse; payload: Parameters<typeof apiClient.updateTask>[1] }) =>
      apiClient.updateTask(task.id, payload, idempotencyKey("detail-edit")),
    onSuccess: () => {
      setMutationError(null);
      void invalidateTasks();
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const detailTransitionMutation = useMutation({
    mutationFn: ({ task, action, toState, waitingFor }: { task: TaskResponse; action: "move" | "complete" | "reopen" | "cancel"; toState?: OpenTaskState; waitingFor?: string }) =>
      apiClient.transitionTask(
        task.id,
        { action, to_state: toState, waiting_for: waitingFor || undefined, expected_revision: task.revision },
        idempotencyKey(`detail-${action}`)
      ),
    onSuccess: () => {
      setMutationError(null);
      void invalidateTasks();
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const subtaskCreateMutation = useMutation({
    mutationFn: ({ task, title }: { task: TaskResponse; title: string }) =>
      apiClient.createSubtask(task.id, { title }, idempotencyKey("subtask-create")),
    onSuccess: () => {
      setMutationError(null);
      void invalidateTasks();
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const subtaskTransitionMutation = useMutation({
    mutationFn: ({ task, subtask, action }: { task: TaskResponse; subtask: TaskSubtaskResponse; action: "complete" | "reopen" | "cancel" }) =>
      apiClient.transitionSubtask(task.id, subtask.id, { action, expected_revision: subtask.revision }, idempotencyKey(`subtask-${action}`)),
    onSuccess: () => {
      setMutationError(null);
      void invalidateTasks();
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const commentCreateMutation = useMutation({
    mutationFn: ({ task, body }: { task: TaskResponse; body: string }) =>
      apiClient.createComment(task.id, { body }, idempotencyKey("comment-create")),
    onSuccess: () => {
      setMutationError(null);
      void invalidateTasks();
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const projectMutation = useMutation({
    mutationFn: ({ action, project, name }: { action: "create" | "rename" | "archive"; project?: ProjectResponse; name?: string }) => {
      if (action === "create") {
        return apiClient.createProject({ name: name ?? "" }, idempotencyKey("create-project"));
      }
      if (!project) {
        throw new Error("Project is required.");
      }
      if (action === "archive") {
        return apiClient.archiveProject(project.id, project.revision, idempotencyKey("archive-project"));
      }
      return apiClient.updateProject(project.id, { name, expected_revision: project.revision }, idempotencyKey("rename-project"));
    },
    onSuccess: (_project, variables) => {
      setMutationError(null);
      void invalidateTasks();
      void queryClient.invalidateQueries({ queryKey: ["tasks", "projects"] });
      if (variables.action === "archive" && variables.project?.id === projectId) {
        navigate("/tasks/next");
      }
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const tagMutation = useMutation({
    mutationFn: ({ action, tag, name }: { action: "create" | "rename" | "delete"; tag?: TagResponse; name?: string }) => {
      if (action === "create") {
        return apiClient.createTag({ name: name ?? "" }, idempotencyKey("create-tag"));
      }
      if (!tag) {
        throw new Error("Tag is required.");
      }
      if (action === "delete") {
        return apiClient.deleteTag(tag.id, tag.revision, idempotencyKey("delete-tag"));
      }
      return apiClient.updateTag(tag.id, { name, expected_revision: tag.revision }, idempotencyKey("rename-tag"));
    },
    onSuccess: (_tag, variables) => {
      setMutationError(null);
      void invalidateTasks();
      void queryClient.invalidateQueries({ queryKey: ["tasks", "tags"] });
      if (variables.action === "delete" && variables.tag?.id === tagId) {
        navigate("/tasks/next");
      }
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const canonicalInboxCount = inboxBadgeQuery.data?.counts_by_state.inbox ?? (isInboxProductView ? counts.inbox : 0);
  const shellCounts = useMemo(
    () => ({ ...counts, inbox: canonicalInboxCount }),
    [canonicalInboxCount, counts]
  );

  const title = useMemo(() => {
    if (projectId) {
      return projects.find((project) => project.id === projectId)?.name ?? "Project";
    }
    if (tagId) {
      const tag = tags.find((item) => item.id === tagId)?.name ?? "tag";
      return `#${tag.replace(/^[#@]/, "")}`;
    }
    if (dateView) {
      return dateViewLabels[dateView];
    }
    return stateLabels[state ?? "next"];
  }, [dateView, projectId, projects, state, tagId, tags]);

  const taskNoun = counts[state ?? "next"] === 1 ? "task" : "tasks";
  const subtitle = state ? `${counts[state]} ${taskNoun}` : `${tasks.length} ${tasks.length === 1 ? "task" : "tasks"}`;

  const hasFrameError = taskQuery.isError || projectsQuery.isError || tagsQuery.isError;

  return (
    <AppShell
      counts={shellCounts}
      projects={projects}
      tags={tags}
      activeState={state}
      activeProjectId={projectId}
      activeTagId={tagId}
      onCreateProject={(name) => projectMutation.mutate({ action: "create", name })}
      onRenameProject={(project, name) => projectMutation.mutate({ action: "rename", project, name })}
      onArchiveProject={(project) => projectMutation.mutate({ action: "archive", project })}
      onCreateTag={(name) => tagMutation.mutate({ action: "create", name })}
      onRenameTag={(tag, name) => tagMutation.mutate({ action: "rename", tag, name })}
      onDeleteTag={(tag) => tagMutation.mutate({ action: "delete", tag })}
    >
      <section aria-labelledby="task-list-title" className="mx-auto max-w-5xl">
        <div className="mb-4 flex flex-wrap items-baseline gap-3">
          <h1 id="task-list-title" className="m-0 text-title font-semibold text-slate-900">
            {title}
          </h1>
          <span className="text-xs text-slate-600">{subtitle}</span>
          <label className="ml-auto inline-flex items-center gap-2 text-xs text-slate-600">
            Sort
            <select
              aria-label="Sort tasks"
              className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-700"
              value={sort}
              onChange={(event) => {
                const next = new URLSearchParams(searchParams);
                const value = parseTaskSort(event.currentTarget.value);
                if (value === "manual") {
                  next.delete("sort");
                } else {
                  next.set("sort", value);
                }
                setSearchParams(next, { replace: true });
              }}
            >
              <option value="manual">Manual</option>
              <option value="due">Due date</option>
              <option value="priority">Priority</option>
              <option value="title">Title</option>
            </select>
          </label>
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
            taskPathBase={listPath}
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
            onProjectChange={(task, nextProjectId) =>
              updateMutation.mutate({ task, payload: { project_id: nextProjectId || null } })
            }
            onAddTag={(task, tagIdToAdd) =>
              updateMutation.mutate({ task, payload: { tag_ids: Array.from(new Set([...task.tag_ids, tagIdToAdd])) } })
            }
            onRemoveTag={(task, tagIdToRemove) =>
              updateMutation.mutate({ task, payload: { tag_ids: task.tag_ids.filter((id) => id !== tagIdToRemove) } })
            }
            onSaveEdit={(task) => updateMutation.mutate({ task, payload: { title: editingTitle.trim() } })}
          />
        ) : (
          <EmptyState state={state} />
        )}

        {taskQuery.hasNextPage ? (
          <div className="mt-3 flex justify-center">
            <button
              type="button"
              className="h-9 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 shadow-soft transition hover:border-sky-200 hover:text-brand-primary disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => void taskQuery.fetchNextPage()}
              disabled={taskQuery.isFetchingNextPage}
            >
              {taskQuery.isFetchingNextPage ? "Loading more tasks…" : "Load more tasks"}
            </button>
          </div>
        ) : null}

        {dateView ? (
          <DateViewCaptureHint />
        ) : (
          <TaskCreator
            newTitle={newTitle}
            newWaitingFor={newWaitingFor}
            projects={projects}
            tags={tags}
            contextProjectId={projectId}
            contextTagId={tagId}
            state={state}
            showCompleted={showCompleted}
            isCreating={createMutation.isPending}
            onCreate={(draft) => createMutation.mutate(draft)}
            onTitleChange={setNewTitle}
            onWaitingForChange={setNewWaitingFor}
            onToggleCompleted={setShowCompleted}
          />
        )}

        {taskId ? (
          <TaskDetailPanel
            task={detailQuery.data}
            projects={projects}
            tags={tags}
            isLoading={detailQuery.isLoading}
            error={detailQuery.error}
            onClose={() => navigate(listPath)}
            onSave={(task, payload) => detailUpdateMutation.mutate({ task, payload })}
            onTransition={(task, action, toState, waitingFor) =>
              detailTransitionMutation.mutate({ task, action, toState, waitingFor })
            }
            onCreateSubtask={(task, title) => subtaskCreateMutation.mutate({ task, title })}
            onTransitionSubtask={(task, subtask, action) =>
              subtaskTransitionMutation.mutate({ task, subtask, action })
            }
            onCreateComment={(task, body) => commentCreateMutation.mutate({ task, body })}
          />
        ) : null}
      </section>
    </AppShell>
  );
}

function TaskList({
  tasks,
  projects,
  tags,
  taskPathBase,
  editingTaskId,
  editingTitle,
  onBeginEdit,
  onCancelEdit,
  onComplete,
  onEditTitle,
  onMoveToNext,
  onProjectChange,
  onAddTag,
  onRemoveTag,
  onSaveEdit
}: {
  tasks: TaskResponse[];
  projects: ProjectResponse[];
  tags: TagResponse[];
  taskPathBase: string;
  editingTaskId: string | null;
  editingTitle: string;
  onBeginEdit: (task: TaskResponse) => void;
  onCancelEdit: () => void;
  onComplete: (task: TaskResponse) => void;
  onEditTitle: (title: string) => void;
  onMoveToNext: (task: TaskResponse) => void;
  onProjectChange: (task: TaskResponse, projectId: string) => void;
  onAddTag: (task: TaskResponse, tagId: string) => void;
  onRemoveTag: (task: TaskResponse, tagId: string) => void;
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
            detailPath={`${taskPathBase}/${task.id}`}
            isEditing={editingTaskId === task.id}
            editingTitle={editingTitle}
            onBeginEdit={onBeginEdit}
            onCancelEdit={onCancelEdit}
            onComplete={onComplete}
            onEditTitle={onEditTitle}
            onMoveToNext={onMoveToNext}
            projects={projects}
            allTags={tags}
            onProjectChange={onProjectChange}
            onAddTag={onAddTag}
            onRemoveTag={onRemoveTag}
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
  detailPath,
  isEditing,
  editingTitle,
  onBeginEdit,
  onCancelEdit,
  onComplete,
  onEditTitle,
  onMoveToNext,
  projects,
  allTags,
  onProjectChange,
  onAddTag,
  onRemoveTag,
  onSaveEdit
}: {
  task: TaskResponse;
  project?: ProjectResponse;
  tags: TagResponse[];
  detailPath: string;
  isEditing: boolean;
  editingTitle: string;
  projects: ProjectResponse[];
  allTags: TagResponse[];
  onBeginEdit: (task: TaskResponse) => void;
  onCancelEdit: () => void;
  onComplete: (task: TaskResponse) => void;
  onEditTitle: (title: string) => void;
  onMoveToNext: (task: TaskResponse) => void;
  onProjectChange: (task: TaskResponse, projectId: string) => void;
  onAddTag: (task: TaskResponse, tagId: string) => void;
  onRemoveTag: (task: TaskResponse, tagId: string) => void;
  onSaveEdit: (task: TaskResponse) => void;
}): JSX.Element {
  const isTerminal = task.state === "completed" || task.state === "cancelled";
  const availableTags = allTags.filter((tag) => !task.tag_ids.includes(tag.id));

  return (
    <article
      className={`flex min-h-[48px] flex-col gap-2 rounded-xl border px-4 py-3 shadow-soft transition hover:shadow-raised sm:flex-row sm:items-center sm:gap-3 ${isTerminal ? "border-emerald-100 bg-emerald-50/50" : "border-slate-200 bg-white"}`}
      role="listitem"
    >
      {isTerminal ? (
        <span className="inline-flex h-8 shrink-0 items-center justify-center rounded-lg border border-emerald-200 bg-white px-2 text-xs font-medium text-emerald-700">
          {task.state === "completed" ? "Completed" : "Cancelled"}
        </span>
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
        <Link to={detailPath} className={`min-w-0 flex-1 text-sm font-medium text-slate-900 hover:text-brand-primary ${isTerminal ? "line-through decoration-emerald-500/70" : ""}`}>{task.title}</Link>
      )}
      {task.due_date ? (
        <span className="w-fit rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[11px] text-rose-700">
          {formatDueDate(task.due_date)}
        </span>
      ) : null}
      <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
        {project ? (
          <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600">
            @{project.name.replace(/^@/, "")}
          </span>
        ) : null}
        {tags.map((tag) => (
          <button
            key={tag.id}
            type="button"
            className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600 hover:bg-rose-50 hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={`Remove ${tag.name} from ${task.title}`}
            onClick={() => onRemoveTag(task, tag.id)}
            disabled={isTerminal}
          >
            #{tag.name.replace(/^[#@]/, "")} ×
          </button>
        ))}
        <label className="sr-only" htmlFor={`task-project-${task.id}`}>Project</label>
        <select
          id={`task-project-${task.id}`}
          aria-label={`Project for ${task.title}`}
          className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-600"
          value={project?.id ?? ""}
          onChange={(event) => onProjectChange(task, event.currentTarget.value)}
          disabled={isTerminal}
        >
          <option value="">No project</option>
          {projects.map((option) => (
            <option key={option.id} value={option.id}>{option.name}</option>
          ))}
        </select>
        <label className="sr-only" htmlFor={`task-tag-${task.id}`}>Add tag</label>
        <select
          id={`task-tag-${task.id}`}
          aria-label={`Add tag to ${task.title}`}
          className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-600"
          value=""
          onChange={(event) => {
            if (event.currentTarget.value) {
              onAddTag(task, event.currentTarget.value);
            }
          }}
          disabled={isTerminal || availableTags.length === 0}
        >
          <option value="">Add tag</option>
          {availableTags.map((option) => (
            <option key={option.id} value={option.id}>#{option.name.replace(/^[#@]/, "")}</option>
          ))}
        </select>
        {!isEditing && !isTerminal ? (
          <button type="button" className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-600" aria-label={`Edit ${task.title}`} onClick={() => onBeginEdit(task)}>
            <Edit3 className="h-3.5 w-3.5" aria-hidden />
            Edit
          </button>
        ) : null}
        {!isEditing && !isTerminal && task.state !== "next" ? (
          <button type="button" className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-600" aria-label={`Move ${task.title} to Next`} onClick={() => onMoveToNext(task)}>
            Move to Next
          </button>
        ) : null}
      </div>
    </article>
  );
}

function TaskDetailPanel({
  task,
  projects,
  tags,
  isLoading,
  error,
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
  onClose: () => void;
  onSave: (task: TaskResponse, payload: Parameters<typeof apiClient.updateTask>[1]) => void;
  onTransition: (task: TaskResponse, action: "move" | "complete" | "reopen" | "cancel", toState?: OpenTaskState, waitingFor?: string) => void;
  onCreateSubtask: (task: TaskResponse, title: string) => void;
  onTransitionSubtask: (task: TaskResponse, subtask: TaskSubtaskResponse, action: "complete" | "reopen" | "cancel") => void;
  onCreateComment: (task: TaskResponse, body: string) => void;
}): JSX.Element {
  return (
    <aside className="mt-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-raised" aria-labelledby="task-detail-title">
      <div className="mb-3 flex items-center gap-3">
        <h2 id="task-detail-title" className="m-0 flex-1 text-lg font-semibold text-slate-900">
          Task detail
        </h2>
        <button type="button" className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 px-2 text-xs text-slate-600" onClick={onClose}>
          <X className="h-3.5 w-3.5" aria-hidden />
          Close
        </button>
      </div>

      {isLoading ? <p className="text-sm text-slate-600">Loading task detail…</p> : null}
      {error ? <p role="alert" className="text-sm text-rose-700">{getErrorMessage(error)}</p> : null}
      {task ? (
        <div className="space-y-5">
          <form
            className="grid gap-3 md:grid-cols-2"
            key={`${task.id}-${task.revision}`}
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const tagIds = form.getAll("tag_ids").map(String);
              const details = String(form.get("details") ?? "").trim();
              const projectId = String(form.get("project_id") ?? "");
              const dueDate = String(form.get("due_date") ?? "");
              const waitingFor = String(form.get("waiting_for") ?? "").trim();
              onSave(task, {
                title: String(form.get("title") ?? "").trim(),
                details: details || null,
                project_id: projectId || null,
                tag_ids: tagIds,
                due_date: dueDate || null,
                priority: String(form.get("priority") ?? "none") as TaskPriority,
                ...(task.state === "waiting" ? { waiting_for: waitingFor } : {}),
                expected_revision: task.revision
              });
            }}
          >
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
              Title
              <input name="title" aria-label="Title" defaultValue={task.title} className="min-h-10 rounded-lg border border-slate-200 px-3 text-sm text-slate-900" />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
              Project
              <select name="project_id" aria-label="Project" defaultValue={task.project_id ?? ""} className="min-h-10 rounded-lg border border-slate-200 px-3 text-sm text-slate-900">
                <option value="">No project</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600 md:col-span-2">
              Details
              <textarea name="details" aria-label="Details" defaultValue={task.details ?? ""} rows={3} className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900" />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
              Due date
              <input name="due_date" aria-label="Due date" type="date" defaultValue={task.due_date ?? ""} className="min-h-10 rounded-lg border border-slate-200 px-3 text-sm text-slate-900" />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
              Priority
              <select name="priority" aria-label="Priority" defaultValue={task.priority} className="min-h-10 rounded-lg border border-slate-200 px-3 text-sm text-slate-900">
                <option value="none">None</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
              Waiting for
              <input name="waiting_for" aria-label="Waiting for" defaultValue={task.waiting_for ?? ""} className="min-h-10 rounded-lg border border-slate-200 px-3 text-sm text-slate-900" />
              <span className="text-[11px] font-normal text-slate-500">Required when moving or reopening to Waiting.</span>
            </label>
            <fieldset className="flex flex-wrap gap-2 text-xs font-medium text-slate-600">
              <legend className="mb-1 w-full">Tags</legend>
              {tags.map((tag) => (
                <label key={tag.id} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1">
                  <input name="tag_ids" type="checkbox" value={tag.id} defaultChecked={task.tag_ids.includes(tag.id)} />
                  #{tag.name.replace(/^[#@]/, "")}
                </label>
              ))}
            </fieldset>
            <div className="flex flex-wrap items-end gap-2 md:col-span-2">
              <button type="submit" className="h-10 rounded-lg bg-brand-primary px-4 text-sm font-semibold text-white">Save task detail</button>
              {task.state !== "completed" && task.state !== "cancelled" ? (
                <>
                  <button type="button" className="h-10 rounded-lg border border-emerald-200 px-3 text-sm text-emerald-700" onClick={() => onTransition(task, "complete")}>Complete</button>
                  <button type="button" className="h-10 rounded-lg border border-rose-200 px-3 text-sm text-rose-700" onClick={() => onTransition(task, "cancel")}>Cancel</button>
                  {openStateOptions.filter((option) => option !== task.state).map((option) => (
                    <TaskTransitionButton
                      key={option}
                      label={`Move to ${stateLabels[option].replace(" actions", "")}`}
                      targetState={option}
                      action="move"
                      task={task}
                      onTransition={onTransition}
                    />
                  ))}
                </>
              ) : (
                openStateOptions.map((option) => (
                  <TaskTransitionButton
                    key={option}
                    label={`Reopen to ${stateLabels[option].replace(" actions", "")}`}
                    targetState={option}
                    action="reopen"
                    task={task}
                    onTransition={onTransition}
                  />
                ))
              )}
            </div>
          </form>

          <form
            className="flex gap-2"
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
            <input name="subtask_title" aria-label="New subtask title" className="min-h-10 flex-1 rounded-lg border border-slate-200 px-3 text-sm" placeholder="Add a subtask" />
            <button type="submit" className="h-10 rounded-lg border border-slate-200 px-3 text-sm">Add subtask</button>
          </form>
          <div className="space-y-2" aria-label="Subtasks">
            {(task.subtasks ?? []).map((subtask) => (
              <div key={subtask.id} className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm">
                <span className="flex-1">{subtask.title}</span>
                <span className="text-xs text-slate-500">{subtask.state}</span>
                {subtask.state === "open" ? (
                  <button type="button" className="text-xs text-emerald-700" onClick={() => onTransitionSubtask(task, subtask, "complete")}>Complete</button>
                ) : (
                  <button type="button" className="text-xs text-slate-700" onClick={() => onTransitionSubtask(task, subtask, "reopen")}>Reopen</button>
                )}
              </div>
            ))}
          </div>

          <form
            className="flex gap-2"
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
            <input name="comment_body" aria-label="New comment" className="min-h-10 flex-1 rounded-lg border border-slate-200 px-3 text-sm" placeholder="Add a comment" />
            <button type="submit" className="h-10 rounded-lg border border-slate-200 px-3 text-sm">Add comment</button>
          </form>
          <div className="space-y-2" aria-label="Comments">
            {(task.comments ?? []).map((comment) => (
              <p key={comment.id} className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{comment.body}</p>
            ))}
          </div>
        </div>
      ) : null}
    </aside>
  );
}

function TaskTransitionButton({
  task,
  action,
  targetState,
  label,
  onTransition
}: {
  task: TaskResponse;
  action: "move" | "reopen";
  targetState: OpenTaskState;
  label: string;
  onTransition: (task: TaskResponse, action: "move" | "complete" | "reopen" | "cancel", toState?: OpenTaskState, waitingFor?: string) => void;
}): JSX.Element {
  return (
    <button
      type="button"
      className="h-10 rounded-lg border border-slate-200 px-3 text-sm text-slate-700"
      onClick={(event) => {
        const detailForm = event.currentTarget.form;
        const waitingFor = detailForm
          ? String(new FormData(detailForm).get("waiting_for") ?? "")
          : undefined;
        onTransition(task, action, targetState, targetState === "waiting" ? waitingFor : undefined);
      }}
    >
      {label}
    </button>
  );
}

function TaskCreator({
  newTitle,
  newWaitingFor,
  projects,
  tags,
  contextProjectId,
  contextTagId,
  state,
  showCompleted,
  isCreating,
  onCreate,
  onTitleChange,
  onWaitingForChange,
  onToggleCompleted
}: {
  newTitle: string;
  newWaitingFor: string;
  projects: ProjectResponse[];
  tags: TagResponse[];
  contextProjectId?: string;
  contextTagId?: string;
  state?: OpenTaskState;
  showCompleted: boolean;
  isCreating: boolean;
  onCreate: (draft: SmartAddDraft) => void;
  onTitleChange: (title: string) => void;
  onWaitingForChange: (value: string) => void;
  onToggleCompleted: (show: boolean) => void;
}): JSX.Element {
  const waitingForRequired = state === "waiting";
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [caret, setCaret] = useState(0);
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(0);
  const [suggestionsOpen, setSuggestionsOpen] = useState(true);
  const smartAddSuggestionsId = "smart-add-suggestions";
  const smartAddOptions = useMemo(
    () => ({ projects, tags, contextProjectId, contextTagId }),
    [projects, tags, contextProjectId, contextTagId]
  );
  const draft = useMemo(() => parseSmartAdd(newTitle, smartAddOptions), [newTitle, smartAddOptions]);
  const chips = draft.hasCompletedTokens ? smartAddChips(draft, smartAddOptions) : [];
  const suggestions = smartAddSuggestions(newTitle, caret, smartAddOptions);
  const popupOpen = suggestionsOpen && suggestions.length > 0;
  const selectedSuggestionIndex = Math.min(activeSuggestionIndex, Math.max(suggestions.length - 1, 0));

  const submitDraft = () => {
    if (draft.isValid && (!waitingForRequired || newWaitingFor.trim())) {
      setSuggestionsOpen(false);
      onCreate(draft);
    }
  };

  const updateCaretFromInput = () => {
    setCaret(inputRef.current?.selectionStart ?? newTitle.length);
  };

  const applySuggestion = (suggestion: SmartAddSuggestion) => {
    const applied = applySmartAddSuggestion(newTitle, caret, suggestion);
    if (!applied) {
      return;
    }
    onTitleChange(applied.text);
    setCaret(applied.caret);
    setSuggestionsOpen(false);
    window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.setSelectionRange(applied.caret, applied.caret);
    }, 0);
  };

  return (
    <div className="mt-3 space-y-3">
      <form
        className="flex flex-col gap-2 rounded-xl border border-dashed border-slate-200 bg-slate-50/70 p-3 sm:flex-row sm:items-center"
        onSubmit={(event) => {
          event.preventDefault();
          submitDraft();
        }}
      >
        <Plus className="hidden h-3.5 w-3.5 text-slate-500 sm:block" aria-hidden />
        <label className="sr-only" htmlFor="new-task-title">New task title</label>
        <input
          ref={inputRef}
          id="new-task-title"
          aria-label="New task title"
          aria-expanded={popupOpen}
          aria-controls={popupOpen ? smartAddSuggestionsId : undefined}
          aria-activedescendant={popupOpen ? `${smartAddSuggestionsId}-option-${selectedSuggestionIndex}` : undefined}
          className="min-h-10 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none focus:border-sky-300"
          placeholder="Add a task with #tag and @project — or dump with the mic above"
          value={newTitle}
          onChange={(event) => {
            onTitleChange(event.currentTarget.value);
            setCaret(event.currentTarget.selectionStart ?? event.currentTarget.value.length);
            setActiveSuggestionIndex(0);
            setSuggestionsOpen(true);
          }}
          onClick={updateCaretFromInput}
          onKeyUp={updateCaretFromInput}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
              event.preventDefault();
              submitDraft();
              return;
            }
            if (!popupOpen) {
              return;
            }
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              const direction = event.key === "ArrowDown" ? 1 : -1;
              setActiveSuggestionIndex((current) =>
                (current + direction + suggestions.length) % suggestions.length
              );
              return;
            }
            if (event.key === "Escape") {
              event.preventDefault();
              setSuggestionsOpen(false);
              return;
            }
            if (event.key === "Enter" || event.key === "Tab") {
              event.preventDefault();
              const suggestion = suggestions[selectedSuggestionIndex];
              if (suggestion) {
                applySuggestion(suggestion);
              }
            }
          }}
        />
        {waitingForRequired ? (
          <>
            <label className="sr-only" htmlFor="new-task-waiting-for">Waiting for</label>
            <input
              id="new-task-waiting-for"
              aria-label="Waiting for"
              className="min-h-10 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none focus:border-sky-300"
              placeholder="Waiting for who or what?"
              value={newWaitingFor}
              onChange={(event) => onWaitingForChange(event.currentTarget.value)}
            />
          </>
        ) : null}
        <button type="submit" disabled={isCreating || !draft.isValid || (waitingForRequired && !newWaitingFor.trim())} className="h-10 rounded-lg bg-brand-primary px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">
          Add task
        </button>
      </form>
      {popupOpen ? (
        <SmartAddSuggestions
          suggestions={suggestions}
          activeIndex={selectedSuggestionIndex}
          listboxId={smartAddSuggestionsId}
          onSelect={applySuggestion}
        />
      ) : null}
      {chips.length ? (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600" aria-label="Smart Add classification chips">
          <span>Will add:</span>
          {chips.map((chip) => (
            <span key={`${chip.kind}-${chip.label}`} className="rounded-full bg-slate-100 px-2.5 py-0.5 text-slate-700">
              {chip.kind === "tag" ? "#" : "@"}{chip.label.replace(/^[#@]/, "")}
            </span>
          ))}
          <span className="text-slate-500">Title: “{draft.cleanTitle}”</span>
        </div>
      ) : null}
      <label className="inline-flex items-center gap-2 text-xs font-medium text-slate-600">
        <input type="checkbox" checked={showCompleted} onChange={(event) => onToggleCompleted(event.currentTarget.checked)} />
        Show terminal tasks
      </label>
    </div>
  );
}

function DateViewCaptureHint(): JSX.Element {
  return (
    <div className="mt-3 rounded-xl border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-800">
      Date views are filters over existing tasks. Add a task from Inbox, Next, Waiting, Someday, a Project, or a Tag, then set its due date in task detail.
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

function parseTaskSort(value: string | null): TaskSort {
  if (value === "due" || value === "priority" || value === "title") {
    return value;
  }
  return "manual";
}

function localDateIso(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
