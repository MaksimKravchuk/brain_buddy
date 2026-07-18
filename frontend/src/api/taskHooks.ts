import { useQuery } from "@tanstack/react-query";

import { apiClient } from "./client";
import type { OpenTaskState, TaskListFilters } from "./taskTypes";

export const taskKeys = {
  all: ["tasks"] as const,
  list: (filters: TaskListFilters) => [...taskKeys.all, "list", filters] as const,
  detail: (taskId: string) => [...taskKeys.all, "detail", taskId] as const,
  projects: () => [...taskKeys.all, "projects"] as const,
  tags: () => [...taskKeys.all, "tags"] as const
};

export function useTaskList(filters: TaskListFilters) {
  return useQuery({
    queryKey: taskKeys.list(filters),
    queryFn: ({ signal }) => apiClient.listTasks(filters, signal)
  });
}

export function useTaskDetail(taskId: string | undefined) {
  return useQuery({
    enabled: Boolean(taskId),
    queryKey: taskKeys.detail(taskId ?? ""),
    queryFn: ({ signal }) => apiClient.getTask(taskId ?? "", signal)
  });
}

export function useProjects() {
  return useQuery({
    queryKey: taskKeys.projects(),
    queryFn: ({ signal }) => apiClient.listProjects(signal)
  });
}

export function useTags() {
  return useQuery({
    queryKey: taskKeys.tags(),
    queryFn: ({ signal }) => apiClient.listTags(signal)
  });
}

export function parseOpenTaskState(value: string | undefined): OpenTaskState {
  if (value === "inbox" || value === "next" || value === "waiting" || value === "someday") {
    return value;
  }
  return "next";
}

export type TaskDateView = "overdue" | "today" | "upcoming";

export function parseTaskDateView(value: string | undefined): TaskDateView | undefined {
  if (value === "overdue" || value === "today" || value === "upcoming") {
    return value;
  }
  return undefined;
}
