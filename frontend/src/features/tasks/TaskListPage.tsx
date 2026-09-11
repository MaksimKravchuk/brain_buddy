import { AlertTriangle, CalendarDays, Check, ChevronDown, Layers, Plus, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useAgentConnections, useAgentKeys, useAgentRunSummaries } from "../../api/agentHooks";
import { hasFeatureFlag } from "../../api/auth";
import type { AgentConnectionResponse, AgentRunResponse, AgentRunSummaryResponse } from "../../api/agentTypes";

import { apiClient } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";
import { getTaskCacheScope, parseOpenTaskState, parseTaskDateView, taskKeys, useProjects, useTags, useTaskDetail, useTaskList } from "../../api/taskHooks";
import type { OpenTaskState, ProjectResponse, TagResponse, TaskCounts, TaskResponse, TaskSubtaskResponse, TaskSort } from "../../api/taskTypes";
import { AppShell } from "../../components/shell/AppShell";
import { Button } from "../../components/ui/Button";
import { getErrorMessage } from "../../utils/error";
import { applySmartAddSuggestion, parseSmartAdd, smartAddChips, smartAddSuggestions } from "./smartAdd";
import type { SmartAddDraft, SmartAddSuggestion } from "./smartAdd";
import { SmartAddSuggestions } from "./SmartAddSuggestions";
import { TaskTitleAutocompleteSuggestions } from "./TaskTitleAutocompleteSuggestions";
import { TaskDetailPanel } from "./TaskDetailPanel";
import { AgentHandoffOverlay } from "../agents/AgentHandoffOverlay";
import { TaskAgentControl } from "./TaskAgentControl";
import { readTaskAgentPreference, rememberTaskAgentPreference } from "./taskAgentPreference";
import { getTaskDetailAutosaveController } from "./taskDetailAutosave";
import type { AutosaveResult } from "./taskDetailAutosave";
import { useTaskTitleAutocomplete } from "./useTaskTitleAutocomplete";
import { useTaskCompletionAnimation } from "./useTaskCompletionAnimation";

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
const emptyAgentRunSummaries: Record<string, AgentRunSummaryResponse> = {};

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
  const listPath = projectId
    ? `/projects/${projectId}`
    : tagId
      ? `/tags/${tagId}`
      : `/tasks/${params.state ?? "next"}`;
  const taskSearch = searchParams.toString();
  const closeTarget = useMemo(() => ({ pathname: listPath, search: taskSearch }), [listPath, taskSearch]);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [newTitle, setNewTitle] = useState("");
  const [newWaitingFor, setNewWaitingFor] = useState("");
  const showCancelled = searchParams.get("showCancelled") === "1";
  const pendingCompletionsRef = useRef(new Set<string>());
  const [pendingCompletions, setPendingCompletions] = useState(new Set<string>());
  const completionFocusRef = useRef(new Map<string, HTMLElement>());
  const [rowHandoff, setRowHandoff] = useState<{ task: TaskResponse; connectionId: string } | null>(null);
  const [agentFocusTaskId, setAgentFocusTaskId] = useState<string | null>(null);
  const [selectionRecoveryMessage, setSelectionRecoveryMessage] = useState<string | null>(null);
  const [selectionRecoveryVersion, setSelectionRecoveryVersion] = useState(0);
  const recoveryAttemptRef = useRef<{
    taskId: string;
    routeKey: string;
    expectedRouteKey: string | null;
    redirected: boolean;
    fetchedPages: number;
    stopped: boolean;
  } | null>(null);
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
  const openingTaskIdRef = useRef<string | undefined>(undefined);
  const previousTaskIdRef = useRef<string | undefined>(undefined);
  const focusSettledTaskIdRef = useRef<string | undefined>(undefined);
  const navigationControlRef = useRef<HTMLButtonElement | null>(null);
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
    includeCompleted: true,
    includeCancelled: showCancelled,
    q: searchQuery,
    sort,
    dueBefore: dateView === "overdue" ? today : undefined,
    dueOn: dateView === "today" ? today : undefined,
    dueAfter: dateView === "upcoming" ? today : undefined
  });
  const {
    dataUpdatedAt: taskQueryDataUpdatedAt,
    fetchNextPage: fetchNextTaskPage,
    hasNextPage: taskQueryHasNextPage,
    isFetchingNextPage: taskQueryIsFetchingNextPage,
    isLoading: taskQueryIsLoading
  } = taskQuery;
  const inboxBadgeQuery = useTaskList({ state: "inbox", unassignedProject: true, limit: 1 });
  const detailQuery = useTaskDetail(taskId);
  const projectsQuery = useProjects();
  const tagsQuery = useTags();
  const projects = projectsQuery.data ?? emptyProjects;
  const tags = tagsQuery.data ?? emptyTags;
  const tasks = taskQuery.data?.items ?? [];
  const openTasks = tasks.filter((task) => task.state !== "completed" && task.state !== "cancelled");
  const completedTasks = tasks.filter((task) => task.state === "completed");
  const cancelledTasks = tasks.filter((task) => task.state === "cancelled");
  const openGroups = groupByProject ? groupTasksByProject(openTasks, projects) : [];
  const counts = taskQuery.data?.counts_by_state ?? emptyCounts;
  const selectedTaskVisible = Boolean(taskId && tasks.some((task) => task.id === taskId));
  const projectsRecoveryPending = projectsQuery.isLoading || projectsQuery.isError;

  useEffect(() => {
    const previousTaskId = previousTaskIdRef.current;
    if (taskId) {
      if (!previousTaskId) openingTaskIdRef.current = taskId;
      if (navigationControlRef.current) {
        const requestedLabel = navigationControlRef.current.getAttribute("aria-label");
        navigationControlRef.current = null;
        const requestedControl = requestedLabel
          ? Array.from(detailHeadingRef.current?.parentElement?.querySelectorAll<HTMLButtonElement>("[data-task-navigation]") ?? [])
              .find((control) => control.getAttribute("aria-label") === requestedLabel)
          : null;
        if (requestedControl && !requestedControl.disabled) requestedControl.focus({ preventScroll: true });
        else detailHeadingRef.current?.parentElement?.querySelector<HTMLButtonElement>("[data-task-navigation]:not(:disabled)")?.focus({ preventScroll: true });
        focusSettledTaskIdRef.current = taskId;
      } else if (selectedTaskVisible && focusSettledTaskIdRef.current !== taskId && detailHeadingRef.current) {
        detailHeadingRef.current?.focus({ preventScroll: true });
        focusSettledTaskIdRef.current = taskId;
      }
    } else if (previousTaskId) {
      const originLink = rowLinkRefs.current.get(openingTaskIdRef.current ?? "");
      if (originLink && document.contains(originLink)) {
        originLink.focus({ preventScroll: true });
      } else {
        listHeadingRef.current?.focus({ preventScroll: true });
      }
      focusSettledTaskIdRef.current = undefined;
    }
    previousTaskIdRef.current = taskId;
  }, [detailQuery.data, selectedTaskVisible, taskId]);

  const user = useAuthStore((store) => store.user);
  const accountId = user?.id;
  const cacheScope = getTaskCacheScope(accountId ?? null);
  const scopeKey = JSON.stringify(cacheScope);
  const completionAnimation = useTaskCompletionAnimation(scopeKey, JSON.stringify({ state, projectId, tagId, dateView, searchQuery, sort, groupByProject, showCancelled }));
  const isCurrentScope = () => {
    const current = getTaskCacheScope();
    return current.accountId === cacheScope.accountId && current.apiOrigin === cacheScope.apiOrigin;
  };
  const invalidateTasks = () => queryClient.invalidateQueries({ queryKey: ["tasks"] });
  const applyCanonicalTask = (canonical: TaskResponse, animateCompletion = false) => {
    if (!isCurrentScope()) return;
    if (animateCompletion && canonical.state === "completed") {
      const focused = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
      completionAnimation.capture(canonical.id, completionFocusRef.current.get(`${scopeKey}:${canonical.id}`) ?? focused);
      if (canonical.id === taskId) queueMicrotask(() => navigate(closeTarget));
    }
    queryClient.setQueryData(taskKeys.detail(canonical.id, cacheScope), canonical);
    queryClient.setQueriesData<{
      pages: Array<{ items: TaskResponse[] }>;
      pageParams: unknown[];
    }>({ queryKey: taskKeys.lists(cacheScope) }, (cached) => {
      if (!cached) return cached;
      return {
        ...cached,
        pages: cached.pages.map((page) => ({
          ...page,
          items: page.items.map((item) => item.id === canonical.id ? canonical : item)
        }))
      };
    });
    return invalidateTasks();
  };
  const detailController = detailQuery.data && accountId
    ? getTaskDetailAutosaveController(accountId, cacheScope.apiOrigin, detailQuery.data, (accepted) => applyCanonicalTask(accepted, true))
    : null;
  const refetchCanonicalProjections = async (canonical: TaskResponse) => {
    // Apply the server-authoritative detail and list snapshot before waiting on
    // the network refresh, so Discard never leaves a stale row/count visible.
    void applyCanonicalTask(canonical);
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
  const closeSelectedTask = useCallback(() => {
    detailController?.flush();
    navigate(closeTarget);
  }, [closeTarget, detailController, navigate]);

  // Inline detail has one source of truth: the selected task in the URL. Both
  // keys only collapse; there is no hidden local state that can reopen it.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!taskId) return;
      const shortcut = event.key === "\\" && (event.metaKey || event.ctrlKey);
      if (event.key !== "Escape" && !shortcut) return;
      if (Array.from(document.querySelectorAll('[role="dialog"][aria-modal="true"]')).some((modal) => !modal.closest('[inert], [aria-hidden="true"]'))) return;
      const target = event.target as HTMLElement;
      if (event.key === "Escape" && target.closest('[data-escape-keeps-draft], select, [role="combobox"], [role="listbox"], [role="menu"]')) return;
      event.preventDefault();
      closeSelectedTask();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closeSelectedTask, taskId]);

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
  const openCount = state ? counts[state] : Object.values(counts).reduce((total, count) => total + count, 0);
  const taskNoun = openCount === 1 ? "task" : "tasks";
  const meta = state === "inbox"
    ? "Process these — decide the next action for each."
    : `${openCount} ${taskNoun}`;

  const hasFrameError = (taskQuery.isError && !taskQuery.data) || projectsQuery.isError || tagsQuery.isError;

  // Existing run chips stay visible after rollout is disabled or a refresh
  // fails. New hand-offs wait for a successful summary projection, otherwise
  // an unknown assigned task could be dispatched twice.
  const hasOwner = Boolean(user);
  const relayEnabled = hasFeatureFlag(user, "external_agent_relay");
  const agentKeys = useAgentKeys();
  const agentRunSummariesQuery = useAgentRunSummaries(tasks.map((task) => task.id), hasOwner);
  const agentRunSummaries = agentRunSummariesQuery.data ?? emptyAgentRunSummaries;
  const agentHandoffEnabled = relayEnabled && agentRunSummariesQuery.isSuccess;
  const agentConnectionsQuery = useAgentConnections(relayEnabled);
  const agentConnections = agentConnectionsQuery.data ?? [];
  const preferredConnection = accountId && agentConnectionsQuery.data !== undefined
    ? readTaskAgentPreference(
        { ownerId: accountId, apiOrigin: cacheScope.apiOrigin },
        agentConnectionsQuery.data
      )
    : null;

  useEffect(() => {
    if (!agentFocusTaskId || !agentRunSummaries[agentFocusTaskId]) return;
    const control = Array.from(document.querySelectorAll<HTMLElement>("[data-agent-assigned-control]"))
      .find((element) => element.dataset.agentAssignedControl === agentFocusTaskId);
    if (!control) return;
    control.focus({ preventScroll: true });
    setAgentFocusTaskId(null);
  }, [agentFocusTaskId, agentRunSummaries]);

  const closeRowHandoff = () => setRowHandoff(null);
  const handleRowHandoffDispatched = (run: AgentRunResponse) => {
    if (accountId && rowHandoff) {
      rememberTaskAgentPreference(
        { ownerId: accountId, apiOrigin: cacheScope.apiOrigin },
        run.connection_id
      );
    }
    const taskToFocus = rowHandoff?.task.id;
    setRowHandoff(null);
    setAgentFocusTaskId(taskToFocus ?? null);
    void queryClient.invalidateQueries({ queryKey: agentKeys.connections() });
  };

  // Shared by the flat list and by every project group, so the two render paths
  // can never drift apart.
  const taskListProps = {
    tags,
    taskPathBase: listPath,
    taskSearch: searchParams.toString(),
    selectedTaskId: taskId,
    registerRowLink,
    pendingCompletions,
    scopeKey,
    onComplete: (task: TaskResponse) => {
      if (!accountId) return;
      const pendingKey = `${scopeKey}:${task.id}`;
      if (pendingCompletionsRef.current.has(pendingKey)) return;
      const controller = getTaskDetailAutosaveController(accountId, cacheScope.apiOrigin, task, (accepted) => applyCanonicalTask(accepted, true));
      const snapshot = controller.getSnapshot();
      const completionInFlight = snapshot.inFlight?.kind === "transition" && "action" in snapshot.inFlight.body && snapshot.inFlight.body.action === "complete";
      const retryCompletion = completionInFlight && snapshot.status === "failed" && snapshot.error?.retryAllowed;
      if (!retryCompletion && (snapshot.barriers.some((barrier) => barrier.action === "complete") || completionInFlight)) return;
      if (document.activeElement instanceof HTMLButtonElement && document.activeElement.closest("[data-task-id]")?.getAttribute("data-task-id") === task.id) completionFocusRef.current.set(pendingKey, document.activeElement);
      pendingCompletionsRef.current.add(pendingKey);
      setPendingCompletions(new Set(pendingCompletionsRef.current));
      conflictControllerRef.current = controller;
      const save = retryCompletion ? controller.resumeRecovery() : controller.save({ kind: "transition", payload: { action: "complete" } }, idempotencyKey("complete"));
      void save
        .then((result) => { if (isCurrentScope()) handleAutosaveResult(result, controller); })
        .catch((caught: unknown) => { if (isCurrentScope()) setMutationError(getErrorMessage(caught)); })
        .finally(() => {
          pendingCompletionsRef.current.delete(pendingKey);
          completionFocusRef.current.delete(pendingKey);
          setPendingCompletions(new Set(pendingCompletionsRef.current));
        });
    },
    agentRuns: agentRunSummaries,
    relayEnabled: agentHandoffEnabled,
    agentConnections,
    preferredConnectionId: preferredConnection?.id,
    onReviewAgent: (task: TaskResponse, connectionId: string) => setRowHandoff({ task, connectionId }),
    onOpenTask: (task: TaskResponse) => {
      if (task.id !== taskId) navigate({ pathname: `${listPath}/${task.id}`, search: searchParams.toString() });
    },
    onCloseSelectedTask: closeSelectedTask
  };

  const isSavedNotice = mutationError === "Saved";
  const mutationNotice = mutationError ? (
    <div role={isSavedNotice ? "status" : "alert"} className={`relative mb-3 flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2 text-sm ${isSavedNotice ? "border-slate-200 bg-slate-50 text-slate-600" : "border-rose-200 bg-rose-50 text-rose-700"}`}>
      <span>{mutationError}</span>
      {autosaveConflict ? <Button size="sm" variant="secondary" onClick={() => void autosaveConflict.retry().then(handleAutosaveResult).catch((caught: unknown) => setMutationError(getErrorMessage(caught)))}>Retry</Button> : recoveryAvailable ? <Button size="sm" variant="secondary" onClick={recoverAutosave}>Retry</Button> : null}
      {(autosaveConflict || recoveryAvailable) ? <Button size="sm" variant="ghost" onMouseDown={(event) => event.preventDefault()} onClick={discardAutosave}>Discard</Button> : null}
    </div>
  ) : null;

  const displayedTasks = [...(groupByProject ? openGroups.flatMap((group) => group.tasks) : openTasks), ...completedTasks, ...cancelledTasks];
  const taskPosition = displayedTasks.findIndex((task) => task.id === taskId);
  const navigateTask = (id: string) => {
    navigationControlRef.current = document.activeElement?.matches("[data-task-navigation]") ? document.activeElement as HTMLButtonElement : null;
    navigate({ pathname: `${listPath}/${id}`, search: searchParams.toString() });
  };
  const panel = taskId ? (
    <TaskDetailPanel
      layout="inline"
      task={detailQuery.data}
      autosave={detailController ?? undefined}
      resetKey={canonicalResetKey}
      projects={projects}
      tags={tags}
      isLoading={detailQuery.isLoading}
      error={detailQuery.error}
      headingRef={detailHeadingRef}
      onClose={closeSelectedTask}
      notice={mutationNotice}
      navigation={{
        position: taskPosition + 1,
        total: displayedTasks.length,
        onPrevious: taskPosition > 0 ? () => navigateTask(displayedTasks[taskPosition - 1].id) : undefined,
        onNext: taskPosition >= 0 && taskPosition < displayedTasks.length - 1 ? () => navigateTask(displayedTasks[taskPosition + 1].id) : undefined
      }}
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

  const currentRouteKey = `${listPath}${searchParams.toString() ? `?${searchParams.toString()}` : ""}`;

  useEffect(() => {
    if (!taskId || selectedTaskVisible) {
      recoveryAttemptRef.current = null;
      setSelectionRecoveryMessage(null);
      return;
    }
    if (detailQuery.isError) {
      setSelectionRecoveryMessage(getErrorMessage(detailQuery.error));
      return;
    }
    const selected = detailQuery.data;
    if (!selected) return;

    let attempt = recoveryAttemptRef.current;
    if (!attempt || attempt.taskId !== taskId) {
      attempt = {
        taskId,
        routeKey: currentRouteKey,
        expectedRouteKey: null,
        redirected: false,
        fetchedPages: 0,
        stopped: false
      };
      recoveryAttemptRef.current = attempt;
    } else if (attempt.routeKey !== currentRouteKey) {
      if (attempt.expectedRouteKey === currentRouteKey) {
        attempt.routeKey = currentRouteKey;
        attempt.expectedRouteKey = null;
      } else {
        // A user-driven route/filter change is a new bounded recovery attempt.
        attempt = {
          taskId,
          routeKey: currentRouteKey,
          expectedRouteKey: null,
          redirected: false,
          fetchedPages: 0,
          stopped: false
        };
        recoveryAttemptRef.current = attempt;
      }
    }
    if (attempt.stopped || taskQueryIsLoading || taskQueryIsFetchingNextPage || projectsRecoveryPending) return;

    if (!attempt.redirected) {
      const target = canonicalTaskTarget({
        task: selected,
        projects,
        state,
        projectId,
        tagId,
        dateView: Boolean(dateView),
        listPath,
        searchParams
      });
      const targetKey = `${target.pathname}${target.search ? `?${target.search}` : ""}`;
      attempt.redirected = true;
      if (targetKey !== currentRouteKey) {
        attempt.expectedRouteKey = targetKey;
        navigate({ pathname: `${target.pathname}/${taskId}`, search: target.search }, { replace: true });
        return;
      }
    }

    if (taskQueryHasNextPage && attempt.fetchedPages < 10) {
      attempt.fetchedPages += 1;
      setSelectionRecoveryMessage(`Loading the row for “${selected.title}”…`);
      const activeAttempt = attempt;
      void fetchNextTaskPage().then((result) => {
        if (result.isError && recoveryAttemptRef.current === activeAttempt) {
          activeAttempt.stopped = true;
          setSelectionRecoveryMessage(`Could not load the row for “${selected.title}”.`);
        }
      });
      return;
    }

    attempt.stopped = true;
    setSelectionRecoveryMessage(
      taskQueryHasNextPage
        ? `The row for “${selected.title}” is beyond the automatic 10-page limit.`
        : `The row for “${selected.title}” is not in this list.`
    );
  }, [
    taskId,
    selectedTaskVisible,
    detailQuery.data,
    detailQuery.error,
    detailQuery.isError,
    dateView,
    listPath,
    navigate,
    projectId,
    projects,
    projectsRecoveryPending,
    searchParams,
    state,
    tagId,
    fetchNextTaskPage,
    taskQueryIsLoading,
    taskQueryIsFetchingNextPage,
    taskQueryHasNextPage,
    taskQueryDataUpdatedAt,
    currentRouteKey,
    selectionRecoveryVersion
  ]);

  const selectionRecoveryNotice = taskId && !selectedTaskVisible && selectionRecoveryMessage ? (
    <div role={detailQuery.isError ? "alert" : "status"} className="mb-3 flex flex-wrap items-center gap-2 border-y border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
      <span>{selectionRecoveryMessage}</span>
      {!detailQuery.isError ? (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            recoveryAttemptRef.current = null;
            setSelectionRecoveryMessage(null);
            setSelectionRecoveryVersion((version) => version + 1);
          }}
        >
          Retry / load more
        </Button>
      ) : (
        <Button size="sm" variant="secondary" onClick={() => void detailQuery.refetch()}>Retry</Button>
      )}
      <Button size="sm" variant="ghost" onClick={closeSelectedTask}>Close</Button>
    </div>
  ) : null;
  const agentSummaryNotice = agentRunSummariesQuery.isError && agentRunSummariesQuery.data ? (
    <div role="status" className="mb-3 flex items-center gap-2 border-y border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
      <span>Agent statuses may be out of date.</span>
      <Button size="sm" variant="ghost" onClick={() => void agentRunSummariesQuery.refetch()}>Retry</Button>
    </div>
  ) : null;

  const taskCreator = dateView ? null : (
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
  );

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
        <div className="mb-5 flex flex-wrap items-end gap-x-3 gap-y-2">
          <div className="min-w-0">
            <h1 id="task-list-title" ref={listHeadingRef} tabIndex={-1} className="m-0 text-title font-semibold text-slate-900 outline-none">
              {title}
            </h1>
            <p className="m-0 mt-1 text-xs text-slate-500">{meta}</p>
          </div>
          <div className="ml-auto flex items-center gap-1.5 max-[359px]:w-full max-[359px]:flex-wrap max-[359px]:justify-end">
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
                checked={showCancelled}
                onChange={(event) => {
                  const next = new URLSearchParams(searchParams);
                  if (event.currentTarget.checked) next.set("showCancelled", "1");
                  else next.delete("showCancelled");
                  setSearchParams(next, { replace: true });
                }}
              />
              Show cancelled
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

        {!taskId ? mutationNotice : null}
        {selectionRecoveryNotice}
        {agentSummaryNotice}

        <div ref={completionAnimation.containerRef}>
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
          <div className="flex flex-col gap-6">
              {groupByProject ? openGroups.map((group) => (
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
                  <TaskList {...taskListProps} tasks={group.tasks} label={group.name} inlineDetail={panel} />
                </section>
              )) : openTasks.length ? <TaskList {...taskListProps} tasks={openTasks} inlineDetail={panel} /> : null}
            {taskCreator}
            {completedTasks.length ? (
              <section aria-labelledby="completed-tasks-heading">
                <h2 id="completed-tasks-heading" className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Completed</h2>
                <TaskList {...taskListProps} tasks={completedTasks} label="Completed" inlineDetail={panel} />
              </section>
            ) : null}
            {cancelledTasks.length ? (
              <section aria-labelledby="cancelled-tasks-heading">
                <h2 id="cancelled-tasks-heading" className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Cancelled</h2>
                <TaskList {...taskListProps} tasks={cancelledTasks} label="Cancelled" inlineDetail={panel} />
              </section>
            ) : null}
          </div>
        ) : (
          <>
            <EmptyState
              state={state}
              onClearSearch={searchQuery.trim() ? () => {
                const next = new URLSearchParams(searchParams);
                next.delete("q");
                setSearchParams(next, { replace: true });
                listHeadingRef.current?.focus();
              } : undefined}
            />
            {taskCreator}
          </>
        )}
        </div>

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

        {dateView ? <DateViewCaptureHint /> : null}
      </section>
      {rowHandoff ? createPortal(
        <AgentHandoffOverlay
          taskId={rowHandoff.task.id}
          taskTitle={rowHandoff.task.title}
          seed={{ connectionId: rowHandoff.connectionId, includeDetails: true, supportingItems: [] }}
          onClose={closeRowHandoff}
          onDispatched={handleRowHandoffDispatched}
        />,
        document.body
      ) : null}
    </AppShell>
  );
}

function canonicalTaskTarget({
  task,
  projects,
  state,
  projectId,
  tagId,
  dateView,
  listPath,
  searchParams
}: {
  task: TaskResponse;
  projects: ProjectResponse[];
  state?: OpenTaskState;
  projectId?: string;
  tagId?: string;
  dateView: boolean;
  listPath: string;
  searchParams: URLSearchParams;
}): { pathname: string; search: string } {
  const currentMembership = !dateView && (
    projectId ? task.project_id === projectId
      : tagId ? task.tag_ids.includes(tagId)
        : state === "inbox" ? task.state === "inbox" && task.project_id === null
          : state ? task.state === state
          : false
  );
  const clean = new URLSearchParams();
  const sort = searchParams.get("sort");
  if (sort) clean.set("sort", sort);
  if (task.state === "cancelled") clean.set("showCancelled", "1");

  if (currentMembership) return { pathname: listPath, search: clean.toString() };
  if (task.project_id && projects.some((project) => project.id === task.project_id)) {
    return { pathname: `/projects/${task.project_id}`, search: clean.toString() };
  }
  if (task.state === "inbox" || task.state === "next" || task.state === "waiting" || task.state === "someday") {
    return { pathname: `/tasks/${task.state}`, search: clean.toString() };
  }
  return { pathname: "/tasks/next", search: clean.toString() };
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
  variant: "due" | "neutral";
  children: ReactNode;
}): React.JSX.Element {
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
  tags,
  taskPathBase,
  taskSearch,
  selectedTaskId,
  registerRowLink,
  pendingCompletions,
  scopeKey,
  onComplete,
  agentRuns,
  relayEnabled,
  agentConnections,
  preferredConnectionId,
  onReviewAgent,
  onOpenTask,
  onCloseSelectedTask,
  inlineDetail,
  label
}: {
  tasks: TaskResponse[];
  tags: TagResponse[];
  taskPathBase: string;
  taskSearch: string;
  selectedTaskId?: string;
  registerRowLink: (taskId: string, el: HTMLAnchorElement | null) => void;
  pendingCompletions: Set<string>;
  scopeKey: string;
  onComplete: (task: TaskResponse) => void;
  /** Latest external run per task, sparse: most tasks have none. */
  agentRuns: Record<string, AgentRunSummaryResponse>;
  relayEnabled: boolean;
  agentConnections: readonly AgentConnectionResponse[];
  preferredConnectionId?: string;
  onReviewAgent: (task: TaskResponse, connectionId: string) => void;
  onOpenTask: (task: TaskResponse) => void;
  onCloseSelectedTask: () => void;
  inlineDetail?: ReactNode;
  /** Names this list for assistive tech; each group supplies its project name. */
  label?: string;
}): React.JSX.Element {
  const tagById = new Map(tags.map((tag) => [tag.id, tag]));

  return (
    <div className="border-t border-slate-200" role="list" aria-label={label ?? "Tasks"}>
      {tasks.map((task) => (
        <TaskRow
          key={task.id}
          task={task}
          tags={task.tag_ids.map((id) => tagById.get(id)).filter((tag): tag is TagResponse => Boolean(tag))}
          detailPath={`${taskPathBase}/${task.id}${taskSearch ? `?${taskSearch}` : ""}`}
          isSelected={selectedTaskId === task.id}
          registerRowLink={registerRowLink}
          completionPending={pendingCompletions.has(`${scopeKey}:${task.id}`)}
          onComplete={onComplete}
          agentRun={agentRuns[task.id]}
          relayEnabled={relayEnabled}
          agentConnections={agentConnections}
          preferredConnectionId={preferredConnectionId}
          onReviewAgent={onReviewAgent}
          onOpenTask={onOpenTask}
          onCloseSelectedTask={onCloseSelectedTask}
          inlineDetail={selectedTaskId === task.id ? inlineDetail : undefined}
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
  completionPending,
  onComplete,
  agentRun,
  relayEnabled,
  agentConnections,
  preferredConnectionId,
  onReviewAgent,
  onOpenTask,
  onCloseSelectedTask,
  inlineDetail
}: {
  task: TaskResponse;
  tags: TagResponse[];
  detailPath: string;
  isSelected: boolean;
  registerRowLink: (taskId: string, el: HTMLAnchorElement | null) => void;
  completionPending: boolean;
  onComplete: (task: TaskResponse) => void;
  agentRun?: AgentRunSummaryResponse;
  relayEnabled: boolean;
  agentConnections: readonly AgentConnectionResponse[];
  preferredConnectionId?: string;
  onReviewAgent: (task: TaskResponse, connectionId: string) => void;
  onOpenTask: (task: TaskResponse) => void;
  onCloseSelectedTask: () => void;
  inlineDetail?: ReactNode;
}): React.JSX.Element {
  const isTerminal = task.state === "completed" || task.state === "cancelled";
  const navigate = useNavigate();
  const subtasks = task.subtasks ?? [];
  const doneSubtasks = subtasks.filter((subtask) => subtask.state !== "open").length;

  return (
    <article
      className="group border-b border-slate-200 bg-white"
      role="listitem"
      data-task-id={task.id}
      data-task-state={task.state}
    >
      <div
        data-testid="task-row-header"
        className={`flex h-11 min-w-0 items-center gap-2 px-1.5 transition-colors duration-150 ${isSelected ? "bg-slate-50" : "hover:bg-slate-50/70"}`}
        onClick={(event) => {
          const target = event.target as HTMLElement;
          if (target.closest("a, button, input, textarea, select, label")) return;
          if (isSelected) onCloseSelectedTask();
          else navigate(detailPath);
        }}
      >
        {isTerminal ? (
          <span
            role="img"
            aria-label={task.state === "completed" ? "Completed" : "Cancelled"}
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
            className="group/complete -ml-1.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-full"
            aria-label={`Complete ${task.title}`}
            disabled={completionPending}
            onClick={() => onComplete(task)}
          >
            <span className="flex h-[18px] w-[18px] items-center justify-center rounded-full border-[1.5px] border-slate-300 bg-white text-transparent transition-colors duration-200 ease-smooth group-hover/complete:border-sky-700">
              <Check className="h-[11px] w-[11px]" aria-hidden />
            </span>
          </button>
        )}
        <Link
          ref={(el) => registerRowLink(task.id, el)}
          to={isSelected ? ".." : detailPath}
          relative={isSelected ? "path" : undefined}
          onClick={(event) => {
            if (!isSelected) return;
            event.preventDefault();
            onCloseSelectedTask();
          }}
          aria-expanded={isSelected}
          className={`min-w-0 flex-1 truncate text-sm font-medium outline-none hover:text-sky-700 focus-visible:rounded focus-visible:ring-2 focus-visible:ring-brand-primary ${
            isTerminal ? "text-slate-500 line-through decoration-slate-300" : "text-slate-900"
          }`}
        >
          {task.title}
        </Link>
        {task.due_date ? (
          <span className="hidden md:inline-flex">
            <Chip variant="due">
              <CalendarDays className="h-[11px] w-[11px]" aria-hidden />
              {formatDueDate(task.due_date)}
            </Chip>
          </span>
        ) : null}
        {subtasks.length ? (
          <span className="hidden md:inline-flex">
            <Chip variant="neutral">
              {doneSubtasks} / {subtasks.length}
            </Chip>
          </span>
        ) : null}
        <span className="ml-auto hidden min-w-0 shrink items-center gap-2.5 overflow-hidden sm:flex sm:max-w-[34%]">
          {task.state === "waiting" && task.waiting_for ? (
            <span className="max-w-[140px] truncate text-[11px] text-slate-400">{task.waiting_for}</span>
          ) : null}
          {tags.map((tag) => (
            <Chip key={tag.id} variant="neutral">{tagLabel(tag)}</Chip>
          ))}
        </span>
        <TaskAgentControl
          task={task}
          run={agentRun}
          relayEnabled={relayEnabled}
          connections={agentConnections}
          preferredConnectionId={preferredConnectionId}
          onReview={(connectionId) => onReviewAgent(task, connectionId)}
          onOpenTask={() => onOpenTask(task)}
        />
      </div>
      {isSelected && inlineDetail ? (
        <div className="border-t border-slate-200 bg-white" data-testid="inline-task-detail">
          {inlineDetail}
        </div>
      ) : null}
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
