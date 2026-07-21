/* istanbul ignore file -- task shell rendering is covered by route tests and Playwright snapshots. */
import { AlertTriangle, ArrowLeft, ArrowUpDown, Check, Edit3, Layers, Plus, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../api/client";
import { parseOpenTaskState, parseTaskDateView, useAllTaskPages, useProjects, useTags, useTaskDetail, useTaskList } from "../../api/taskHooks";
import type { OpenTaskState, ProjectResponse, TagResponse, TaskCounts, TaskPriority, TaskResponse, TaskSort, TaskSubtaskResponse, TaskUpdateRequest } from "../../api/taskTypes";
import { AppShell, SoonChip } from "../../components/shell/AppShell";
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

interface TaskDetailLocationState {
  fromList?: boolean;
}

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
  const location = useLocation();
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
  // The detail heading can remount without the route changing: completing a
  // task (or any mutation that flips detailIsInProjection/isDesktop) swaps
  // between the standalone panel and the in-row panel, unmounting one heading
  // and mounting another. Refocusing on every such mount would steal focus
  // from whatever control the user is actively using (e.g. the Complete
  // button they just clicked). Only carry focus across that remount when the
  // outgoing heading actually held it — i.e. the swap happened while the
  // heading itself was focused (the initial transient standalone -> in-row
  // swap while the list is still loading), not mid-mutation while focus was
  // elsewhere. Opening a task or switching tasks is handled separately by the
  // effect below, keyed on taskId.
  const detailHeadingWasFocusedRef = useRef(false);
  const registerDetailHeading = useCallback((el: HTMLHeadingElement | null) => {
    if (el) {
      const shouldRestoreFocus = detailHeadingWasFocusedRef.current;
      detailHeadingRef.current = el;
      if (shouldRestoreFocus) {
        el.focus();
      }
      detailHeadingWasFocusedRef.current = false;
      return;
    }
    detailHeadingWasFocusedRef.current = document.activeElement === detailHeadingRef.current;
    detailHeadingRef.current = null;
  }, []);

  const sort = parseTaskSort(searchParams.get("sort"));
  const searchQuery = searchParams.get("q") ?? "";
  const today = localDateIso();
  const isInboxProductView = state === "inbox" && !projectId && !tagId && !dateView;
  const canGroupByProject = !projectId;
  const groupByProject = canGroupByProject && searchParams.get("group") === "project";
  const listFilters = {
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
  };
  const taskQuery = useTaskList(listFilters, { enabled: !groupByProject });
  const allTasksQuery = useAllTaskPages(listFilters, { enabled: groupByProject });
  const inboxBadgeQuery = useTaskList({ state: "inbox", unassignedProject: true, limit: 1 });
  const detailQuery = useTaskDetail(taskId);
  const projectsQuery = useProjects();
  const tagsQuery = useTags();

  useEffect(() => {
    if (taskId) {
      detailHeadingRef.current?.focus();
    } else if (previousTaskIdRef.current) {
      const originLink = rowLinkRefs.current.get(previousTaskIdRef.current);
      if (originLink && document.contains(originLink)) {
        originLink.focus();
      } else {
        listHeadingRef.current?.focus();
      }
    }
    previousTaskIdRef.current = taskId;
  }, [taskId]);

  const projects = projectsQuery.data ?? emptyProjects;
  const tags = tagsQuery.data ?? emptyTags;
  const tasks = taskQuery.data?.items ?? [];
  const counts = groupByProject
    ? allTasksQuery.data?.counts_by_state ?? emptyCounts
    : taskQuery.data?.counts_by_state ?? emptyCounts;
  const activeProjectionTasks = groupByProject ? allTasksQuery.data?.items ?? [] : tasks;
  const detailIsInProjection = Boolean(taskId && activeProjectionTasks.some((task) => task.id === taskId));

  const invalidateTasks = () => queryClient.invalidateQueries({ queryKey: ["tasks"] });
  const listPath = projectId
    ? `/projects/${projectId}`
    : tagId
      ? `/tags/${tagId}`
      : `/tasks/${params.state ?? "next"}`;
  const closeTarget = { pathname: listPath, search: searchParams.toString() };
  const openedFromList = Boolean((location.state as TaskDetailLocationState | null)?.fromList);
  const closeDetail = () => {
    if (openedFromList) {
      navigate(-1);
    } else {
      navigate(closeTarget, { replace: true });
    }
  };

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

  // Counts by open state ignore only the state filter and honor project/tag/date/query
  // filters, so their sum is the exact non-terminal total for a flat, non-state view
  // without draining every cursor page. Once terminal tasks are included there is no
  // canonical exact total, so the flat subtitle falls back to loaded-subset "N+" copy
  // until every page has been fetched.
  const openTasksTotal = counts.inbox + counts.next + counts.waiting + counts.someday;
  let subtitleCount: number;
  let subtitleIsPartial = false;
  if (groupByProject) {
    subtitleCount = activeProjectionTasks.length;
  } else if (showCompleted) {
    // Once terminal rows are included, `counts[state]` (open-only) is no
    // longer truthful for a state route either — it silently drops the
    // completed/cancelled rows the list is now showing. Use the same
    // loaded-rows-plus-partial-flag truth used by every other flat view.
    subtitleCount = activeProjectionTasks.length;
    subtitleIsPartial = Boolean(taskQuery.hasNextPage);
  } else if (state) {
    subtitleCount = counts[state];
  } else {
    subtitleCount = openTasksTotal;
  }
  const subtitle = subtitleIsPartial
    ? `${subtitleCount}+ tasks`
    : `${subtitleCount} ${subtitleCount === 1 ? "task" : "tasks"}`;

  const hasFrameError = taskQuery.isError || projectsQuery.isError || tagsQuery.isError;

  const toggleGroupByProject = () => {
    const next = new URLSearchParams(searchParams);
    if (groupByProject) {
      next.delete("group");
    } else {
      next.set("group", "project");
    }
    setSearchParams(next, { replace: true });
  };

  const projectGroups = useMemo(
    () => (allTasksQuery.data ? groupTasksByProject(allTasksQuery.data.items, projects) : []),
    [allTasksQuery.data, projects]
  );

  const sharedTaskListProps = {
    projects,
    tags,
    taskPathBase: listPath,
    taskSearch: searchParams.toString(),
    editingTaskId,
    editingTitle,
    registerRowLink,
    onBeginEdit: (task: TaskResponse) => {
      setEditingTaskId(task.id);
      setEditingTitle(task.title);
    },
    onCancelEdit: () => {
      setEditingTaskId(null);
      setEditingTitle("");
    },
    onComplete: (task: TaskResponse) => transitionMutation.mutate({ task, action: "complete" }),
    onEditTitle: (title: string) => setEditingTitle(title),
    onMoveToNext: (task: TaskResponse) => transitionMutation.mutate({ task, action: "move", toState: "next" }),
    onSaveEdit: (task: TaskResponse) => updateMutation.mutate({ task, payload: { title: editingTitle.trim() } }),
    expandedTaskId: taskId,
    onCollapse: closeDetail,
    registerDetailHeading,
    detailTask: detailQuery.data,
    detailIsLoading: detailQuery.isLoading,
    detailError: detailQuery.error,
    onSaveDetail: (task: TaskResponse, payload: Parameters<typeof apiClient.updateTask>[1]) =>
      detailUpdateMutation.mutate({ task, payload }),
    onTransitionDetail: (task: TaskResponse, action: "move" | "complete" | "reopen" | "cancel", toState?: OpenTaskState, waitingFor?: string) =>
      detailTransitionMutation.mutate({ task, action, toState, waitingFor }),
    onCreateSubtask: (task: TaskResponse, title: string) => subtaskCreateMutation.mutate({ task, title }),
    onTransitionSubtask: (task: TaskResponse, subtask: TaskSubtaskResponse, action: "complete" | "reopen" | "cancel") =>
      subtaskTransitionMutation.mutate({ task, subtask, action }),
    onCreateComment: (task: TaskResponse, body: string) => commentCreateMutation.mutate({ task, body })
  };

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
      mobileDetailOpen={Boolean(taskId) && !isDesktop}
    >
      <section aria-labelledby="task-list-title" className="mx-auto max-w-[760px]">
        {isDesktop || !taskId ? (
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div className="flex flex-col gap-0.5">
              <h1 id="task-list-title" ref={listHeadingRef} tabIndex={-1} className="m-0 text-[20px] font-semibold leading-[1.3] text-slate-900 outline-none">
                {title}
              </h1>
              <span className="text-xs text-slate-500">{subtitle}</span>
            </div>
            <div className="flex items-center gap-1">
              {canGroupByProject ? (
                <button
                  type="button"
                  aria-pressed={groupByProject}
                  className={`inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium transition ${
                    groupByProject ? "bg-info-bg text-info-fg" : "text-slate-600 hover:bg-surface-sunken hover:text-slate-900"
                  }`}
                  onClick={toggleGroupByProject}
                >
                  <Layers className="h-3.5 w-3.5" aria-hidden />
                  Group by project
                </button>
              ) : null}
              <label className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-xs font-medium text-slate-600 transition hover:bg-surface-sunken hover:text-slate-900">
                <ArrowUpDown className="h-3.5 w-3.5" aria-hidden />
                <span className="sr-only">Sort</span>
                <select
                  aria-label="Sort tasks"
                  className="h-full max-w-[90px] border-0 bg-transparent pr-1 text-xs font-medium text-slate-600 outline-none"
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
          </div>
        ) : null}

        {mutationError ? <div role="alert" className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{mutationError}</div> : null}

        {isDesktop || !taskId ? (
          groupByProject ? (
            allTasksQuery.isError || projectsQuery.isError || tagsQuery.isError ? (
              <ErrorState
                message={getErrorMessage(allTasksQuery.error ?? projectsQuery.error ?? tagsQuery.error)}
                onRetry={() => {
                  void allTasksQuery.refetch();
                  void projectsQuery.refetch();
                  void tagsQuery.refetch();
                }}
              />
            ) : allTasksQuery.isLoading || projectsQuery.isLoading || tagsQuery.isLoading ? (
              <LoadingState label={`${title} grouped by project`} />
            ) : projectGroups.length ? (
              <div className="flex flex-col gap-5" data-testid="grouped-task-list" aria-label={`${title} grouped by project`}>
                {projectGroups.map((group) => {
                  const groupKey = group.project?.id ?? "no-project";
                  return (
                    <section key={groupKey} aria-labelledby={`task-group-${groupKey}`}>
                      <h2
                        id={`task-group-${groupKey}`}
                        className="mb-2 flex items-center gap-2 px-1 text-xs font-semibold uppercase tracking-wide text-slate-500"
                      >
                        <span
                          aria-hidden
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{ backgroundColor: group.project?.color ?? "#94a3b8" }}
                        />
                        <span>{group.project ? group.project.name : "No project"}</span>
                        <span className="font-normal normal-case tracking-normal text-slate-400">{group.tasks.length}</span>
                      </h2>
                      <TaskList
                        {...sharedTaskListProps}
                        tasks={group.tasks}
                        showProjectColumn={false}
                        listLabel={group.project ? `Tasks in ${group.project.name}` : "Tasks with no project"}
                      />
                    </section>
                  );
                })}
              </div>
            ) : (
              <EmptyState state={state} />
            )
          ) : hasFrameError ? (
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
            <TaskList {...sharedTaskListProps} tasks={tasks} showProjectColumn />
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
            headingRef={registerDetailHeading}
            onClose={closeDetail}
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

        {(isDesktop || !taskId) && !groupByProject && taskQuery.hasNextPage ? (
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
            showCompleted={showCompleted}
            isCreating={createMutation.isPending}
            onCreate={(draft) => createMutation.mutate(draft)}
            onTitleChange={setNewTitle}
            onWaitingForChange={setNewWaitingFor}
            onToggleCompleted={setShowCompleted}
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
  showProjectColumn = true,
  listLabel = "Tasks",
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
  registerDetailHeading,
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
  showProjectColumn?: boolean;
  listLabel?: string;
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
  registerDetailHeading: (el: HTMLHeadingElement | null) => void;
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
    <div className="flex flex-col gap-2" role="list" aria-label={listLabel}>
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
            showProjectColumn={showProjectColumn}
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
                headingRef={registerDetailHeading}
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
  showProjectColumn,
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
  showProjectColumn: boolean;
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
  const isWaiting = task.state === "waiting" && Boolean(task.waiting_for);
  const navigate = useNavigate();

  return (
    <article
      className={`group flex flex-col gap-1.5 rounded-[14px] border p-3.5 shadow-soft transition hover:shadow-raised sm:gap-2 sm:rounded-[12px] sm:px-3 sm:py-4 ${
        isTerminal ? "border-emerald-100 bg-emerald-50/50" : isExpanded ? "border-slate-200 bg-white shadow-raised" : "border-slate-200 bg-white"
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
        navigate(detailPath, { state: { fromList: true } });
      }}
    >
      <div className="flex items-start gap-3 sm:items-center">
        {isTerminal ? (
          <span className="inline-flex h-8 shrink-0 items-center justify-center rounded-lg border border-emerald-200 bg-white px-2 text-xs font-medium text-emerald-700">
            {task.state === "completed" ? "Completed" : "Cancelled"}
          </span>
        ) : (
          <button
            type="button"
            className="relative -m-[11px] flex h-11 w-11 shrink-0 items-center justify-center sm:m-0 sm:h-[18px] sm:w-[18px] sm:rounded-full sm:border-[1.5px] sm:border-slate-300 sm:bg-white sm:text-white sm:hover:border-sky-400 sm:hover:bg-sky-500"
            aria-label={`Complete ${task.title}`}
            onClick={() => onComplete(task)}
          >
            <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full border-[1.5px] border-slate-300 bg-white text-white sm:hidden" aria-hidden>
              <Check className="h-3.5 w-3.5" />
            </span>
            <Check className="hidden h-3 w-3 sm:block" aria-hidden />
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
          <Link
            ref={(el) => registerRowLink(task.id, el)}
            to={detailPath}
            state={{ fromList: true }}
            className={`min-w-0 flex-1 break-words text-sm font-medium leading-snug text-slate-900 hover:text-brand-primary ${isTerminal ? "line-through decoration-emerald-500/70" : ""}`}
          >
            {task.title}
          </Link>
        )}
        {!isEditing && !isTerminal ? (
          <span className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100">
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
                className="h-7 whitespace-nowrap rounded-lg border border-slate-200 bg-white px-2 text-[11px] text-slate-600 hover:text-slate-900"
                aria-label={`Move ${task.title} to Next`}
                onClick={() => onMoveToNext(task)}
              >
                → Next
              </button>
            ) : null}
          </span>
        ) : null}
        {project && showProjectColumn ? (
          <span className="hidden shrink-0 self-start pt-0.5 text-right text-[11px] leading-snug text-slate-500 sm:block sm:w-[96px]">
            {project.name}
          </span>
        ) : null}
      </div>
      {isWaiting || task.due_date || tags.length || (project && showProjectColumn) ? (
        <div className="flex flex-wrap items-center gap-1.5 pl-[34px] sm:pl-[30px]">
          {isWaiting ? (
            <span className="text-[11px] text-slate-500">
              Waiting on {task.waiting_for}
              {task.waiting_since ? ` · since ${formatWaitingSince(task.waiting_since)}` : ""}
            </span>
          ) : null}
          {task.due_date ? <Chip variant="due">{formatDueDate(task.due_date)}</Chip> : null}
          {tags.map((tag) => (
            <Chip key={tag.id} variant="neutral">{tagLabel(tag)}</Chip>
          ))}
          {project && showProjectColumn ? (
            <span className="text-[11px] text-slate-500 sm:hidden">{project.name}</span>
          ) : null}
        </div>
      ) : null}
      {children}
    </article>
  );
}

const detailFieldClass =
  "min-h-10 rounded-lg border border-slate-200 px-3 text-sm text-slate-900 outline-none focus:border-brand-primary focus:shadow-ring-focus";

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
  headingRef: (el: HTMLHeadingElement | null) => void;
  onClose: () => void;
  onSave: (task: TaskResponse, payload: Parameters<typeof apiClient.updateTask>[1]) => void;
  onTransition: (task: TaskResponse, action: "move" | "complete" | "reopen" | "cancel", toState?: OpenTaskState, waitingFor?: string) => void;
  onCreateSubtask: (task: TaskResponse, title: string) => void;
  onTransitionSubtask: (task: TaskResponse, subtask: TaskSubtaskResponse, action: "complete" | "reopen" | "cancel") => void;
  onCreateComment: (task: TaskResponse, body: string) => void;
}): JSX.Element {
  const summaryProject = task?.project_id ? projects.find((candidate) => candidate.id === task.project_id) : undefined;
  const summaryState = task
    ? task.state === "completed"
      ? "Completed"
      : task.state === "cancelled"
        ? "Cancelled"
        : stateLabels[task.state]
    : undefined;

  return (
    <aside
      className="-mx-4 -my-5 flex min-h-screen flex-col gap-[18px] bg-surface-base px-4 py-5 sm:-mx-6 sm:px-6 motion-safe:lg:animate-detail-enter lg:m-0 lg:min-h-0 lg:bg-transparent lg:p-0 lg:pt-3.5 lg:border-t lg:border-slate-200"
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
        <button
          type="button"
          className="hidden h-8 items-center gap-1 rounded-lg border border-slate-200 px-2 text-xs text-slate-600 lg:inline-flex"
          onClick={onClose}
        >
          <X className="h-3.5 w-3.5" aria-hidden />
          Close
        </button>
      </div>

      {isLoading ? <p className="text-sm text-slate-600">Loading task detail…</p> : null}
      {error ? <p role="alert" className="text-sm text-rose-700">{getErrorMessage(error)}</p> : null}
      {task ? (
        <div className="flex flex-col gap-[18px]">
          <div
            data-testid="task-detail-summary"
            className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600 lg:hidden"
          >
            {summaryState ? <Chip variant="neutral">{summaryState}</Chip> : null}
            {summaryProject ? <Chip variant="neutral">{summaryProject.name}</Chip> : null}
            {task.due_date ? <Chip variant="due">{formatDueDate(task.due_date)}</Chip> : null}
            {task.priority !== "none" ? <Chip variant="neutral">{task.priority} priority</Chip> : null}
            {task.state === "waiting" && task.waiting_for ? <span>Waiting on {task.waiting_for}</span> : null}
          </div>
          <form
            className="grid gap-3 lg:grid-cols-2"
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
              <input name="title" aria-label="Title" defaultValue={task.title} className={detailFieldClass} />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
              Project
              <select name="project_id" aria-label="Project" defaultValue={task.project_id ?? ""} className={detailFieldClass}>
                <option value="">No project</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600 lg:col-span-2">
              Details
              <textarea name="details" aria-label="Details" defaultValue={task.details ?? ""} rows={3} className={`${detailFieldClass} py-2`} />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
              Due date
              <input name="due_date" aria-label="Due date" type="date" defaultValue={task.due_date ?? ""} className={detailFieldClass} />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
              Priority
              <select name="priority" aria-label="Priority" defaultValue={task.priority} className={detailFieldClass}>
                <option value="none">None</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
              Waiting for
              <input name="waiting_for" aria-label="Waiting for" defaultValue={task.waiting_for ?? ""} className={detailFieldClass} />
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
            <div className="flex flex-wrap items-end gap-2 lg:col-span-2">
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

          <div className="flex flex-col gap-2">
            <h3 className="m-0 text-xs font-semibold uppercase tracking-wide text-slate-500">Subtasks</h3>
            <div className="flex flex-col gap-1.5" aria-label="Subtasks">
              {(task.subtasks ?? []).map((subtask) => {
                const done = subtask.state !== "open";
                return (
                  <div key={subtask.id} className="flex items-center gap-2 text-sm">
                    <button
                      type="button"
                      className="relative -m-[15px] flex h-11 w-11 shrink-0 items-center justify-center lg:m-0 lg:h-[14px] lg:w-[14px]"
                      aria-label={done ? `Reopen ${subtask.title}` : `Complete ${subtask.title}`}
                      onClick={() => onTransitionSubtask(task, subtask, done ? "reopen" : "complete")}
                    >
                      <span
                        aria-hidden
                        className={`flex h-[14px] w-[14px] items-center justify-center rounded-full border border-[1.5px] ${
                          done ? "border-brand-primary bg-brand-primary text-white" : "border-slate-300 bg-white text-white"
                        }`}
                      >
                        <Check className="h-2.5 w-2.5" />
                      </span>
                    </button>
                    <span className={done ? "text-slate-500 line-through" : "text-slate-800"}>{subtask.title}</span>
                  </div>
                );
              })}
            </div>
            <form
              className="flex w-full gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/70 p-2 lg:max-w-[380px]"
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
              <input name="subtask_title" aria-label="New subtask title" className="min-h-10 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm" placeholder="Add a subtask" />
              <button type="submit" className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm">Add subtask</button>
            </form>
          </div>

          <div className="flex flex-col gap-2" data-testid="task-detail-agent">
            <h3 className="m-0 text-xs font-semibold uppercase tracking-wide text-slate-500">Agent</h3>
            <div className="flex items-center gap-2">
              <SoonChip />
              <span className="sr-only">Coming soon</span>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <h3 className="m-0 text-xs font-semibold uppercase tracking-wide text-slate-500">Comments</h3>
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
              className="flex w-full gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/70 p-2 lg:max-w-[380px]"
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
              <input name="comment_body" aria-label="New comment" className="min-h-10 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm" placeholder="Add a comment" />
              <button type="submit" className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm">Add comment</button>
            </form>
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

function formatWaitingSince(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

interface ProjectGroup {
  project: ProjectResponse | null;
  tasks: TaskResponse[];
}

function groupTasksByProject(tasks: TaskResponse[], projects: ProjectResponse[]): ProjectGroup[] {
  const byProjectId = new Map<string, TaskResponse[]>();
  const unassigned: TaskResponse[] = [];
  for (const task of tasks) {
    if (task.project_id) {
      const bucket = byProjectId.get(task.project_id) ?? [];
      bucket.push(task);
      byProjectId.set(task.project_id, bucket);
    } else {
      unassigned.push(task);
    }
  }
  const groups: ProjectGroup[] = projects
    .filter((project) => byProjectId.has(project.id))
    .map((project) => ({ project, tasks: byProjectId.get(project.id) ?? [] }));
  if (unassigned.length) {
    groups.push({ project: null, tasks: unassigned });
  }
  return groups;
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
