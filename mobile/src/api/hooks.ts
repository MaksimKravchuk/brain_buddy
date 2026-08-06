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

import { useApi } from "@/auth/SessionProvider";
import type {
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

export function useUpdateTask(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (payload: TaskUpdateRequest) =>
      api.updateTask(taskId, payload, newIdempotencyKey()),
    onSuccess: invalidate,
  });
}

export function useTransitionTask(taskId?: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (input: { taskId?: string; payload: TaskTransitionRequest }) => {
      const target = input.taskId ?? taskId;
      if (!target) {
        throw new Error("taskId is required");
      }
      return api.transitionTask(target, input.payload, newIdempotencyKey());
    },
    onSuccess: invalidate,
  });
}

export function useCreateSubtask(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (title: string) => api.createSubtask(taskId, { title }, newIdempotencyKey()),
    onSuccess: invalidate,
  });
}

export function useTransitionSubtask(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
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
  });
}

export function useCreateComment(taskId: string) {
  const api = useApi();
  const invalidate = useInvalidateTasks();
  return useMutation({
    mutationFn: (body: string) => api.createComment(taskId, { body }, newIdempotencyKey()),
    onSuccess: invalidate,
  });
}
