import { useMemo } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { apiClient } from "./client";
import type { AuthUser } from "./auth";
import type { TaskCounts, TaskListFilters, TaskResponse } from "./taskTypes";
import type { OpenTaskState } from "./taskTypes";
import { useAuthStore } from "../stores/authStore";

// Every task-tracker cache entry is qualified by the signed-in principal so
// a same-SPA identity switch (logout, session loss, login/signup as a
// different account) can never have a new principal's query read another
// principal's cached list/detail/project/tag entry through a colliding key.
// installTaskCacheOwnerGuard (api/taskCacheOwnerGuard.ts) complements this by
// synchronously purging the outgoing owner's subtree on that same transition.
export function taskOwnerKey(user: AuthUser | null): string {
  return user?.id ?? "anon";
}

export function getCurrentTaskOwnerKey(): string {
  return taskOwnerKey(useAuthStore.getState().user);
}

export function getCurrentAuthEpoch(): number {
  return useAuthStore.getState().epoch;
}

// The signed-in principal *and* the auth epoch in effect when a task
// request/mutation was initiated. Owner id alone cannot distinguish a
// session from an earlier, since-ended session that happened to resolve to
// the same owner (e.g. A -> anon -> the same A signing back in) -- the
// monotonic epoch is what makes that distinction possible. Every task
// request/mutation must capture this at initiation and re-check it before
// publishing/rebasing/invalidating anything, so a response that arrives
// after the session has moved on can never act on stale authority.
export interface TaskRequestContext {
  owner: string;
  epoch: number;
}

export function captureTaskRequestContext(): TaskRequestContext {
  const state = useAuthStore.getState();
  return { owner: taskOwnerKey(state.user), epoch: state.epoch };
}

export function isStaleTaskRequestContext(context: TaskRequestContext): boolean {
  const current = captureTaskRequestContext();
  return context.owner !== current.owner || context.epoch !== current.epoch;
}

// Thrown by a task queryFn when the owner+epoch captured at its own start is
// no longer current by the time its response arrives. Never caught and
// "handled" by falling back to some other value -- a stale response must
// never become query data, full stop, regardless of whether anything else
// happens to be cached. Query.retry (see taskRequestRetry below) is what
// turns this into a silent, invisible self-heal: React Query treats a
// retryable failure as still-fetching, not as an error, and (per its own
// semantics) keeps serving the last successful `data` throughout, so there
// is no user-visible error and no gap in what's rendered. The retry's own
// fresh call to captureTaskRequestContext() picks up the now-current
// session, so it succeeds immediately in the overwhelmingly common case
// where no further transition happens in between.
export class StaleTaskRequestError extends Error {
  constructor() {
    super("Task request's owner/epoch is no longer current; discarding response.");
    this.name = "StaleTaskRequestError";
  }
}

const STALE_TASK_REQUEST_MAX_RETRIES = 5;

/** Pass as a query's `retry` option so a StaleTaskRequestError silently
 * re-issues the request instead of ever surfacing as `isError`. Any other
 * error (network failure, 404, etc.) is left alone -- this returns false
 * for those on the very first failure, matching a plain `retry: false`. */
export function taskRequestRetry(failureCount: number, error: unknown): boolean {
  return error instanceof StaleTaskRequestError && failureCount < STALE_TASK_REQUEST_MAX_RETRIES;
}

/** Paired with taskRequestRetry: retry immediately -- by the time staleness
 * is detected, the transition that caused it has already completed, so
 * there is nothing to back off for. */
export const taskRequestRetryDelay = 0;

/**
 * Throws StaleTaskRequestError if the owner+epoch captured when a task
 * request/mutation was initiated is no longer current. Call this on every
 * task query/mutation continuation before it can publish, invalidate, or
 * otherwise act -- never rely on cache-key eviction (installTaskCacheOwnerGuard)
 * alone to prevent a stale response from being observed, since that guards
 * the cache subtree, not any particular in-flight request/continuation.
 */
export function assertTaskRequestCurrent(context: TaskRequestContext): void {
  if (isStaleTaskRequestContext(context)) {
    throw new StaleTaskRequestError();
  }
}

function hasRevision(value: unknown): value is { revision: number } {
  return typeof value === "object" && value !== null && typeof (value as { revision?: unknown }).revision === "number";
}

/**
 * Resolves what a freshly fetched, revision-bearing task-tracker response
 * (a single Task) should publish as. Throws StaleTaskRequestError -- never
 * falls back to the fetched value, even when nothing is cached yet to
 * protect -- if the capturing request's owner+epoch is no longer current;
 * see assertTaskRequestCurrent. Independently of auth staleness, never
 * returns a fetched value older than an existing `revision`-bearing cache
 * entry -- an older response must not move a Task's cache entry backwards
 * even within the same, still-current session (e.g. a slower background
 * refetch racing a faster mutation).
 */
export function reconcileTaskResponse<T>(
  queryClient: QueryClient,
  queryKey: readonly unknown[],
  context: TaskRequestContext,
  fetched: T
): T {
  assertTaskRequestCurrent(context);
  const existing = queryClient.getQueryData<T>(queryKey);
  if (hasRevision(existing) && hasRevision(fetched) && existing.revision > fetched.revision) {
    return existing;
  }
  return fetched;
}

export const taskKeys = {
  all: (owner: string = getCurrentTaskOwnerKey()) => ["tasks", owner] as const,
  list: (filters: TaskListFilters, owner: string = getCurrentTaskOwnerKey()) =>
    [...taskKeys.all(owner), "list", filters] as const,
  allPages: (filters: TaskListFilters, owner: string = getCurrentTaskOwnerKey()) =>
    [...taskKeys.all(owner), "all-pages", filters] as const,
  detail: (taskId: string, owner: string = getCurrentTaskOwnerKey()) =>
    [...taskKeys.all(owner), "detail", taskId] as const,
  projects: (owner: string = getCurrentTaskOwnerKey()) => [...taskKeys.all(owner), "projects"] as const,
  tags: (owner: string = getCurrentTaskOwnerKey()) => [...taskKeys.all(owner), "tags"] as const
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
    retry: taskRequestRetry,
    retryDelay: taskRequestRetryDelay,
    queryFn: async ({ signal }) => {
      // Captured once for the whole drain -- every page below belongs to
      // the same logical request/response, initiated at this instant.
      const context = captureTaskRequestContext();
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
      // The whole drained result only ever gets returned/published here, at
      // the very end -- a single check against the context captured at the
      // start covers a transition at any point during the drain.
      assertTaskRequestCurrent(context);
      return { items: Array.from(seenItems.values()), counts_by_state: counts };
    }
  });
}

export function useTaskList(filters: TaskListFilters, options?: { enabled?: boolean }) {
  const query = useInfiniteQuery({
    queryKey: taskKeys.list(filters),
    queryFn: async ({ pageParam, signal }) => {
      const context = captureTaskRequestContext();
      const page = await apiClient.listTasks({ ...filters, cursor: pageParam }, signal);
      assertTaskRequestCurrent(context);
      return page;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: options?.enabled ?? true,
    retry: taskRequestRetry,
    retryDelay: taskRequestRetryDelay
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
  const queryClient = useQueryClient();
  return useQuery({
    enabled: Boolean(taskId),
    queryKey: taskKeys.detail(taskId ?? ""),
    retry: taskRequestRetry,
    retryDelay: taskRequestRetryDelay,
    queryFn: async ({ signal }) => {
      const context = captureTaskRequestContext();
      const queryKey = taskKeys.detail(taskId ?? "", context.owner);
      const fetched = await apiClient.getTask(taskId ?? "", signal);
      return reconcileTaskResponse(queryClient, queryKey, context, fetched);
    }
  });
}

export function useProjects() {
  return useQuery({
    queryKey: taskKeys.projects(),
    retry: taskRequestRetry,
    retryDelay: taskRequestRetryDelay,
    queryFn: async ({ signal }) => {
      const context = captureTaskRequestContext();
      const fetched = await apiClient.listProjects(signal);
      assertTaskRequestCurrent(context);
      return fetched;
    }
  });
}

export function useTags() {
  return useQuery({
    queryKey: taskKeys.tags(),
    retry: taskRequestRetry,
    retryDelay: taskRequestRetryDelay,
    queryFn: async ({ signal }) => {
      const context = captureTaskRequestContext();
      const fetched = await apiClient.listTags(signal);
      assertTaskRequestCurrent(context);
      return fetched;
    }
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
