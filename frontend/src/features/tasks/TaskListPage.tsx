/* istanbul ignore file -- task shell rendering is covered by route tests and Playwright snapshots. */
import { AlertTriangle, ArrowLeft, ArrowRight, Check, ChevronDown, Edit3, Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../api/client";
import { parseOpenTaskState, parseTaskDateView, useProjects, useTags, useTaskDetail, useTaskList } from "../../api/taskHooks";
import type { OpenTaskState, ProjectResponse, TagResponse, TaskCounts, TaskPriority, TaskResponse, TaskSort, TaskSubtaskResponse, TaskUpdateRequest } from "../../api/taskTypes";
import { AppShell, SoonChip } from "../../components/shell/AppShell";
import { Button } from "../../components/ui/Button";
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

const desktopMediaQuery = "(min-width: 1024px)";

function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return true;
    }
    return window.matchMedia(desktopMediaQuery).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mediaQueryList = window.matchMedia(desktopMediaQuery);
    const onChange = () => setIsDesktop(mediaQueryList.matches);
    onChange();
    mediaQueryList.addEventListener("change", onChange);
    return () => mediaQueryList.removeEventListener("change", onChange);
  }, []);

  return isDesktop;
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
  const isDesktop = useIsDesktop();
  const [newTitle, setNewTitle] = useState("");
  const [newWaitingFor, setNewWaitingFor] = useState("");
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [showCompleted, setShowCompleted] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const rowLinkRefs = useRef<Map<string, HTMLAnchorElement>>(new Map());
  const detailHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const listHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const previousTaskIdRef = useRef<string | undefined>(undefined);
  const registerRowLink = (rowTaskId: string, el: HTMLAnchorElement | null) => {
    if (el) {
      rowLinkRefs.current.set(rowTaskId, el);
    } else {
      rowLinkRefs.current.delete(rowTaskId);
    }
  };

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

  useEffect(() => {
    if (taskId && isDesktop) {
      detailHeadingRef.current?.focus();
    } else if (!taskId && isDesktop && previousTaskIdRef.current) {
      const originLink = rowLinkRefs.current.get(previousTaskIdRef.current);
      if (originLink && document.contains(originLink)) {
        originLink.focus();
      } else {
        listHeadingRef.current?.focus();
      }
    }
    previousTaskIdRef.current = taskId;
  }, [detailQuery.data, isDesktop, taskId]);

  const projects = projectsQuery.data ?? emptyProjects;
  const tags = tagsQuery.data ?? emptyTags;
  const tasks = taskQuery.data?.items ?? [];
  const counts = taskQuery.data?.counts_by_state ?? emptyCounts;
  const detailIsInProjection = Boolean(taskId && tasks.some((task) => task.id === taskId));

  const invalidateTasks = () => queryClient.invalidateQueries({ queryKey: ["tasks"] });
  const listPath = projectId
    ? `/projects/${projectId}`
    : tagId
      ? `/tags/${tagId}`
      : `/tasks/${params.state ?? "next"}`;
  const closeTarget = { pathname: listPath, search: searchParams.toString() };

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
      <section aria-labelledby="task-list-title" className="mx-auto max-w-[760px]">
        {isDesktop || !taskId ? (
          <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 id="task-list-title" ref={listHeadingRef} tabIndex={-1} className="m-0 text-title font-semibold text-slate-900 outline-none">
              {title}
            </h1>
            <span className="text-xs text-slate-600">{subtitle}</span>
            <div className="ml-auto flex items-center gap-1.5">
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-medium text-slate-600 transition-colors duration-200 ease-smooth hover:bg-surface-sunken hover:text-slate-900">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 rounded border-slate-300 text-brand-primary accent-brand-primary"
                  checked={showCompleted}
                  onChange={(event) => setShowCompleted(event.currentTarget.checked)}
                />
                Show completed
              </label>
              <label className="inline-flex items-center gap-1.5 text-xs text-slate-500">
                Sort
                <span className="relative inline-flex">
                  <select
                    aria-label="Sort tasks"
                    className="h-8 appearance-none rounded-lg border border-slate-200 bg-white pl-2.5 pr-7 text-xs font-medium text-slate-700 shadow-soft outline-none transition-colors duration-200 ease-smooth hover:border-slate-300 focus:border-brand-primary"
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
                  <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden />
                </span>
              </label>
            </div>
          </div>
        ) : null}

        {mutationError ? <div role="alert" className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{mutationError}</div> : null}

        {isDesktop || !taskId ? (
          hasFrameError ? (
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
              taskSearch={searchParams.toString()}
              editingTaskId={editingTaskId}
              editingTitle={editingTitle}
              registerRowLink={registerRowLink}
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
              onSaveEdit={(task) => updateMutation.mutate({ task, payload: { title: editingTitle.trim() } })}
              expandedTaskId={taskId}
              onCollapse={() => navigate(closeTarget)}
              detailHeadingRef={detailHeadingRef}
              detailTask={detailQuery.data}
              detailIsLoading={detailQuery.isLoading}
              detailError={detailQuery.error}
              onSaveDetail={(task, payload) => detailUpdateMutation.mutate({ task, payload })}
              onTransitionDetail={(task, action, toState, waitingFor) =>
                detailTransitionMutation.mutate({ task, action, toState, waitingFor })
              }
              onCreateSubtask={(task, title) => subtaskCreateMutation.mutate({ task, title })}
              onTransitionSubtask={(task, subtask, action) =>
                subtaskTransitionMutation.mutate({ task, subtask, action })
              }
              onCreateComment={(task, body) => commentCreateMutation.mutate({ task, body })}
            />
          ) : (
            <EmptyState state={state} />
          )
        ) : null}

        {taskId && (!isDesktop || !detailIsInProjection) ? (
          <TaskDetailPanel
            task={detailQuery.data}
            projects={projects}
            tags={tags}
            isLoading={detailQuery.isLoading}
            error={detailQuery.error}
            headingRef={detailHeadingRef}
            onClose={() => navigate(closeTarget)}
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

        {(isDesktop || !taskId) && taskQuery.hasNextPage ? (
          <div className="mt-3 flex justify-center">
            <Button
              variant="secondary"
              onClick={() => void taskQuery.fetchNextPage()}
              isLoading={taskQuery.isFetchingNextPage}
            >
              {taskQuery.isFetchingNextPage ? "Loading more tasks…" : "Load more tasks"}
            </Button>
          </div>
        ) : null}

        {!(isDesktop || !taskId) ? null : dateView ? (
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
            isCreating={createMutation.isPending}
            onCreate={(draft) => createMutation.mutate(draft)}
            onTitleChange={setNewTitle}
            onWaitingForChange={setNewWaitingFor}
          />
        )}
      </section>
    </AppShell>
  );
}

function Chip({ variant = "neutral", children }: { variant?: "due" | "neutral"; children: ReactNode }): JSX.Element {
  const variantClass =
    variant === "due"
      ? "border-due-border bg-due-bg text-due-fg"
      : "border-transparent bg-context-bg text-context-fg";
  return (
    <span className={`inline-flex h-[22px] shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 text-[11px] font-medium ${variantClass}`}>
      {children}
    </span>
  );
}

function tagLabel(tag: TagResponse): string {
  return tag.name.startsWith("@") ? tag.name : `#${tag.name.replace(/^#/, "")}`;
}

function TaskList({
  tasks,
  projects,
  tags,
  taskPathBase,
  taskSearch,
  editingTaskId,
  editingTitle,
  registerRowLink,
  onBeginEdit,
  onCancelEdit,
  onComplete,
  onEditTitle,
  onMoveToNext,
  onSaveEdit,
  expandedTaskId,
  onCollapse,
  detailHeadingRef,
  detailTask,
  detailIsLoading,
  detailError,
  onSaveDetail,
  onTransitionDetail,
  onCreateSubtask,
  onTransitionSubtask,
  onCreateComment
}: {
  tasks: TaskResponse[];
  projects: ProjectResponse[];
  tags: TagResponse[];
  taskPathBase: string;
  taskSearch: string;
  editingTaskId: string | null;
  editingTitle: string;
  registerRowLink: (taskId: string, el: HTMLAnchorElement | null) => void;
  onBeginEdit: (task: TaskResponse) => void;
  onCancelEdit: () => void;
  onComplete: (task: TaskResponse) => void;
  onEditTitle: (title: string) => void;
  onMoveToNext: (task: TaskResponse) => void;
  onSaveEdit: (task: TaskResponse) => void;
  expandedTaskId?: string;
  onCollapse: () => void;
  detailHeadingRef: RefObject<HTMLHeadingElement>;
  detailTask?: TaskResponse;
  detailIsLoading: boolean;
  detailError: unknown;
  onSaveDetail: (task: TaskResponse, payload: Parameters<typeof apiClient.updateTask>[1]) => void;
  onTransitionDetail: (task: TaskResponse, action: "move" | "complete" | "reopen" | "cancel", toState?: OpenTaskState, waitingFor?: string) => void;
  onCreateSubtask: (task: TaskResponse, title: string) => void;
  onTransitionSubtask: (task: TaskResponse, subtask: TaskSubtaskResponse, action: "complete" | "reopen" | "cancel") => void;
  onCreateComment: (task: TaskResponse, body: string) => void;
}): JSX.Element {
  const projectById = new Map(projects.map((project) => [project.id, project]));
  const tagById = new Map(tags.map((tag) => [tag.id, tag]));

  return (
    <div className="flex flex-col gap-2" role="list" aria-label="Tasks">
      {tasks.map((task) => {
        const project = task.project_id ? projectById.get(task.project_id) : undefined;
        const taskTags = task.tag_ids.map((id) => tagById.get(id)).filter((tag): tag is TagResponse => Boolean(tag));
        const isExpanded = expandedTaskId === task.id;
        return (
          <TaskRow
            key={task.id}
            task={task}
            project={project}
            tags={taskTags}
            detailPath={`${taskPathBase}/${task.id}${taskSearch ? `?${taskSearch}` : ""}`}
            isEditing={editingTaskId === task.id}
            editingTitle={editingTitle}
            registerRowLink={registerRowLink}
            onBeginEdit={onBeginEdit}
            onCancelEdit={onCancelEdit}
            onComplete={onComplete}
            onEditTitle={onEditTitle}
            onMoveToNext={onMoveToNext}
            onSaveEdit={onSaveEdit}
            isExpanded={isExpanded}
          >
            {isExpanded ? (
              <TaskDetailPanel
                task={detailTask}
                projects={projects}
                tags={tags}
                isLoading={detailIsLoading}
                error={detailError}
                headingRef={detailHeadingRef}
                onClose={onCollapse}
                onSave={onSaveDetail}
                onTransition={onTransitionDetail}
                onCreateSubtask={onCreateSubtask}
                onTransitionSubtask={onTransitionSubtask}
                onCreateComment={onCreateComment}
              />
            ) : null}
          </TaskRow>
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
  registerRowLink,
  onBeginEdit,
  onCancelEdit,
  onComplete,
  onEditTitle,
  onMoveToNext,
  onSaveEdit,
  isExpanded,
  children
}: {
  task: TaskResponse;
  project?: ProjectResponse;
  tags: TagResponse[];
  detailPath: string;
  isEditing: boolean;
  editingTitle: string;
  registerRowLink: (taskId: string, el: HTMLAnchorElement | null) => void;
  onBeginEdit: (task: TaskResponse) => void;
  onCancelEdit: () => void;
  onComplete: (task: TaskResponse) => void;
  onEditTitle: (title: string) => void;
  onMoveToNext: (task: TaskResponse) => void;
  onSaveEdit: (task: TaskResponse) => void;
  isExpanded: boolean;
  children?: ReactNode;
}): JSX.Element {
  const isTerminal = task.state === "completed" || task.state === "cancelled";
  const navigate = useNavigate();

  return (
    <article
      className={`group flex flex-col gap-2 rounded-[12px] border px-4 py-3 shadow-soft transition-shadow duration-200 ease-smooth hover:shadow-raised ${
        isTerminal ? "border-slate-200 bg-slate-50/70" : isExpanded ? "border-slate-200 bg-white shadow-raised" : "border-slate-200 bg-white"
      }`}
      role="listitem"
      onClick={(event) => {
        if (isExpanded) {
          return;
        }
        const target = event.target as HTMLElement;
        if (target.closest("a, button, input, textarea, select, label")) {
          return;
        }
        navigate(detailPath);
      }}
    >
      {/* Wrapping row: below `sm` the checkbox and title claim the first line and the
          chips wrap underneath, instead of each chip stretching to the card width.
          `sm:contents` dissolves the checkbox/title wrapper so that from `sm` up the
          row is a single flex line again and the project name can still `ml-auto`. */}
      <div className="flex min-h-[32px] flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex min-w-0 basis-full items-center gap-3 sm:contents">
        {isTerminal ? (
          <span
            aria-hidden
            className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border-[1.5px] ${
              task.state === "completed"
                ? "border-emerald-500 bg-emerald-500 text-white"
                : "border-slate-300 bg-slate-200 text-slate-500"
            }`}
          >
            {task.state === "completed" ? <Check className="h-3 w-3" /> : <X className="h-2.5 w-2.5" />}
          </span>
        ) : (
          <button
            type="button"
            className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border border-[1.5px] border-slate-300 bg-white text-white hover:border-sky-400 hover:bg-sky-500"
            aria-label={`Complete ${task.title}`}
            onClick={() => onComplete(task)}
          >
            <Check className="h-3 w-3" aria-hidden />
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
            <Button type="submit" size="sm">Save task title</Button>
            <Button variant="secondary" size="sm" onClick={onCancelEdit}>Cancel</Button>
          </form>
        ) : (
          <Link
            ref={(el) => registerRowLink(task.id, el)}
            to={detailPath}
            className={`min-w-0 flex-1 truncate text-sm font-medium hover:text-brand-primary ${
              isTerminal ? "text-slate-400 line-through decoration-slate-300" : "text-slate-900"
            }`}
          >
            {task.title}
          </Link>
        )}
        </div>
        {isTerminal ? <Chip variant="neutral">{task.state === "completed" ? "Completed" : "Cancelled"}</Chip> : null}
        {!isEditing && !isTerminal ? (
          <span className="hidden shrink-0 items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100 sm:flex">
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 hover:text-slate-900"
              aria-label={`Edit ${task.title}`}
              onClick={() => onBeginEdit(task)}
            >
              <Edit3 className="h-3.5 w-3.5" aria-hidden />
            </button>
            {task.state !== "next" ? (
              <button
                type="button"
                className="inline-flex h-7 items-center gap-1 whitespace-nowrap rounded-lg border border-slate-200 bg-white px-2 text-[11px] font-medium text-slate-600 transition-colors duration-200 ease-smooth hover:border-slate-300 hover:text-slate-900"
                aria-label={`Move ${task.title} to Next`}
                onClick={() => onMoveToNext(task)}
              >
                <ArrowRight className="h-3 w-3" aria-hidden />
                Next
              </button>
            ) : null}
          </span>
        ) : null}
        {task.due_date ? <Chip variant="due">{formatDueDate(task.due_date)}</Chip> : null}
        {tags.map((tag) => (
          <Chip key={tag.id} variant="neutral">{tagLabel(tag)}</Chip>
        ))}
        {project ? (
          <span className="min-w-0 shrink truncate text-[11px] text-slate-400 sm:ml-auto sm:text-right lg:max-w-[160px]">{project.name}</span>
        ) : null}
      </div>
      {children}
    </article>
  );
}

const detailFieldClass =
  "min-h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition-colors duration-200 ease-smooth hover:border-slate-300 focus:border-brand-primary focus:shadow-ring-focus";

const detailCaptionClass = "text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500";

function DetailField({ label, children }: { label: string; children: ReactNode }): JSX.Element {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className={detailCaptionClass}>{label}</span>
      {children}
    </label>
  );
}

function DetailSection({ title, children }: { title: string; children: ReactNode }): JSX.Element {
  return (
    <section className="flex min-w-0 flex-col gap-2">
      <h3 className={`m-0 ${detailCaptionClass}`}>{title}</h3>
      {children}
    </section>
  );
}

function TaskDetailPanel({
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
  headingRef: RefObject<HTMLHeadingElement>;
  onClose: () => void;
  onSave: (task: TaskResponse, payload: Parameters<typeof apiClient.updateTask>[1]) => void;
  onTransition: (task: TaskResponse, action: "move" | "complete" | "reopen" | "cancel", toState?: OpenTaskState, waitingFor?: string) => void;
  onCreateSubtask: (task: TaskResponse, title: string) => void;
  onTransitionSubtask: (task: TaskResponse, subtask: TaskSubtaskResponse, action: "complete" | "reopen" | "cancel") => void;
  onCreateComment: (task: TaskResponse, body: string) => void;
}): JSX.Element {
  const isOpenState = Boolean(task && task.state !== "completed" && task.state !== "cancelled");

  return (
    <aside
      className="-mx-4 -my-5 flex min-h-[calc(100vh-56px)] min-w-0 flex-col gap-[18px] bg-surface-base px-4 py-5 sm:-mx-6 sm:px-6 motion-safe:lg:animate-detail-enter lg:m-0 lg:min-h-0 lg:bg-transparent lg:p-0 lg:pt-3.5 lg:border-t lg:border-slate-200"
      aria-labelledby="task-detail-title"
    >
      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-label="Back to list"
          className="-ml-1 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 lg:hidden"
          onClick={onClose}
        >
          <ArrowLeft className="h-5 w-5" aria-hidden />
        </button>
        <h2
          id="task-detail-title"
          ref={headingRef}
          tabIndex={-1}
          className="sr-only m-0 flex-1 text-sm font-semibold uppercase tracking-wide text-slate-500 outline-none lg:not-sr-only"
        >
          Task detail
        </h2>
        <p className="m-0 min-w-0 flex-1 break-words whitespace-normal text-[20px] font-semibold leading-[1.3] tracking-[-0.015em] text-slate-900 lg:hidden">
          {task?.title ?? "Task"}
        </p>
        <Button
          variant="secondary"
          size="sm"
          className="hidden lg:inline-flex"
          leftIcon={<X aria-hidden />}
          onClick={onClose}
        >
          Close
        </Button>
      </div>

      {isLoading ? <p className="text-sm text-slate-600">Loading task detail…</p> : null}
      {error ? <p role="alert" className="text-sm text-rose-700">{getErrorMessage(error)}</p> : null}
      {task ? (
        <div className="flex flex-col gap-[18px]">
          <form
            className="flex min-w-0 flex-col gap-3"
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
            <DetailField label="Title">
              <input name="title" aria-label="Title" defaultValue={task.title} className={detailFieldClass} />
            </DetailField>
            <DetailField label="Details">
              <textarea
                name="details"
                aria-label="Details"
                defaultValue={task.details ?? ""}
                rows={3}
                placeholder="Notes, links, whatever helps you pick this up again"
                className={`${detailFieldClass} py-2 placeholder:text-slate-400`}
              />
            </DetailField>
            <div className="grid min-w-0 gap-3 sm:grid-cols-3">
              <DetailField label="Project">
                <select name="project_id" aria-label="Project" defaultValue={task.project_id ?? ""} className={detailFieldClass}>
                  <option value="">No project</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>{project.name}</option>
                  ))}
                </select>
              </DetailField>
              <DetailField label="Due date">
                <input name="due_date" aria-label="Due date" type="date" defaultValue={task.due_date ?? ""} className={detailFieldClass} />
              </DetailField>
              <DetailField label="Priority">
                <select name="priority" aria-label="Priority" defaultValue={task.priority} className={detailFieldClass}>
                  <option value="none">None</option>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </DetailField>
            </div>
            <fieldset className="min-w-0">
              <legend className={`mb-1.5 ${detailCaptionClass}`}>Tags</legend>
              <div className="flex flex-wrap gap-1.5">
                {tags.map((tag) => (
                  <label key={tag.id} className="inline-flex cursor-pointer items-center">
                    <input
                      name="tag_ids"
                      type="checkbox"
                      value={tag.id}
                      defaultChecked={task.tag_ids.includes(tag.id)}
                      className="peer sr-only"
                    />
                    <span className="rounded-full border border-slate-200 bg-white px-2.5 py-[3px] text-[11px] font-medium text-slate-600 transition-colors duration-200 ease-smooth hover:border-slate-300 peer-checked:border-brand-primary peer-checked:bg-info-bg peer-checked:text-info-fg peer-focus-visible:shadow-ring-focus">
                      #{tag.name.replace(/^[#@]/, "")}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="flex min-w-0 flex-col gap-3 border-t border-slate-200 pt-3">
              <div className="flex flex-wrap items-center gap-2">
                <Button type="submit" size="md">Save task detail</Button>
                {isOpenState ? (
                  <>
                    <Button
                      variant="secondary"
                      size="md"
                      className="border-emerald-200 text-emerald-700 hover:border-emerald-300 hover:text-emerald-800"
                      leftIcon={<Check aria-hidden />}
                      onClick={() => onTransition(task, "complete")}
                    >
                      Complete
                    </Button>
                    <Button variant="danger" size="md" onClick={() => onTransition(task, "cancel")}>
                      Cancel task
                    </Button>
                  </>
                ) : null}
              </div>
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                <span className={`mr-0.5 ${detailCaptionClass}`}>{isOpenState ? "Move to" : "Reopen to"}</span>
                {(isOpenState ? openStateOptions.filter((option) => option !== task.state) : openStateOptions).map((option) => (
                  <TaskTransitionButton
                    key={option}
                    label={`${isOpenState ? "Move to" : "Reopen to"} ${stateLabels[option].replace(" actions", "")}`}
                    text={stateLabels[option].replace(" actions", "")}
                    targetState={option}
                    action={isOpenState ? "move" : "reopen"}
                    task={task}
                    onTransition={onTransition}
                  />
                ))}
              </div>
              <DetailField label="Waiting for">
                <input
                  name="waiting_for"
                  aria-label="Waiting for"
                  defaultValue={task.waiting_for ?? ""}
                  placeholder="Who or what are you waiting on?"
                  className={`${detailFieldClass} placeholder:text-slate-400 sm:max-w-[380px]`}
                />
                <span className="text-[11px] text-slate-500">Required to move or reopen a task into Waiting for.</span>
              </DetailField>
            </div>
          </form>

          <DetailSection title="Subtasks">
            <div className="flex flex-col gap-1.5" aria-label="Subtasks">
              {(task.subtasks ?? []).map((subtask) => {
                const done = subtask.state !== "open";
                return (
                  <div key={subtask.id} className="flex items-center gap-2 text-sm">
                    <button
                      type="button"
                      className={`flex h-[14px] w-[14px] shrink-0 items-center justify-center rounded-full border border-[1.5px] ${
                        done ? "border-brand-primary bg-brand-primary text-white" : "border-slate-300 bg-white text-white"
                      }`}
                      aria-label={done ? `Reopen ${subtask.title}` : `Complete ${subtask.title}`}
                      onClick={() => onTransitionSubtask(task, subtask, done ? "reopen" : "complete")}
                    >
                      <Check className="h-2.5 w-2.5" aria-hidden />
                    </button>
                    <span className={done ? "text-slate-500 line-through" : "text-slate-800"}>{subtask.title}</span>
                  </div>
                );
              })}
            </div>
            <form
              className="flex w-full min-w-0 items-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/70 p-2 lg:max-w-[420px]"
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
              <input
                name="subtask_title"
                aria-label="New subtask title"
                className="min-h-9 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none transition-colors duration-200 ease-smooth focus:border-brand-primary placeholder:text-slate-400"
                placeholder="Add a subtask"
              />
              <Button type="submit" variant="secondary" size="sm">Add subtask</Button>
            </form>
          </DetailSection>

          <div data-testid="task-detail-agent">
            <DetailSection title="Agent">
              <div className="flex items-center gap-2">
                <SoonChip />
                <span className="sr-only">Coming soon</span>
              </div>
            </DetailSection>
          </div>

          <DetailSection title="Comments">
            <div className="flex flex-col gap-2" aria-label="Comments">
              {(task.comments ?? []).map((comment) => (
                <div key={comment.id} className="flex items-start gap-2">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-100 text-[10px] font-semibold text-sky-700">
                    {comment.actor_id.slice(0, 2).toUpperCase()}
                  </span>
                  <p className="m-0 min-w-0 flex-1 text-sm text-slate-700">{comment.body}</p>
                </div>
              ))}
            </div>
            <form
              className="flex w-full min-w-0 items-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/70 p-2 lg:max-w-[420px]"
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
              <input
                name="comment_body"
                aria-label="New comment"
                className="min-h-9 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none transition-colors duration-200 ease-smooth focus:border-brand-primary placeholder:text-slate-400"
                placeholder="Add a comment"
              />
              <Button type="submit" variant="secondary" size="sm">Add comment</Button>
            </form>
          </DetailSection>
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
  text,
  onTransition
}: {
  task: TaskResponse;
  action: "move" | "reopen";
  targetState: OpenTaskState;
  /** Accessible name — spells out the action ("Move to Inbox"). */
  label: string;
  /** Visible text — the destination only, since the group already reads "Move to". */
  text: string;
  onTransition: (task: TaskResponse, action: "move" | "complete" | "reopen" | "cancel", toState?: OpenTaskState, waitingFor?: string) => void;
}): JSX.Element {
  return (
    <Button
      variant="secondary"
      size="sm"
      aria-label={label}
      onClick={(event) => {
        const detailForm = event.currentTarget.form;
        const waitingFor = detailForm
          ? String(new FormData(detailForm).get("waiting_for") ?? "")
          : undefined;
        onTransition(task, action, targetState, targetState === "waiting" ? waitingFor : undefined);
      }}
    >
      {text}
    </Button>
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
  isCreating,
  onCreate,
  onTitleChange,
  onWaitingForChange
}: {
  newTitle: string;
  newWaitingFor: string;
  projects: ProjectResponse[];
  tags: TagResponse[];
  contextProjectId?: string;
  contextTagId?: string;
  state?: OpenTaskState;
  isCreating: boolean;
  onCreate: (draft: SmartAddDraft) => void;
  onTitleChange: (title: string) => void;
  onWaitingForChange: (value: string) => void;
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
        className="flex flex-col gap-2 rounded-[12px] border border-dashed border-slate-200 bg-slate-50/70 p-3 sm:flex-row sm:items-center"
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
        <Button
          type="submit"
          size="lg"
          isLoading={isCreating}
          disabled={!draft.isValid || (waitingForRequired && !newWaitingFor.trim())}
        >
          Add task
        </Button>
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
        <div key={item} className="h-12 animate-pulse rounded-[12px] border border-slate-200 bg-white" />
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
          <Button
            variant="secondary"
            className="mt-3 border-rose-200 text-rose-800 hover:border-rose-300 hover:text-rose-900"
            leftIcon={<RotateCcw aria-hidden />}
            onClick={onRetry}
          >
            Retry
          </Button>
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
