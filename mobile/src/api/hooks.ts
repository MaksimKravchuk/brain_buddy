/**
 * React Query hooks over the API client.
 *
 * Mirrors the web app's pattern (`frontend/src/api/taskHooks.ts`): all task,
 * project, and tag queries live under the `["tasks"]` root so any mutation
 * invalidates every affected view — lists, counts, browse rows, and detail.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ApiError } from "@/api/client";

import { useApi } from "@/auth/SessionProvider";
import type {
  AgentConnectionCreateRequest,
  AgentConnectionDisconnectRequest,
  AgentConnectionRotateRequest,
  AgentHandoffConfirmRequest,
  AgentHandoffPreviewRequest,
  SmartAddTaskCreateRequest,
  TaskCreateRequest,
  TaskListFilters,
  TaskListResponse,
  TaskTransitionRequest,
  TaskUpdateRequest,
} from "@/api/types";
import { newIdempotencyKey } from "@/utils/ids";

export const taskKeys = {
  root: ["tasks"] as const,
  list: (filters: Omit<TaskListFilters, "cursor">) => ["tasks", "list", filters] as const,
  detail: (taskId: string) => ["tasks", "detail", taskId] as const,
  projects: ["tasks", "projects"] as const,
  tags: ["tasks", "tags"] as const,
};

export const agentKeys = {
  root: ["agents"] as const,
  connections: ["agents", "connections"] as const,
  connection: (connectionId: string) => ["agents", "connections", connectionId] as const,
  taskRuns: (taskId: string) => ["agents", "runs", "task", taskId] as const,
  run: (runId: string) => ["agents", "runs", runId] as const,
  summaries: (taskIds: string[]) => ["agents", "summaries", taskIds] as const,
};

const PAGE_SIZE = 50;

export function useTaskList(filters: Omit<TaskListFilters, "cursor">) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: taskKeys.list(filters),
    queryFn: ({ pageParam, signal }) =>
      api.listTasks({ ...filters, cursor: pageParam, limit: PAGE_SIZE }, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage: TaskListResponse) =>
      lastPage.has_more && lastPage.next_cursor ? lastPage.next_cursor : undefined,
  });
}

export function useTask(taskId: string) {
  const api = useApi();
  return useQuery({
    queryKey: taskKeys.detail(taskId),
    queryFn: ({ signal }) => api.getTask(taskId, signal),
  });
}

export function useProjects() {
  const api = useApi();
  return useQuery({
    queryKey: taskKeys.projects,
    queryFn: ({ signal }) => api.listProjects(signal),
  });
}

export function useTags() {
  const api = useApi();
  return useQuery({
    queryKey: taskKeys.tags,
    queryFn: ({ signal }) => api.listTags(signal),
  });
}

function useInvalidateTasks() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: taskKeys.root });
}

export function useCreateTask() {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (payload: TaskCreateRequest) => api.createTask(payload, newIdempotencyKey()),
    onSuccess: invalidate,
  });
}

export function useSmartAddTask() {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (payload: SmartAddTaskCreateRequest) =>
      api.smartAddTask(payload, newIdempotencyKey()),
    onSuccess: invalidate,
  });
}

/**
 * A 409 means our `expected_revision` is stale: refetch so the screen's
 * "the latest version is shown" claim is actually true and the next attempt
 * carries the fresh revision.
 */
function useInvalidateOnConflict() {
  const invalidate = useInvalidateTasks();
  return (error: unknown) => {
    if (error instanceof ApiError && error.status === 409) {
      invalidate();
    }
  };
}

export function useUpdateTask(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  const onConflict = useInvalidateOnConflict();
  return useMutation({
    mutationFn: (payload: TaskUpdateRequest) =>
      api.updateTask(taskId, payload, newIdempotencyKey()),
    onSuccess: invalidate,
    onError: onConflict,
  });
}

export function useTransitionTask(taskId?: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  const onConflict = useInvalidateOnConflict();
  return useMutation({
    mutationFn: (input: { taskId?: string; payload: TaskTransitionRequest }) => {
      const target = input.taskId ?? taskId;
      if (!target) {
        throw new Error("taskId is required");
      }
      return api.transitionTask(target, input.payload, newIdempotencyKey());
    },
    onSuccess: invalidate,
    onError: onConflict,
  });
}

export function useCreateSubtask(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  const onConflict = useInvalidateOnConflict();
  return useMutation({
    mutationFn: (title: string) => api.createSubtask(taskId, { title }, newIdempotencyKey()),
    onSuccess: invalidate,
    onError: onConflict,
  });
}

export function useTransitionSubtask(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  const onConflict = useInvalidateOnConflict();
  return useMutation({
    mutationFn: (input: {
      subtaskId: string;
      action: "complete" | "reopen" | "cancel";
      expectedRevision: number;
    }) =>
      api.transitionSubtask(
        taskId,
        input.subtaskId,
        { action: input.action, expected_revision: input.expectedRevision },
        newIdempotencyKey(),
      ),
    onSuccess: invalidate,
    onError: onConflict,
  });
}

export function useCreateComment(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  const onConflict = useInvalidateOnConflict();
  return useMutation({
    mutationFn: (body: string) => api.createComment(taskId, { body }, newIdempotencyKey()),
    onSuccess: invalidate,
    onError: onConflict,
  });
}

// --- External agents ---
//
// Agent state lives under the `["agents"]` root so a connection change never
// silently invalidates task lists (and vice versa). Runs are attached to a
// task but are not part of it: a connector report never mutates the Task.

function useInvalidateAgents() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: agentKeys.root });
}

export function useAgentConnections(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: agentKeys.connections,
    queryFn: ({ signal }) => api.listAgentConnections(signal),
    enabled,
  });
}

export function useAgentConnection(connectionId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: agentKeys.connection(connectionId),
    queryFn: ({ signal }) => api.getAgentConnection(connectionId, signal),
    enabled,
  });
}

/**
 * The 201 body carries the inbound signing secret exactly once. It is returned
 * to the caller for a one-time panel and deliberately never written into the
 * query cache.
 */
export function useCreateAgentConnection() {
  const api = useApi();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (payload: AgentConnectionCreateRequest) =>
      api.createAgentConnection(payload, newIdempotencyKey()),
    onSuccess: invalidate,
  });
}

export function useTestAgentConnection() {
  const api = useApi();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (connectionId: string) => api.testAgentConnection(connectionId),
    onSuccess: invalidate,
  });
}

export function useRotateAgentCredential() {
  const api = useApi();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (input: { connectionId: string; payload: AgentConnectionRotateRequest }) =>
      api.rotateAgentCredential(input.connectionId, input.payload, newIdempotencyKey()),
    onSuccess: invalidate,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        invalidate();
      }
    },
  });
}

export function useDisconnectAgentConnection() {
  const api = useApi();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (input: { connectionId: string; payload: AgentConnectionDisconnectRequest }) =>
      api.disconnectAgentConnection(input.connectionId, input.payload, newIdempotencyKey()),
    onSuccess: invalidate,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        invalidate();
      }
    },
  });
}

export function useAgentRuns(taskId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: agentKeys.taskRuns(taskId),
    queryFn: ({ signal }) => api.listAgentRuns(taskId, signal),
    enabled,
  });
}

/**
 * The latest run per task, for the compact task list.
 *
 * Asked only about the task IDs actually on screen, and only while the
 * account's `external_agent_relay` flag is on — the backend answers 404
 * otherwise, and a list of tasks must never manufacture an error for a
 * capability the user cannot see. The answer is sparse: a task with no hand-off
 * is simply absent, so its row stays exactly as it was.
 */
export function useAgentRunSummaries(taskIds: string[], enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: agentKeys.summaries(taskIds),
    queryFn: ({ signal }) => api.listAgentRunSummaries(taskIds, signal),
    enabled: enabled && taskIds.length > 0,
  });
}

/** Reserves a run id and returns the manifest to review. Nothing is sent. */
export function usePreviewAgentHandoff(taskId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: (payload: AgentHandoffPreviewRequest) => api.previewAgentHandoff(taskId, payload),
  });
}

/**
 * The key is derived from the reviewed manifest token, not from a fresh random
 * value, so retrying the hand-off the user actually reviewed returns the
 * original run instead of starting a second one. Matches the web semantics in
 * `frontend/src/features/agents/AgentHandoffOverlay.tsx`; re-previewing mints a
 * new token, which is exactly when a new key is wanted.
 */
export function useConfirmAgentHandoff(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (payload: AgentHandoffConfirmRequest) =>
      api.confirmAgentHandoff(taskId, payload, `agent-handoff-${payload.manifest_token}`),
    onSuccess: invalidate,
  });
}

/**
 * The caller owns the key (see `useIntentKey`): a reply that timed out may
 * already have reached the server, so the retry must carry the same key.
 */
export function useReplyToAgentRun() {
  const api = useApi();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (input: { runId: string; message: string; idempotencyKey: string }) =>
      api.replyToAgentRun(input.runId, { message: input.message }, input.idempotencyKey),
    onSuccess: invalidate,
  });
}

export function useCancelAgentRun() {
  const api = useApi();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (input: { runId: string; idempotencyKey: string }) =>
      api.cancelAgentRun(input.runId, input.idempotencyKey),
    onSuccess: invalidate,
  });
}
