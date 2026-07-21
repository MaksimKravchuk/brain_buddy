import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../client";
import { useAllTaskPages, useProjects, useTags, useTaskDetail, useTaskList } from "../taskHooks";
import { useAuthStore } from "../../stores/authStore";
import type { ProjectResponse, TagResponse, TaskListResponse, TaskResponse } from "../taskTypes";

// These specs deliberately do NOT install installTaskCacheOwnerGuard and
// never change the resolved owner id -- only the auth epoch. That means the
// query key each hook computes never changes and its underlying React Query
// `Query` object is never evicted/recreated. If a hook's own safety net
// depended solely on cache-key eviction (the purge in taskCacheOwnerGuard)
// rather than checking its own captured owner+epoch before publishing, a
// stale response released here would still land in `data`. Each hook must
// defend this on its own.
//
// Every mock below answers its FIRST call with a manually-held promise
// (resolved, after the epoch bump, with a distinctively-labeled "stale"
// payload) and every subsequent call -- i.e. the hook's own silent
// self-heal retry -- with an immediately-resolved, distinctively-labeled
// "fresh" payload, simulating a real backend that would simply answer the
// retried request with the current, correct state.
function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const baseTask: TaskResponse = {
  id: "task-1",
  title: "Fix onboarding drop-off",
  details: null,
  state: "next",
  project_id: null,
  tag_ids: [],
  due_date: null,
  priority: "none",
  waiting_for: null,
  waiting_since: null,
  order_key: 1,
  source_capture_ids: [],
  created_at: "2026-07-15T10:00:00Z",
  updated_at: "2026-07-15T10:00:00Z",
  completed_at: null,
  cancelled_at: null,
  revision: 1
};

const staleTask: TaskResponse = { ...baseTask, title: "STALE (must never publish)", revision: 7 };
const freshTask: TaskResponse = { ...baseTask, title: "Fresh after retry", revision: 1 };

const staleTaskList: TaskListResponse = {
  items: [staleTask],
  next_cursor: null,
  has_more: false,
  counts_by_state: { inbox: 0, next: 1, waiting: 0, someday: 0 }
};
const freshTaskList: TaskListResponse = {
  items: [freshTask],
  next_cursor: null,
  has_more: false,
  counts_by_state: { inbox: 0, next: 1, waiting: 0, someday: 0 }
};

const staleProjects: ProjectResponse[] = [
  { id: "project-stale", name: "STALE PROJECT (must never publish)", color: null, state: "active", revision: 1, open_task_count: 0 }
];
const freshProjects: ProjectResponse[] = [
  { id: "project-fresh", name: "Fresh after retry", color: null, state: "active", revision: 1, open_task_count: 0 }
];

const staleTags: TagResponse[] = [
  { id: "tag-stale", name: "stale-tag (must never publish)", state: "active", revision: 1, open_task_count: 0 }
];
const freshTags: TagResponse[] = [
  { id: "tag-fresh", name: "fresh-after-retry", state: "active", revision: 1, open_task_count: 0 }
];

/** First call returns the held deferred; every later call (the hook's own
 * silent retry) resolves immediately with `freshValue`. */
function mockFirstCallHeldThenFresh<T>(deferred: { promise: Promise<T> }, freshValue: T) {
  let callCount = 0;
  return vi.fn(() => {
    callCount += 1;
    if (callCount === 1) {
      return deferred.promise;
    }
    return Promise.resolve(freshValue);
  });
}

describe("taskHooks epoch safety (no cache-key eviction involved)", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: { id: "user-1", email: "a@example.test" }, status: "authed", epoch: 1 });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    useAuthStore.setState({ user: null, status: "anon", epoch: 0 });
  });

  it("useTaskDetail never publishes a response captured before an epoch bump, even with nothing cached to fall back to", async () => {
    const deferred = createDeferred<TaskResponse>();
    vi.spyOn(apiClient, "getTask").mockImplementation(mockFirstCallHeldThenFresh(deferred, freshTask));
    const queryClient = new QueryClient();

    const { result } = renderHook(() => useTaskDetail("task-1"), { wrapper: createWrapper(queryClient) });

    await waitFor(() => expect(apiClient.getTask).toHaveBeenCalledTimes(1));

    // The epoch advances (a session transition) with the SAME owner id --
    // no purge/eviction is involved since installTaskCacheOwnerGuard was
    // never installed in this test and the owner text never changes.
    act(() => {
      useAuthStore.setState((state) => ({ epoch: state.epoch + 1 }));
    });

    await act(async () => {
      deferred.resolve(staleTask);
    });

    // The query silently self-heals via its own retry -- never surfacing
    // the stale response, and never surfacing a user-visible error either.
    await waitFor(() => expect(result.current.data?.title).toBe("Fresh after retry"));
    expect(result.current.isError).toBe(false);
    expect(queryClient.getQueryData(["tasks", "user-1", "detail", "task-1"])).toMatchObject({
      title: "Fresh after retry"
    });
  });

  it("useTaskList never publishes a page captured before an epoch bump", async () => {
    const deferred = createDeferred<TaskListResponse>();
    vi.spyOn(apiClient, "listTasks").mockImplementation(mockFirstCallHeldThenFresh(deferred, freshTaskList));
    const queryClient = new QueryClient();

    const { result } = renderHook(() => useTaskList({ state: "next" }), { wrapper: createWrapper(queryClient) });

    await waitFor(() => expect(apiClient.listTasks).toHaveBeenCalledTimes(1));

    act(() => {
      useAuthStore.setState((state) => ({ epoch: state.epoch + 1 }));
    });

    await act(async () => {
      deferred.resolve(staleTaskList);
    });

    await waitFor(() => expect(result.current.data?.items[0]?.title).toBe("Fresh after retry"));
    expect(result.current.isError).toBe(false);
  });

  it("useAllTaskPages never publishes a page captured before an epoch bump", async () => {
    const deferred = createDeferred<TaskListResponse>();
    vi.spyOn(apiClient, "listTasks").mockImplementation(mockFirstCallHeldThenFresh(deferred, freshTaskList));
    const queryClient = new QueryClient();

    const { result } = renderHook(() => useAllTaskPages({ state: "next" }, { enabled: true }), {
      wrapper: createWrapper(queryClient)
    });

    await waitFor(() => expect(apiClient.listTasks).toHaveBeenCalledTimes(1));

    act(() => {
      useAuthStore.setState((state) => ({ epoch: state.epoch + 1 }));
    });

    await act(async () => {
      deferred.resolve(staleTaskList);
    });

    await waitFor(() => expect(result.current.data?.items[0]?.title).toBe("Fresh after retry"));
    expect(result.current.isError).toBe(false);
  });

  it("useProjects never publishes a response captured before an epoch bump", async () => {
    const deferred = createDeferred<ProjectResponse[]>();
    vi.spyOn(apiClient, "listProjects").mockImplementation(mockFirstCallHeldThenFresh(deferred, freshProjects));
    const queryClient = new QueryClient();

    const { result } = renderHook(() => useProjects(), { wrapper: createWrapper(queryClient) });

    await waitFor(() => expect(apiClient.listProjects).toHaveBeenCalledTimes(1));

    act(() => {
      useAuthStore.setState((state) => ({ epoch: state.epoch + 1 }));
    });

    await act(async () => {
      deferred.resolve(staleProjects);
    });

    await waitFor(() => expect(result.current.data?.[0]?.id).toBe("project-fresh"));
    expect(result.current.isError).toBe(false);
  });

  it("useTags never publishes a response captured before an epoch bump", async () => {
    const deferred = createDeferred<TagResponse[]>();
    vi.spyOn(apiClient, "listTags").mockImplementation(mockFirstCallHeldThenFresh(deferred, freshTags));
    const queryClient = new QueryClient();

    const { result } = renderHook(() => useTags(), { wrapper: createWrapper(queryClient) });

    await waitFor(() => expect(apiClient.listTags).toHaveBeenCalledTimes(1));

    act(() => {
      useAuthStore.setState((state) => ({ epoch: state.epoch + 1 }));
    });

    await act(async () => {
      deferred.resolve(staleTags);
    });

    await waitFor(() => expect(result.current.data?.[0]?.id).toBe("tag-fresh"));
    expect(result.current.isError).toBe(false);
  });
});
