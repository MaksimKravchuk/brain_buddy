import { AlertTriangle, Bot, CalendarDays, Check, ChevronDown, Layers, Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useAgentRunSummaries } from "../../api/agentHooks";
import type { AgentRunSummaryResponse } from "../../api/agentTypes";

import { apiClient, getApiBaseUrl } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";
import { parseOpenTaskState, parseTaskDateView, taskKeys, useProjects, useTags, useTaskDetail, useTaskList } from "../../api/taskHooks";
import type { OpenTaskState, ProjectResponse, TagResponse, TaskCounts, TaskResponse, TaskSubtaskResponse, TaskSort } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { Button } from "../../components/ui/Button";
import { getErrorMessage } from "../../utils/error";
import { applySmartAddSuggestion, parseSmartAdd, smartAddChips, smartAddSuggestions } from "./smartAdd";
import type { SmartAddDraft, SmartAddSuggestion } from "./smartAdd";
import { SmartAddSuggestions } from "./SmartAddSuggestions";
import { TaskTitleAutocompleteSuggestions } from "./TaskTitleAutocompleteSuggestions";
import { TaskDetailPanel } from "./TaskDetailPanel";
import { getTaskDetailAutosaveController } from "./taskDetailAutosave";
import type { AutosaveResult } from "./taskDetailAutosave";
import { useTaskTitleAutocomplete } from "./useTaskTitleAutocomplete";

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

function idempotencyKey(action: string): string {
  return `task-shell-${action}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function captureSignature(draft: SmartAddDraft, state: OpenTaskState | undefined, projectId: string | undefined, tagId: string | undefined, waitingFor: string): string {
  return JSON.stringify({
    title: draft.cleanTitle,
    state: state ?? "inbox",
    ...(state === "waiting" ? { waiting_for: waitingFor.trim() } : {}),
    ...(draft.hasCompletedTokens ? { project: draft.project, tags: draft.tags } : { ...(projectId ? { project_id: projectId } : {}), ...(tagId ? { tag_ids: [tagId] } : {}) })
  });
}

// Sidebar writes are modelled as commands rather than one loose bag of optional
// fields, so "rename without a project" cannot be constructed at all instead of
// being caught by a runtime guard no caller can reach.
type ProjectCommand =
  | { action: "create"; name: string }
  | { action: "rename"; project: ProjectResponse; name: string }
  | { action: "archive"; project: ProjectResponse };

type TagCommand =
  | { action: "create"; name: string }
  | { action: "rename"; tag: TagResponse; name: string }
  | { action: "delete"; tag: TagResponse };

export function TaskListPage({ mode }: { mode?: "state" | "project" | "tag" }): React.JSX.Element {
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
  const [showCompleted, setShowCompleted] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [autosaveConflict, setAutosaveConflict] = useState<Extract<AutosaveResult, { status: "conflict" }> | null>(null);
  const [recoveryAvailable, setRecoveryAvailable] = useState(false);
  const [canonicalResetKey, setCanonicalResetKey] = useState(0);
  const conflictControllerRef = useRef<ReturnType<typeof getTaskDetailAutosaveController> | null>(null);
  const discardFocusRef = useRef<HTMLElement | null>(null);
  const newTitleRef = useRef(newTitle);
  const newWaitingForRef = useRef(newWaitingFor);
  newTitleRef.current = newTitle;
  newWaitingForRef.current = newWaitingFor;
  type CaptureRequest = {
    payload: Parameters<typeof apiClient.createTask>[0] | Parameters<typeof apiClient.smartAddTask>[0];
    key: string;
    signature: string;
    smart: boolean;
    restoreFocus: () => void;
  };
  const captureAttemptRef = useRef<{ signature: string; key: string } | null>(null);
  const [captureSettlementVersion, setCaptureSettlementVersion] = useState(0);
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
  // A project view is already one project, and Inbox is by definition the
  // projectless projection, so grouping either would produce a single heading.
  const canGroupByProject = !projectId && state !== "inbox";
  // The prototype groups by project out of the box; the URL carries the
  // opt-out beside `sort` so a flat view survives reload and sharing.
  const groupByProject = canGroupByProject && searchParams.get("group") !== "off";
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
    if (taskId) {
      setPanelOpen(true);
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
  const counts = taskQuery.data?.counts_by_state ?? emptyCounts;

  const accountId = useAuthStore((store) => store.user?.id);
  const detailController = detailQuery.data && accountId
    ? getTaskDetailAutosaveController(accountId, getApiBaseUrl(), detailQuery.data, (accepted) => {
        queryClient.setQueryData(taskKeys.detail(accepted.id), accepted);
        queryClient.setQueriesData<{ pages: Array<{ items: TaskResponse[] }>; pageParams: unknown[] }>(
          { queryKey: ["tasks", "list"] },
          (cached) => cached ? { ...cached, pages: cached.pages.map((page) => ({ ...page, items: page.items.map((item) => item.id === accepted.id ? accepted : item) })) } : cached
        );
        return invalidateTasks();
      })
    : null;

  const invalidateTasks = () => queryClient.invalidateQueries({ queryKey: ["tasks"] });
  const applyCanonicalTask = (canonical: TaskResponse) => {
    queryClient.setQueryData(taskKeys.detail(canonical.id), canonical);
    queryClient.setQueriesData<{
      pages: Array<{ items: TaskResponse[] }>;
      pageParams: unknown[];
    }>({ queryKey: ["tasks", "list"] }, (cached) => {
      if (!cached) return cached;
      return {
        ...cached,
        pages: cached.pages.map((page) => ({
          ...page,
          items: page.items.map((item) => item.id === canonical.id ? canonical : item)
        }))
      };
    });
    void invalidateTasks();
  };
  const refetchCanonicalProjections = async (canonical: TaskResponse) => {
    // Apply the server-authoritative detail and list snapshot before waiting on
    // the network refresh, so Discard never leaves a stale row/count visible.
    applyCanonicalTask(canonical);
    await taskQuery.refetch();
  };
  useEffect(() => {
    setAutosaveConflict(null);
    const available = Boolean(detailController?.recover());
    setRecoveryAvailable(available);
    if (available) setMutationError("Unsaved task change recovered. Retry or Discard.");
  }, [detailController, taskId]);

  useEffect(() => {
    if (canonicalResetKey === 0 || !discardFocusRef.current) return;
    discardFocusRef.current.focus();
    discardFocusRef.current = null;
  }, [canonicalResetKey]);

  const handleAutosaveResult = (result: AutosaveResult, controller?: ReturnType<typeof getTaskDetailAutosaveController>) => {
    if (result.status === "conflict") {
      conflictControllerRef.current = controller ?? detailController;
      setAutosaveConflict(result);
      setMutationError("Task changed elsewhere. Choose Retry or Discard.");
      return;
    }
    setAutosaveConflict(null);
    setRecoveryAvailable(false);
    setMutationError("Saved");
    window.setTimeout(() => setMutationError((message) => message === "Saved" ? null : message), 1500);
  };

  const recoverAutosave = () => {
    if (!detailController) return;
    void detailController.resumeRecovery().then(handleAutosaveResult).catch((caught: unknown) => setMutationError(getErrorMessage(caught)));
  };

  const discardAutosave = async () => {
    const controller = detailController ?? conflictControllerRef.current;
    if (!controller || !window.confirm("Discard this unsaved change?")) return;
    if (document.activeElement instanceof HTMLTextAreaElement && document.activeElement.getAttribute("aria-label") === "Title") {
      discardFocusRef.current = document.activeElement;
    } else {
      discardFocusRef.current = detailHeadingRef.current ?? listHeadingRef.current;
    }
    if (autosaveConflict) {
      await refetchCanonicalProjections(autosaveConflict.discard());
      setCanonicalResetKey((key) => key + 1);
      setAutosaveConflict(null);
      setRecoveryAvailable(false);
      setMutationError(null);
      return;
    }
    controller.discardRecovery();
    try {
      const { data: canonical } = await detailQuery.refetch();
      if (canonical) {
        await refetchCanonicalProjections(canonical);
        setCanonicalResetKey((key) => key + 1);
      }
      setRecoveryAvailable(false);
      setMutationError(null);
    } catch (caught: unknown) {
      setMutationError(getErrorMessage(caught));
    }
  };
  const listPath = projectId
    ? `/projects/${projectId}`
    : tagId
      ? `/tags/${tagId}`
      : `/tasks/${params.state ?? "next"}`;
  const closeTarget = { pathname: listPath, search: searchParams.toString() };

  // Prototype keyboard model: Escape deselects the task, ⌘\ toggles the panel.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "\\" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setPanelOpen((open) => !open);
        return;
      }
      if (event.key !== "Escape" || !taskId) {
        return;
      }
      const target = event.target as HTMLElement | null;
      // A modal surface (brain dump, mobile drawer) or a focused field owns
      // Escape; deselecting underneath it would yank the view away.
      if (target?.closest("input, textarea, select, [role=dialog]") || document.querySelector('[role="dialog"][aria-modal="true"]')) {
        return;
      }
      navigate(closeTarget);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  });

  const createMutation = useMutation({
    mutationFn: (request: CaptureRequest) => request.smart
      ? apiClient.smartAddTask(request.payload as Parameters<typeof apiClient.smartAddTask>[0], request.key).then((response) => response.task)
      : apiClient.createTask(request.payload as Parameters<typeof apiClient.createTask>[0], request.key),
    onSuccess: (_task, request) => {
      const currentDraft = parseSmartAdd(newTitleRef.current, { projects, tags, contextProjectId: projectId, contextTagId: tagId });
      if (captureSignature(currentDraft, state, projectId, tagId, newWaitingForRef.current) === request.signature) {
        setNewTitle("");
        setNewWaitingFor("");
        request.restoreFocus();
      }
      captureAttemptRef.current = null;
      setCaptureSettlementVersion((version) => version + 1);
      setMutationError(null);
      void invalidateTasks();
      void queryClient.invalidateQueries({ queryKey: ["tasks", "projects"] });
      void queryClient.invalidateQueries({ queryKey: ["tasks", "tags"] });
    },
    onError: (caught: unknown) => {
      setCaptureSettlementVersion((version) => version + 1);
      setMutationError(getErrorMessage(caught));
    }
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
    mutationFn: (command: ProjectCommand) => {
      if (command.action === "create") {
        return apiClient.createProject({ name: command.name }, idempotencyKey("create-project"));
      }
      if (command.action === "archive") {
        return apiClient.archiveProject(command.project.id, command.project.revision, idempotencyKey("archive-project"));
      }
      return apiClient.updateProject(
        command.project.id,
        { name: command.name, expected_revision: command.project.revision },
        idempotencyKey("rename-project")
      );
    },
    onSuccess: (_project, command) => {
      setMutationError(null);
      void invalidateTasks();
      void queryClient.invalidateQueries({ queryKey: ["tasks", "projects"] });
      if (command.action === "archive" && command.project.id === projectId) {
        navigate("/tasks/next");
      }
    },
    onError: (caught: unknown) => setMutationError(getErrorMessage(caught))
  });

  const tagMutation = useMutation({
    mutationFn: (command: TagCommand) => {
      if (command.action === "create") {
        return apiClient.createTag({ name: command.name }, idempotencyKey("create-tag"));
      }
      if (command.action === "delete") {
        return apiClient.deleteTag(command.tag.id, command.tag.revision, idempotencyKey("delete-tag"));
      }
      return apiClient.updateTag(
        command.tag.id,
        { name: command.name, expected_revision: command.tag.revision },
        idempotencyKey("rename-tag")
      );
    },
    onSuccess: (_tag, command) => {
      setMutationError(null);
      void invalidateTasks();
      void queryClient.invalidateQueries({ queryKey: ["tasks", "tags"] });
      if (command.action === "delete" && command.tag.id === tagId) {
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

  // The prototype's Inbox pane leads with a processing hint instead of a count.
  const taskNoun = counts[state ?? "next"] === 1 ? "task" : "tasks";
  const meta = state === "inbox"
    ? "Process these — decide the next action for each."
    : state
      ? `${counts[state]} ${taskNoun}`
      : `${tasks.length} ${tasks.length === 1 ? "task" : "tasks"}`;

  const hasFrameError = taskQuery.isError || projectsQuery.isError || tagsQuery.isError;

  // Existing run chips stay visible after rollout is disabled; only creation of
  // new hand-offs is gated. A failed summary fetch still degrades to no chips.
  const hasOwner = Boolean(useAuthStore((store) => store.user));
  const agentRunSummaries =
    useAgentRunSummaries(tasks.map((task) => task.id), hasOwner).data ?? {};

  // Shared by the flat list and by every project group, so the two render paths
  // can never drift apart.
  const taskListProps = {
    tags,
    taskPathBase: listPath,
    taskSearch: searchParams.toString(),
    selectedTaskId: taskId,
    registerRowLink,
    onComplete: (task: TaskResponse) => {
      if (!accountId) return;
      const controller = getTaskDetailAutosaveController(accountId, getApiBaseUrl(), task, (accepted) => {
        queryClient.setQueryData(taskKeys.detail(accepted.id), accepted);
        return invalidateTasks();
      });
      conflictControllerRef.current = controller;
      void controller.save({ kind: "transition", payload: { action: "complete" } }, idempotencyKey("complete"))
        .then((result) => handleAutosaveResult(result, controller))
        .catch((caught: unknown) => setMutationError(getErrorMessage(caught)));
    },
    agentRuns: agentRunSummaries
  };

  const panel = panelOpen && taskId ? (
    <TaskDetailPanel
      task={detailQuery.data}
      autosave={detailController ?? undefined}
      resetKey={canonicalResetKey}
      projects={projects}
      tags={tags}
      isLoading={detailQuery.isLoading}
      error={detailQuery.error}
      headingRef={detailHeadingRef}
      onClose={() => navigate(closeTarget)}
      // Autosave owns every mutation when a controller exists; these fallbacks
      // are only reached with no account (and thus no controller), where there
      // is nothing to save, so they stay no-ops rather than dead `.save()` calls.
      onSave={() => undefined}
      onTransition={() => undefined}
      onCreateSubtask={(task, subtaskTitle) => subtaskCreateMutation.mutate({ task, title: subtaskTitle })}
      onTransitionSubtask={(task, subtask, action) => subtaskTransitionMutation.mutate({ task, subtask, action })}
      onCreateComment={(task, body) => commentCreateMutation.mutate({ task, body })}
    />
  ) : null;

  return (
    <AppShell
      counts={shellCounts}
      projects={projects}
      tags={tags}
      activeState={state}
      activeProjectId={projectId}
      activeTagId={tagId}
      panel={panel}
      onCreateProject={(name) => projectMutation.mutate({ action: "create", name })}
      onRenameProject={(project, name) => projectMutation.mutate({ action: "rename", project, name })}
      onArchiveProject={(project) => projectMutation.mutate({ action: "archive", project })}
      onCreateTag={(name) => tagMutation.mutate({ action: "create", name })}
      onRenameTag={(tag, name) => tagMutation.mutate({ action: "rename", tag, name })}
      onDeleteTag={(tag) => tagMutation.mutate({ action: "delete", tag })}
    >
      <section aria-labelledby="task-list-title" className="mx-auto max-w-[760px]">
        <div className="mb-5 flex flex-wrap items-end gap-x-3 gap-y-2">
          <div className="min-w-0">
            <h1 id="task-list-title" ref={listHeadingRef} tabIndex={-1} className="m-0 text-title font-semibold text-slate-900 outline-none">
              {title}
            </h1>
            <p className="m-0 mt-1 text-xs text-slate-500">{meta}</p>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            {canGroupByProject ? (
              <Button
                variant={groupByProject ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={groupByProject}
                leftIcon={<Layers aria-hidden />}
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  if (groupByProject) {
                    next.set("group", "off");
                  } else {
                    next.delete("group");
                  }
                  setSearchParams(next, { replace: true });
                }}
              >
                Group by project
              </Button>
            ) : null}
            <label className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-lg px-2.5 text-xs font-medium text-slate-600 transition-colors duration-200 ease-smooth hover:bg-surface-sunken hover:text-slate-900">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 rounded border-slate-300 text-brand-primary accent-brand-primary"
                checked={showCompleted}
                onChange={(event) => setShowCompleted(event.currentTarget.checked)}
              />
              Show completed
            </label>
            <label className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-slate-600 transition-colors duration-200 ease-smooth hover:bg-surface-sunken hover:text-slate-900">
              <span className="text-slate-500">Sort</span>
              <span className="relative inline-flex">
                <select
                  aria-label="Sort tasks"
                  className="appearance-none bg-transparent pr-5 text-xs font-medium text-slate-700 outline-none"
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
                <ChevronDown className="pointer-events-none absolute right-0 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden />
              </span>
            </label>
          </div>
        </div>

        {mutationError ? (
          <div role="alert" className="relative z-50 mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            <span>{mutationError}</span>
            {autosaveConflict ? <Button size="sm" variant="secondary" onClick={() => void autosaveConflict.retry().then(handleAutosaveResult).catch((caught: unknown) => setMutationError(getErrorMessage(caught)))}>Retry</Button> : recoveryAvailable ? <Button size="sm" variant="secondary" onClick={recoverAutosave}>Retry</Button> : null}
            {(autosaveConflict || recoveryAvailable) ? <Button size="sm" variant="ghost" onMouseDown={(event) => event.preventDefault()} onClick={discardAutosave}>Discard</Button> : null}
          </div>
        ) : null}

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
          groupByProject ? (
            <div className="flex flex-col gap-6">
              {groupTasksByProject(tasks, projects).map((group) => (
                <section key={group.key} aria-labelledby={`task-group-${group.key}`}>
                  <div className="mb-2 flex items-baseline gap-2.5 px-1">
                    <span
                      className="h-2 w-2 shrink-0 self-center rounded-full"
                      style={{ backgroundColor: group.color ?? "#cbd5e1" }}
                      aria-hidden
                    />
                    <h2
                      id={`task-group-${group.key}`}
                      className="m-0 min-w-0 truncate text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500"
                    >
                      {group.name}
                    </h2>
                    <span className="text-xs font-medium text-slate-400">{group.tasks.length}</span>
                  </div>
                  <TaskList {...taskListProps} tasks={group.tasks} label={group.name} />
                </section>
              ))}
            </div>
          ) : (
            <TaskList {...taskListProps} tasks={tasks} />
          )
        ) : (
          <EmptyState
            state={state}
            onClearSearch={searchQuery.trim() ? () => {
              const next = new URLSearchParams(searchParams);
              next.delete("q");
              setSearchParams(next, { replace: true });
              listHeadingRef.current?.focus();
            } : undefined}
          />
        )}

        {taskQuery.hasNextPage ? (
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
            isCreating={createMutation.isPending}
            captureSettlementVersion={captureSettlementVersion}
            onCreate={(draft, restoreFocus) => {
              const waitingFor = newWaitingForRef.current;
              const payload = {
                title: draft.cleanTitle,
                state: state ?? "inbox",
                ...(state === "waiting" ? { waiting_for: waitingFor.trim() } : {}),
                ...(draft.hasCompletedTokens
                  ? { project: draft.project, tags: draft.tags }
                  : { ...(projectId ? { project_id: projectId } : {}), ...(tagId ? { tag_ids: [tagId] } : {}) })
              };
              const signature = captureSignature(draft, state, projectId, tagId, waitingFor);
              const previous = captureAttemptRef.current;
              const key = previous?.signature === signature ? previous.key : idempotencyKey(draft.hasCompletedTokens ? "smart-add" : "create");
              captureAttemptRef.current = { signature, key };
              createMutation.mutate({ payload, key, signature, smart: draft.hasCompletedTokens, restoreFocus });
            }}
            onTitleChange={setNewTitle}
            onWaitingForChange={setNewWaitingFor}
          />
        )}
      </section>
    </AppShell>
  );
}

interface TaskProjectGroup {
  key: string;
  name: string;
  color: string | null;
  tasks: TaskResponse[];
}

/**
 * Groups tasks by project, preserving the order the server returned so an active
 * sort still holds inside each group. Groups appear in first-seen order and
 * "No project" sinks to the bottom, matching the design prototype.
 */
function groupTasksByProject(tasks: TaskResponse[], projects: ProjectResponse[]): TaskProjectGroup[] {
  const projectById = new Map(projects.map((project) => [project.id, project]));
  const groups: TaskProjectGroup[] = [];
  const byKey = new Map<string, TaskProjectGroup>();

  for (const task of tasks) {
    const key = task.project_id ?? "__none__";
    let group = byKey.get(key);
    if (!group) {
      const project = task.project_id ? projectById.get(task.project_id) : undefined;
      group = {
        key,
        name: project?.name ?? "No project",
        color: project?.color ?? null,
        tasks: []
      };
      byKey.set(key, group);
      groups.push(group);
    }
    group.tasks.push(task);
  }

  return groups.sort((left, right) => Number(left.key === "__none__") - Number(right.key === "__none__"));
}

// Every call site names its variant, so there is deliberately no default: a
// silent fallback would let a new call site render the wrong chip unnoticed.
function Chip({ variant, children }: {
  variant: "due" | "neutral" | "agent" | "needs-you";
  children: ReactNode;
}): React.JSX.Element {
  const variantClass =
    variant === "due"
      ? "border-due-border bg-due-bg text-due-fg"
      : variant === "agent"
        ? "border-ai-border bg-ai-bg text-ai-fg"
        : variant === "needs-you"
          ? "border-needs-you-border bg-needs-you-bg text-needs-you-fg"
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
  tags,
  taskPathBase,
  taskSearch,
  selectedTaskId,
  registerRowLink,
  onComplete,
  agentRuns,
  label
}: {
  tasks: TaskResponse[];
  tags: TagResponse[];
  taskPathBase: string;
  taskSearch: string;
  selectedTaskId?: string;
  registerRowLink: (taskId: string, el: HTMLAnchorElement | null) => void;
  onComplete: (task: TaskResponse) => void;
  /** Latest external run per task, sparse: most tasks have none. */
  agentRuns: Record<string, AgentRunSummaryResponse>;
  /** Names this list for assistive tech; each group supplies its project name. */
  label?: string;
}): React.JSX.Element {
  const tagById = new Map(tags.map((tag) => [tag.id, tag]));

  return (
    <div className="flex flex-col gap-[5px]" role="list" aria-label={label ?? "Tasks"}>
      {tasks.map((task) => (
        <TaskRow
          key={task.id}
          task={task}
          tags={task.tag_ids.map((id) => tagById.get(id)).filter((tag): tag is TagResponse => Boolean(tag))}
          detailPath={`${taskPathBase}/${task.id}${taskSearch ? `?${taskSearch}` : ""}`}
          isSelected={selectedTaskId === task.id}
          registerRowLink={registerRowLink}
          onComplete={onComplete}
          agentRun={agentRuns[task.id]}
        />
      ))}
    </div>
  );
}

function TaskRow({
  task,
  tags,
  detailPath,
  isSelected,
  registerRowLink,
  onComplete,
  agentRun
}: {
  task: TaskResponse;
  tags: TagResponse[];
  detailPath: string;
  isSelected: boolean;
  registerRowLink: (taskId: string, el: HTMLAnchorElement | null) => void;
  onComplete: (task: TaskResponse) => void;
  agentRun?: AgentRunSummaryResponse;
}): React.JSX.Element {
  const isTerminal = task.state === "completed" || task.state === "cancelled";
  const navigate = useNavigate();
  const subtasks = task.subtasks ?? [];
  const doneSubtasks = subtasks.filter((subtask) => subtask.state !== "open").length;

  return (
    <article
      className={`group rounded-[12px] border px-3.5 py-[7px] transition-colors duration-200 ease-smooth ${
        isSelected ? "border-sky-700 bg-info-bg" : "border-slate-200 bg-white hover:bg-slate-50"
      } ${isTerminal ? "opacity-45" : ""}`}
      role="listitem"
      onClick={(event) => {
        const target = event.target as HTMLElement;
        if (target.closest("a, button, input, textarea, select, label")) {
          return;
        }
        navigate(detailPath);
      }}
    >
      <div className="flex min-h-[26px] flex-wrap items-center gap-x-2.5 gap-y-1.5">
        {isTerminal ? (
          <span
            aria-hidden
            className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border-[1.5px] ${
              task.state === "completed"
                ? "border-brand-primary bg-brand-primary text-white"
                : "border-slate-300 bg-slate-200 text-slate-500"
            }`}
          >
            {task.state === "completed" ? <Check className="h-[11px] w-[11px]" /> : <X className="h-2.5 w-2.5" />}
          </span>
        ) : (
          <button
            type="button"
            className="group/complete -my-[7px] -ml-3 flex h-11 w-11 shrink-0 items-center justify-center rounded-full"
            aria-label={`Complete ${task.title}`}
            onClick={() => onComplete(task)}
          >
            <span className="flex h-[18px] w-[18px] items-center justify-center rounded-full border-[1.5px] border-slate-300 bg-white text-transparent transition-colors duration-200 ease-smooth group-hover/complete:border-sky-700">
              <Check className="h-[11px] w-[11px]" aria-hidden />
            </span>
          </button>
        )}
        <Link
          ref={(el) => registerRowLink(task.id, el)}
          to={detailPath}
          className={`min-w-0 flex-1 truncate text-sm font-medium hover:text-brand-primary ${
            isTerminal ? "text-slate-500 line-through decoration-slate-300" : "text-slate-900"
          }`}
        >
          {task.title}
        </Link>
        {task.due_date ? (
          <Chip variant="due">
            <CalendarDays className="h-[11px] w-[11px]" aria-hidden />
            {formatDueDate(task.due_date)}
          </Chip>
        ) : null}
        {agentRun ? (
          // The server's own label, verbatim: the card can never describe a run
          // more confidently than the detail view does.
          <Chip variant={agentRun.needs_user ? "needs-you" : "agent"}>
            <Bot className="h-[11px] w-[11px]" aria-hidden />
            {agentRun.primary_state_label}
          </Chip>
        ) : null}
        {subtasks.length ? (
          <Chip variant="neutral">
            {doneSubtasks} / {subtasks.length}
          </Chip>
        ) : null}
        <span className="ml-auto flex shrink-0 items-center gap-2.5">
          {task.state === "waiting" && task.waiting_for ? (
            <span className="max-w-[140px] truncate text-[11px] text-slate-400">{task.waiting_for}</span>
          ) : null}
          {tags.map((tag) => (
            <Chip key={tag.id} variant="neutral">{tagLabel(tag)}</Chip>
          ))}
        </span>
      </div>
    </article>
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
  captureSettlementVersion,
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
  captureSettlementVersion: number;
  onCreate: (draft: SmartAddDraft, restoreFocus: () => void) => void;
  onTitleChange: (title: string) => void;
  onWaitingForChange: (value: string) => void;
}): React.JSX.Element {
  const waitingForRequired = state === "waiting";
  const inputRef = useRef<HTMLInputElement | null>(null);
  const composerRef = useRef<HTMLFormElement | null>(null);
  const submitLockedRef = useRef(false);
  const previousSettlementVersionRef = useRef(captureSettlementVersion);
  const [submitLocked, setSubmitLocked] = useState(false);
  const [caret, setCaret] = useState(0);
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(0);
  const [activeCompletionIndex, setActiveCompletionIndex] = useState(0);
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
  const autocompleteEnabled = useAuthStore(
    (store) => store.user?.feature_flags?.task_title_autocomplete === true
  );
  const autocomplete = useTaskTitleAutocomplete({
    enabled: autocompleteEnabled,
    draft: newTitle,
    projectId: contextProjectId ?? null,
    smartAddActive: popupOpen || draft.hasCompletedTokens
  });
  const completionListboxId = "task-title-completions";
  const completionsOpen = !popupOpen && autocomplete.candidates.length === 3;

  const placeholder = state === "next"
    ? "Add a next action"
    : contextProjectId
      ? "Add a task to this project"
      : "Add a task";

  const submitDraft = () => {
    if (!submitLockedRef.current && draft.isValid && (!waitingForRequired || newWaitingFor.trim())) {
      submitLockedRef.current = true;
      setSubmitLocked(true);
      setSuggestionsOpen(false);
      const origin = document.activeElement;
      onCreate(draft, () => {
        if (!origin || !composerRef.current?.contains(origin)) return;
        const active = document.activeElement;
        if (active === document.body || composerRef.current.contains(active)) inputRef.current?.focus();
      });
    }
  };

  useEffect(() => {
    if (captureSettlementVersion !== previousSettlementVersionRef.current) {
      previousSettlementVersionRef.current = captureSettlementVersion;
      submitLockedRef.current = false;
      setSubmitLocked(false);
    }
  }, [captureSettlementVersion]);

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

  const applyCompletion = (candidate: string, rank: number) => {
    onTitleChange(candidate);
    autocomplete.dismiss(candidate);
    setActiveCompletionIndex(0);
    inputRef.current?.focus();
    if (autocomplete.requestId) {
      void autocomplete.recordAcceptance(autocomplete.requestId, rank);
    }
  };

  return (
    <div className="mt-2 space-y-3">
      {/* The prototype's dashed "add task" row; the smart-add form lives inside
          it so the affordance is directly typable rather than click-to-expand. */}
      <form
        ref={composerRef}
        className="flex w-full flex-wrap items-center gap-3 rounded-[12px] border-[1.5px] border-dashed border-slate-300 bg-transparent px-4 py-3 transition-colors duration-200 ease-smooth focus-within:border-brand-primary hover:border-brand-primary"
        onSubmit={(event) => {
          event.preventDefault();
          submitDraft();
        }}
      >
        <Plus className="h-4 w-4 shrink-0 text-slate-400" aria-hidden />
        <label className="sr-only" htmlFor="new-task-title">New task title</label>
        <input
          ref={inputRef}
          id="new-task-title"
          aria-label="New task title"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={popupOpen || completionsOpen}
          aria-controls={popupOpen ? smartAddSuggestionsId : completionsOpen ? completionListboxId : undefined}
          aria-activedescendant={
            popupOpen
              ? `${smartAddSuggestionsId}-option-${selectedSuggestionIndex}`
              : completionsOpen
                ? `${completionListboxId}-option-${activeCompletionIndex}`
                : undefined
          }
          className="min-w-0 flex-1 bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400"
          placeholder={placeholder}
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
              if (!completionsOpen) return;
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                const direction = event.key === "ArrowDown" ? 1 : -1;
                setActiveCompletionIndex((current) => (current + direction + 3) % 3);
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                autocomplete.dismiss();
                return;
              }
              if (event.key === "Enter") {
                event.preventDefault();
                const candidate = autocomplete.candidates[activeCompletionIndex];
                if (candidate) applyCompletion(candidate, activeCompletionIndex + 1);
              }
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
              className="min-w-0 flex-1 bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400"
              placeholder="Waiting for who or what?"
              value={newWaitingFor}
              onChange={(event) => onWaitingForChange(event.currentTarget.value)}
            />
          </>
        ) : null}
        {newTitle.trim() ? (
          <Button
            type="submit"
            size="sm"
            isLoading={isCreating || submitLocked}
            disabled={submitLocked || !draft.isValid || (waitingForRequired && !newWaitingFor.trim())}
          >
            {isCreating || submitLocked ? "Adding task…" : "Add task"}
          </Button>
        ) : null}
      </form>
      {popupOpen ? (
        <SmartAddSuggestions
          suggestions={suggestions}
          activeIndex={selectedSuggestionIndex}
          listboxId={smartAddSuggestionsId}
          onSelect={applySuggestion}
        />
      ) : null}
      {!popupOpen && autocomplete.provider ? (
        <label className="flex items-start gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={autocomplete.consent}
            onChange={(event) => autocomplete.setConsent(event.currentTarget.checked)}
          />
          <span>
            Allow {autocomplete.provider} to process this draft, the selected Project name, and up to 50 prior task titles from this account for this request.
          </span>
        </label>
      ) : null}
      {completionsOpen ? (
        <TaskTitleAutocompleteSuggestions
          candidates={autocomplete.candidates}
          activeIndex={activeCompletionIndex}
          listboxId={completionListboxId}
          onSelect={applyCompletion}
        />
      ) : null}
      <div
        className="text-xs text-slate-500"
        role={autocomplete.loading || autocomplete.error ? "status" : undefined}
        aria-live="polite"
      >
        {autocomplete.loading ? "Finding title suggestions…" : autocomplete.error}
      </div>
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

function DateViewCaptureHint(): React.JSX.Element {
  return (
    <div className="mt-3 rounded-xl border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-800">
      Date views are filters over existing tasks. Add a task from Inbox, Next, Waiting, Someday, a Project, or a Tag, then set its due date in task detail.
    </div>
  );
}

function LoadingState({ label }: { label: string }): React.JSX.Element {
  return (
    <div className="space-y-[5px]" aria-label={`Loading ${label}`}>
      {[0, 1, 2, 3].map((item) => (
        <div key={item} className="h-10 animate-pulse rounded-[12px] border border-slate-200 bg-white" />
      ))}
    </div>
  );
}

function EmptyState({ state, onClearSearch }: { state?: OpenTaskState; onClearSearch?: () => void }): React.JSX.Element {
  const label = state ? stateLabels[state] : "This view";
  return (
    <div className="rounded-xl border border-dashed border-slate-200 bg-white/70 px-5 py-8 text-center text-sm text-slate-600">
      <p className="font-medium text-slate-900">{onClearSearch ? "No tasks match your search" : `${label} is clear`}</p>
      {onClearSearch ? (
        <Button variant="secondary" className="mt-3" onClick={onClearSearch}>Clear search</Button>
      ) : (
        <p className="mt-1">Use Brain dump when you are ready to capture what's on your mind.</p>
      )}
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }): React.JSX.Element {
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
