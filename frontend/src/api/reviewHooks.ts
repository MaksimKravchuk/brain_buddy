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
import { create } from "zustand";

import { hasFeatureFlag } from "./auth";
import { getApiBaseUrl } from "./client";
import { reviewApi } from "./review";
import type { DecisionRequest, ParkAcknowledgement, ReviewSettingsUpdate, ReviewState, ThresholdDays } from "./review";
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

/** The account (and API origin) a review write was started for. */
export type ReviewWriteScope = ReturnType<typeof getReviewCacheScope>;

/**
 * Captured when a write starts, so its answer is written to the caches of the
 * account that sent it, never to whoever is signed in when it arrives.
 */
export function captureReviewScope(accountId = useAuthStore.getState().user?.id ?? null): ReviewWriteScope {
  return getReviewCacheScope(accountId);
}

/** Whether that account is still the one signed in, against the same API. */
export function isCurrentReviewScope(scope: ReviewWriteScope): boolean {
  const current = getReviewCacheScope();
  return scope.accountId === current.accountId && scope.apiOrigin === current.apiOrigin;
}

/**
 * Put the server's task into the detail and list caches of the account that
 * started the write, then refetch. A late answer for an account that has
 * signed out (or switched) writes nothing: it is not this session's data.
 */
export function applyReviewTask(queryClient: QueryClient, task: TaskResponse, scope: ReviewWriteScope): void {
  if (!isCurrentReviewScope(scope)) {
    return;
  }
  const taskScope = getTaskCacheScope(scope.accountId);
  queryClient.setQueryData(taskKeys.detail(task.id, taskScope), task);
  queryClient.setQueriesData<CachedTaskPages>({ queryKey: taskKeys.lists(taskScope) }, (cached) =>
    cached && {
      ...cached,
      pages: cached.pages.map((page) => ({
        ...page,
        items: page.items.map((item) => (item.id === task.id ? task : item))
      }))
    }
  );
  refreshAfterReviewWrite(queryClient, scope);
}

export function refreshAfterReviewWrite(queryClient: QueryClient, scope: ReviewWriteScope): void {
  if (!isCurrentReviewScope(scope)) {
    return;
  }
  void queryClient.invalidateQueries({ queryKey: taskKeys.all });
  void queryClient.invalidateQueries({ queryKey: reviewKeys.all });
}

export function useDecideTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, body, idempotencyKey }: { taskId: string; body: DecisionRequest; idempotencyKey: string }) =>
      reviewApi.decide(taskId, body, idempotencyKey),
    onMutate: () => captureReviewScope(),
    onSuccess: (response, _variables, scope) => applyReviewTask(queryClient, response.task, scope)
  });
}

export function useAcknowledgeExplainer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ timeZone, idempotencyKey }: { timeZone: string; idempotencyKey: string }) =>
      reviewApi.acknowledgeExplainer({ time_zone: timeZone }, idempotencyKey),
    onMutate: () => captureReviewScope(),
    onSuccess: (state, _variables, scope) => {
      if (!isCurrentReviewScope(scope)) {
        return;
      }
      queryClient.setQueryData(reviewKeys.state(scope), state);
      refreshAfterReviewWrite(queryClient, scope);
    }
  });
}

export interface ThresholdNotice {
  accountId: string;
  threshold_days: ThresholdDays;
  /** The owner park floor the change set (FR-039): nothing parks before it. */
  floor: string;
}

/**
 * The one-time "threshold just changed" note on Next actions (design D-01 /
 * M-01): set by a saved threshold change, cleared by its OK.
 */
export const useThresholdNotice = create<{ notice: ThresholdNotice | null; dismiss: () => void }>((set) => ({
  notice: null,
  dismiss: () => set({ notice: null })
}));

export function announceThresholdChange(accountId: string, change: Omit<ThresholdNotice, "accountId">): void {
  useThresholdNotice.setState({ notice: { accountId, ...change } });
}

export function useUpdateReviewSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, idempotencyKey }: { body: ReviewSettingsUpdate; idempotencyKey: string }) =>
      reviewApi.updateSettings(body, idempotencyKey),
    onMutate: () => captureReviewScope(),
    onSuccess: (settings, { body }, scope) => {
      if (!isCurrentReviewScope(scope)) {
        return;
      }
      queryClient.setQueryData<ReviewState>(reviewKeys.state(scope), (state) => state && { ...state, settings });
      if (body.threshold_days !== undefined) {
        announceThresholdChange(scope.accountId as string, { threshold_days: settings.threshold_days, floor: settings.owner_park_floor_at as string });
      }
      refreshAfterReviewWrite(queryClient, scope);
    }
  });
}

export function useAcknowledgeParks() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, idempotencyKey }: { body: ParkAcknowledgement; idempotencyKey: string }) =>
      reviewApi.acknowledgeParks(body, idempotencyKey),
    onMutate: () => captureReviewScope(),
    onSuccess: (_answer, _variables, scope) => {
      if (isCurrentReviewScope(scope)) {
        void queryClient.invalidateQueries({ queryKey: reviewKeys.all });
      }
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
