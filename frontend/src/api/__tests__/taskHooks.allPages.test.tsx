import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { apiClient } from "../client";
import { useAllTaskPages } from "../taskHooks";
import type { TaskListResponse, TaskResponse } from "../taskTypes";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function taskFixture(id: string): TaskResponse {
  return {
    id,
    title: `Task ${id}`,
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
    revision: 1,
    subtasks: [],
    comments: []
  };
}

const emptyCounts = { inbox: 0, next: 0, waiting: 0, someday: 0 };

describe("useAllTaskPages", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });

  afterEach(() => {
    queryClient.clear();
    vi.restoreAllMocks();
  });

  it("de-duplicates items by task id across overlapping pages while preserving first-seen order", async () => {
    const pages: TaskListResponse[] = [
      { items: [taskFixture("t1"), taskFixture("t2")], next_cursor: "cursor-2", has_more: true, counts_by_state: emptyCounts },
      { items: [taskFixture("t2"), taskFixture("t3")], next_cursor: null, has_more: false, counts_by_state: emptyCounts }
    ];
    let call = 0;
    vi.spyOn(apiClient, "listTasks").mockImplementation(() => Promise.resolve(pages[call++]));

    const { result } = renderHook(() => useAllTaskPages({ state: "next" }, { enabled: true }), {
      wrapper: createWrapper(queryClient)
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items.map((item) => item.id)).toEqual(["t1", "t2", "t3"]);
    expect(apiClient.listTasks).toHaveBeenCalledTimes(2);
  });

  it("terminates with a clear error instead of looping forever on a repeated cursor", async () => {
    const loopingPage: TaskListResponse = {
      items: [taskFixture("t1")],
      next_cursor: "stuck-cursor",
      has_more: true,
      counts_by_state: emptyCounts
    };
    const listTasksSpy = vi.spyOn(apiClient, "listTasks").mockResolvedValue(loopingPage);

    const { result } = renderHook(() => useAllTaskPages({ state: "next" }, { enabled: true }), {
      wrapper: createWrapper(queryClient)
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(listTasksSpy.mock.calls.length).toBeLessThan(10);
  });

  it("never reports a partial group as complete when has_more is true but no cursor is returned", async () => {
    const inconsistentPage: TaskListResponse = {
      items: [taskFixture("t1")],
      next_cursor: null,
      has_more: true,
      counts_by_state: emptyCounts
    };
    vi.spyOn(apiClient, "listTasks").mockResolvedValue(inconsistentPage);

    const { result } = renderHook(() => useAllTaskPages({ state: "next" }, { enabled: true }), {
      wrapper: createWrapper(queryClient)
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});
