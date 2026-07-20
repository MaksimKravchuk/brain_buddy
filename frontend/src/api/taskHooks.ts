import { useMemo } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { apiClient } from "./client";
import type { TaskCounts, TaskListFilters, TaskResponse } from "./taskTypes";
import type { OpenTaskState } from "./taskTypes";

export const taskKeys = {
  all: ["tasks"] as const,
  list: (filters: TaskListFilters) => [...taskKeys.all, "list", filters] as const,
  allPages: (filters: TaskListFilters) => [...taskKeys.all, "all-pages", filters] as const,
  detail: (taskId: string) => [...taskKeys.all, "detail", taskId] as const,
  projects: () => [...taskKeys.all, "projects"] as const,
  tags: () => [...taskKeys.all, "tags"] as const
};

const emptyCounts: TaskCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

export interface AllTaskPagesResult {
  items: TaskResponse[];
  counts_by_state: TaskCounts;
}

/**
 * Drains every opaque cursor page for `filters` before resolving, so a
 * consumer (e.g. Group by project) never renders a group built from a
 * partial result set. Grouping-off list views must keep using
 * `useTaskList`'s incremental Load-more pagination instead of this hook.
 */
export function useAllTaskPages(filters: TaskListFilters, options: { enabled: boolean }) {
  return useQuery<AllTaskPagesResult>({
    queryKey: taskKeys.allPages(filters),
    enabled: options.enabled,
    queryFn: async ({ signal }) => {
      const seenItems = new Map<string, TaskResponse>();
      const seenCursors = new Set<string>();
      let counts = emptyCounts;
      let cursor: string | undefined;
      let hasMore = true;
      while (hasMore) {
        const page = await apiClient.listTasks({ ...filters, cursor, limit: 200 }, signal);
        for (const item of page.items) {
          if (!seenItems.has(item.id)) {
            seenItems.set(item.id, item);
          }
        }
        counts = page.counts_by_state;
        if (!page.has_more) {
          hasMore = false;
          break;
        }
        const nextCursor = page.next_cursor ?? undefined;
        if (!nextCursor || nextCursor === cursor || seenCursors.has(nextCursor)) {
          throw new Error("Task list pagination did not advance; aborting to avoid an infinite loop.");
        }
        seenCursors.add(nextCursor);
        cursor = nextCursor;
      }
      return { items: Array.from(seenItems.values()), counts_by_state: counts };
    }
  });
}

export function useTaskList(filters: TaskListFilters, options?: { enabled?: boolean }) {
  const query = useInfiniteQuery({
    queryKey: taskKeys.list(filters),
    queryFn: ({ pageParam, signal }) => apiClient.listTasks({ ...filters, cursor: pageParam }, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: options?.enabled ?? true
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
