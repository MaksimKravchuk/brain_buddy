import { useMemo } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { apiClient } from "./client";
import type { OpenTaskState, TaskListFilters } from "./taskTypes";

export const taskKeys = {
  all: ["tasks"] as const,
  list: (filters: TaskListFilters) => [...taskKeys.all, "list", filters] as const,
  detail: (taskId: string) => [...taskKeys.all, "detail", taskId] as const,
  projects: () => [...taskKeys.all, "projects"] as const,
  tags: () => [...taskKeys.all, "tags"] as const,
  brainDumpProviders: () => ["brain-dump-providers"] as const
};

export function useBrainDumpProviders(enabled: boolean) {
  // The configured external voice providers are static server config, so this
  // is fetched once (never retried on error) and only while the fresh-recording
  // screen is shown, where its result seeds the consent the user grants.
  return useQuery({
    enabled,
    queryKey: taskKeys.brainDumpProviders(),
    queryFn: ({ signal }) => apiClient.getBrainDumpProviders(signal),
    retry: false,
    staleTime: Infinity
  });
}

export function useTaskList(filters: TaskListFilters) {
  const query = useInfiniteQuery({
    queryKey: taskKeys.list(filters),
    queryFn: ({ pageParam, signal }) => apiClient.listTasks({ ...filters, cursor: pageParam }, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined
  });

  const data = useMemo(() => {
    if (!query.data) {
      return undefined;
    }
    const pages = query.data.pages;
    const firstPage = pages[0];
    const lastPage = pages[pages.length - 1];
    return {
      items: pages.flatMap((page) => page.items),
      next_cursor: lastPage.next_cursor,
      has_more: lastPage.has_more,
      counts_by_state: firstPage.counts_by_state
    };
  }, [query.data]);

  return { ...query, data };
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
