/**
 * React Query glue for the weekly review (spec 020).
 *
 * Exposure follows the server flag: nothing here asks the review API while
 * `weekly_review` is not effective for the signed-in account (FR-042). Every
 * write puts the server's own task into the task caches and then refetches,
 * because the server is the authority on the clock (contracts/formulation-clock
 * §3 "decision undo" is server only) and on a same-key replay's projection.
 */
import { useEffect, useState, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { hasFeatureFlag } from "./auth";
import { getApiBaseUrl } from "./client";
import { reviewApi } from "./review";
import type { DecisionRequest, ParkAcknowledgement, ReviewSettingsUpdate, ReviewState } from "./review";
import { getTaskCacheScope, taskKeys } from "./taskHooks";
import type { TaskResponse } from "./taskTypes";
import { useAuthStore } from "../stores/authStore";

export const WEEKLY_REVIEW_FLAG = "weekly_review";

export function getReviewCacheScope(accountId = useAuthStore.getState().user?.id ?? null) {
  return { accountId, apiOrigin: getApiBaseUrl() };
}

export const reviewKeys = {
  all: ["review"] as const,
  state: (scope = getReviewCacheScope()) => ["review", "state", scope] as const
};

export function useWeeklyReviewEnabled(): boolean {
  const user = useAuthStore((store) => store.user);
  return hasFeatureFlag(user, WEEKLY_REVIEW_FLAG);
}

export function useReviewState() {
  const enabled = useWeeklyReviewEnabled();
  const accountId = useAuthStore((store) => store.user?.id ?? null);
  return useQuery({
    enabled,
    queryKey: reviewKeys.state(getReviewCacheScope(accountId)),
    queryFn: ({ signal }) => reviewApi.getState(signal),
    retry: false,
    staleTime: 30_000
  });
}

type CachedTaskPages = { pages: Array<{ items: TaskResponse[] }>; pageParams: unknown[] };

/** Put the server's task into the detail and list caches, then refetch both. */
export function applyReviewTask(queryClient: QueryClient, task: TaskResponse): void {
  const scope = getTaskCacheScope();
  queryClient.setQueryData(taskKeys.detail(task.id, scope), task);
  queryClient.setQueriesData<CachedTaskPages>({ queryKey: taskKeys.lists(scope) }, (cached) =>
    cached && {
      ...cached,
      pages: cached.pages.map((page) => ({
        ...page,
        items: page.items.map((item) => (item.id === task.id ? task : item))
      }))
    }
  );
  refreshAfterReviewWrite(queryClient);
}

export function refreshAfterReviewWrite(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: taskKeys.all });
  void queryClient.invalidateQueries({ queryKey: reviewKeys.all });
}

export function useDecideTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, body, idempotencyKey }: { taskId: string; body: DecisionRequest; idempotencyKey: string }) =>
      reviewApi.decide(taskId, body, idempotencyKey),
    onSuccess: (response) => applyReviewTask(queryClient, response.task)
  });
}

export function useAcknowledgeExplainer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ timeZone, idempotencyKey }: { timeZone: string; idempotencyKey: string }) =>
      reviewApi.acknowledgeExplainer({ time_zone: timeZone }, idempotencyKey),
    onSuccess: (state) => {
      queryClient.setQueryData(reviewKeys.state(), state);
      refreshAfterReviewWrite(queryClient);
    }
  });
}

export function useUpdateReviewSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, idempotencyKey }: { body: ReviewSettingsUpdate; idempotencyKey: string }) =>
      reviewApi.updateSettings(body, idempotencyKey),
    onSuccess: (settings) => {
      queryClient.setQueryData<ReviewState>(reviewKeys.state(), (state) => state && { ...state, settings });
      refreshAfterReviewWrite(queryClient);
    }
  });
}

export function useAcknowledgeParks() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, idempotencyKey }: { body: ParkAcknowledgement; idempotencyKey: string }) =>
      reviewApi.acknowledgeParks(body, idempotencyKey),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: reviewKeys.all });
    }
  });
}

function subscribeOnline(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

/** The web is not offline-first: review writes are disabled while offline. */
export function useOnlineStatus(): boolean {
  return useSyncExternalStore(subscribeOnline, () => navigator.onLine, () => true);
}

/**
 * The browser clock, re-read every minute so markers move without a refetch.
 * Idle when `enabled` is false, so a page without the review never ticks.
 */
export function useReviewClock(enabled = true, intervalMs = 60_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const id = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(id);
  }, [enabled, intervalMs]);
  return now;
}
