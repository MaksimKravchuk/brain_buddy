/**
 * Shared fixtures and a render harness for the review step tests: a step is
 * rendered inside the same context the shell gives it.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import type { ReviewSession, ReviewState, SessionCounts } from "../../../api/review";
import type { TaskResponse } from "../../../api/taskTypes";
import { ShellToastContext, type ShellNotify, type ShellToastOptions } from "../../../components/shell/shellToast";
import { useAuthStore } from "../../../stores/authStore";
import { ReviewRunContext, type ReviewRun } from "../steps/reviewRun";

export const DAY = 86_400_000;
export const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();

export const zeroCounts: SessionCounts = {
  done: 0,
  reformulated: 0,
  first_step: 0,
  waiting: 0,
  someday: 0,
  cancelled: 0,
  extended: 0,
  inbox_processed: 0,
  kept: 0,
  moved_to_next: 0
};

export function taskFixture(overrides?: Partial<TaskResponse>): TaskResponse {
  return {
    id: "task_1",
    title: "Buy printer paper",
    details: null,
    state: "inbox",
    project_id: null,
    tag_ids: [],
    due_date: null,
    priority: "none",
    waiting_for: null,
    waiting_since: null,
    order_key: 1,
    source_capture_ids: [],
    created_at: iso(-3 * DAY),
    updated_at: iso(-2 * DAY),
    completed_at: null,
    cancelled_at: null,
    revision: 3,
    formulation: null,
    parked: null,
    ...overrides
  };
}

/** A Next task that asks for a decision. */
export function askingTask(id: string, title: string, overrides: Partial<TaskResponse> = {}): TaskResponse {
  return taskFixture({
    id,
    title,
    state: "next",
    revision: 7,
    formulation: {
      id: `form_${id}`,
      started_at: iso(-15 * DAY),
      extended_at: null,
      extension_reason: null,
      park_floor_at: null,
      consecutive_stalled: 0,
      ageing_at: iso(-8 * DAY),
      ask_at: iso(-1 * DAY),
      park_due_at: iso(6 * DAY),
      paused_until: null
    },
    ...overrides
  });
}

export function sessionFixture(overrides: Partial<ReviewSession> = {}): ReviewSession {
  return {
    id: "review_1",
    mode: "full",
    entry: "sidebar",
    origin: "web",
    status: "open",
    started_at: iso(-1 * DAY),
    last_activity_at: iso(-1 * DAY),
    ended_at: null,
    current_step: "wins",
    steps: {
      wins: "pending",
      mind_sweep: "pending",
      inbox: "pending",
      decisions: "pending",
      rest_of_next: "pending",
      waiting: "pending",
      projects: "pending",
      someday: "pending",
      dates: "pending",
      summary: "pending"
    },
    counts: zeroCounts,
    clear_start: null,
    revision: 1,
    ...overrides
  };
}

export function stateFixture(overrides: Partial<ReviewState> = {}): ReviewState {
  return {
    settings: {
      threshold_days: 14,
      review_weekday: 5,
      review_time: "16:00",
      time_zone: "Europe/Berlin",
      onboarded_at: iso(-30 * DAY),
      activated_at: iso(-30 * DAY),
      owner_park_floor_at: null,
      revision: 3
    },
    explainer_seen: true,
    grace_until: iso(-16 * DAY),
    last_counted_review_at: iso(-9 * DAY),
    last_counted_review: null,
    next_review_at: "2026-10-16T14:00:00Z",
    restart_mode: false,
    open_session: null,
    unseen_parks: [],
    counts: { asks_for_decision: 0, moves_tomorrow: 0 },
    receipts: [],
    server_now: iso(0),
    ...overrides
  };
}

export function signIn(id = "user-1", flags: Record<string, boolean> = { weekly_review: true }) {
  act(() => {
    useAuthStore.setState({ user: { id, email: `${id}@example.test`, feature_flags: flags }, status: "authed" });
  });
}

export const notify = vi.fn<ShellNotify>();
export const lastToast = (): [string, ShellToastOptions | undefined] => notify.mock.calls[notify.mock.calls.length - 1] as [string, ShellToastOptions | undefined];

export function renderInRun(
  ui: React.ReactNode,
  { session = sessionFixture(), state = stateFixture(), progress = vi.fn(async () => undefined), beginWrite = vi.fn(() => () => undefined), setUnsaved = vi.fn(), skipStep = vi.fn(), confirmDiscard = vi.fn((close: () => void) => close()), finish = vi.fn(async () => undefined), client = new QueryClient({ defaultOptions: { queries: { retry: false } } }) }: Partial<ReviewRun> & { client?: QueryClient } = {}
) {
  const run: ReviewRun = { session, state, progress, beginWrite, setUnsaved, confirmDiscard, skipStep, finish };
  const view = render(
    <QueryClientProvider client={client}>
      <ShellToastContext.Provider value={notify}>
        <MemoryRouter>
          <ReviewRunContext.Provider value={run}>{ui}</ReviewRunContext.Provider>
        </MemoryRouter>
      </ShellToastContext.Provider>
    </QueryClientProvider>
  );
  return { ...view, run, client };
}
