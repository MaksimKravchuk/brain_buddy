import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { reviewApi, type DecisionResponse } from "../../../api/review";
import type { ProjectResponse, TaskResponse } from "../../../api/taskTypes";
import { useAuthStore } from "../../../stores/authStore";
import { FormulationBlock } from "../FormulationBlock";
import { formatReviewDate, formatReviewTime } from "../formulation";

vi.mock("../../../api/review", async () => {
  const actual = await vi.importActual<typeof import("../../../api/review")>("../../../api/review");
  return { ...actual, reviewApi: { ...actual.reviewApi, decide: vi.fn() } };
});
const decide = vi.mocked(reviewApi.decide);

const DAY = 86_400_000;
const NOW = Date.now();
const iso = (offsetMs: number) => new Date(NOW + offsetMs).toISOString();

const projects: ProjectResponse[] = [
  { id: "project-home", name: "Home", color: null, state: "active", revision: 1, open_task_count: 3 },
  { id: "project-old", name: "Old flat", color: null, state: "archived", revision: 2, open_task_count: 0 }
];

function task(overrides: Partial<TaskResponse> = {}, formulation: Partial<NonNullable<TaskResponse["formulation"]>> | null = {}): TaskResponse {
  return {
    id: "task-1",
    title: "Renovate the bathroom",
    details: null,
    state: "next",
    project_id: "project-home",
    tag_ids: [],
    due_date: null,
    priority: "none",
    waiting_for: null,
    waiting_since: null,
    order_key: 1,
    source_capture_ids: [],
    created_at: iso(-30 * DAY),
    updated_at: iso(-15 * DAY),
    completed_at: null,
    cancelled_at: null,
    revision: 7,
    formulation: formulation === null ? null : {
      id: "form_a",
      started_at: iso(-15 * DAY),
      extended_at: null,
      extension_reason: null,
      park_floor_at: null,
      consecutive_stalled: 0,
      ageing_at: iso(-8 * DAY),
      ask_at: iso(-1 * DAY),
      park_due_at: iso(6 * DAY),
      paused_until: null,
      ...formulation
    },
    parked: null,
    ...overrides
  };
}

function Harness({ initial }: { initial: TaskResponse }): React.JSX.Element {
  const headingRef = useRef<HTMLHeadingElement>(null);
  return (
    <div>
      <h2 ref={headingRef} tabIndex={-1}>Task detail</h2>
      <FormulationBlock task={initial} projects={projects} headingRef={headingRef} />
    </div>
  );
}

function renderBlock(initial: TaskResponse) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Harness initial={initial} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  return { ...view, client };
}

const block = () => screen.getByRole("region", { name: "This wording" });

beforeEach(() => {
  act(() => {
    useAuthStore.setState({ user: { id: "user-1", email: "max@example.test", feature_flags: { weekly_review: true } }, status: "authed" });
  });
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
});

afterEach(async () => {
  cleanup();
  await act(() => new Promise<void>((resolve) => setTimeout(resolve, 20)));
  onlineManager.setOnline(true);
  vi.restoreAllMocks();
  decide.mockReset();
  window.localStorage.clear();
  act(() => {
    useAuthStore.setState({ user: null, status: "loading" });
  });
});

describe("020-FR-010 D-06 This wording block", () => {
  it("020-FR-010 a task that asks shows the marker, its days, the reassurance and Decide", () => {
    renderBlock(task());

    expect(within(block()).getByText("Asks for a decision")).toBeInTheDocument();
    expect(within(block()).getByText("15 days in Next")).toBeInTheDocument();
    expect(within(block()).getByText("The wording hasn't moved for a while. That's feedback on the wording, not on you. Changing notes, Tags, project or priority doesn't restart the clock.")).toBeInTheDocument();
    const decideButton = within(block()).getByRole("button", { name: "Decide" });
    expect(decideButton).toHaveClass("min-h-11", "max-sm:w-full");
  });

  it("020-FR-004 Ageing appears here, with the day it will ask; a fresh task shows its days only", () => {
    const { unmount } = renderBlock(task({}, { ageing_at: iso(-1 * DAY), ask_at: iso(5 * DAY), park_due_at: iso(12 * DAY), started_at: iso(-9 * DAY) }));
    expect(within(block()).getByText("Ageing")).toBeInTheDocument();
    expect(within(block()).getByText("9 days in Next")).toBeInTheDocument();
    expect(within(block()).getByText(`Asks for a decision from ${formatReviewDate(iso(5 * DAY))} if the wording stays the same.`)).toBeInTheDocument();
    expect(within(block()).queryByRole("button", { name: "Decide" })).not.toBeInTheDocument();
    unmount();

    renderBlock(task({}, { started_at: iso(-2 * DAY), ageing_at: iso(5 * DAY), ask_at: iso(12 * DAY), park_due_at: iso(19 * DAY) }));
    expect(within(block()).getByText("2 days in Next")).toBeInTheDocument();
    expect(within(block()).queryByText("Ageing")).not.toBeInTheDocument();
    expect(within(block()).queryByRole("button", { name: "Decide" })).not.toBeInTheDocument();
  });

  it("020-FR-046 a future due date pauses the clock until that day", () => {
    renderBlock(task({ due_date: "2026-10-16" }, { paused_until: iso(4 * DAY) }));
    expect(within(block()).getByText("Paused until the due date")).toBeInTheDocument();
    expect(within(block()).getByText(`The clock starts on ${formatReviewDate(iso(4 * DAY))}. Until then this task won't ask for a decision or move to Someday.`)).toBeInTheDocument();
    expect(within(block()).queryByRole("button", { name: "Decide" })).not.toBeInTheDocument();
  });

  it("020-FR-012 a task within a day of its park says exactly when, and keeps Decide", () => {
    const parkAt = iso(10 * 60 * 60 * 1000);
    renderBlock(task({}, { park_due_at: parkAt }));
    expect(within(block()).getByText("Moves to Someday tomorrow")).toBeInTheDocument();
    expect(within(block()).getByText(`If nothing is decided, it moves to Someday / maybe on ${formatReviewDate(parkAt)} at ${formatReviewTime(parkAt)}. Nothing is lost, and you can bring it back in one click.`)).toBeInTheDocument();
    expect(within(block()).getByRole("button", { name: "Decide" })).toBeInTheDocument();
  });

  it("020-FR-009 a kept wording quotes its reason back with the new dates", () => {
    renderBlock(task({}, {
      started_at: iso(-18 * DAY),
      extended_at: iso(-4 * DAY),
      extension_reason: "Waiting to measure the sink first",
      ageing_at: iso(-11 * DAY),
      ask_at: iso(3 * DAY),
      park_due_at: iso(10 * DAY)
    }));
    expect(within(block()).getByText("Kept 7 more days")).toBeInTheDocument();
    expect(within(block()).getByText("“Waiting to measure the sink first”")).toBeInTheDocument();
    expect(within(block()).getByText(
      `Kept on ${formatReviewDate(iso(-4 * DAY))}. Asks again on ${formatReviewDate(iso(3 * DAY))}; moves to Someday on ${formatReviewDate(iso(10 * DAY))} if still undecided. This wording can't be extended again.`
    )).toBeInTheDocument();
    expect(within(block()).queryByRole("button", { name: "Decide" })).not.toBeInTheDocument();
  });

  it("020-FR-012 a parked task says when it moved and what was kept, or that its archived project needs restoring", () => {
    const parkedAt = iso(-1 * DAY);
    const { unmount } = renderBlock(task({ state: "someday", parked: { at: parkedAt, formulation_id: "form_a" } }, null));
    expect(within(block()).getByText("Parked automatically")).toBeInTheDocument();
    expect(within(block()).getByText(`Moved here on ${formatReviewDate(parkedAt)} at ${formatReviewTime(parkedAt)}. Project, Tags, notes and due date were kept.`)).toBeInTheDocument();
    unmount();

    renderBlock(task({ state: "someday", project_id: "project-old", parked: { at: parkedAt, formulation_id: "form_a" } }, null));
    expect(within(block()).getByText(`Moved here on ${formatReviewDate(parkedAt)} at ${formatReviewTime(parkedAt)}. Its project “Old flat” is archived, so restore the project before moving this back to Next actions.`)).toBeInTheDocument();
  });

  it("020-FR-051 shows no block before the explainer was seen, outside Next, or with the flag off", () => {
    const { unmount } = renderBlock(task({}, { ageing_at: null, ask_at: null, park_due_at: null }));
    expect(screen.queryByRole("region", { name: "This wording" })).not.toBeInTheDocument();
    unmount();

    const waiting = renderBlock(task({ state: "waiting" }, null));
    expect(screen.queryByRole("region", { name: "This wording" })).not.toBeInTheDocument();
    waiting.unmount();

    act(() => {
      useAuthStore.setState({ user: { id: "user-1", email: "max@example.test" } });
    });
    renderBlock(task());
    expect(screen.queryByRole("region", { name: "This wording" })).not.toBeInTheDocument();
  });

  it("020-FR-040 offline the facts stay and Decide stays focusable with the reason", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    renderBlock(task());

    const decideButton = within(block()).getByRole("button", { name: "Decide" });
    expect(decideButton).toHaveAttribute("aria-disabled", "true");
    expect(decideButton).toHaveAccessibleDescription("You're offline. Decisions need a connection. Retry when you're back online.");
    await user.tab();
    expect(decideButton).toHaveFocus();
    await user.click(decideButton);
    expect(screen.getByText("You're offline. Decisions need a connection on the web.")).toBeInTheDocument();
  });

  it("020-FR-010 Decide opens the decision dialog and Close returns focus to Decide", async () => {
    const user = userEvent.setup();
    renderBlock(task());

    await user.click(within(block()).getByRole("button", { name: "Decide" }));
    expect(screen.getByRole("dialog", { name: "Renovate the bathroom" })).toBeInTheDocument();
    expect(screen.getByText("15 days in Next · Home")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(within(block()).getByRole("button", { name: "Decide" })).toHaveFocus();
  });

  it("020-FR-010 after a decision that removes the task from Next, focus goes to the panel heading", async () => {
    const user = userEvent.setup();
    const asking = task();
    const response: DecisionResponse = {
      decision: { id: "decision_1", type: "someday", task_id: "task-1", session_id: null, decided_at: iso(0), substantive: null, stall_reason: null, ai_use: "none", yielded_auto_park: false },
      task: { ...asking, state: "someday", revision: 8, formulation: null },
      created_task: null,
      receipt: null,
      session_counts: null
    };
    decide.mockResolvedValueOnce(response);
    const { rerender, client } = renderBlock(asking);

    await user.click(within(block()).getByRole("button", { name: "Decide" }));
    await user.click(within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name: /^Release to Someday/ }));
    rerender(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Harness initial={response.task} />
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => expect(screen.getByRole("heading", { name: "Task detail" })).toHaveFocus());
  });

  it("020-FR-001 a project-less task names no project in the dialog", async () => {
    const user = userEvent.setup();
    renderBlock(task({ project_id: null }));
    await user.click(within(block()).getByRole("button", { name: "Decide" }));
    expect(screen.getByText("15 days in Next · no project")).toBeInTheDocument();
  });
});
